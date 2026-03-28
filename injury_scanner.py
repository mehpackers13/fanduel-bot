"""
INJURY SCANNER — runs every 30 minutes
Fast scan: only checks injury reports and alerts on NEW key injuries.
Does not call the Odds API (saves API budget).
Alerts Discord immediately when a key player is ruled out.
"""
import json
import datetime
import config
from logger import log
from espn_api import get_injuries, get_key_player_out, get_scoreboard
from discord_alerts import send_injury_alert

_SEEN_FILE = config.DATA_DIR / "seen_injuries.json"


def _load_seen() -> set:
    if _SEEN_FILE.exists():
        try:
            return set(json.loads(_SEEN_FILE.read_text()))
        except Exception:
            pass
    return set()


def _save_seen(seen: set) -> None:
    config.DATA_DIR.mkdir(exist_ok=True)
    _SEEN_FILE.write_text(json.dumps(list(seen)))


def run_injury_scan() -> int:
    """Returns number of new injuries found."""
    log("Running injury scan")
    seen     = _load_seen()
    new_seen = set(seen)
    new_count = 0

    for sport_key, (sport_code, league) in config.ESPN_SPORTS.items():
        injuries = get_injuries(sport_key)
        games    = get_scoreboard(sport_key)

        for game in games:
            comp       = game.get("competitions", [{}])[0]
            teams_data = comp.get("competitors", [])
            game_name  = game.get("name", "")

            for team_data in teams_data:
                team_name = team_data.get("team", {}).get("displayName", "")
                key_out   = get_key_player_out(injuries, team_name)

                for player in key_out:
                    inj_key = f"{player['player']}_{player['status']}"
                    if inj_key in seen:
                        continue
                    new_seen.add(inj_key)
                    new_count += 1
                    send_injury_alert(
                        sport     = config.SPORT_DISPLAY.get(sport_key, sport_key),
                        team      = team_name,
                        player    = player["player"],
                        position  = player["position"],
                        game      = game_name,
                    )
                    log(f"  NEW injury: {player['player']} ({team_name}) — {player['status']}")

    _save_seen(new_seen)
    if new_count == 0:
        log(f"Injury scan complete — no new key injuries")
    else:
        log(f"Injury scan complete — {new_count} new injury alert(s) sent")
    return new_count
