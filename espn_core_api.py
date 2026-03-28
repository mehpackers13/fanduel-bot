"""
ESPN CORE API — PRIMARY ODDS SOURCE
=====================================
Completely free. No API key. No rate limits. Works from any IP.
Returns real DraftKings odds: moneylines, spreads, totals.
Includes opening vs current odds for built-in line movement detection.

Base: https://sports.core.api.espn.com/v2/sports/{sport}/leagues/{league}/

Tested endpoints (all return 200 with real data):
  /events?limit=20&dates=YYYYMMDD   — today's games
  /events/{id}/competitions/{id}/odds — DraftKings odds with open/current
  /injuries                          — injury reports
"""

import datetime
import json
import time
from pathlib import Path
from typing import Optional

import requests

import config
from logger import log

# ── ESPN league codes ─────────────────────────────────────────────────────────
LEAGUES = {
    "americanfootball_nfl": ("football",   "nfl"),
    "basketball_nba":       ("basketball", "nba"),
    "baseball_mlb":         ("baseball",   "mlb"),
    "icehockey_nhl":        ("hockey",     "nhl"),
    "soccer_usa_mls":       ("soccer",     "usa.1"),
    "soccer_epl":           ("soccer",     "eng.1"),
    "soccer_esp_la_liga":   ("soccer",     "esp.1"),
    "soccer_ger_bundesliga":("soccer",     "ger.1"),
    "soccer_ita_serie_a":   ("soccer",     "ita.1"),
    "soccer_fra_ligue_one": ("soccer",     "fra.1"),
    "mma_mixed_martial_arts":("mma",       "ufc"),
}

BASE = "https://sports.core.api.espn.com/v2/sports"
SITE_BASE = "https://site.api.espn.com/apis/site/v2/sports"

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)",
    "Accept":     "application/json",
}

# Cache file — saves parsed games between scans
_CACHE_FILE = config.DATA_DIR / "espn_cache.json"
_CACHE_TTL_MINUTES = 90


# ── HTTP helper ───────────────────────────────────────────────────────────────

def _get(url: str, params: dict = None) -> Optional[dict]:
    """Single GET with timeout and error handling."""
    try:
        resp = requests.get(url, headers=_HEADERS, params=params, timeout=12)
        if resp.status_code == 200:
            return resp.json()
        if resp.status_code not in (404, 451):   # expected for off-season
            log(f"ESPN {resp.status_code}: {url[-80:]}", "WARN")
    except requests.Timeout:
        log(f"ESPN timeout: {url[-60:]}", "WARN")
    except Exception as exc:
        log(f"ESPN error: {exc}", "WARN")
    return None


def _deref(ref_obj: dict) -> Optional[dict]:
    """Follow an ESPN $ref link."""
    if not ref_obj:
        return None
    url = ref_obj.get("$ref", "")
    if not url:
        return None
    return _get(url)


# ── Cache ─────────────────────────────────────────────────────────────────────

def _load_cache() -> dict:
    config.DATA_DIR.mkdir(exist_ok=True)
    if _CACHE_FILE.exists():
        try:
            return json.loads(_CACHE_FILE.read_text())
        except Exception:
            pass
    return {}


def _save_cache(data: dict) -> None:
    config.DATA_DIR.mkdir(exist_ok=True)
    _CACHE_FILE.write_text(json.dumps(data, indent=2))


def _cache_fresh(cache: dict, key: str) -> bool:
    entry = cache.get(key, {})
    ts = entry.get("ts", "")
    if not ts:
        return False
    try:
        age = (datetime.datetime.utcnow() - datetime.datetime.fromisoformat(ts)).total_seconds() / 60
        return age < _CACHE_TTL_MINUTES
    except Exception:
        return False


# ── Odds parsing ──────────────────────────────────────────────────────────────

def _parse_american(val) -> Optional[int]:
    """Extract American odds integer from ESPN's oddly-nested format."""
    if val is None:
        return None
    if isinstance(val, (int, float)):
        v = int(val)
        return v if v != 0 else None
    if isinstance(val, dict):
        # ESPN sometimes returns {"value":1.91,"american":"-110","displayValue":"..."}
        am = val.get("american") or val.get("alternateDisplayValue") or val.get("displayValue")
        if am:
            try:
                return int(str(am).replace("+", "").strip())
            except Exception:
                pass
        # Try decimal odds → American
        dec = val.get("value") or val.get("decimal")
        if dec:
            d = float(dec)
            if d >= 2.0:
                return int((d - 1) * 100)
            elif d > 1.0:
                return int(-100 / (d - 1))
    return None


