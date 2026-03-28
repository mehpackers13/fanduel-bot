"""
BANKROLL TRACKER
================
Reads starting bankroll from config.py (update manually when balance changes).
Tracks bets placed and outcomes for ROI calculation.
"""
import config
from logger import log


def get_bankroll() -> float:
    return config.BANKROLL


def max_bet() -> float:
    return round(config.BANKROLL * config.MAX_BET_PCT, 2)


def bet_summary() -> str:
    return (
        f"Bankroll: ${config.BANKROLL:.2f} | "
        f"Max single bet: ${max_bet():.2f} | "
        f"Kelly fraction: {config.KELLY_FRACTION:.0%}"
    )
