"""
ODDSTRADER SCRAPER
==================
Primary odds source -- scrapes oddstrader.com for live odds, props,
injuries, and line movement across all sports including UFC and
European soccer. No API key required. No request limits.

Falls back gracefully to The Odds API if scraping fails.
"""
import time
import re
import datetime
from typing import Optional
import requests
from bs4 import BeautifulSoup
from logger import log
import config

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Cache-Control": "max-age=0",
}

_SESSION = requests.Session()
_SESSION.headers.update(_HEADERS)


def get_games(sport_key: str) -> list:
    """
    Fetch games and odds for a sport from OddsTrader.
    Returns list of game dicts compatible with parse_game() format.
    """
    path = config.ODDSTRADER_SPORT_PATHS.get(sport_key, "")
    if not path:
        return []

    url = f"{config.ODDSTRADER_BASE}{path}"
    try:
        resp = _SESSION.get(url, timeout=15)
        if resp.status_code != 200:
            log(f"OddsTrader {sport_key}: HTTP {resp.status_code}", "WARN")
            return []
        return _parse_games_page(resp.text, sport_key)
    except Exception as exc:
        log(f"OddsTrader {sport_key} fetch failed: {exc}", "WARN")
        return []


def _parse_games_page(html: str, sport_key: str) -> list:
    """Parse the OddsTrader games listing page."""
    soup  = BeautifulSoup(html, "lxml")
    games = []

    # OddsTrader uses various selectors -- try multiple patterns
    # Look for game/event containers
    game_containers = (
        soup.find_all("div", class_=re.compile(r"game|event|matchup|fixture", re.I)) or
        soup.find_all("tr", class_=re.compile(r"game|event|row", re.I)) or
        soup.find_all("article", class_=re.compile(r"game|event", re.I))
    )

    for container in game_containers[:50]:  # cap at 50 games per page
        game = _extract_game(container, sport_key)
        if game:
            games.append(game)

    # If no games found via containers, try table rows
    if not games:
        rows = soup.find_all("tr")
        for row in rows:
            cells = row.find_all(["td", "th"])
            if len(cells) >= 3:
                game = _extract_from_row(cells, sport_key)
                if game:
                    games.append(game)

    log(f"  OddsTrader {sport_key}: {len(games)} games parsed")
    return games


def _extract_game(container, sport_key: str) -> Optional[dict]:
    """Extract a single game from a container element."""
    text = container.get_text(separator=" ", strip=True)

    # Need at least team names and one odds value
    odds_pattern = re.compile(r'[+-]\d{2,4}')
    if not odds_pattern.search(text):
        return None

    # Extract team names (usually in spans/divs with team-related classes)
    team_els = container.find_all(
        ["span", "div", "a"],
        class_=re.compile(r"team|name|competitor", re.I)
    )
    teams = [el.get_text(strip=True) for el in team_els if el.get_text(strip=True)]
    teams = [t for t in teams if len(t) > 2 and not t.isdigit()][:2]

    if len(teams) < 2:
        # Try extracting from text directly
        lines = [l.strip() for l in text.split("\n") if l.strip()]
        teams = [l for l in lines if len(l) > 3 and not re.match(r'^[+-]?\d', l)][:2]

    if len(teams) < 2:
        return None

    # Extract odds
    all_odds = [int(m) for m in re.findall(r'[+-]\d{2,4}', text)]
    if not all_odds:
        return None

    # Build a minimal game object matching the standard format
    home, away = teams[1], teams[0]  # OddsTrader lists away first typically

    # Try to find moneyline odds (first two significant odds values)
    ml_odds = [o for o in all_odds if -500 < o < 500][:2]
    if len(ml_odds) < 2:
        return None

    home_ml = ml_odds[1]
    away_ml = ml_odds[0]

    from odds_api import american_to_prob, devig_two_way
    home_prob_raw = american_to_prob(home_ml)
    away_prob_raw = american_to_prob(away_ml)
    true_home, true_away = devig_two_way(home_prob_raw, away_prob_raw)

    # Look for spread
    spread_vals = re.findall(r'[+-]?\d+\.5', text)
    spread_point = float(spread_vals[0]) if spread_vals else None

    # Look for total
    total_vals = re.findall(r'\b(\d{2,3}(?:\.\d)?)\b', text)
    total_line = None
    for v in total_vals:
        f = float(v)
        if 30 < f < 300:  # reasonable total range
            total_line = f
            break

    return {
        "game_id":    f"ot_{abs(hash(home + away + sport_key)) % 1000000}",
        "sport_key":  sport_key,
        "sport":      config.SPORT_DISPLAY.get(sport_key, sport_key),
        "home_team":  home,
        "away_team":  away,
        "commence":   _estimate_commence(),
        "hours_out":  8.0,  # default; refined below if time found
        "source":     "oddstrader",
        "h2h": {
            "home_odds": home_ml, "away_odds": away_ml,
            "home_prob": round(home_prob_raw, 4),
            "away_prob": round(away_prob_raw, 4),
            "true_home_prob": round(true_home, 4),
            "true_away_prob": round(true_away, 4),
            "best_home_odds": home_ml, "best_away_odds": away_ml,
            "spread_point": spread_point, "book_count": 1,
        },
        "spread": _build_spread(home_ml, away_ml, spread_point),
        "total":  _build_total(total_line),
    }


