"""
MAIN SCANNER
============
Fetches all active sports, parses games, runs edge detection.
Silent by default — only alerts when genuine multi-signal edges found.
"""
import datetime
import config
from logger import log
from odds_api import get_odds, parse_game
from edge_calculator import evaluate_game, BetOpportunity
from outcomes import log_opportunity, ensure_log
from discord_alerts import send_bet_alert
from bankroll import bet_summary


def run_scan(morning_mode: bool = False) -> list:
    """
    Full scan. Returns list of BetOpportunity objects that were alerted.
    morning_mode=True returns top 3 without re-alerting (for briefing).
    """
    ensure_log()
    log("=" * 60)
    log(f"Starting {'morning' if morning_mode else 'full'} scan")
    log(bet_summary())

    all_opps = []
    total_games = 0

    for sport_key in config.SPORT_KEYS:
        raw_games = get_odds(sport_key)
        if not raw_games:
            continue

        games = []
        for raw in raw_games:
            parsed = parse_game(raw, sport_key)
            if parsed:
                games.append(parsed)

        total_games += len(games)

        for game in games:
            try:
                opp = evaluate_game(game)
                if opp:
                    all_opps.append(opp)
            except Exception as exc:
                log(f"  Error evaluating {game.get('home_team','?')}: {exc}", "WARN")

    # Sort by confidence desc, then edge desc
    all_opps.sort(key=lambda o: (-o.confidence, -o.edge_pct))

    if morning_mode:
        log(f"Morning scan complete — {total_games} games checked, {len(all_opps)} opportunities")
        return all_opps

    # Alert on all qualifying opportunities
    alerted = 0
    for opp in all_opps:
        send_bet_alert(opp)
        log_opportunity(opp)
        alerted += 1

    if alerted == 0:
        log(f"Scan complete — {total_games} games checked, 0 alerts (silence = discipline)")
    else:
        log(f"Scan complete — {total_games} games checked, {alerted} alert(s) sent")

    log("=" * 60)
    return all_opps
