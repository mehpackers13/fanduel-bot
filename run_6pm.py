"""
run_6pm.py
==========
Daily 6pm ET parlay builder.
Reads today's best bets from bets_log.csv and sends a parlay suggestion to Discord
if 2+ distinct games qualified as best bets today.
Runs via .github/workflows/afternoon.yml at 22:00 UTC (6pm ET) Mon-Fri.
"""
import csv
import datetime
from pathlib import Path

import config
from discord_alerts import send_parlay_suggestion
from logger import log


def _side_name(row: dict) -> str:
    game = row.get("game", "")
    side = row.get("bet_side", "")
    if not game or not side:
        return side
    parts = game.split(" @ ")
    away = parts[0].strip() if parts else ""
    home = parts[-1].strip() if len(parts) > 1 else ""
    if side == "home":
        return home
    if side == "away":
        return away
    return side.upper()


class _ParlayLeg:
    """Lightweight stand-in for BetOpportunity so send_parlay_suggestion() works."""
    def __init__(self, row: dict):
        game = row.get("game", "")
        parts = game.split(" @ ")
        self.away_team   = parts[0].strip() if parts else ""
        self.home_team   = parts[-1].strip() if len(parts) > 1 else ""
        self.sport       = row.get("sport", "")
        self.bet_type    = row.get("bet_type", "moneyline")
        self.bet_side    = row.get("bet_side", "")
        self.line        = row.get("line", "")
        self.edge_pct    = float(row.get("edge_pct") or 0)
        self.confidence  = int(float(row.get("confidence") or 0))
        self.signals     = [s.strip() for s in row.get("signals", "").split("+") if s.strip()]
        self.alert_type  = "best_bet"
        bet_size         = float(row.get("suggested_bet") or config.UNIT_SIZE * 2)
        self.units       = round(bet_size / config.UNIT_SIZE, 1)
        self.unit_dollars = bet_size


def _todays_best_bets() -> list[_ParlayLeg]:
    """Return best bets logged today (UTC date) from bets_log.csv, de-duped by game."""
    path = config.BETS_LOG
    if not path.exists():
        log("bets_log.csv not found — nothing to build parlay from")
        return []

    # Use both UTC and ET "today" to catch any timezone edge
    today_utc = datetime.datetime.utcnow().strftime("%Y-%m-%d")
    # ET is UTC-4 (EDT) or UTC-5 (EST); April is EDT
    today_et  = (datetime.datetime.utcnow() - datetime.timedelta(hours=4)).strftime("%Y-%m-%d")

    seen_games = set()
    legs = []
    with open(path, newline="") as f:
        for row in csv.DictReader(f):
            ts = row.get("timestamp", "")[:10]
            if ts not in (today_utc, today_et):
                continue
            # Only include best bets (suggested_bet >= 2 units AND confidence >= 60)
            bet_size = float(row.get("suggested_bet") or 0)
            if bet_size < config.UNIT_SIZE * 2:
                continue
            if int(float(row.get("confidence") or 0)) < 60:
                continue
            game = row.get("game", "")
            if game in seen_games:
                continue
            seen_games.add(game)
            legs.append(_ParlayLeg(row))

    return legs


def main() -> None:
    log("=" * 60)
    log("6pm parlay builder starting")
    legs = _todays_best_bets()
    if len(legs) < 2:
        log(f"Only {len(legs)} qualifying best bet(s) today — no parlay suggestion sent")
        log("=" * 60)
        return

    log(f"Building parlay from {len(legs)} best bet(s)")
    try:
        send_parlay_suggestion(legs[:3])   # cap at 3-leg parlays
        log(f"6pm parlay suggestion sent ({len(legs[:3])} legs)")
    except Exception as exc:
        log(f"Parlay send failed: {exc}", "WARN")
    log("=" * 60)


if __name__ == "__main__":
    main()
