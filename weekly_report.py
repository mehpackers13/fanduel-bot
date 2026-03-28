"""
WEEKLY REPORT -- Sunday 8pm ET
Full performance breakdown sent to Discord.
Includes UFC win rate and ROI breakdown.
"""
import json
import config
from logger import log
from self_improve import run_analysis
from discord_alerts import send_weekly_report


def _build_ufc_stats(bets_log) -> dict:
    """
    Extract UFC-specific win rate and ROI from bets log.
    bets_log: list of bet dicts with 'sport', 'result', 'profit' fields.
    Returns dict with wins, losses, win_rate, roi.
    """
    ufc_bets = [b for b in bets_log if b.get("sport") == "UFC"]
    if not ufc_bets:
        return {}

    completed = [b for b in ufc_bets if b.get("result") in ("win", "loss", "push")]
    if not completed:
        return {}

    wins   = sum(1 for b in completed if b.get("result") == "win")
    losses = sum(1 for b in completed if b.get("result") == "loss")
    total  = wins + losses

    total_wagered = sum(b.get("bet_amount", 0) for b in completed if b.get("bet_amount"))
    total_profit  = sum(b.get("profit", 0) for b in completed)
    roi = (total_profit / total_wagered * 100) if total_wagered > 0 else 0.0

    return {
        "wins":     wins,
        "losses":   losses,
        "win_rate": round((wins / total * 100) if total > 0 else 0.0, 1),
        "roi":      round(roi, 1),
        "bets":     total,
    }


def _load_bets_log() -> list:
    """Load raw bets from bets_log.csv, return list of dicts."""
    bets = []
    if not config.BETS_LOG.exists():
        return bets
    try:
        import csv
        with open(config.BETS_LOG, newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                bets.append(dict(row))
    except Exception as exc:
        log(f"Could not load bets log: {exc}", "WARN")
    return bets


def run_weekly() -> None:
    log("=" * 60)
    log("Running weekly performance report")

    stats = run_analysis()
    if not stats:
        stats = {
            "completed":    0,
            "win_rate":     0,
            "roi":          0,
            "by_sport":     {},
            "best_signal":  "Not enough data",
            "worst_signal": "Not enough data",
        }

    stats["completed"] = stats.get("total_bets", 0)

    # Add UFC breakdown
    bets_log = _load_bets_log()
    ufc_stats = _build_ufc_stats(bets_log)
    if ufc_stats:
        stats["ufc"] = ufc_stats
        log(f"UFC record: {ufc_stats['wins']}W-{ufc_stats['losses']}L | "
            f"Win rate {ufc_stats['win_rate']:.1f}% | ROI {ufc_stats['roi']:+.1f}%")

    send_weekly_report(stats)
    log("Weekly report sent")
    log("=" * 60)
