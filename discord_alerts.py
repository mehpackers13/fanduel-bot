"""
DISCORD ALERTS
==============
Sends formatted alerts to #sports-alerts Discord channel.
"""
import datetime
import requests

import config
from logger import log
from kelly import unit_size, parlay_odds, parlay_payout

_COLOR_STRONG = 0x00FF7F   # green
_COLOR_MEDIUM = 0xFFD700   # gold
_COLOR_WEAK   = 0xFF8C00   # orange
_COLOR_INFO   = 0x4169E1   # blue
_COLOR_WARN   = 0xFF4444   # red


def _post(webhook: str, payload: dict) -> bool:
    if not webhook:
        log("No Discord webhook configured -- alert not sent", "WARN")
        return False
    try:
        resp = requests.post(webhook, json=payload, timeout=8)
        if resp.status_code in (200, 204):
            return True
        log(f"Discord returned {resp.status_code}: {resp.text[:200]}", "WARN")
    except Exception as exc:
        log(f"Discord send failed: {exc}", "WARN")
    return False


def _sports(payload: dict) -> bool:
    return _post(config.DISCORD_SPORTS_WEBHOOK, payload)


def _health(payload: dict) -> bool:
    return _post(config.DISCORD_HEALTH_WEBHOOK or config.DISCORD_SPORTS_WEBHOOK, payload)


def _confidence_color(confidence: int) -> int:
    if confidence >= 80:
        return _COLOR_STRONG
    elif confidence >= 70:
        return _COLOR_MEDIUM
    return _COLOR_WEAK


def _side_name(opp) -> str:
    """Return the human-readable side for the bet."""
    if opp.bet_side == "home":
        return opp.home_team
    if opp.bet_side == "away":
        return opp.away_team
    return opp.bet_side.upper()


def _bet_label(opp) -> str:
    """Return bet type label: SPREAD, MONEYLINE, or TOTAL."""
    return opp.bet_type.upper()


def _size_label(opp) -> str:
    """Return unit/dollar label e.g. '3u Best Bet ($30)'."""
    u   = opp.units
    dol = opp.unit_dollars
    if opp.alert_type == "best_bet":
        return f"**{u}u** Best Bet (${dol:.0f})"
    return f"**{u}u** Sprinkle (${dol:.0f})"


def _books_line(opp) -> str:
    """Best available books line, or empty if not available."""
    h2h = getattr(opp, "_raw_game", {})
    # If we have bookmaker info, format it; otherwise skip
    return ""


def send_bet_alert(opp) -> None:
    """
    Send a best-bet alert to #sports-alerts.

    Format:
      🎯 NBA | Milwaukee Bucks @ Boston Celtics

      **SPREAD -- Celtics -4.5**  ·  3u Best Bet ($30)

      Edge: 9.2%  ·  Confidence: 74/100
      Signals: sharp money + public fade + rest disadvantage
      <reasoning text>
    """
    game_str    = f"{opp.away_team} @ {opp.home_team}"
    side        = _side_name(opp)
    bet_label   = _bet_label(opp)
    size_label  = _size_label(opp)
    signals_str = " + ".join(s.replace("_", " ") for s in opp.signals)

    description = (
        f"**{bet_label} -- {side} {opp.line}**  \u00b7  {size_label}\n\n"
        f"Edge: {opp.edge_pct:.1f}%  \u00b7  Confidence: {opp.confidence}/100\n"
        f"Signals: {signals_str}\n"
        f"{opp.reasoning}"
    )

    embed = {
        "title":       f"\U0001f3af {opp.sport} | {game_str}",
        "description": description,
        "color":       _confidence_color(opp.confidence),
        "footer":      {"text": "fanduel-bot | silence = discipline"},
        "timestamp":   datetime.datetime.utcnow().isoformat() + "Z",
    }

    if _sports({"embeds": [embed]}):
        log(f"Best bet alert sent: {game_str} | {opp.bet_type} {side} {opp.line} | "
            f"edge {opp.edge_pct:.1f}% | {opp.units}u")


def send_sprinkle_alert(opp) -> None:
    """
    Send a sprinkle alert to #sports-alerts.

    Format:
      💎 MLB | Yankees @ Red Sox

      **TOTAL UNDER 8.5**  ·  1u Sprinkle ($10)

      Edge: 6.1%  ·  Confidence: 63/100
      Signals: weather edge + rest disadvantage
      <reasoning text>
    """
    game_str    = f"{opp.away_team} @ {opp.home_team}"
    side        = _side_name(opp)
    bet_label   = _bet_label(opp)
    size_label  = _size_label(opp)
    signals_str = " + ".join(s.replace("_", " ") for s in opp.signals)

    description = (
        f"**{bet_label} {side} {opp.line}**  \u00b7  {size_label}\n\n"
        f"Edge: {opp.edge_pct:.1f}%  \u00b7  Confidence: {opp.confidence}/100\n"
        f"Signals: {signals_str}\n"
        f"{opp.reasoning}"
    )

    embed = {
        "title":       f"\U0001f48e {opp.sport} | {game_str}",
        "description": description,
        "color":       _COLOR_WEAK,
        "footer":      {"text": "fanduel-bot | silence = discipline"},
        "timestamp":   datetime.datetime.utcnow().isoformat() + "Z",
    }

    if _sports({"embeds": [embed]}):
        log(f"Sprinkle alert sent: {game_str} | {opp.bet_type} {side} {opp.line} | "
            f"edge {opp.edge_pct:.1f}% | {opp.units}u")


