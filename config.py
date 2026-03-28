"""
FANDUEL BOT — CONFIGURATION
============================
Edit this file to customize your settings.
The only thing you MUST update is BANKROLL when your balance changes.
"""
import os
from pathlib import Path

# ── Bankroll ─────────────────────────────────────────────────────────────────
BANKROLL            = 200.0   # UPDATE THIS when your balance changes
MAX_BET_PCT         = 0.05    # never exceed 5% of bankroll per bet
KELLY_FRACTION      = 0.25    # quarter Kelly for safety
MIN_EDGE_PCT        = 5.0     # minimum edge % to consider alerting

# ── Signal scoring ────────────────────────────────────────────────────────────
MIN_CONFIDENCE      = 60      # minimum score to send alert (0-100)
MIN_SIGNALS         = 2       # minimum number of signals that must stack

SIGNAL_WEIGHTS = {
    "sharp_money":      25,   # line moves opposite to public
    "public_fade":      20,   # 75%+ public on one side
    "late_injury":      30,   # key player ruled out, line not adjusted
    "rest_disadvantage":15,   # back-to-back or 3-in-4
    "travel_disadvantage":15, # cross-country/red-eye travel
    "weather_edge":     20,   # wind>15mph or rain for outdoor games
    "prop_historical":  25,   # player prop vs historical matchup data
}

# ── Filters ───────────────────────────────────────────────────────────────────
PUBLIC_FADE_THRESHOLD   = 75.0   # % public on one side to trigger fade
WIND_SPEED_THRESHOLD    = 15     # mph — above this affects NFL/MLB totals
MIN_GAME_HOURS_OUT      = 1.0    # skip games starting in under 1 hour
MAX_GAME_HOURS_OUT      = 48.0   # skip games more than 48 hours out

# ── Sports ────────────────────────────────────────────────────────────────────
# The Odds API sport keys
SPORT_KEYS = [
    "americanfootball_nfl",
    "basketball_nba",
    "baseball_mlb",
    "icehockey_nhl",
    "soccer_usa_mls",
    "soccer_epl",
    "soccer_esp_la_liga",
    "soccer_ger_bundesliga",
    "soccer_ita_serie_a",
    "soccer_fra_ligue_one",
]

SPORT_DISPLAY = {
    "americanfootball_nfl": "NFL",
    "basketball_nba":       "NBA",
    "baseball_mlb":         "MLB",
    "icehockey_nhl":        "NHL",
    "soccer_usa_mls":       "MLS",
    "soccer_epl":           "EPL",
    "soccer_esp_la_liga":   "La Liga",
    "soccer_ger_bundesliga":"Bundesliga",
    "soccer_ita_serie_a":   "Serie A",
    "soccer_fra_ligue_one": "Ligue 1",
}

OUTDOOR_SPORTS = {"americanfootball_nfl", "baseball_mlb"}

# ── ESPN sport codes ──────────────────────────────────────────────────────────
ESPN_SPORTS = {
    "americanfootball_nfl": ("football",  "nfl"),
    "basketball_nba":       ("basketball","nba"),
    "baseball_mlb":         ("baseball",  "mlb"),
    "icehockey_nhl":        ("hockey",    "nhl"),
    "soccer_usa_mls":       ("soccer",    "usa.1"),
    "soccer_epl":           ("soccer",    "eng.1"),
    "soccer_esp_la_liga":   ("soccer",    "esp.1"),
    "soccer_ger_bundesliga":("soccer",    "ger.1"),
    "soccer_ita_serie_a":   ("soccer",    "ita.1"),
    "soccer_fra_ligue_one": ("soccer",    "fra.1"),
}

# ── API ───────────────────────────────────────────────────────────────────────
ODDS_API_KEY        = os.environ.get("ODDS_API_KEY", "")
ODDS_API_BASE       = "https://api.the-odds-api.com/v4"
ODDS_API_MONTHLY_LIMIT = 490        # leave 10 as buffer from 500 free
ODDS_CACHE_MINUTES  = 110           # cache odds for ~2 hours between scans

# ── Discord ───────────────────────────────────────────────────────────────────
DISCORD_SPORTS_WEBHOOK = os.environ.get(
    "DISCORD_SPORTS_WEBHOOK",
    ""   # paste your #sports-alerts webhook URL here for local testing
)
DISCORD_HEALTH_WEBHOOK = os.environ.get("DISCORD_HEALTH_WEBHOOK", "")

# ── Paths ─────────────────────────────────────────────────────────────────────
BASE_DIR        = Path(__file__).parent
DATA_DIR        = BASE_DIR / "data"
DOCS_DIR        = BASE_DIR / "docs"
BETS_LOG        = BASE_DIR / "bets_log.csv"
BOT_LOG         = BASE_DIR / "bot.log"
API_USAGE_JSON  = DATA_DIR / "api_usage.json"
ODDS_CACHE_JSON = DATA_DIR / "odds_cache.json"
PERFORMANCE_JSON= DATA_DIR / "performance.json"