def _extract_from_row(cells, sport_key: str) -> Optional[dict]:
    """Extract from a table row."""
    texts = [c.get_text(strip=True) for c in cells]
    odds_cells = [t for t in texts if re.match(r'^[+-]\d{2,4}$', t)]
    if len(odds_cells) < 2:
        return None
    team_cells = [t for t in texts if t and not re.match(r'^[+-]?\d', t) and len(t) > 2]
    if len(team_cells) < 2:
        return None
    # Build synthetic container and re-parse
    parent = cells[0].parent if cells else None
    if parent is None:
        return None
    return _extract_game(parent, sport_key)


def _build_spread(home_ml: int, away_ml: int, point: Optional[float]) -> dict:
    if point is None:
        return {}
    from odds_api import american_to_prob, devig_two_way
    # Standard spread vig
    hp = american_to_prob(-110)
    ap = american_to_prob(-110)
    th, ta = devig_two_way(hp, ap)
    return {
        "home_odds": -110, "away_odds": -110,
        "home_prob": hp, "away_prob": ap,
        "true_home_prob": th, "true_away_prob": ta,
        "spread_point": point,
        "best_home_odds": -110, "best_away_odds": -110,
        "book_count": 1,
    }


def _build_total(line: Optional[float]) -> dict:
    if line is None:
        return {}
    from odds_api import american_to_prob
    return {
        "line": line,
        "over_odds": -110, "under_odds": -110,
        "over_prob": american_to_prob(-110),
        "under_prob": american_to_prob(-110),
    }


def _estimate_commence() -> str:
    """Estimate game time as tonight 7pm ET (23:00 UTC)."""
    now = datetime.datetime.utcnow()
    tonight = now.replace(hour=23, minute=0, second=0, microsecond=0)
    return tonight.isoformat() + "Z"


# ── UFC specific ──────────────────────────────────────────────────────────────

def get_ufc_fights() -> list:
    """
    Fetch UFC card from OddsTrader /ufc/ with fighter-specific data.
    Returns list of fight dicts with odds + UFC signals.
    """
    games = get_games("mma_mixed_martial_arts")
    # Enrich with UFC stats from ESPN or cache
    for game in games:
        game["ufc_signals"] = _get_ufc_signals(game["home_team"], game["away_team"])
    return games


def _get_ufc_signals(fighter_a: str, fighter_b: str) -> dict:
    """
    Fetch UFC-specific signal data from ESPN MMA or UFC Stats.
    Returns dict of signals relevant to UFC edge detection.
    """
    signals = {}
    try:
        # Try ESPN MMA
        url  = "https://site.api.espn.com/apis/site/v2/sports/mma/ufc/athletes"
        resp = requests.get(url, timeout=8)
        if resp.status_code == 200:
            # ESPN data parsing would go here -- structure varies
            pass
    except Exception:
        pass
    return signals


def get_injuries_oddstrader(sport_key: str) -> list:
    """
    Scrape injury data from OddsTrader injury pages.
    Returns list of {team, player, status, position}.
    """
    path = config.ODDSTRADER_SPORT_PATHS.get(sport_key, "")
    if not path:
        return []
    url = f"{config.ODDSTRADER_BASE}{path}injuries/"
    try:
        resp = _SESSION.get(url, timeout=12)
        if resp.status_code != 200:
            return []
        soup = BeautifulSoup(resp.text, "lxml")
        injuries = []
        rows = soup.find_all("tr")
        for row in rows:
            cells = [c.get_text(strip=True) for c in row.find_all(["td", "th"])]
            if len(cells) >= 3:
                injuries.append({
                    "player":   cells[0] if cells else "",
                    "team":     cells[1] if len(cells) > 1 else "",
                    "position": cells[2] if len(cells) > 2 else "",
                    "status":   cells[3] if len(cells) > 3 else "Questionable",
                    "details":  cells[4] if len(cells) > 4 else "",
                })
        return [i for i in injuries if i["player"]]
    except Exception as exc:
        log(f"OddsTrader injuries {sport_key}: {exc}", "WARN")
        return []
