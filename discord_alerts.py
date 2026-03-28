"""
DISCORD ALERTS
==============
Sends formatted alerts to #sports-alerts Discord channel.
"""
import datetime
import requests

import config
from logger import log

_COLOR_STRONG = 0x00FF7F   # green
_COLOR_MEDIUM = 0xFFD700   # gold
_COLOR_WEAK   = 0xFF8C00   # orange
_COLOR_INFO   = 0x4169E1   # blue
_COLOR_WARN   = 0xFF4444   # red


def _post(webhook: str, payload: dict) -> bool:
    if not webhook:
        log("No Discord webhook configured — alert not sent", "WARN")
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


def send_bet_alert(opp) -> None:
    """Send a full bet opportunity alert to #sports-alerts."""
    game_str   = f"{opp.away_team} @ {opp.home_team}"
    side_name  = opp.home_team if opp.bet_side == "home" else (
                 opp.away_team if opp.bet_side == "away" else opp.bet_side.upper())
    signals_str = " + ".join(f"**{s.replace('_',' ')}**" for s in opp.signals)
    size_note   = f"${opp.suggested_bet:.0f} ({opp.kelly_fraction*100:.1f}% bankroll)"

    embed = {
        "title":       f"🎯 {opp.sport} | {game_str}",
        "description": opp.reasoning,
        "color":       _confidence_color(opp.confidence),
        "fields": [
            {"name": "Bet",          "value": f"**{opp.bet_type.upper()} — {side_name} {opp.line}**", "inline": True},
            {"name": "Edge",         "value": f"**{opp.edge_pct:.1f}%**",              "inline": True},
            {"name": "Confidence",   "value": f"**{opp.confidence}/100**",             "inline": True},
            {"name": "Signals",      "value": signals_str,                             "inline": False},
            {"name": "Suggested Bet","value": size_note,                               "inline": True},
            {"name": "Game Time",    "value": f"In {opp.hours_out:.1f}h",              "inline": True},
        ],
        "footer":    {"text": "fanduel-bot | silence = discipline"},
        "timestamp": datetime.datetime.utcnow().isoformat() + "Z",
    }
    if _sports({"embeds": [embed]}):
        log(f"Alert sent: {game_str} | {opp.bet_type} {side_name} | edge {opp.edge_pct:.1f}%")


def send_morning_briefing(opps: list, date_str: str) -> None:
    """Send daily 7am briefing with top opportunities."""
    if not opps:
        embed = {
            "title":       f"☀️ Morning Briefing — {date_str}",
            "description": "No qualifying opportunities found for today. Staying patient.",
            "color":       _COLOR_INFO,
            "footer":      {"text": "fanduel-bot"},
            "timestamp":   datetime.datetime.utcnow().isoformat() + "Z",
        }
        _sports({"embeds": [embed]})
        return

    fields = []
    for i, opp in enumerate(opps[:3], 1):
        game  = f"{opp.away_team} @ {opp.home_team}"
        side  = opp.home_team if opp.bet_side=="home" else (opp.away_team if opp.bet_side=="away" else opp.bet_side.upper())
        sigs  = " + ".join(opp.signals)
        fields.append({
            "name":  f"#{i} {opp.sport} | {game}",
            "value": f"{opp.bet_type.upper()} {side} {opp.line} | Edge {opp.edge_pct:.1f}% | Conf {opp.confidence} | ${opp.suggested_bet:.0f}\n_{sigs}_",
            "inline": False,
        })

    embed = {
        "title":       f"☀️ Morning Briefing — {date_str}",
        "description": f"**{len(opps)} opportunity{'s' if len(opps)>1 else ''} found** — top 3 shown below.",
        "color":       _COLOR_INFO,
        "fields":      fields,
        "footer":      {"text": "fanduel-bot"},
        "timestamp":   datetime.datetime.utcnow().isoformat() + "Z",
    }
    _sports({"embeds": [embed]})
    log(f"Morning briefing sent: {len(opps)} opportunities")


def send_weekly_report(stats: dict) -> None:
    """Sunday evening performance report."""
    completed = stats.get("completed", 0)
    wr = stats.get("win_rate", 0)
    roi_val = stats.get("roi", 0)
    by_sport = stats.get("by_sport", {})

    sport_lines = "\n".join(
        f"• {s}: {d['wins']}-{d['losses']} ({d['roi']:+.1f}% ROI)"
        for s, d in sorted(by_sport.items(), key=lambda x: -x[1].get("roi", 0))
    ) or "No completed bets yet."

    embed = {
        "title":       "📊 Weekly Performance Report",
        "description": f"**{completed} bets completed** | Win rate {wr:.1f}% | ROI {roi_val:+.1f}%",
        "color":       _COLOR_STRONG if roi_val > 0 else _COLOR_WARN,
        "fields": [
            {"name": "By Sport",   "value": sport_lines, "inline": False},
            {"name": "Best Signal","value": stats.get("best_signal", "Insufficient data"), "inline": True},
            {"name": "Worst Signal","value": stats.get("worst_signal","Insufficient data"),"inline": True},
        ],
        "footer":    {"text": "fanduel-bot | weekly report"},
        "timestamp": datetime.datetime.utcnow().isoformat() + "Z",
    }
    _sports({"embeds": [embed]})


def send_injury_alert(sport: str, team: str, player: str, position: str, game: str) -> None:
    embed = {
        "title":       f"🚨 Injury Alert — {sport}",
        "description": f"**{player}** ({position}) ruled OUT for {team}\n_Game: {game}_\n\nMonitor lines — may not have fully adjusted yet.",
        "color":       _COLOR_WARN,
        "footer":      {"text": "fanduel-bot"},
        "timestamp":   datetime.datetime.utcnow().isoformat() + "Z",
    }
    _sports({"embeds": [embed]})


def send_health_ping(message: str, color: int = _COLOR_INFO) -> None:
    embed = {
        "title":       "🤖 fanduel-bot",
        "description": message,
        "color":       color,
        "timestamp":   datetime.datetime.utcnow().isoformat() + "Z",
    }
    _health({"embeds": [embed]})


def send_test_alert() -> bool:
    embed = {
        "title":       "✅ fanduel-bot — Webhook Test",
        "description": "Discord webhook is connected and working.\n\nThe bot is live and scanning for edges. You'll only receive alerts when multiple signals stack on the same game with 60+ confidence.",
        "color":       _COLOR_STRONG,
        "fields": [
            {"name": "Sports covered", "value": "NFL · NBA · MLB · NHL · MLS · EPL · La Liga · Bundesliga · Serie A · Ligue 1", "inline": False},
            {"name": "Minimum edge",   "value": "5%",   "inline": True},
            {"name": "Min confidence", "value": "60/100","inline": True},
            {"name": "Min signals",    "value": "2 stacking", "inline": True},
        ],
        "footer":    {"text": "fanduel-bot | silence = discipline"},
        "timestamp": datetime.datetime.utcnow().isoformat() + "Z",
    }
    return _sports({"embeds": [embed]})