def _american_to_prob(odds: int) -> float:
    if odds < 0:
        return abs(odds) / (abs(odds) + 100)
    return 100 / (odds + 100)


def _devig(p_home: float, p_away: float) -> tuple:
    total = p_home + p_away
    if total <= 0:
        return p_home, p_away
    return p_home / total, p_away / total


def _parse_odds_item(raw_odds: dict, home_name: str, away_name: str) -> Optional[dict]:
    """
    Parse a single ESPN odds provider response into standardised format.
    Returns dict with h2h, spread, total, line_movement.
    """
    if not raw_odds:
        return None

    home_block = raw_odds.get("homeTeamOdds", {})
    away_block = raw_odds.get("awayTeamOdds", {})

    # Current moneylines
    home_ml = _parse_american(home_block.get("moneyLine"))
    away_ml = _parse_american(away_block.get("moneyLine"))

    # Spread
    spread_raw = raw_odds.get("spread")
    spread_pt  = None
    try:
        spread_pt = float(spread_raw) if spread_raw is not None else None
    except Exception:
        pass

    home_spread_odds = _parse_american(home_block.get("spreadOdds")) or -110
    away_spread_odds = _parse_american(away_block.get("spreadOdds")) or -110

    # Total
    total_raw  = raw_odds.get("overUnder")
    total_line = None
    try:
        total_line = float(total_raw) if total_raw is not None else None
    except Exception:
        pass

    over_odds  = _parse_american(raw_odds.get("overOdds"))  or -110
    under_odds = _parse_american(raw_odds.get("underOdds")) or -110

    # Opening odds (for line movement)
    home_open_block = home_block.get("open", {})
    away_open_block = away_block.get("open", {})
    open_home_ml = _parse_american(home_open_block.get("moneyLine") if isinstance(home_open_block, dict) else home_open_block)
    open_away_ml = _parse_american(away_open_block.get("moneyLine") if isinstance(away_open_block, dict) else away_open_block)

    open_spread_raw = raw_odds.get("open", {})
    open_spread_pt  = None
    if isinstance(open_spread_raw, dict):
        try:
            open_spread_pt = float(open_spread_raw.get("spread", 0) or 0) or None
        except Exception:
            pass

    if not home_ml or not away_ml:
        return None

    # Devigged probabilities
    home_prob_raw = _american_to_prob(home_ml)
    away_prob_raw = _american_to_prob(away_ml)
    true_home, true_away = _devig(home_prob_raw, away_prob_raw)

    # Line movement: spread moved 1.5+ points = sharp money indicator
    spread_moved = None
    if spread_pt is not None and open_spread_pt is not None:
        spread_moved = round(abs(spread_pt - open_spread_pt), 1)

    return {
        "h2h": {
            "home_odds": home_ml, "away_odds": away_ml,
            "home_prob": round(home_prob_raw, 4),
            "away_prob": round(away_prob_raw, 4),
            "true_home_prob": round(true_home, 4),
            "true_away_prob": round(true_away, 4),
            "best_home_odds": home_ml, "best_away_odds": away_ml,
            "spread_point": spread_pt, "book_count": 1,
        },
        "spread": {
            "home_odds": home_spread_odds, "away_odds": away_spread_odds,
            "home_prob": _american_to_prob(home_spread_odds),
            "away_prob": _american_to_prob(away_spread_odds),
            "true_home_prob": 0.5, "true_away_prob": 0.5,
            "spread_point": spread_pt,
            "best_home_odds": home_spread_odds,
            "best_away_odds": away_spread_odds,
            "book_count": 1,
        } if spread_pt is not None else {},
        "total": {
            "line": total_line,
            "over_odds": over_odds, "under_odds": under_odds,
            "over_prob": _american_to_prob(over_odds),
            "under_prob": _american_to_prob(under_odds),
        } if total_line else {},
        "line_movement": {
            "open_home_ml":    open_home_ml,
            "open_away_ml":    open_away_ml,
            "current_home_ml": home_ml,
            "current_away_ml": away_ml,
            "open_spread":     open_spread_pt,
            "current_spread":  spread_pt,
            "spread_moved":    spread_moved,
            "is_sharp":        spread_moved is not None and spread_moved >= 1.5,
        },
    }


