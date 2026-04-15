"""
OUTCOMES TRACKER
================
Logs every alert to bets_log.csv.
Outcomes are auto-resolved by checking ESPN scores after games complete.
After 30+ outcomes, self_improve.py uses this data to tune signal weights.
"""
import csv
import datetime
from pathlib import Path
from typing import Optional

import config
from logger import log

FIELDS = [
    "timestamp", "sport", "game", "bet_type", "bet_side", "line",
    "edge_pct", "confidence", "signals", "suggested_bet",
    "implied_prob", "true_prob", "reasoning",
    "game_id",    # ESPN game ID for auto-resolving outcomes
    "sport_key",  # ESPN sport key (e.g. "basketball_nba")
    "outcome",    # auto-filled: W / L / P / blank (pending)
    "profit_loss",
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
        "game_id":      getattr(opp, "game_id", ""),
        "sport_key":    getattr(opp, "sport_key", ""),
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


# ── Auto-resolve helpers ──────────────────────────────────────────────────────

def _rewrite_log(rows: list) -> None:
    """Rewrite the entire CSV with updated rows (preserves all columns)."""
    with open(config.BETS_LOG, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def _determine_outcome(bet_type: str, bet_side: str, line_str,
                       home_score: float, away_score: float) -> Optional[str]:
    """
    Returns "W", "L", or "P" given the final home/away scores.
    bet_type: moneyline / spread / total
    bet_side: home team name / away team name / "over" / "under"
    line_str: numeric line (e.g. -3.5, 47.5, or "" for moneyline)
    """
    try:
        bet_type = (bet_type or "").lower()
        bet_side = (bet_side or "").lower()

        if "moneyline" in bet_type or "ml" in bet_type:
            if home_score == away_score:
                return "P"
            home_won = home_score > away_score
            # bet_side contains a team name fragment; match "home" or "away" side
            # We stored bet_side as the team name in edge_calculator
            # Check if the bet is on the home team
            # Since we don't know team names here, use a convention:
            # edge_calculator stores bet_side as the actual team name
            # We'll compare against "home" keyword or just return None to skip
            return None  # needs team name context — skip for now

        if "spread" in bet_type:
            try:
                line = float(line_str)
            except (TypeError, ValueError):
                return None
            # Spread is always expressed from the favourite's perspective
            # bet_side tells us which team we bet on
            # Convention: if bet_side contains "home", we cover if home + line > away
            if "home" in bet_side:
                covered = (home_score + line) > away_score
                push    = (home_score + line) == away_score
            else:
                covered = (away_score + line) > home_score
                push    = (away_score + line) == home_score
            if push:
                return "P"
            return "W" if covered else "L"

        if "total" in bet_type or "over" in bet_side or "under" in bet_side:
            try:
                line = float(str(line_str).lstrip("oOuU"))
            except (TypeError, ValueError):
                return None
            total = home_score + away_score
            if total == line:
                return "P"
            if "over" in bet_side:
                return "W" if total > line else "L"
            if "under" in bet_side:
                return "W" if total < line else "L"

    except Exception as exc:
        log(f"_determine_outcome error: {exc}", "WARN")
    return None


def auto_resolve_outcomes() -> int:
    """
    Check ESPN scores for all pending bets and fill in outcome + profit_loss.
    Returns number of bets resolved.
    """
    import espn_core_api

    rows = read_all()
    resolved = 0

    for row in rows:
        if row.get("outcome") in ("W", "L", "P"):
            continue  # already resolved

        game_id  = row.get("game_id", "")
        sport_key = row.get("sport_key", "")
        if not game_id or not sport_key:
            continue  # no ESPN data stored

        try:
            result = espn_core_api.get_game_result(game_id, sport_key)
        except Exception as exc:
            log(f"ESPN lookup error for {game_id}: {exc}", "WARN")
            continue

        if not result or not result.get("completed"):
            continue  # game not finished yet

        # Only resolve bets logged >= 3 hours ago (game needs time to complete)
        try:
            ts_str = row.get("timestamp", "")[:16]  # "2026-04-13 21:55"
            bet_ts = datetime.datetime.strptime(ts_str, "%Y-%m-%d %H:%M")
            # Timestamps stored as ET (UTC-4); convert to UTC for comparison
            bet_ts_utc = bet_ts + datetime.timedelta(hours=4)
            if datetime.datetime.utcnow() < bet_ts_utc + datetime.timedelta(hours=3):
                continue  # too soon — check again later
        except Exception:
            pass  # if we can't parse the timestamp, proceed with resolution

        home_score = result["home_score"]
        away_score = result["away_score"]

        outcome = _determine_outcome(
            row.get("bet_type", ""),
            row.get("bet_side", ""),
            row.get("line", ""),
            home_score,
            away_score,
        )

        if outcome is None:
            # Moneyline: determine by matching team name to home/away
            bet_side_lower = (row.get("bet_side") or "").lower()
            home_team_lower = result.get("home_team", "").lower()
            away_team_lower = result.get("away_team", "").lower()
            if home_score == away_score:
                outcome = "P"
            elif any(part in bet_side_lower for part in home_team_lower.split() if len(part) > 3):
                outcome = "W" if home_score > away_score else "L"
            elif any(part in bet_side_lower for part in away_team_lower.split() if len(part) > 3):
                outcome = "W" if away_score > home_score else "L"
            else:
                continue  # can't match team — leave pending

        row["outcome"] = outcome

        # Calculate profit/loss
        try:
            bet_amt   = float(row.get("suggested_bet") or 0)
            imp_prob  = float(row.get("implied_prob") or 0) / 100
            if bet_amt > 0 and imp_prob > 0:
                payout = bet_amt * (1 / imp_prob - 1)
                if outcome == "W":
                    row["profit_loss"] = round(payout, 2)
                elif outcome == "L":
                    row["profit_loss"] = round(-bet_amt, 2)
                else:
                    row["profit_loss"] = 0.0
        except Exception:
            pass

        resolved += 1
        log(f"Auto-resolved {game_id}: {row.get('game')} → {outcome} "
            f"(home {home_score}, away {away_score})")

    if resolved:
        _rewrite_log(rows)
        log(f"Wrote {resolved} auto-resolved outcome(s) to {config.BETS_LOG}")

    return resolved
