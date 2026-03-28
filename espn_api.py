"""
ESPN FREE API
=============
No API key needed. Used for:
  - Today's game schedules
  - Injury reports
  - Team news
  - Previous game locations (for travel disadvantage)
"""
import datetime
from typing import Optional

import requests

import config
from logger import log

BASE = "https://site.api.espn.com/apis/site/v2/sports"
_TIMEOUT = 10


def get_scoreboard(sport_key: str) -> list:
    """Fetch today's games for a sport."""
    codes = config.ESPN_SPORTS.get(sport_key)
    if not codes:
        return []
    sport, league = codes
    try:
        url  = f"{BASE}/{sport}/{league}/scoreboard"
        resp = requests.get(url, timeout=_TIMEOUT)
        if resp.status_code == 200:
            data   = resp.json()
            events = data.get("events", [])
            return events
    except Exception as exc:
        log(f"ESPN scoreboard error ({sport_key}): {exc}", "WARN")
    return []


def get_injuries(sport_key: str) -> list:
    """
    Fetch current injury report for a sport.
    Returns list of {team, player, status, position}.
    """
    codes = config.ESPN_SPORTS.get(sport_key)
    if not codes:
        return []
    sport, league = codes
    injuries = []
    try:
        url  = f"{BASE}/{sport}/{league}/injuries"
        resp = requests.get(url, timeout=_TIMEOUT)
        if resp.status_code == 200:
            data  = resp.json()
            items = data.get("items", [])
            for item in items:
                team = item.get("team", {}).get("displayName", "")
                for athlete in item.get("injuries", []):
                    injuries.append({
                        "team":     team,
                        "player":   athlete.get("athlete", {}).get("displayName", ""),
                        "position": athlete.get("athlete", {}).get("position", {}).get("abbreviation", ""),
                        "status":   athlete.get("status", ""),
                        "type":     athlete.get("type", ""),
                        "details":  athlete.get("shortComment", ""),
                    })
    except Exception as exc:
        log(f"ESPN injuries error ({sport_key}): {exc}", "WARN")
    return injuries


def get_key_player_out(injuries: list, team: str) -> list:
    """
    Filter injuries to key players (starters) listed as OUT for a team.
    Key positions: QB, RB, WR, TE, C, PG, SG, SF, PF, C, SP, RP, G, D, F.
    """
    key_positions = {
        # NFL
        "QB", "RB", "WR", "TE", "LT", "RT", "C",
        # NBA
        "PG", "SG", "SF", "PF",
        # MLB
        "SP", "RP", "1B", "2B", "3B", "SS", "LF", "CF", "RF", "C",
        # NHL
        "G", "D", "LW", "RW", "C",
        # Soccer
        "GK", "CB", "LB", "RB", "CM", "CAM", "LW", "RW", "ST",
    }
    out_statuses = {"Out", "Doubtful", "IR", "IL", "Injured"}
    result = []
    for inj in injuries:
        if team.lower() not in inj["team"].lower():
            continue
        if any(s.lower() in inj["status"].lower() for s in out_statuses):
            if inj["position"].upper() in key_positions:
                result.append(inj)
    return result


def get_schedule(sport_key: str, days_back: int = 3) -> list:
    """
    Fetch recent schedule to detect back-to-backs and previous locations.
    """
    codes = config.ESPN_SPORTS.get(sport_key)
    if not codes:
        return []
    sport, league = codes
    games = []
    try:
        for d in range(days_back, -1, -1):
            date = (datetime.date.today() - datetime.timedelta(days=d)).strftime("%Y%m%d")
            url  = f"{BASE}/{sport}/{league}/scoreboard?dates={date}"
            resp = requests.get(url, timeout=_TIMEOUT)
            if resp.status_code == 200:
                for ev in resp.json().get("events", []):
                    comp  = ev.get("competitions", [{}])[0]
                    venue = comp.get("venue", {})
                    teams_data = comp.get("competitors", [])
                    for t in teams_data:
                        games.append({
                            "date":     date,
                            "team":     t.get("team", {}).get("displayName", ""),
                            "home":     t.get("homeAway", "") == "home",
                            "city":     venue.get("address", {}).get("city", ""),
                            "state":    venue.get("address", {}).get("state", ""),
                            "result":   comp.get("status", {}).get("type", {}).get("completed", False),
                        })
    except Exception as exc:
        log(f"ESPN schedule error ({sport_key}): {exc}", "WARN")
    return games


def check_back_to_back(schedule: list, team: str) -> bool:
    """Returns True if team played yesterday (back-to-back)."""
    yesterday = (datetime.date.today() - datetime.timedelta(days=1)).strftime("%Y%m%d")
    for game in schedule:
        if game["date"] == yesterday and team.lower() in game["team"].lower():
            return True
    return False


def check_3_in_4(schedule: list, team: str) -> bool:
    """Returns True if team is playing their 3rd game in 4 nights."""
    recent_dates = set()
    for d in range(1, 4):
        date = (datetime.date.today() - datetime.timedelta(days=d)).strftime("%Y%m%d")
        for game in schedule:
            if game["date"] == date and team.lower() in game["team"].lower():
                recent_dates.add(date)
    return len(recent_dates) >= 2


def check_travel_disadvantage(schedule: list, team: str, game_city: str) -> bool:
    """
    Returns True if team traveled cross-country (3+ time zones) in last 48h.
    Rough check using city/state.
    """
    east_cities  = {"boston","new york","brooklyn","philadelphia","washington","miami","atlanta","charlotte","orlando","toronto","montreal"}
    west_cities  = {"los angeles","san francisco","oakland","seattle","portland","phoenix","las vegas","sacramento","san diego","denver","salt lake city","vancouver"}
    yesterday_loc = ""
    for d in range(1, 3):
        date = (datetime.date.today() - datetime.timedelta(days=d)).strftime("%Y%m%d")
        for game in schedule:
            if game["date"] == date and team.lower() in game["team"].lower():
                yesterday_loc = game.get("city", "").lower()
                break
        if yesterday_loc:
            break
    if not yesterday_loc or not game_city:
        return False
    curr_city = game_city.lower()
    was_west  = any(c in yesterday_loc for c in west_cities)
    now_east  = any(c in curr_city     for c in east_cities)
    was_east  = any(c in yesterday_loc for c in east_cities)
    now_west  = any(c in curr_city     for c in west_cities)
    return (was_west and now_east) or (was_east and now_west)
