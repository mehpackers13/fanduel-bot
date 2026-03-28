"""
EDGE CALCULATOR
===============
Runs all 7 signal checks on a parsed game.
Only returns an alert if:
  1. At least MIN_SIGNALS signals fire
  2. Total confidence score >= MIN_CONFIDENCE
  3. Edge >= MIN_EDGE_PCT

Design: silent by default. Multiple weak signals > one strong signal.
"""
import datetime
from dataclasses import dataclass, field
from typing import Optional

import config
from logger import log
from odds_api import american_to_prob
from action_network import get_public_betting
from espn_api import (get_injuries, get_key_player_out,
                      get_schedule, check_back_to_back,
                      check_3_in_4, check_travel_disadvantage)
from weather_api import get_weather, weather_edge


@dataclass
class BetOpportunity:
    game_id:      str
    sport:        str
    sport_key:    str
    home_team:    str
    away_team:    str
    commence:     str
    hours_out:    float
    bet_type:     str        # "moneyline", "spread", "total"
    bet_side:     str        # "home", "away", "over", "under"
    line:         str        # e.g. "-3.5" or "+145" or "o47.5"
    implied_prob: float
    true_prob:    float
    edge_pct:     float
    confidence:   int        # 0-100
    signals:      list       # list of signal names that fired
    signal_details: dict     # signal name -> description
    reasoning:    str
    kelly_fraction: float    = 0.0
    suggested_bet:  float    = 0.0


def evaluate_game(game: dict) -> Optional[BetOpportunity]:
    """
    Run all signals on a game. Return a BetOpportunity if thresholds met,
    otherwise return None.
    """
    sport_key = game["sport_key"]
    home      = game["home_team"]
    away      = game["away_team"]

    signals        = {}   # name -> description
    confidence     = 0
    best_opp       = None
    best_score     = 0

    # ── 1. Public fade + sharp money ─────────────────────────────────────────
    pub = get_public_betting(home, away, sport_key)
    home_bets = pub.get("home_bets_pct", 50)
    away_bets = pub.get("away_bets_pct", 50)

    # Public fade: 75%+ on one side
    if home_bets >= config.PUBLIC_FADE_THRESHOLD:
        signals["public_fade"] = f"{home_bets:.0f}% public on {home} — fade value on {away}"
        confidence += config.SIGNAL_WEIGHTS["public_fade"]
    elif away_bets >= config.PUBLIC_FADE_THRESHOLD:
        signals["public_fade"] = f"{away_bets:.0f}% public on {away} — fade value on {home}"
        confidence += config.SIGNAL_WEIGHTS["public_fade"]

    # Sharp money: line moves opposite to public
    if pub.get("sharp_side"):
        sharp = pub["sharp_side"]
        signals["sharp_money"] = (
            f"Sharp money on {home if sharp == 'home' else away} — "
            f"line moved opposite to {home_bets:.0f}% public"
        )
        confidence += config.SIGNAL_WEIGHTS["sharp_money"]

    # ── 2. Late injury signal ─────────────────────────────────────────────────
    injuries = get_injuries(sport_key)
    home_out = get_key_player_out(injuries, home)
    away_out = get_key_player_out(injuries, away)

    if home_out:
        names = ", ".join(f"{p['player']} ({p['position']})" for p in home_out[:2])
        signals["late_injury"] = f"{home} key player(s) out: {names}"
        confidence += config.SIGNAL_WEIGHTS["late_injury"]
    if away_out:
        names = ", ".join(f"{p['player']} ({p['position']})" for p in away_out[:2])
        signals["late_injury"] = f"{away} key player(s) out: {names}"
        confidence += config.SIGNAL_WEIGHTS["late_injury"]

    # ── 3. Rest / schedule disadvantage ──────────────────────────────────────
    schedule = get_schedule(sport_key)
    venue    = _get_venue(game)

    home_b2b = check_back_to_back(schedule, home)
    away_b2b = check_back_to_back(schedule, away)
    home_3in4= check_3_in_4(schedule, home)
    away_3in4= check_3_in_4(schedule, away)

    if home_b2b:
        signals["rest_disadvantage"] = f"{home} on back-to-back — fatigue factor"
        confidence += config.SIGNAL_WEIGHTS["rest_disadvantage"]
    elif away_b2b:
        signals["rest_disadvantage"] = f"{away} on back-to-back — fatigue factor"
        confidence += config.SIGNAL_WEIGHTS["rest_disadvantage"]
    elif home_3in4:
        signals["rest_disadvantage"] = f"{home} playing 3rd game in 4 nights"
        confidence += config.SIGNAL_WEIGHTS["rest_disadvantage"]
    elif away_3in4:
        signals["rest_disadvantage"] = f"{away} playing 3rd game in 4 nights"
        confidence += config.SIGNAL_WEIGHTS["rest_disadvantage"]

    # ── 4. Travel disadvantage ────────────────────────────────────────────────
    if venue:
        if check_travel_disadvantage(schedule, away, venue):
            signals["travel_disadvantage"] = f"{away} cross-country travel to {venue}"
            confidence += config.SIGNAL_WEIGHTS["travel_disadvantage"]

    # ── 5. Weather edge (NFL/MLB outdoor only) ────────────────────────────────
    if sport_key in config.OUTDOOR_SPORTS and venue:
        wx   = get_weather(venue)
        has_wx, wx_desc = weather_edge(wx, sport_key)
        if has_wx:
            signals["weather_edge"] = wx_desc
            confidence += config.SIGNAL_WEIGHTS["weather_edge"]

    # ── Gate check: need MIN_SIGNALS and MIN_CONFIDENCE ───────────────────────
    if len(signals) < config.MIN_SIGNALS:
        return None
    if confidence < config.MIN_CONFIDENCE:
        return None

    # ── Find the best betting line given our signals ──────────────────────────
    opp = _find_best_bet(game, signals, confidence, home_out, away_out, pub)
    return opp


