"""
ACTION NETWORK — Next.js Data Endpoint
========================================
Uses Action Network's public _next/data JSON endpoint (no auth, no API key).
This endpoint is their standard Next.js server-side data feed and is not
IP-restricted like their internal /web/v1/games API was.

Data path for consensus (bookmaker id "15"):
  pageProps.scoreboardResponse.games[N]
    .markets["15"].event
      .{moneyline|spread|total}[K]
        .bet_info.{tickets|money}.percent

Caches the full sport response for 30 minutes to avoid hitting them on every
game evaluation (one fetch per sport per 30 min, not per game).
"""
import json
import re
import time
import datetime
from pathlib import Path
from typing import Optional
import requests

from logger import log

# ── Config ─────────────────────────────────────────────────────────────────────

_CACHE_TTL_SECONDS = 1800   # 30-minute cache per sport
_TIMEOUT           = 12     # seconds

_HEADERS = {
    "User-Agent":      "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) "
                       "Chrome/122.0.0.0 Safari/537.36",
    "Accept":          "application/json, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer":         "https://www.actionnetwork.com/",
}

# Map our sport keys to Action Network URL slugs
_AN_SPORT_PATH = {
    "americanfootball_nfl": "nfl/odds",
    "basketball_nba":       "nba/odds",
    "baseball_mlb":         "mlb/odds",
    "icehockey_nhl":        "nhl/odds",
    "soccer_usa_mls":       "mls/odds",
}

# Consensus bookmaker id in Action Network data
_CONSENSUS_ID = "15"

# In-memory cache: sport_key → {fetched_at: float, games: list}
_cache: dict = {}

# Build ID cache (AN build ID changes on deployments, not per-request)
_build_id_cache: dict = {}   # sport_path → (buildId, fetched_at)
_BUILD_ID_TTL = 3600         # re-fetch build ID every hour


# ── Public entry point ─────────────────────────────────────────────────────────

def get_public_betting(home_team: str, away_team: str, sport_key: str) -> dict:
    """
    Returns a dict with public betting splits for a specific game.

    Keys:
      home_bets_pct   – % of bets on home team (tickets)
      away_bets_pct   – % of bets on away team
      home_money_pct  – % of money on home team
      away_money_pct  – % of money on away team
      sharp_side      – "home", "away", or None (line moved opposite to public)

    Returns {} if sport not supported or data unavailable.
    """
    sport_path = _AN_SPORT_PATH.get(sport_key)
    if not sport_path:
        return {}

    games = _get_games_cached(sport_path)
    if not games:
        return {}

    return _extract_game(games, home_team, away_team)


# ── Data fetching ──────────────────────────────────────────────────────────────

def _get_games_cached(sport_path: str) -> list:
    """Return cached games list or fetch fresh from Action Network."""
    entry = _cache.get(sport_path)
    if entry and (time.time() - entry["fetched_at"]) < _CACHE_TTL_SECONDS:
        return entry["games"]

    games = _fetch_games(sport_path)
    _cache[sport_path] = {"fetched_at": time.time(), "games": games}
    return games


def _fetch_games(sport_path: str) -> list:
    """
    Fetch games from Action Network _next/data JSON endpoint.
    Returns list of raw game dicts or [].
    """
    build_id = _get_build_id(sport_path)
    if not build_id:
        return []

    url = f"https://www.actionnetwork.com/_next/data/{build_id}/{sport_path}.json"
    try:
        resp = requests.get(url, headers=_HEADERS, timeout=_TIMEOUT)
        if resp.status_code != 200:
            log(f"Action Network {sport_path}: HTTP {resp.status_code}", "WARN")
            return []

        data  = resp.json()
        games = (data.get("pageProps", {})
                     .get("scoreboardResponse", {})
                     .get("games", []))
        log(f"Action Network {sport_path}: {len(games)} games fetched")
        return games

    except Exception as exc:
        log(f"Action Network fetch error ({sport_path}): {exc}", "WARN")
        return []


