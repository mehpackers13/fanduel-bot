"""
UNIT-BASED FRACTIONAL KELLY CRITERION
======================================
1 unit = 1% of bankroll (auto-calculated from config.BANKROLL).
All bet sizes expressed in units, then converted to dollars.

Alert types:
  Best Bet:  2-4 units (highest edge plays)
  Sprinkle:  1 unit (speculative value plays)

Hard cap: never exceed config.MAX_BET_PCT (5%) per bet.
"""
import config
from logger import log


def unit_size() -> float:
    """1 unit = 1% of current bankroll."""
    return round(config.BANKROLL * 0.01, 2)


def kelly_units(true_prob: float, implied_prob: float) -> tuple:
    """
    Returns (units: float, dollars: float, alert_type: str).
    alert_type is "best_bet" or "sprinkle" or None (no bet).
    """
    if implied_prob <= 0 or implied_prob >= 1 or true_prob <= implied_prob:
        return 0, 0, None

    b = (1.0 / implied_prob) - 1
    p = true_prob
    q = 1 - true_prob

    full_kelly      = (b * p - q) / b if b > 0 else 0.0
    frac_kelly      = full_kelly * config.KELLY_FRACTION
    kelly_pct       = min(frac_kelly, config.MAX_BET_PCT)
    kelly_unit_val  = kelly_pct / 0.01  # convert % to units

    # Determine alert type
    if kelly_unit_val >= config.BEST_BET_MIN_UNITS:
        units      = min(round(kelly_unit_val), config.BEST_BET_MAX_UNITS)
        alert_type = "best_bet"
    elif kelly_unit_val >= 0.5:
        units      = config.SPRINKLE_UNITS
        alert_type = "sprinkle"
    else:
        return 0, 0, None

    dollars = round(units * unit_size(), 2)
    return units, dollars, alert_type


def kelly_bet_size(true_prob: float, implied_prob: float) -> tuple:
    """
    Legacy interface for backward compatibility.
    Returns (kelly_fraction, suggested_dollars).
    """
    if implied_prob <= 0 or implied_prob >= 1:
        return 0.0, 0.0

    decimal_odds = 1.0 / implied_prob
    b = decimal_odds - 1
    p = true_prob
    q = 1 - true_prob

    full_kelly = (b * p - q) / b if b > 0 else 0.0

    if full_kelly <= 0:
        return 0.0, 0.0

    frac_kelly   = full_kelly * config.KELLY_FRACTION
    capped_kelly = min(frac_kelly, config.MAX_BET_PCT)

    dollars = round(config.BANKROLL * capped_kelly, 0)
    dollars = max(dollars, 1.0)

    return round(capped_kelly, 4), dollars


def parlay_odds(odds_list: list) -> int:
    """
    Calculate combined American odds for a parlay.
    odds_list: list of American odds integers.
    Returns combined American odds as integer.
    """
    decimal_product = 1.0
    for o in odds_list:
        if o < 0:
            decimal_product *= (1 + 100 / abs(o))
        else:
            decimal_product *= (1 + o / 100)
    # Convert back to American
    if decimal_product >= 2.0:
        return int((decimal_product - 1) * 100)
    else:
        return int(-100 / (decimal_product - 1))


def parlay_payout(units: int, odds_list: list) -> float:
    """Returns total payout in dollars for a parlay."""
    combined = parlay_odds(odds_list)
    stake    = units * unit_size()
    if combined > 0:
        return round(stake * (combined / 100 + 1), 2)
    else:
        return round(stake * (100 / abs(combined) + 1), 2)


def format_units(units: int, alert_type: str) -> str:
    if alert_type == "best_bet":
        return f"**{units}u** Best Bet (${units * unit_size():.0f})"
    return f"**{units}u** Sprinkle (${units * unit_size():.0f})"


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
