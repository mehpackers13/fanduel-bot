"""
THE ODDS API WRAPPER
====================
Free tier: 500 requests/month. This wrapper tracks usage and caches
responses for 2 hours so we stay well within the limit.

Setup: add ODDS_API_KEY as GitHub Secret (get free key at the-odds-api.com).
"""
import json
import datetime
import time
from typing import Optional

import requests

import config
from logger import log


# ── API usage tracking ────────────────────────────────────────────────────────

def _load_usage() -> dict:
    config.DATA_DIR.mkdir(exist_ok=True)
    if config.API_USAGE_JSON.exists():
        try:
            return json.loads(config.API_USAGE_JSON.read_text())
        except Exception:
            pass
    return {"month": "", "count": 0}


def _save_usage(data: dict) -> None:
    config.DATA_DIR.mkdir(exist_ok=True)
    config.API_USAGE_JSON.write_text(json.dumps(data, indent=2))


def _increment_usage() -> int:
    usage = _load_usage()
    month = datetime.datetime.utcnow().strftime("%Y-%m")
    if usage.get("month") != month:
        usage = {"month": month, "count": 0}
    usage["count"] += 1
    _save_usage(usage)
    return usage["count"]


def _check_budget() -> bool:
    """Returns True if we have API budget remaining."""
    usage = _load_usage()
    month = datetime.datetime.utcnow().strftime("%Y-%m")
    if usage.get("month") != month:
        return True
    remaining = config.ODDS_API_MONTHLY_LIMIT - usage.get("count", 0)
    if remaining <= 0:
        log(f"Odds API monthly budget exhausted ({usage['count']} requests used)", "WARN")
        return False
    if remaining <= 50:
        log(f"Odds API budget low: {remaining} requests remaining this month", "WARN")
    return True


# ── Cache ─────────────────────────────────────────────────────────────────────

def _load_cache() -> dict:
    if config.ODDS_CACHE_JSON.exists():
        try:
            return json.loads(config.ODDS_CACHE_JSON.read_text())
        except Exception:
            pass
    return {}


def _save_cache(data: dict) -> None:
    config.DATA_DIR.mkdir(exist_ok=True)
    config.ODDS_CACHE_JSON.write_text(json.dumps(data, indent=2))


def _cache_key(sport_key: str) -> str:
    return sport_key


def _is_cache_fresh(cache: dict, sport_key: str) -> bool:
    entry = cache.get(sport_key, {})
    fetched_at = entry.get("fetched_at", "")
    if not fetched_at:
        return False
    try:
        fetched = datetime.datetime.fromisoformat(fetched_at)
        age_min = (datetime.datetime.utcnow() - fetched).total_seconds() / 60
        return age_min < config.ODDS_CACHE_MINUTES
    except Exception:
        return False


# ── Main fetch ────────────────────────────────────────────────────────────────

def get_odds(sport_key: str, force_refresh: bool = False) -> list:
    """
    Fetch odds for a sport. Returns list of game objects.
    Uses cache if data is fresh enough. Falls back to cache on API failure.
    """
    if not config.ODDS_API_KEY:
        log(f"No ODDS_API_KEY — skipping {sport_key}", "WARN")
        return []

    cache = _load_cache()

    if not force_refresh and _is_cache_fresh(cache, sport_key):
        games = cache[sport_key].get("games", [])
        log(f"  {sport_key}: {len(games)} games (cached)")
        return games

    if not _check_budget():
        # Return stale cache rather than nothing
        return cache.get(sport_key, {}).get("games", [])

    try:
        url = f"{config.ODDS_API_BASE}/sports/{sport_key}/odds"
        params = {
            "apiKey":      config.ODDS_API_KEY,
            "regions":     "us",
            "markets":     "h2h,spreads,totals",
            "oddsFormat":  "american",
            "dateFormat":  "iso",
        }
        resp = requests.get(url, params=params, timeout=15)

        count = _increment_usage()

        if resp.status_code == 200:
            games = resp.json()
            cache[sport_key] = {
                "fetched_at": datetime.datetime.utcnow().isoformat(),
                "games":      games,
            }
            _save_cache(cache)
            # Log remaining requests from header
            remaining = resp.headers.get("x-requests-remaining", "?")
            log(f"  {sport_key}: {len(games)} games (fresh) — {remaining} API calls left this month")
            return games

        elif resp.status_code == 422:
            # Sport not currently active/in season
            log(f"  {sport_key}: not in season — skipping")
            return []

        else:
            log(f"  {sport_key}: API error {resp.status_code} — using cache", "WARN")
            return cache.get(sport_key, {}).get("games", [])

    except Exception as exc:
        log(f"  {sport_key}: request failed ({exc}) — using cache", "WARN")
        return cache.get(sport_key, {}).get("games", [])


def get_all_active_sports() -> list:
    """Fetch list of currently active sports from the API (1 request)."""
    if not config.ODDS_API_KEY:
        return []
    if not _check_budget():
        return []
    try:
        resp = requests.get(
            f"{config.ODDS_API_BASE}/sports",
            params={"apiKey": config.ODDS_API_KEY},
            timeout=10,
        )
        _increment_usage()
        if resp.status_code == 200:
            return [s for s in resp.json() if s.get("active")]
    except Exception:
        pass
    return []