# ── Main data fetch ───────────────────────────────────────────────────────────

def get_games(sport_key: str, force_refresh: bool = False) -> list:
    """
    Fetch today's games + odds for a sport from ESPN Core API.
    Returns list of game dicts in standard fanduel-bot format.
    Uses 90-minute cache to avoid hammering ESPN.
    """
    codes = LEAGUES.get(sport_key)
    if not codes:
        return []
    sport_code, league_code = codes

    cache = _load_cache()
    if not force_refresh and _cache_fresh(cache, sport_key):
        games = cache[sport_key].get("games", [])
        log(f"  ESPN {sport_key}: {len(games)} games (cached)")
        return games

    today = datetime.date.today().strftime("%Y%m%d")
    url   = f"{BASE}/{sport_code}/leagues/{league_code}/events"

    data  = _get(url, params={"limit": 50, "dates": today})
    if not data:
        # Try without date filter (gets nearest upcoming events)
        data = _get(url, params={"limit": 20})
    if not data:
        log(f"  ESPN {sport_key}: no data", "WARN")
        return cache.get(sport_key, {}).get("games", [])

    items = data.get("items", [])
    games = []

    for item in items:
        game = _parse_event(item.get("$ref", ""), sport_key)
        if game:
            games.append(game)
        time.sleep(0.1)   # gentle rate limiting

    log(f"  ESPN {sport_key}: {len(games)} games (fresh, {len(items)} events found)")

    cache[sport_key] = {
        "ts":    datetime.datetime.utcnow().isoformat(),
        "games": games,
    }
    _save_cache(cache)
    return games


def _parse_event(event_url: str, sport_key: str) -> Optional[dict]:
    """Parse a single ESPN event into a fanduel-bot game dict."""
    if not event_url:
        return None

    ev = _get(event_url)
    if not ev:
        return None

    comps = ev.get("competitions", [])
    if not comps:
        return None
    comp = comps[0]

    # Team names
    competitors = comp.get("competitors", [])
    home_name, away_name = "", ""
    home_team_ref, away_team_ref = {}, {}
    for c in competitors:
        if c.get("homeAway") == "home":
            home_team_ref = c.get("team", {})
            home_name = (home_team_ref.get("displayName") or
                         home_team_ref.get("name") or
                         _get_team_name(home_team_ref.get("$ref", "")))
        elif c.get("homeAway") == "away":
            away_team_ref = c.get("team", {})
            away_name = (away_team_ref.get("displayName") or
                         away_team_ref.get("name") or
                         _get_team_name(away_team_ref.get("$ref", "")))

    if not home_name or not away_name:
        return None

    # Commence time
    commence_str = ev.get("date", "")
    hours_out    = _hours_until(commence_str)
    if hours_out < config.MIN_GAME_HOURS_OUT or hours_out > config.MAX_GAME_HOURS_OUT:
        return None

    # Venue city (for weather/travel)
    venue      = comp.get("venue", {})
    venue_city = (venue.get("address", {}).get("city", "") or
                  venue.get("city", ""))

    # Odds
    odds_ref  = comp.get("odds", {}).get("$ref", "")
    parsed_odds = {}
    if odds_ref:
        odds_data = _get(odds_ref)
        if odds_data:
            for od_item in odds_data.get("items", [])[:1]:   # take first provider (DraftKings)
                raw = _get(od_item.get("$ref", "")) if isinstance(od_item, dict) and "$ref" in od_item else od_item
                if raw:
                    parsed_odds = _parse_odds_item(raw, home_name, away_name) or {}

    if not parsed_odds or not parsed_odds.get("h2h"):
        return None   # no point returning a game with no odds

    game_id = ev.get("id", "") or str(hash(home_name + away_name))

    return {
        "game_id":     f"espn_{game_id}",
        "sport_key":   sport_key,
        "sport":       config.SPORT_DISPLAY.get(sport_key, sport_key),
        "home_team":   home_name,
        "away_team":   away_name,
        "commence":    commence_str,
        "hours_out":   round(hours_out, 1),
        "venue_city":  venue_city,
        "source":      "espn",
        "h2h":         parsed_odds.get("h2h", {}),
        "spread":      parsed_odds.get("spread", {}),
        "total":       parsed_odds.get("total", {}),
        "line_movement": parsed_odds.get("line_movement", {}),
    }


