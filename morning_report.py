"""
MORNING BRIEFING — 7am ET daily
Finds top 3 opportunities for the day and sends to Discord.
"""
import datetime
import config
from logger import log
from scanner import run_scan
from discord_alerts import send_morning_briefing
from outcomes import win_rate, roi, completed_bets


def run_morning() -> None:
    log("=" * 60)
    log("Running morning briefing scan (7am)")

    opps = run_scan(morning_mode=True)
    top3 = opps[:3]

    tz       = datetime.timezone(datetime.timedelta(hours=-4))
    date_str = datetime.datetime.now(tz).strftime("%A, %B %d")

    send_morning_briefing(top3, date_str)

    done = completed_bets()
    if done:
        log(f"Running record: {win_rate():.1f}% win rate | {roi():+.1f}% ROI on {len(done)} bets")

    log("Morning briefing complete")
    log("=" * 60)