# ── Parsing helpers ───────────────────────────────────────────────────────────

def american_to_prob(odds: int) -> float:
    """Convert American odds to implied probability (including vig)."""
    if odds < 0:
        return abs(odds) / (abs(odds) + 100)
    else:
        return 100 / (odds + 100)


def devig_two_way(prob_a: float, prob_b: float) -> tuple:
    """Remove vig from a two-way market. Returns (true_prob_a, true_prob_b)."""
    total = prob_a + prob_b
    if total <= 0:
        return prob_a, prob_b
    return prob_a / total, prob_b / total


def parse_game(raw: dict, sport_key: str) -> Optional[dict]:
    """Parse a raw Odds API game into a clean format."""
    import datetime as dt
    try:
        game_id    = raw.get("id", "")
        home_team  = raw.get("home_team", "")
        away_team  = raw.get("away_team", "")
        commence   = raw.get("commence_time", "")

        commence_dt = dt.datetime.fromisoformat(commence.replace("Z", "+00:00"))
        now_utc     = dt.datetime.now(dt.timezone.utc)
        hours_out   = (commence_dt - now_utc).total_seconds() / 3600

        if hours_out < config.MIN_GAME_HOURS_OUT:
            return None   # game starting too soon
        if hours_out > config.MAX_GAME_HOURS_OUT:
            return None   # game too far out

        bookmakers = raw.get("bookmakers", [])
        if not bookmakers:
            return None

        # Aggregate odds across all books
        h2h_odds   = _aggregate_market(bookmakers, "h2h",    home_team, away_team)
        spread_odds= _aggregate_market(bookmakers, "spreads", home_team, away_team)
        total_odds = _aggregate_totals(bookmakers)

        return {
            "game_id":    game_id,
            "sport_key":  sport_key,
            "sport":      config.SPORT_DISPLAY.get(sport_key, sport_key),
            "home_team":  home_team,
            "away_team":  away_team,
            "commence":   commence,
            "hours_out":  round(hours_out, 1),
            "h2h":        h2h_odds,
            "spread":     spread_odds,
            "total":      total_odds,
            "bookmakers": [b["key"] for b in bookmakers],
        }
    except Exception:
        return None


def _aggregate_market(bookmakers: list, market: str, home: str, away: str) -> dict:
    home_odds_list, away_odds_list = [], []
    for book in bookmakers:
        for mkt in book.get("markets", []):
            if mkt["key"] != market:
                continue
            for outcome in mkt.get("outcomes", []):
                price = outcome.get("price", 0)
                point = outcome.get("point", 0)
                if outcome["name"] == home:
                    home_odds_list.append((price, point))
                elif outcome["name"] == away:
                    away_odds_list.append((price, point))

    if not home_odds_list or not away_odds_list:
        return {}

    avg_home = sum(p for p, _ in home_odds_list) / len(home_odds_list)
    avg_away = sum(p for p, _ in away_odds_list) / len(away_odds_list)
    avg_point = sum(pt for _, pt in home_odds_list) / len(home_odds_list) if market == "spreads" else 0

    home_prob = american_to_prob(avg_home)
    away_prob = american_to_prob(avg_away)
    true_home, true_away = devig_two_way(home_prob, away_prob)

    best_home = max(p for p, _ in home_odds_list)
    best_away = max(p for p, _ in away_odds_list)

    return {
        "home_odds": round(avg_home),
        "away_odds": round(avg_away),
        "home_prob": round(home_prob, 4),
        "away_prob": round(away_prob, 4),
        "true_home_prob": round(true_home, 4),
        "true_away_prob": round(true_away, 4),
        "spread_point":   round(avg_point, 1) if market == "spreads" else None,
        "best_home_odds": best_home,
        "best_away_odds": best_away,
        "book_count":     len(bookmakers),
    }


def _aggregate_totals(bookmakers: list) -> dict:
    overs, unders = [], []
    for book in bookmakers:
        for mkt in book.get("markets", []):
            if mkt["key"] != "totals":
                continue
            for outcome in mkt.get("outcomes", []):
                if outcome["name"] == "Over":
                    overs.append((outcome.get("price", -110), outcome.get("point", 0)))
                elif outcome["name"] == "Under":
                    unders.append((outcome.get("price", -110), outcome.get("point", 0)))

    if not overs or not unders:
        return {}

    avg_line  = sum(pt for _, pt in overs) / len(overs)
    avg_over  = sum(p for p, _ in overs) / len(overs)
    avg_under = sum(p for p, _ in unders) / len(unders)

    return {
        "line":       round(avg_line, 1),
        "over_odds":  round(avg_over),
        "under_odds": round(avg_under),
        "over_prob":  round(american_to_prob(avg_over), 4),
        "under_prob": round(american_to_prob(avg_under), 4),
    }
