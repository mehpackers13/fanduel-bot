"""
OUTCOMES TRACKER
================
Logs every alert to bets_log.csv.
You fill in the 'outcome' column (W/L/P) manually after each game.
After 30+ outcomes, self_improve.py uses this data to tune signal weights.
"""
import csv
import datetime
from pathlib import Path

import config
from logger import log

FIELDS = [
    "timestamp", "sport", "game", "bet_type", "bet_side", "line",
    "edge_pct", "confidence", "signals", "suggested_bet",
    "implied_prob", "true_prob", "reasoning",
    "outcome",      # fill in: W / L / P (push) / blank
    "profit_loss",  # fill in after result
    "notes",
]


def ensure_log() -> None:
    if not config.BETS_LOG.exists():
        with open(config.BETS_LOG, "w", newline="") as f:
            csv.DictWriter(f, fieldnames=FIELDS).writeheader()
        log(f"Created bets log at {config.BETS_LOG}")


def log_opportunity(opp) -> None:
    ensure_log()
    import datetime as dt
    tz  = datetime.timezone(datetime.timedelta(hours=-4))
    row = {
        "timestamp":    dt.datetime.now(tz).strftime("%Y-%m-%d %H:%M ET"),
        "sport":        opp.sport,
        "game":         f"{opp.away_team} @ {opp.home_team}",
        "bet_type":     opp.bet_type,
        "bet_side":     opp.bet_side,
        "line":         opp.line,
        "edge_pct":     opp.edge_pct,
        "confidence":   opp.confidence,
        "signals":      " + ".join(opp.signals),
        "suggested_bet":opp.suggested_bet,
        "implied_prob": round(opp.implied_prob * 100, 1),
        "true_prob":    round(opp.true_prob * 100, 1),
        "reasoning":    opp.reasoning,
        "outcome":      "",
        "profit_loss":  "",
        "notes":        "",
    }
    with open(config.BETS_LOG, "a", newline="") as f:
        csv.DictWriter(f, fieldnames=FIELDS).writerow(row)


def read_all() -> list:
    ensure_log()
    with open(config.BETS_LOG, newline="") as f:
        return list(csv.DictReader(f))


def completed_bets() -> list:
    return [r for r in read_all() if r.get("outcome") in ("W", "L", "P")]


def win_rate(bets: list = None) -> float:
    rows = bets or completed_bets()
    if not rows:
        return 0.0
    wins = sum(1 for r in rows if r.get("outcome") == "W")
    return round(wins / len(rows) * 100, 1)


def roi(bets: list = None) -> float:
    rows = bets or completed_bets()
    if not rows:
        return 0.0
    total_pl     = sum(float(r.get("profit_loss") or 0) for r in rows)
    total_risked = sum(float(r.get("suggested_bet") or 0) for r in rows)
    if total_risked == 0:
        return 0.0
    return round(total_pl / total_risked * 100, 1)