def send_parlay_suggestion(bets: list) -> None:
    """
    Send a parlay suggestion after individual best-bet alerts.

    Format:
      🔗 PARLAY SUGGESTION -- 3 Legs

      Leg 1: Celtics -4.5 (-110)
      Leg 2: Blues ML (-130)
      Leg 3: Oilers -1.5 (-115)

      Combined odds: +512
      1u stake ($10) -> pays $61.20
      2u stake ($20) -> pays $122.40

      ⚠️ Play these individually first. Parlay only if all 3 feel strong.
    """
    if not bets:
        return

    # Collect individual odds for parlay calc
    # Use the implied probability to back-calculate representative odds
    odds_list = []
    legs_text  = []
    for i, opp in enumerate(bets, 1):
        side     = _side_name(opp)
        bet_type = opp.bet_type.upper()
        # Get the line odds as integer if possible
        try:
            line_odds = int(opp.line.replace("+", "")) if opp.line else -110
        except (ValueError, AttributeError):
            line_odds = -110
        odds_list.append(line_odds)
        legs_text.append(f"Leg {i}: {side} {opp.line} ({'+' if line_odds > 0 else ''}{line_odds})")

    combined = parlay_odds(odds_list)
    combined_str = f"+{combined}" if combined > 0 else str(combined)

    pay_1u = parlay_payout(1, odds_list)
    pay_2u = parlay_payout(2, odds_list)
    u_size = unit_size()

    legs_block = "\n".join(legs_text)
    description = (
        f"{legs_block}\n\n"
        f"Combined odds: {combined_str}\n"
        f"1u stake (${u_size:.0f}) \u2192 pays ${pay_1u:.2f}\n"
        f"2u stake (${u_size * 2:.0f}) \u2192 pays ${pay_2u:.2f}\n\n"
        f"\u26a0\ufe0f Play these individually first. Parlay only if all {len(bets)} feel strong."
    )

    embed = {
        "title":       f"\U0001f517 PARLAY SUGGESTION -- {len(bets)} Legs",
        "description": description,
        "color":       _COLOR_INFO,
        "footer":      {"text": "fanduel-bot | parlay is extra credit"},
        "timestamp":   datetime.datetime.utcnow().isoformat() + "Z",
    }
    _sports({"embeds": [embed]})


def send_morning_briefing(opps: list, date_str: str, ufc_section: str = "",
                          unit_summary: dict = None) -> None:
    """Send daily 7am briefing with top opportunities, unit totals, and VIX."""
    us = unit_summary or {}

    # Build unit summary line
    fd_u  = us.get("fanduel")
    kal_u = us.get("kalshi")
    opt_u = us.get("options")

    def _fmt_u(v):
        if v is None:
            return "—"
        sign = "+" if v >= 0 else ""
        color = "🟢" if v > 0 else "🔴" if v < 0 else "⚪"
        return f"{color} {sign}{v:.1f}u"

    combined = None
    try:
        parts = [x for x in [fd_u, kal_u, opt_u] if x is not None]
        combined = round(sum(parts), 2) if parts else None
    except Exception:
        pass

    combined_str = _fmt_u(combined) if combined is not None else "—"
    vix_str = us.get("vix", "N/A")

    fields = []

    # Unit summary block — always shown first
    unit_block = (
        f"Sports (FanDuel): {_fmt_u(fd_u)}\n"
        f"Prediction (Kalshi): {_fmt_u(kal_u)}\n"
        f"Options signals: {_fmt_u(opt_u)}"
    )
    fields.append({"name": f"📊 COMBINED UNITS: {combined_str}", "value": unit_block, "inline": False})
    fields.append({"name": "📈 VIX Level",    "value": vix_str,              "inline": True})
    fields.append({"name": "🎯 Opportunities", "value": str(len(opps)),      "inline": True})

    # Overnight resolutions
    overnight = us.get("overnight", [])
    if overnight:
        o_lines = []
        for b in overnight[-5:]:
            icon = "✅" if b.get("outcome") == "W" else "❌" if b.get("outcome") == "L" else "⚪"
            game = b.get("game", b.get("sport", "?"))
            o_lines.append(f"{icon} {game}")
        fields.append({"name": "🌙 Resolved Overnight", "value": "\n".join(o_lines), "inline": False})

    for i, opp in enumerate(opps[:3], 1):
        game  = f"{opp.away_team} @ {opp.home_team}"
        side  = _side_name(opp)
        sigs  = " + ".join(opp.signals)
        size  = _size_label(opp)
        fields.append({
            "name":  f"#{i} {opp.sport} | {game}",
            "value": (
                f"{opp.bet_type.upper()} {side} {opp.line} | "
                f"Edge {opp.edge_pct:.1f}% | Conf {opp.confidence} | {size}\n"
                f"_{sigs}_"
            ),
            "inline": False,
        })

    if ufc_section:
        fields.append({
            "name":  "\U0001f94a UFC Today",
            "value": ufc_section,
            "inline": False,
        })

    desc = f"**{len(opps)} opportunity{'s' if len(opps) != 1 else ''} found** — top 3 below." if opps \
        else "No qualifying opportunities found for today. Staying patient."

    embed = {
        "title":       f"\u2600\ufe0f Morning Briefing — {date_str}",
        "description": desc,
        "color":       _COLOR_INFO,
        "fields":      fields,
        "footer":      {"text": "fanduel-bot + kalshi-bot + options-bot"},
        "timestamp":   datetime.datetime.utcnow().isoformat() + "Z",
    }
    _sports({"embeds": [embed]})
    log(f"Morning briefing sent: {len(opps)} opportunities | combined units: {combined_str}")


