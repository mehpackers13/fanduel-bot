"""
WEATHER API — wttr.in (completely free, no key needed)
======================================================
Used for NFL and MLB outdoor games only.
Wind > 15mph kills passing games and affects totals.
"""
import requests
from logger import log

# Known outdoor NFL stadiums by city
OUTDOOR_NFL_CITIES = {
    "chicago", "green bay", "pittsburgh", "cleveland", "new york",
    "east rutherford", "foxborough", "boston", "buffalo", "nashville",
    "denver", "kansas city", "baltimore", "cincinnati", "jacksonville",
}

# All MLB stadiums are outdoor unless listed here (retractable roof)
INDOOR_MLB_STADIUMS = {
    "miami", "houston", "seattle", "milwaukee", "phoenix", "toronto",
    "st. petersburg", "tampa",
}


def get_weather(city: str) -> dict:
    """
    Fetch current and forecast weather for a city.
    Returns dict with wind_mph, precip_mm, condition, temp_f.
    """
    if not city:
        return {}
    try:
        url  = f"https://wttr.in/{city.replace(' ', '+')}?format=j1"
        resp = requests.get(url, timeout=8)
        if resp.status_code == 200:
            data    = resp.json()
            current = data.get("current_condition", [{}])[0]
            return {
                "wind_mph":  int(current.get("windspeedMiles", 0)),
                "precip_mm": float(current.get("precipMM", 0)),
                "temp_f":    int(current.get("temp_F", 70)),
                "condition": current.get("weatherDesc", [{}])[0].get("value", ""),
                "humidity":  int(current.get("humidity", 50)),
                "city":      city,
            }
    except Exception as exc:
        log(f"Weather fetch failed for {city}: {exc}", "WARN")
    return {}


def weather_edge(weather: dict, sport_key: str) -> tuple:
    """
    Returns (has_edge: bool, description: str).
    Edge exists when wind > 15mph for NFL/MLB or heavy rain for MLB.
    """
    if not weather:
        return False, ""
    wind = weather.get("wind_mph", 0)
    rain = weather.get("precip_mm", 0)
    if sport_key == "americanfootball_nfl" and wind > 15:
        return True, f"Wind {wind}mph — hammer the UNDER, passing game neutralised"
    if sport_key == "baseball_mlb":
        if wind > 15:
            direction_note = "check wind direction" if wind < 25 else "strong headwind expected"
            return True, f"Wind {wind}mph at MLB game — {direction_note}, affects totals"
        if rain > 2:
            return True, f"Rain {rain}mm forecast — potential delays/cancellations, affects totals"
    return False, ""