def _get_team_name(team_ref_url: str) -> str:
    """Follow a $ref to get team display name."""
    if not team_ref_url:
        return ""
    data = _get(team_ref_url)
    if data:
        return data.get("displayName") or data.get("name") or ""
    return ""


def _hours_until(dt_str: str) -> float:
    """Return hours until a datetime string (ISO format)."""
    if not dt_str:
        return 999.0
    try:
        dt  = datetime.datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
        now = datetime.datetime.now(datetime.timezone.utc)
        return (dt - now).total_seconds() / 3600
    except Exception:
        return 999.0


# ── Injuries ──────────────────────────────────────────────────────────────────

def get_injuries(sport_key: str) -> list:
    """
    Fetch injury report from ESPN Core API.
    Returns list of {team, player, status, position, details}.
    """
    codes = LEAGUES.get(sport_key)
    if not codes:
        return []
    sport_code, league_code = codes
    url  = f"{SITE_BASE}/{sport_code}/{league_code}/injuries"
    data = _get(url)
    if not data:
        return []

    injuries = []
    for item in data.get("items", []):
        team = item.get("team", {}).get("displayName", "")
        for inj in item.get("injuries", []):
            athlete = inj.get("athlete", {})
            injuries.append({
                "team":     team,
                "player":   athlete.get("displayName", ""),
                "position": athlete.get("position", {}).get("abbreviation", ""),
                "status":   inj.get("status", ""),
                "details":  inj.get("shortComment", ""),
                "type":     inj.get("type", ""),
            })
    return injuries


# ── Schedule (for back-to-back detection) ────────────────────────────────────

def get_recent_schedule(sport_key: str, days_back: int = 3) -> list:
    """Fetch recent game schedule to detect back-to-backs."""
    codes = LEAGUES.get(sport_key)
    if not codes:
        return []
    sport_code, league_code = codes

    games = []
    for d in range(days_back, 0, -1):
        date    = (datetime.date.today() - datetime.timedelta(days=d)).strftime("%Y%m%d")
        url     = f"{BASE}/{sport_code}/leagues/{league_code}/events"
        data    = _get(url, params={"limit": 20, "dates": date})
        if not data:
            continue
        for item in data.get("items", []):
            ev = _get(item.get("$ref", ""))
            if not ev:
                continue
            comp  = (ev.get("competitions") or [{}])[0]
            venue = comp.get("venue", {})
            city  = venue.get("address", {}).get("city", "")
            for c in comp.get("competitors", []):
                team_ref = c.get("team", {})
                team_name = (team_ref.get("displayName") or
                             team_ref.get("name") or
                             _get_team_name(team_ref.get("$ref", "")))
                if team_name:
                    games.append({
                        "date":   date,
                        "team":   team_name,
                        "home":   c.get("homeAway") == "home",
                        "city":   city,
                        "result": comp.get("status", {}).get("type", {}).get("completed", False),
                    })
        time.sleep(0.15)
    return games


# ── Sharp line movement ───────────────────────────────────────────────────────

def check_line_movement_sharp(game: dict) -> tuple:
    """
    Returns (is_sharp: bool, description: str).
    Sharp indicator: spread moved 1.5+ points from open to current.
    """
    lm = game.get("line_movement", {})
    if not lm:
        return False, ""

    moved    = lm.get("spread_moved")
    is_sharp = lm.get("is_sharp", False)

    if not is_sharp or moved is None:
        return False, ""

    open_sp  = lm.get("open_spread")
    curr_sp  = lm.get("current_spread")
    home     = game.get("home_team", "home")
    away     = game.get("away_team", "away")

    if open_sp is not None and curr_sp is not None:
        direction = "toward " + (home if curr_sp < open_sp else away)
        desc = (f"Line moved {moved} pts from {open_sp:+.1f} to {curr_sp:+.1f} "
                f"({direction}) — sharp money indicator")
    else:
        desc = f"Spread moved {moved} pts from open — sharp action detected"

    return True, desc
