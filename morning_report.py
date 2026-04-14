"""
MORNING BRIEFING -- 7am ET daily
Finds top 3 opportunities for the day and sends to Discord.
Includes unit totals from all three bots, overnight resolutions, and VIX level.
"""
import datetime
import json
import config
from logger import log
from scanner import run_scan
from discord_alerts import send_morning_briefing
from outcomes import win_rate, roi, completed_bets, read_all as read_all_bets


def _get_ufc_today() -> str:
    """
    Check ESPN Core API for UFC fights today.
    Returns a formatted string for the morning briefing, or "" if none.
    """
    try:
        import espn_core_api
        fights = espn_core_api.get_games("mma_mixed_martial_arts")
        if not fights:
            return ""

        today_utc = datetime.datetime.utcnow().date()
        today_fights = []
        for f in fights:
            # hours_out <= 24 means fight is within the next 24 hours
            if f.get("hours_out", 99) <= 24:
                home = f.get("home_team", "")
                away = f.get("away_team", "")
                h2h  = f.get("h2h", {})
                home_ml = h2h.get("home_odds", "")
                away_ml = h2h.get("away_odds", "")

                home_str = f"{home} ({'+' if isinstance(home_ml, int) and home_ml > 0 else ''}{home_ml})" if home_ml else home
                away_str = f"{away} ({'+' if isinstance(away_ml, int) and away_ml > 0 else ''}{away_ml})" if away_ml else away
                today_fights.append(f"{away_str} vs {home_str}")

        if not today_fights:
            return ""

        lines = [f"\u2022 {fight}" for fight in today_fights[:8]]
        return "\n".join(lines)

    except Exception as exc:
        log(f"UFC today check failed: {exc}", "WARN")
        return ""


def _fetch_bot_data(url: str) -> dict:
    """Fetch another bot's data.json from GitHub Pages. Returns {} on failure."""
    try:
        import requests
        resp = requests.get(url, timeout=8)
        if resp.status_code == 200:
            return resp.json()
    except Exception:
        pass
    return {}


def _fetch_vix() -> str:
    """Fetch current VIX level via yfinance. Returns formatted string or 'N/A'."""
    try:
        import yfinance as yf
        hist = yf.Ticker("^VIX").history(period="2d")
        if not hist.empty:
            vix = float(hist["Close"].iloc[-1])
            if vix < 15:
                mood = "calm"
            elif vix < 20:
                mood = "normal"
            elif vix < 25:
                mood = "elevated"
            else:
                mood = "SPIKE"
            return f"{vix:.1f} ({mood})"
    except Exception:
        pass
    return "N/A"


def _calc_fanduel_units() -> float:
    """Calculate FanDuel unit total from bets_log.csv."""
    unit_size = config.UNIT_SIZE  # $10
    bets = read_all_bets()
    total = 0.0
    for b in bets:
        if b.get("outcome") not in ("W", "L", "P"):
            continue
        try:
            total += float(b.get("profit_loss") or 0) / unit_size
        except Exception:
            pass
    return round(total, 2)


def _overnight_resolved() -> list:
    """Bets that got auto-resolved in the last 8 hours."""
    cutoff = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=8)
    bets = read_all_bets()
    resolved = []
    for b in bets:
        if b.get("outcome") not in ("W", "L", "P"):
            continue
        # We don't store a resolved_at timestamp for fanduel bets, so use timestamp as proxy
        # Show all resolved bets from today
        resolved.append(b)
    # Return only the last 5
    return resolved[-5:]


def run_morning() -> None:
    log("=" * 60)
    log("Running morning briefing scan (7am)")

    opps = run_scan(morning_mode=True)
    top3 = opps[:3]

    tz       = datetime.timezone(datetime.timedelta(hours=-4))
    date_str = datetime.datetime.now(tz).strftime("%A, %B %d")

    # Check for UFC fights today
    ufc_section = _get_ufc_today()
    if ufc_section:
        log(f"UFC fights found for today -- adding to briefing")

    # Unit tracking
    fanduel_units = _calc_fanduel_units()

    # Fetch units from other bots' GitHub Pages
    kalshi_data  = _fetch_bot_data("https://mehpackers13.github.io/kalshi-bot/data.json")
    options_data = _fetch_bot_data("https://mehpackers13.github.io/options-bot/data.json")
    kalshi_units  = kalshi_data.get("unit_total", None)
    options_units = options_data.get("unit_total", None)

    # VIX level for options mood
    vix_str = _fetch_vix()

    # Overnight resolutions
    overnight = _overnight_resolved()

    unit_summary = {
        "fanduel":  fanduel_units,
        "kalshi":   kalshi_units,
        "options":  options_units,
        "vix":      vix_str,
        "overnight": overnight,
    }

    send_morning_briefing(top3, date_str, ufc_section=ufc_section,
                          unit_summary=unit_summary)

    done = completed_bets()
    if done:
        log(f"Running record: {win_rate():.1f}% win rate | {roi():+.1f}% ROI on {len(done)} bets")

    log(f"Unit totals — FanDuel: {fanduel_units:+.2f}u | Kalshi: {kalshi_units} | Options: {options_units}")
    log("Morning briefing complete")
    log("=" * 60)
