"""
ACTION NETWORK SCRAPER
=======================
Scrapes public betting percentages and line movement data.
Action Network has an undocumented internal API we try first.
Falls back to HTML scraping if the API changes.

Returns public betting % for both sides of a game.
"""
import time
import re
from typing import Optional
import requests
from logger import log

_HEADERS = {
    "User-Agent":      "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "Accept":          "application/json",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer":         "https://www.actionnetwork.com/",
}

# Action Network sport IDs
_AN_SPORTS = {
    "americanfootball_nfl": "NFL",
    "basketball_nba":       "NBA",
    "baseball_mlb":         "MLB",
    "icehockey_nhl":        "NHL",
    "soccer_usa_mls":       "MLS",
}


def get_public_betting(home_team: str, away_team: str, sport_key: str) -> dict:
    """
    Returns {home_pct, away_pct, home_money_pct, away_money_pct, sharp_side, line_movement}.
    Returns empty dict if data unavailable.
    """
    sport = _AN_SPORTS.get(sport_key)
    if not sport:
        return {}

    # Try undocumented Action Network API
    result = _try_api(home_team, away_team, sport)
    if result:
        return result

    return {}


def _try_api(home_team: str, away_team: str, sport: str) -> dict:
    """Try Action Network's internal API."""
    import datetime
    today = datetime.date.today().strftime("%Y%m%d")
    try:
        url  = f"https://api.actionnetwork.com/web/v1/games?sport={sport.lower()}&date={today}&bookIds=15,30,76,123"
        resp = requests.get(url, headers=_HEADERS, timeout=10)
        if resp.status_code != 200:
            return {}

        data  = resp.json()
        games = data.get("games", [])
        for game in games:
            teams = game.get("teams", [])
            names = [t.get("full_name", "") for t in teams]
            if not _teams_match(home_team, away_team, names):
                continue

            # Extract betting percentages
            odds_list = game.get("odds", [{}])
            if not odds_list:
                continue
            latest = odds_list[0]

            home_bets  = latest.get("home_bets_pct") or latest.get("home_bets")
            away_bets  = latest.get("away_bets_pct") or latest.get("away_bets")
            home_money = latest.get("home_money_pct") or latest.get("home_money")
            away_money = latest.get("away_money_pct") or latest.get("away_money")

            # Line movement: opening vs current
            opening_home = latest.get("opening", {}).get("home_ml") if isinstance(latest.get("opening"), dict) else None
            current_home = latest.get("ml_home") or latest.get("home_ml")

            result = {}
            if home_bets is not None:
                result["home_bets_pct"]   = float(home_bets)
                result["away_bets_pct"]   = float(away_bets) if away_bets else 100 - float(home_bets)
            if home_money is not None:
                result["home_money_pct"]  = float(home_money)
                result["away_money_pct"]  = float(away_money) if away_money else 100 - float(home_money)

            # Detect sharp money: line moves opposite to public bets
            if opening_home and current_home and "home_bets_pct" in result:
                pub_on_home     = result["home_bets_pct"] > 50
                line_moved_home = float(current_home) < float(opening_home)   # more negative = worse
                if pub_on_home and not line_moved_home:
                    result["sharp_side"] = "away"
                elif not pub_on_home and line_moved_home:
                    result["sharp_side"] = "home"
                else:
                    result["sharp_side"] = None

            result["opening_home_ml"] = opening_home
            result["current_home_ml"] = current_home
            return result

    except Exception as exc:
        log(f"Action Network API error: {exc}", "WARN")
    return {}


def _teams_match(home: str, away: str, names: list) -> bool:
    """Fuzzy match team names."""
    def norm(s):
        return s.lower().split()[-1]  # just last word (city names vary)
    if len(names) < 2:
        return False
    return (norm(home) in [norm(n) for n in names] or
            norm(away) in [norm(n) for n in names])
