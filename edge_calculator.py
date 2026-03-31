"""
EDGE CALCULATOR
===============
Runs all signal checks on a parsed game.
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
from espn_api import (get_key_player_out,
                      check_back_to_back,
                      check_3_in_4, check_travel_disadvantage)
import espn_core_api
from weather_api import get_weather, weather_edge
from kelly import kelly_units, kelly_bet_size, unit_size


@dataclass
class BetOpportunity:
    game_id:        str
    sport:          str
    sport_key:      str
    home_team:      str
    away_team:      str
    commence:       str
    hours_out:      float
    bet_type:       str         # "moneyline", "spread", "total"
    bet_side:       str         # "home", "away", "over", "under"
    line:           str         # e.g. "-3.5" or "+145" or "o47.5"
    implied_prob:   float
    true_prob:      float
    edge_pct:       float
    confidence:     int         # 0-100
    signals:        list        # list of signal names that fired
    signal_details: dict        # signal name -> description
    reasoning:      str
    kelly_fraction: float = 0.0
    suggested_bet:  float = 0.0
    alert_type:     str   = ""  # "best_bet" or "sprinkle"
    units:          int   = 0   # 1 for sprinkle, 2-4 for best_bet
    unit_dollars:   float = 0.0 # units * unit_size()


def _classify_alert(edge_pct: float, confidence: int, signal_count: int) -> Optional[str]:
    """
    Determine alert type based on edge, confidence, and signal count.
    Returns "best_bet", "sprinkle", or None.

    Thresholds:
      best_bet  — conf ≥ 65, edge ≥ 8%, ≥ 2 signals  (strong stack)
      sprinkle  — conf ≥ 35, edge ≥ 5%, ≥ 1 signal   (single strong signal OK)
    """
    if confidence >= 65 and edge_pct >= 8.0 and signal_count >= 2:
        return "best_bet"
    if confidence >= 35 and edge_pct >= 5.0:
        return "sprinkle"
    return None


def _ufc_signals(game: dict) -> dict:
    """
    Detect UFC-specific signals from game metadata.
    Returns dict of signal_name -> description.
    """
    signals = {}
    ufc_data = game.get("ufc_signals", {})

    # Significant strike differential
    strike_diff = ufc_data.get("strike_differential")
    if strike_diff is not None and abs(strike_diff) >= 1.5:
        favored = game["home_team"] if strike_diff > 0 else game["away_team"]
        signals["ufc_strike_diff"] = (
            f"{favored} has significant strike differential of {abs(strike_diff):.1f} per round"
        )

    # Reach advantage
    reach_adv = ufc_data.get("reach_advantage")
    if reach_adv is not None and abs(reach_adv) >= 3:
        favored = game["home_team"] if reach_adv > 0 else game["away_team"]
        signals["ufc_reach_adv"] = (
            f"{favored} has {abs(reach_adv):.0f}\" reach advantage"
        )

    # Weight miss / cut news (keyword match from injury details)
    injuries = game.get("injury_notes", [])
    weight_keywords = ["weight", "cut", "miss", "overweight", "lb"]
    for note in injuries:
        note_lower = str(note).lower()
        if any(kw in note_lower for kw in weight_keywords):
            signals["ufc_weight_miss"] = (
                f"Weight cut / miss concern noted: {str(note)[:80]}"
            )
            break

    # Finishing rate mismatch (finisher vs decision-maker)
    home_finish = ufc_data.get("home_finish_rate", 0)
    away_finish = ufc_data.get("away_finish_rate", 0)
    if home_finish and away_finish:
        diff = abs(home_finish - away_finish)
        if diff >= 0.25:
            finisher  = game["home_team"] if home_finish > away_finish else game["away_team"]
            decider   = game["away_team"] if home_finish > away_finish else game["home_team"]
            signals["ufc_finish_rate"] = (
                f"{finisher} finishes {home_finish if home_finish > away_finish else away_finish:.0%} "
                f"vs {decider} decision rate — finish prop value"
            )

    return signals


def evaluate_game(game: dict) -> Optional[BetOpportunity]:
    """
    Run all signals on a game. Return a BetOpportunity if thresholds met,
    otherwise return None.
    """
    sport_key = game["sport_key"]
    home      = game["home_team"]
    away      = game["away_team"]

    signals    = {}   # name -> description
    confidence = 0

    # ── 1. Public fade + sharp money ─────────────────────────────────────────
    pub = get_public_betting(home, away, sport_key)
    home_bets = pub.get("home_bets_pct", 50)
    away_bets = pub.get("away_bets_pct", 50)

    # Public fade: 75%+ on one side
    if home_bets >= config.PUBLIC_FADE_THRESHOLD:
        signals["public_fade"] = f"{home_bets:.0f}% public on {home} -- fade value on {away}"
        confidence += config.SIGNAL_WEIGHTS["public_fade"]
    elif away_bets >= config.PUBLIC_FADE_THRESHOLD:
        signals["public_fade"] = f"{away_bets:.0f}% public on {away} -- fade value on {home}"
        confidence += config.SIGNAL_WEIGHTS["public_fade"]

    # Sharp money: ESPN built-in line movement (open vs current spread/ML)
    is_sharp, sharp_desc, espn_sharp_side = espn_core_api.check_line_movement_sharp(game)
    if is_sharp:
        signals["sharp_money"] = sharp_desc
        confidence += config.SIGNAL_WEIGHTS["sharp_money"]
    elif pub.get("sharp_side"):
        # Fall back to Action Network divergence-based sharp side
        sharp = pub["sharp_side"]
        signals["sharp_money"] = (
            f"Sharp money on {home if sharp == 'home' else away} -- "
            f"line moved opposite to {home_bets:.0f}% public"
        )
        confidence += config.SIGNAL_WEIGHTS["sharp_money"]
        espn_sharp_side = None   # AN is handling direction; clear ESPN side

    # ── 2. Late injury signal ─────────────────────────────────────────────────
    injuries  = espn_core_api.get_injuries(sport_key)
    home_out  = get_key_player_out(injuries, home)
    away_out  = get_key_player_out(injuries, away)

    if home_out:
        names = ", ".join(f"{p['player']} ({p['position']})" for p in home_out[:2])
        signals["late_injury"] = f"{home} key player(s) out: {names}"
        confidence += config.SIGNAL_WEIGHTS["late_injury"]
    if away_out:
        names = ", ".join(f"{p['player']} ({p['position']})" for p in away_out[:2])
        signals["late_injury"] = f"{away} key player(s) out: {names}"
        confidence += config.SIGNAL_WEIGHTS["late_injury"]

    # ── 3. Rest / schedule disadvantage ──────────────────────────────────────
    schedule = espn_core_api.get_recent_schedule(sport_key)
    venue    = game.get("venue_city") or _get_venue(game)

    home_b2b = check_back_to_back(schedule, home)
    away_b2b = check_back_to_back(schedule, away)
    home_3in4= check_3_in_4(schedule, home)
    away_3in4= check_3_in_4(schedule, away)

    if home_b2b:
        signals["rest_disadvantage"] = f"{home} on back-to-back -- fatigue factor"
        confidence += config.SIGNAL_WEIGHTS["rest_disadvantage"]
    elif away_b2b:
        signals["rest_disadvantage"] = f"{away} on back-to-back -- fatigue factor"
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

    # ── 6. UFC-specific signals ───────────────────────────────────────────────
    if sport_key == "mma_mixed_martial_arts":
        ufc_sigs = _ufc_signals(game)
        for sig_name, sig_desc in ufc_sigs.items():
            signals[sig_name] = sig_desc
            confidence += config.SIGNAL_WEIGHTS.get(sig_name, 15)

    # ── Diagnostic log: always show what was found per game ──────────────────
    sig_names = list(signals.keys()) if signals else []
    pub_pct   = f"pub={home_bets:.0f}%/{away_bets:.0f}%" if pub else "pub=n/a"
    lm        = game.get("line_movement", {})
    ml_note   = ""
    if lm.get("open_home_ml") and lm.get("current_home_ml"):
        ml_note = f" ml_move={lm['open_home_ml']}→{lm['current_home_ml']}"
    log(
        f"  [{away} @ {home}] sigs={sig_names} conf={confidence} "
        f"{pub_pct}{ml_note}",
        "DEBUG"
    )

    # ── Gate check: need MIN_SIGNALS and MIN_CONFIDENCE ───────────────────────
    if len(signals) < config.MIN_SIGNALS:
        log(
            f"    ✗ {away} @ {home} — only {len(signals)}/{config.MIN_SIGNALS} signals "
            f"(need {config.MIN_SIGNALS - len(signals)} more)",
            "DEBUG"
        )
        return None
    if confidence < config.MIN_CONFIDENCE:
        log(
            f"    ✗ {away} @ {home} — conf {confidence} < {config.MIN_CONFIDENCE} threshold",
            "DEBUG"
        )
        return None

    # ── Find the best betting line given our signals ──────────────────────────
    opp = _find_best_bet(game, signals, confidence, home_out, away_out, pub)
    if opp is None:
        log(
            f"    ✗ {away} @ {home} — signals passed but no qualifying bet line found "
            f"(edge below {config.MIN_EDGE_PCT}% or no odds for signal side)",
            "DEBUG"
        )
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

    # ESPN sharp direction fallback when Action Network is blocked (no pub sharp_side)
    if not (sharp_home or sharp_away) and "sharp_money" in signals:
        lm = game.get("line_movement", {})
        open_ml  = lm.get("open_home_ml")
        curr_ml  = lm.get("current_home_ml")
        open_sp  = lm.get("open_spread")
        curr_sp  = lm.get("current_spread")
        if open_ml is not None and curr_ml is not None:
            delta = curr_ml - open_ml
            if abs(delta) >= 25:
                sharp_home = delta < 0   # home became more favored
                sharp_away = delta > 0
        elif open_sp is not None and curr_sp is not None:
            sharp_home = curr_sp < open_sp  # home giving fewer points = sharp on home
            sharp_away = curr_sp > open_sp
    injury_home= "late_injury" in signals and home in signals["late_injury"]
    injury_away= "late_injury" in signals and away in signals["late_injury"]
    weather    = "weather_edge" in signals

    # Moneyline candidates
    h2h = game.get("h2h", {})
    if h2h:
        # Home moneyline
        if sharp_home or (injury_away and not injury_home):
            home_odds_val = h2h.get("best_home_odds", h2h.get("home_odds", 0))
            # Apply ML restrictions
            if config.ML_MIN_ODDS <= home_odds_val <= config.ML_MAX_ODDS:
                edge = h2h["true_home_prob"] - h2h["home_prob"]
                if edge * 100 >= config.MIN_EDGE_PCT:
                    line_str = (f"+{home_odds_val}" if home_odds_val > 0
                                else str(home_odds_val))
                    candidates.append(("moneyline", "home", line_str,
                                       h2h["home_prob"], h2h["true_home_prob"]))

        # Away moneyline
        if fade_home or sharp_away or (injury_home and not injury_away):
            away_odds_val = h2h.get("best_away_odds", h2h.get("away_odds", 0))
            # Apply ML restrictions
            if config.ML_MIN_ODDS <= away_odds_val <= config.ML_MAX_ODDS:
                edge = h2h["true_away_prob"] - h2h["away_prob"]
                if edge * 100 >= config.MIN_EDGE_PCT:
                    line_str = (f"+{away_odds_val}" if away_odds_val > 0
                                else str(away_odds_val))
                    candidates.append(("moneyline", "away", line_str,
                                       h2h["away_prob"], h2h["true_away_prob"]))

    # Totals -- weather or rest pushes toward under
    total = game.get("total", {})
    if total and weather:
        edge_under = total["under_prob"] - 0.5  # simple: assume line is 50/50 in perfect info
        if edge_under * 100 >= config.MIN_EDGE_PCT:
            candidates.append(("total", "under", f"u{total['line']}",
                                total["under_prob"], total["under_prob"] + 0.05))

    # Spread candidates
    spread = game.get("spread", {})
    if spread and (sharp_away or fade_home or injury_home):
        edge = spread["true_away_prob"] - spread["away_prob"]
        if edge * 100 >= config.MIN_EDGE_PCT:
            pt = spread.get("spread_point", 0)
            line_str = f"+{-pt}" if pt < 0 else f"-{pt}"
            candidates.append(("spread", "away", line_str,
                                spread["away_prob"], spread["true_away_prob"]))

    if not candidates:
        return None

    # Pick the best (highest edge)
    bet_type, bet_side, line, implied, true_p = max(candidates, key=lambda x: x[4] - x[3])
    edge_pct = round((true_p - implied) * 100, 1)

    # Classify alert type
    signal_count = len(signals)
    alert_type = _classify_alert(edge_pct, confidence, signal_count)
    if alert_type is None:
        return None

    # Build reasoning
    signal_list  = list(signals.keys())
    reasoning    = _build_reasoning(game, bet_type, bet_side, signals, edge_pct)

    # Unit-based Kelly sizing
    units_val, unit_dol, _atype = kelly_units(true_p, implied)
    if units_val == 0:
        # Fall back to alert_type-based sizing
        if alert_type == "best_bet":
            units_val = config.BEST_BET_MIN_UNITS
        else:
            units_val = config.SPRINKLE_UNITS
        unit_dol = round(units_val * unit_size(), 2)

    # Determine unit count based on alert type
    if alert_type == "best_bet":
        final_units = max(config.BEST_BET_MIN_UNITS,
                          min(int(units_val), config.BEST_BET_MAX_UNITS))
    else:
        final_units = config.SPRINKLE_UNITS

    final_unit_dollars = round(final_units * unit_size(), 2)

    # Legacy kelly fields for backward compatibility
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
        alert_type    = alert_type,
        units         = final_units,
        unit_dollars  = final_unit_dollars,
    )


def _get_venue(game: dict) -> str:
    """Extract city from game data (home team city approximation)."""
    team_cities = {
        "Chicago Bears":          "chicago",
        "Green Bay Packers":      "green bay",
        "Kansas City Chiefs":     "kansas city",
        "Buffalo Bills":          "buffalo",
        "Dallas Cowboys":         "dallas",
        "Denver Broncos":         "denver",
        "Miami Dolphins":         "miami",
        "New England Patriots":   "foxborough",
        "Seattle Seahawks":       "seattle",
        "San Francisco 49ers":    "santa clara",
        "New York Giants":        "east rutherford",
        "New York Jets":          "east rutherford",
        "Los Angeles Rams":       "inglewood",
        "Los Angeles Chargers":   "inglewood",
        "Chicago Cubs":           "chicago",
        "Chicago White Sox":      "chicago",
        "New York Yankees":       "new york",
        "Boston Red Sox":         "boston",
        "Los Angeles Dodgers":    "los angeles",
        "San Francisco Giants":   "san francisco",
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
