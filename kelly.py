"""
FRACTIONAL KELLY CRITERION BET SIZING
======================================
Sizes bets proportionally to edge strength.
Uses 1/4 Kelly (config.KELLY_FRACTION) for safety.
Hard cap at 5% of bankroll (config.MAX_BET_PCT).
"""
import config
from logger import log


def kelly_bet_size(true_prob: float, implied_prob: float) -> tuple:
    """
    Returns (kelly_fraction, suggested_dollars).
    kelly_fraction: fraction of bankroll to bet (after quarter-Kelly and cap)
    suggested_dollars: actual dollar amount rounded to nearest $1
    """
    if implied_prob <= 0 or implied_prob >= 1:
        return 0.0, 0.0

    # Decimal odds from implied probability
    decimal_odds = 1.0 / implied_prob

    # Full Kelly: (bp - q) / b  where b=odds-1, p=true_prob, q=1-true_prob
    b = decimal_odds - 1
    p = true_prob
    q = 1 - true_prob

    full_kelly = (b * p - q) / b if b > 0 else 0.0

    if full_kelly <= 0:
        return 0.0, 0.0

    # Apply fraction and cap
    frac_kelly   = full_kelly * config.KELLY_FRACTION
    capped_kelly = min(frac_kelly, config.MAX_BET_PCT)

    dollars = round(config.BANKROLL * capped_kelly, 0)
    dollars = max(dollars, 1.0)   # minimum $1 bet

    return round(capped_kelly, 4), dollars


def size_description(kelly_f: float) -> str:
    """Human-readable size tier."""
    pct = kelly_f * 100
    if pct >= 4:
        return "Strong (4-5% bankroll)"
    elif pct >= 3:
        return "Medium (3-4% bankroll)"
    elif pct >= 2:
        return "Standard (2-3% bankroll)"
    else:
        return "Small (1-2% bankroll)"
