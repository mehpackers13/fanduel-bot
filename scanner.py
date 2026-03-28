"""
MAIN SCANNER
============
Fetches all active sports, parses games, runs edge detection.
Silent by default -- only alerts when genuine multi-signal edges found.

Primary source: ESPN Core API (free, no key needed).
Fallback: The Odds API (props-only, 5 req/day limit).

Daily limits tracked in data/daily_state.json.
"""
import json
import datetime
import config
from logger import log
from odds_api import get_odds, parse_game
import espn_core_api
from edge_calculator import evaluate_game, BetOpportunity
from outcomes import log_opportunity, ensure_log
from discord_alerts import send_bet_alert, send_sprinkle_alert, send_parlay_suggestion
from bankroll import bet_summary
import kelly as kelly_mod


# ── Daily state ───────────────────────────────────────────────────────────────

def _load_daily_state() -> dict:
    """Load or initialise the daily state JSON."""
    config.DATA_DIR.mkdir(exist_ok=True)
    today = datetime.datetime.utcnow().strftime("%Y-%m-%d")
    default = {
        "date":           today,
        "alerts_sent":    0,
        "best_bets_sent": 0,
        "sprinkles_sent": 0,
        "units_at_risk":  0,
    }
    path = config.DAILY_STATE_JSON
    if path.exists():
        try:
            state = json.loads(path.read_text())
            # Reset if it's a new day
            if state.get("date") != today:
                state = default.copy()
                _save_daily_state(state)
            return state
        except Exception:
            pass
    _save_daily_state(default)
    return default


def _save_daily_state(state: dict) -> None:
    config.DATA_DIR.mkdir(exist_ok=True)
    config.DAILY_STATE_JSON.write_text(json.dumps(state, indent=2))


def _can_send_alert(state: dict, opp: BetOpportunity) -> bool:
    """Return True if daily limits allow sending this alert."""
    if state["alerts_sent"] >= config.MAX_ALERTS_PER_DAY:
        log(f"  Daily alert cap reached ({config.MAX_ALERTS_PER_DAY}) — skipping", "WARN")
        return False
    if state["units_at_risk"] + opp.units > config.MAX_UNITS_PER_DAY:
        log(f"  Daily units cap would be exceeded ({state['units_at_risk']}u + {opp.units}u > {config.MAX_UNITS_PER_DAY}u) — skipping", "WARN")
        return False
    if opp.alert_type == "best_bet" and state["best_bets_sent"] >= config.MAX_BEST_BETS_PER_DAY:
        log(f"  Best bet cap reached ({config.MAX_BEST_BETS_PER_DAY}) — skipping", "WARN")
        return False
    if opp.alert_type == "sprinkle" and state["sprinkles_sent"] >= config.MAX_SPRINKLES_PER_DAY:
        log(f"  Sprinkle cap reached ({config.MAX_SPRINKLES_PER_DAY}) — skipping", "WARN")
        return False
    return True


def _record_alert(state: dict, opp: BetOpportunity) -> None:
    """Update daily state after an alert is sent."""
    state["alerts_sent"]   += 1
    state["units_at_risk"] += opp.units
    if opp.alert_type == "best_bet":
        state["best_bets_sent"] += 1
    elif opp.alert_type == "sprinkle":
        state["sprinkles_sent"] += 1
    _save_daily_state(state)


# ── Game fetching ─────────────────────────────────────────────────────────────

def _fetch_games(sport_key: str) -> tuple:
    """
    Fetch games for a sport. Uses ESPN Core API as primary source.
    Only falls back to The Odds API if ESPN returns an error/timeout
    (not when it returns 0 games — that just means nothing is scheduled).
    Returns (games: list, source: str).
    """
    # Try ESPN Core API first (free, no key, no rate limits)
    try:
        games = espn_core_api.get_games(sport_key)
        # games == [] is valid (no games today); only fall back on exception
        return games, "espn"
    except Exception as exc:
        log(f"  ESPN Core API error for {sport_key}: {exc} — falling back to Odds API", "WARN")

    # Fall back to Odds API only on ESPN error/timeout
    if config.ODDS_API_KEY and _daily_odds_api_ok():
        raw = get_odds(sport_key)
        games = [g for g in (parse_game(r, sport_key) for r in raw) if g]
        return games, "odds_api"

    return [], "none"