def _get_build_id(sport_path: str) -> Optional[str]:
    """
    Extract Next.js buildId from Action Network HTML page.
    Cached per hour — the build ID only changes on deployments.
    """
    cached = _build_id_cache.get(sport_path)
    if cached and (time.time() - cached[1]) < _BUILD_ID_TTL:
        return cached[0]

    url = f"https://www.actionnetwork.com/{sport_path}"
    try:
        resp = requests.get(url, headers={**_HEADERS, "Accept": "text/html"},
                            timeout=_TIMEOUT)
        if resp.status_code != 200:
            log(f"Action Network HTML {url}: HTTP {resp.status_code}", "WARN")
            return None

        # __NEXT_DATA__ JSON embedded in the page
        match = re.search(r'"buildId"\s*:\s*"([^"]+)"', resp.text)
        if not match:
            log(f"Action Network: buildId not found in {url}", "WARN")
            return None

        build_id = match.group(1)
        _build_id_cache[sport_path] = (build_id, time.time())
        return build_id

    except Exception as exc:
        log(f"Action Network buildId error ({sport_path}): {exc}", "WARN")
        return None


# ── Parsing ────────────────────────────────────────────────────────────────────

def _extract_game(games: list, home_team: str, away_team: str) -> dict:
    """
    Find the matching game and extract consensus public betting splits.
    Action Network stores teams as away[0] / home[1] in the teams array.
    """
    for game in games:
        teams = game.get("teams", [])
        if len(teams) < 2:
            continue

        # teams[0] = away, teams[1] = home in AN convention
        an_away = teams[0].get("full_name", "") or teams[0].get("name", "")
        an_home = teams[1].get("full_name", "") or teams[1].get("name", "")

        if not _teams_match(home_team, away_team, [an_home, an_away]):
            continue

        return _parse_consensus(game, an_home, an_away, home_team)

    return {}


def _parse_consensus(game: dict, an_home: str, an_away: str,
                     our_home: str) -> dict:
    """
    Extract public % splits from consensus market (bookmaker id 15).
    Determines if our home_team corresponds to AN's home or away side.
    """
    markets = game.get("markets", {})
    consensus = markets.get(_CONSENSUS_ID, {})
    event     = consensus.get("event", {})

    # Figure out which side is "home" in our coordinate system vs AN's
    home_is_an_home = _norm(our_home) == _norm(an_home)

    result: dict = {}

    # ── Moneyline betting % ────────────────────────────────────────────────────
    ml_list = event.get("moneyline", [])
    for bet in ml_list:
        bet_info = bet.get("bet_info", {})
        tickets_pct = _safe_pct(bet_info.get("tickets", {}).get("percent"))
        money_pct   = _safe_pct(bet_info.get("money", {}).get("percent"))
        if tickets_pct is None:
            continue

        # AN stores each bet as a side; match by "home_team_id" presence
        # Simpler: check "selection" or "side" field
        side = bet.get("selection", bet.get("side", ""))
        is_home_bet = _side_is_home(side, an_home, an_away)

        if is_home_bet is None:
            continue

        # Map to our home/away coordinate system
        if is_home_bet == home_is_an_home:
            result["home_bets_pct"]  = tickets_pct
            result["home_money_pct"] = money_pct or tickets_pct
        else:
            result["away_bets_pct"]  = tickets_pct
            result["away_money_pct"] = money_pct or tickets_pct

    # Fill in the missing side if only one was found
    if "home_bets_pct" in result and "away_bets_pct" not in result:
        result["away_bets_pct"]  = round(100 - result["home_bets_pct"], 1)
        result["away_money_pct"] = round(100 - result.get("home_money_pct",
                                                          result["home_bets_pct"]), 1)
    elif "away_bets_pct" in result and "home_bets_pct" not in result:
        result["home_bets_pct"]  = round(100 - result["away_bets_pct"], 1)
        result["home_money_pct"] = round(100 - result.get("away_money_pct",
                                                          result["away_bets_pct"]), 1)

    if not result:
        # Fallback: parse top-level aggregate if nested structure differs
        result = _parse_aggregate_fallback(event, home_is_an_home)

    if not result:
        return {}

    # ── Sharp money detection ─────────────────────────────────────────────────
    # Sharp: public heavily on one side BUT line moved the other way
    home_bets = result.get("home_bets_pct", 50)
    # Grab opening vs current ML from the game object (not consensus)
    open_ml_home  = _dig(game, "markets", "68", "event", "moneyline", 0, "opening", "value")
    curr_ml_home  = _dig(game, "markets", "68", "event", "moneyline", 0, "value")

    if open_ml_home and curr_ml_home:
        try:
            open_f = float(open_ml_home)
            curr_f = float(curr_ml_home)
            pub_on_home = home_bets > 55
            # Negative ML = favorite; more negative = even bigger favorite
            line_moved_toward_home = curr_f < open_f  # e.g. -120 → -140
            if pub_on_home and not line_moved_toward_home:
                result["sharp_side"] = "away"
            elif not pub_on_home and line_moved_toward_home:
                result["sharp_side"] = "home"
        except (TypeError, ValueError):
            pass

    return result