def _find_best_bet(game: dict, signals: dict, confidence: int,
                   home_out: list, away_out: list, pub: dict) -> Optional[BetOpportunity]:
    """Given signals, find the specific bet with the largest edge."""
    home = game["home_team"]
    away = game["away_team"]
    candidates = []

    # Determine which side signals favor
    fade_home  = "public_fade" in signals and "fade value on" + " " + away in signals.get("public_fade","")
    sharp_away = pub.get("sharp_side") == "away"
    sharp_home = pub.get("sharp_side") == "home"
    injury_home= "late_injury" in signals and home in signals["late_injury"]
    injury_away= "late_injury" in signals and away in signals["late_injury"]
    weather    = "weather_edge" in signals

    # Moneyline candidates
    h2h = game.get("h2h", {})
    if h2h:
        # Home moneyline
        if (sharp_home or (injury_away and not injury_home)):
            edge = h2h["true_home_prob"] - h2h["home_prob"]
            if edge * 100 >= config.MIN_EDGE_PCT:
                candidates.append(("moneyline", "home", f"+{h2h['best_home_odds']}" if h2h['best_home_odds'] > 0 else str(h2h['best_home_odds']), h2h["home_prob"], h2h["true_home_prob"]))
        # Away moneyline
        if (fade_home or sharp_away or (injury_home and not injury_away)):
            edge = h2h["true_away_prob"] - h2h["away_prob"]
            if edge * 100 >= config.MIN_EDGE_PCT:
                candidates.append(("moneyline", "away", f"+{h2h['best_away_odds']}" if h2h['best_away_odds'] > 0 else str(h2h['best_away_odds']), h2h["away_prob"], h2h["true_away_prob"]))

    # Totals — weather or rest pushes toward under
    total = game.get("total", {})
    if total and weather:
        edge_under = total["under_prob"] - 0.5   # simple: assume line is 50/50 in perfect info
        if edge_under * 100 >= config.MIN_EDGE_PCT:
            candidates.append(("total", "under", f"u{total['line']}", total["under_prob"], total["under_prob"] + 0.05))

    # Spread candidates
    spread = game.get("spread", {})
    if spread and (sharp_away or fade_home or injury_home):
        edge = spread["true_away_prob"] - spread["away_prob"]
        if edge * 100 >= config.MIN_EDGE_PCT:
            pt = spread.get("spread_point", 0)
            candidates.append(("spread", "away", f"+{-pt}" if pt < 0 else f"-{pt}", spread["away_prob"], spread["true_away_prob"]))

    if not candidates:
        return None

    # Pick the best (highest edge)
    bet_type, bet_side, line, implied, true_p = max(candidates, key=lambda x: x[4] - x[3])
    edge_pct = round((true_p - implied) * 100, 1)

    # Build reasoning
    signal_list  = list(signals.keys())
    signal_descs = list(signals.values())
    reasoning    = _build_reasoning(game, bet_type, bet_side, signals, edge_pct)

    # Kelly sizing
    from kelly import kelly_bet_size
    kelly_f, suggested = kelly_bet_size(true_p, implied)

    return BetOpportunity(
        game_id       = game["game_id"],
        sport         = game["sport"],
        sport_key     = game["sport_key"],
        home_team     = home,
        away_team     = away,
        commence      = game["commence"],
        hours_out     = game["hours_out"],
        bet_type      = bet_type,
        bet_side      = bet_side,
        line          = line,
        implied_prob  = round(implied, 4),
        true_prob     = round(true_p,  4),
        edge_pct      = edge_pct,
        confidence    = min(confidence, 100),
        signals       = signal_list,
        signal_details= signals,
        reasoning     = reasoning,
        kelly_fraction= kelly_f,
        suggested_bet = suggested,
    )


def _get_venue(game: dict) -> str:
    """Extract city from game data (home team city approximation)."""
    # In real usage, ESPN schedule data would give us the exact venue city.
    # As a fallback, we use the home team name to infer city.
    team_cities = {
        "Chicago Bears": "chicago",         "Green Bay Packers": "green bay",
        "Kansas City Chiefs": "kansas city", "Buffalo Bills": "buffalo",
        "Dallas Cowboys": "dallas",          "Denver Broncos": "denver",
        "Miami Dolphins": "miami",           "New England Patriots": "foxborough",
        "Seattle Seahawks": "seattle",       "San Francisco 49ers": "santa clara",
        "New York Giants": "east rutherford","New York Jets": "east rutherford",
        "Los Angeles Rams": "inglewood",     "Los Angeles Chargers": "inglewood",
        "Chicago Cubs": "chicago",           "Chicago White Sox": "chicago",
        "New York Yankees": "new york",      "Boston Red Sox": "boston",
        "Los Angeles Dodgers": "los angeles","San Francisco Giants": "san francisco",
    }
    return team_cities.get(game.get("home_team", ""), "")


def _build_reasoning(game: dict, bet_type: str, bet_side: str,
                     signals: dict, edge_pct: float) -> str:
    side_name = game["home_team"] if bet_side == "home" else (
                game["away_team"] if bet_side == "away" else bet_side.upper())
    parts = [f"Edge {edge_pct:.1f}% on {side_name} {bet_type}."]
    for desc in list(signals.values())[:2]:
        parts.append(desc + ".")
    return " ".join(parts)