def send_weekly_report(stats: dict) -> None:
    """Sunday evening performance report."""
    completed = stats.get("completed", 0)
    wr        = stats.get("win_rate", 0)
    roi_val   = stats.get("roi", 0)
    by_sport  = stats.get("by_sport", {})

    sport_lines = "\n".join(
        f"\u2022 {s}: {d['wins']}-{d['losses']} ({d['roi']:+.1f}% ROI)"
        for s, d in sorted(by_sport.items(), key=lambda x: -x[1].get("roi", 0))
    ) or "No completed bets yet."

    # UFC breakdown
    ufc_data  = stats.get("ufc", {})
    ufc_lines = ""
    if ufc_data:
        ufc_lines = (
            f"\n\n**UFC** -- {ufc_data.get('wins',0)}W-{ufc_data.get('losses',0)}L "
            f"| Win rate {ufc_data.get('win_rate',0):.1f}% "
            f"| ROI {ufc_data.get('roi',0):+.1f}%"
        )

    embed = {
        "title":       "\U0001f4ca Weekly Performance Report",
        "description": (
            f"**{completed} bets completed** | Win rate {wr:.1f}% | ROI {roi_val:+.1f}%"
            f"{ufc_lines}"
        ),
        "color":       _COLOR_STRONG if roi_val > 0 else _COLOR_WARN,
        "fields": [
            {"name": "By Sport",    "value": sport_lines,                           "inline": False},
            {"name": "Best Signal", "value": stats.get("best_signal","Insufficient data"),  "inline": True},
            {"name": "Worst Signal","value": stats.get("worst_signal","Insufficient data"), "inline": True},
        ],
        "footer":    {"text": "fanduel-bot | weekly report"},
        "timestamp": datetime.datetime.utcnow().isoformat() + "Z",
    }
    _sports({"embeds": [embed]})


def send_injury_alert(sport: str, team: str, player: str, position: str, game: str) -> None:
    embed = {
        "title":       f"\U0001f6a8 Injury Alert -- {sport}",
        "description": (
            f"**{player}** ({position}) ruled OUT for {team}\n"
            f"_Game: {game}_\n\n"
            f"Monitor lines -- may not have fully adjusted yet."
        ),
        "color":       _COLOR_WARN,
        "footer":      {"text": "fanduel-bot"},
        "timestamp":   datetime.datetime.utcnow().isoformat() + "Z",
    }
    _sports({"embeds": [embed]})


def send_health_ping(message: str, color: int = _COLOR_INFO) -> None:
    embed = {
        "title":       "\U0001f916 fanduel-bot",
        "description": message,
        "color":       color,
        "timestamp":   datetime.datetime.utcnow().isoformat() + "Z",
    }
    _health({"embeds": [embed]})


def send_test_alert() -> bool:
    embed = {
        "title":       "\u2705 fanduel-bot -- Webhook Test",
        "description": (
            "Discord webhook is connected and working.\n\n"
            "The bot is live and scanning for edges. You'll only receive alerts when "
            "multiple signals stack on the same game with 60+ confidence."
        ),
        "color":       _COLOR_STRONG,
        "fields": [
            {
                "name":  "Sports covered",
                "value": "NFL \u00b7 NBA \u00b7 MLB \u00b7 NHL \u00b7 MLS \u00b7 EPL \u00b7 La Liga \u00b7 Bundesliga \u00b7 Serie A \u00b7 Ligue 1 \u00b7 UFC",
                "inline": False,
            },
            {"name": "Minimum edge",   "value": "5%",        "inline": True},
            {"name": "Min confidence", "value": "60/100",    "inline": True},
            {"name": "Min signals",    "value": "2 stacking","inline": True},
            {"name": "Best Bet size",  "value": "2-4 units", "inline": True},
            {"name": "Sprinkle size",  "value": "1 unit",    "inline": True},
            {"name": "Unit = ",        "value": f"${unit_size():.0f} (1% bankroll)", "inline": True},
        ],
        "footer":    {"text": "fanduel-bot | silence = discipline"},
        "timestamp": datetime.datetime.utcnow().isoformat() + "Z",
    }
    return _sports({"embeds": [embed]})