def _daily_odds_api_ok() -> bool:
    """Return True if we have Odds API daily budget remaining."""
    import json as _json
    path = config.DATA_DIR / "odds_api_daily.json"
    today = datetime.datetime.utcnow().strftime("%Y-%m-%d")
    try:
        if path.exists():
            data = _json.loads(path.read_text())
            if data.get("date") == today:
                return data.get("count", 0) < config.ODDS_API_DAILY_LIMIT
    except Exception:
        pass
    return True


# ── Parlay suggestion ─────────────────────────────────────────────────────────

def _maybe_send_parlay(best_bets_alerted: list) -> None:
    """
    If 2-3 best bets have been alerted this session, send a parlay suggestion.
    Only fires after individual alerts have been sent.
    """
    if len(best_bets_alerted) < 2 or len(best_bets_alerted) > 3:
        return
    try:
        send_parlay_suggestion(best_bets_alerted)
        log(f"Parlay suggestion sent for {len(best_bets_alerted)} legs")
    except Exception as exc:
        log(f"Parlay suggestion failed: {exc}", "WARN")


# ── Main scan ─────────────────────────────────────────────────────────────────

def run_scan(morning_mode: bool = False) -> list:
    """
    Full scan. Returns list of BetOpportunity objects that were alerted.
    morning_mode=True returns top opportunities without re-alerting (for briefing).
    """
    ensure_log()
    log("=" * 60)
    log(f"Starting {'morning' if morning_mode else 'full'} scan")
    log(bet_summary())

    all_opps    = []
    total_games = 0

    for sport_key in config.SPORT_KEYS:
        games, source = _fetch_games(sport_key)
        if not games:
            continue

        total_games += len(games)
        log(f"  {sport_key}: {len(games)} games from {source}")

        for game in games:
            try:
                opp = evaluate_game(game)
                if opp:
                    all_opps.append(opp)
            except Exception as exc:
                log(f"  Error evaluating {game.get('home_team','?')}: {exc}", "WARN")

    # Sort: best_bets first by confidence, then sprinkles by confidence
    def _sort_key(o):
        type_order = 0 if o.alert_type == "best_bet" else 1
        return (type_order, -o.confidence, -o.edge_pct)

    all_opps.sort(key=_sort_key)

    if morning_mode:
        log(f"Morning scan complete -- {total_games} games checked, {len(all_opps)} opportunities")
        return all_opps

    # Alert on qualifying opportunities, respecting daily limits
    state            = _load_daily_state()
    alerted          = 0
    best_bets_alerted = []

    for opp in all_opps:
        if not _can_send_alert(state, opp):
            continue

        try:
            if opp.alert_type == "best_bet":
                send_bet_alert(opp)
                best_bets_alerted.append(opp)
            else:
                send_sprinkle_alert(opp)

            log_opportunity(opp)
            _record_alert(state, opp)
            alerted += 1
        except Exception as exc:
            log(f"  Alert send error for {opp.home_team}: {exc}", "WARN")

    # Parlay suggestion if 2-3 best bets were sent this session
    if best_bets_alerted:
        _maybe_send_parlay(best_bets_alerted)

    if alerted == 0:
        log(f"Scan complete -- {total_games} games checked, 0 alerts (silence = discipline)")
    else:
        log(f"Scan complete -- {total_games} games checked, {alerted} alert(s) sent "
            f"({state['units_at_risk']}u at risk today)")

    log("=" * 60)
    return all_opps
