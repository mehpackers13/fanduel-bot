"""
MORNING BRIEFING -- 7am ET daily
Finds top 3 opportunities for the day and sends to Discord.
Includes a UFC section if any fights are scheduled today.
"""
import datetime
import config
from logger import log
from scanner import run_scan
from discord_alerts import send_morning_briefing
from outcomes import win_rate, roi, completed_bets


def _get_ufc_today() -> str:
    """
    Check OddsTrader for UFC fights today.
    Returns a formatted string for the morning briefing, or "" if none.
    """
    try:
        from oddstrader import get_ufc_fights
        fights = get_ufc_fights()
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

    send_morning_briefing(top3, date_str, ufc_section=ufc_section)

    done = completed_bets()
    if done:
        log(f"Running record: {win_rate():.1f}% win rate | {roi():+.1f}% ROI on {len(done)} bets")

    log("Morning briefing complete")
    log("=" * 60)
