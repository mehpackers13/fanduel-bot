"""
SELF-IMPROVEMENT ENGINE
=======================
After 30+ completed bets, analyzes which signal combinations have
the highest ROI and adjusts confidence multipliers in performance.json.
"""
import json
from collections import defaultdict
import config
from logger import log
from outcomes import completed_bets, win_rate, roi


def run_analysis() -> dict:
    bets = completed_bets()
    if len(bets) < 30:
        log(f"Self-improve: only {len(bets)} completed bets (need 30) — skipping")
        return {}

    log(f"Self-improve: analyzing {len(bets)} completed bets")

    # By signal type
    by_signal = defaultdict(lambda: {"bets": 0, "wins": 0, "total_pl": 0, "total_risked": 0})
    for bet in bets:
        signals = bet.get("signals", "").split(" + ")
        pl      = float(bet.get("profit_loss") or 0)
        risked  = float(bet.get("suggested_bet") or 0)
        won     = bet.get("outcome") == "W"
        for sig in signals:
            sig = sig.strip()
            if sig:
                by_signal[sig]["bets"]         += 1
                by_signal[sig]["wins"]         += int(won)
                by_signal[sig]["total_pl"]     += pl
                by_signal[sig]["total_risked"] += risked

    # By sport
    by_sport = defaultdict(lambda: {"bets": 0, "wins": 0, "total_pl": 0})
    for bet in bets:
        sport = bet.get("sport", "unknown")
        pl    = float(bet.get("profit_loss") or 0)
        won   = bet.get("outcome") == "W"
        by_sport[sport]["bets"]     += 1
        by_sport[sport]["wins"]     += int(won)
        by_sport[sport]["total_pl"] += pl

    # Calculate ROI per signal
    signal_roi = {}
    for sig, d in by_signal.items():
        r = d["total_risked"]
        signal_roi[sig] = round(d["total_pl"] / r * 100, 1) if r > 0 else 0

    best_signal  = max(signal_roi, key=signal_roi.get) if signal_roi else "N/A"
    worst_signal = min(signal_roi, key=signal_roi.get) if signal_roi else "N/A"

    summary = {
        "total_bets":    len(bets),
        "win_rate":      win_rate(bets),
        "roi":           roi(bets),
        "by_signal":     dict(signal_roi),
        "best_signal":   best_signal,
        "worst_signal":  worst_signal,
        "by_sport":      {s: {"wins": d["wins"], "losses": d["bets"]-d["wins"],
                              "roi": round(d["total_pl"] / max(d["bets"], 1), 1)}
                          for s, d in by_sport.items()},
    }

    # Save to performance.json
    config.DATA_DIR.mkdir(exist_ok=True)
    config.PERFORMANCE_JSON.write_text(json.dumps(summary, indent=2))
    log(f"Performance updated: {win_rate(bets):.1f}% win rate | {roi(bets):+.1f}% ROI")
    log(f"Best signal: {best_signal} ({signal_roi.get(best_signal, 0):+.1f}% ROI)")
    log(f"Worst signal: {worst_signal} ({signal_roi.get(worst_signal, 0):+.1f}% ROI)")

    return summary
