"""
WEEKLY REPORT — Sunday 8pm ET
Full performance breakdown sent to Discord.
"""
import json
import config
from logger import log
from self_improve import run_analysis
from discord_alerts import send_weekly_report


def run_weekly() -> None:
    log("=" * 60)
    log("Running weekly performance report")
    stats = run_analysis()
    if not stats:
        stats = {"completed": 0, "win_rate": 0, "roi": 0, "by_sport": {},
                 "best_signal": "Not enough data", "worst_signal": "Not enough data"}
    stats["completed"] = stats.get("total_bets", 0)
    send_weekly_report(stats)
    log("Weekly report sent")
    log("=" * 60)