def _parse_aggregate_fallback(event: dict, home_is_an_home: bool) -> dict:
    """
    Try aggregate bet_info at the event level when per-bet parsing fails.
    Some AN responses store totals directly on the event rather than per-bet.
    """
    result = {}
    for market_type in ("moneyline", "spread"):
        bets = event.get(market_type, [])
        if not bets:
            continue
        # Look for a bet with both sides' aggregated data
        for bet in bets:
            info = bet.get("bet_info", {})
            # Try "home_tickets" / "away_tickets" style
            ht = _safe_pct(info.get("home_tickets", {}).get("percent")
                           or info.get("home_bets"))
            at = _safe_pct(info.get("away_tickets", {}).get("percent")
                           or info.get("away_bets"))
            if ht and at:
                if home_is_an_home:
                    result["home_bets_pct"] = ht
                    result["away_bets_pct"] = at
                else:
                    result["home_bets_pct"] = at
                    result["away_bets_pct"] = ht
                return result
    return result


# ── Helpers ────────────────────────────────────────────────────────────────────

def _safe_pct(val) -> Optional[float]:
    """Convert a percentage value to float, return None if invalid."""
    if val is None:
        return None
    try:
        f = float(val)
        return f if 0 <= f <= 100 else None
    except (TypeError, ValueError):
        return None


def _norm(name: str) -> str:
    """Last word of team name (strips city), lower-cased."""
    return name.strip().lower().split()[-1] if name.strip() else ""


def _teams_match(home: str, away: str, names: list) -> bool:
    """Fuzzy match: check if our team names appear in the AN names list."""
    our   = {_norm(home), _norm(away)}
    their = {_norm(n) for n in names}
    return len(our & their) >= 1  # at least one name matches


def _side_is_home(side: str, an_home: str, an_away: str) -> Optional[bool]:
    """
    Given a selection/side string from AN data, determine if it refers to
    the home team (True) or away team (False).  None if indeterminate.
    """
    if not side:
        return None
    s = side.lower()
    if _norm(an_home) in s or "home" in s:
        return True
    if _norm(an_away) in s or "away" in s:
        return False
    return None


def _dig(obj, *keys):
    """Safe deep-get: returns None if any key is missing or index OOB."""
    cur = obj
    for k in keys:
        if cur is None:
            return None
        if isinstance(k, int):
            if isinstance(cur, list) and len(cur) > k:
                cur = cur[k]
            else:
                return None
        else:
            cur = cur.get(k) if isinstance(cur, dict) else None
    return cur
