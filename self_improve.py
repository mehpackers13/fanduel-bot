"""
SELF-IMPROVEMENT ENGINE
=======================
Analyzes every completed bet in bets_log.csv, updates models.json with
per-signal ROI, and auto-disables signals whose live performance is negative.

Running policy:
  - A signal is DISABLED when bets >= AUTO_DISABLE_MIN_BETS AND
    roi% < AUTO_DISABLE_MAX_ROI (default -5%).
  - A disabled signal is RE-ENABLED when its roi% recovers to
    AUTO_REENABLE_MIN_ROI (default 0%).
  - Changes persist in data/models.json which is committed every scan,
    so the scanner starts the next run with everything the bot has learned.
"""
import json
import datetime
from collections import defaultdict

import config
import models as _models
from logger import log
from outcomes import completed_bets, win_rate, roi


def _analyze_signals(bets: list) -> dict:
    """Compute per-signal {bets, wins, pl, risked, roi%} from completed bets."""
    by_signal = defaultdict(lambda: {"bets": 0, "wins": 0, "pl": 0.0, "risked": 0.0})
    for b in bets:
        try:
            pl     = float(b.get("profit_loss") or 0)
            risked = float(b.get("suggested_bet") or 0)
        except Exception:
            pl, risked = 0.0, 0.0
        won = (b.get("outcome") or "").strip().upper() == "W"
        for sig in (b.get("signals") or "").split(" + "):
            sig = sig.strip()
            if not sig:
                continue
            d = by_signal[sig]
            d["bets"]   += 1
            d["wins"]   += int(won)
            d["pl"]     += pl
            d["risked"] += risked
    out = {}
    for sig, d in by_signal.items():
        r = d["risked"]
        out[sig] = {
            "bets":   d["bets"],
            "wins":   d["wins"],
            "losses": d["bets"] - d["wins"],
            "pl":     round(d["pl"], 2),
            "risked": round(r, 2),
            "roi":    round(d["pl"] / r * 100, 1) if r > 0 else 0.0,
        }
    return out


def _update_blocklist(perf: dict, prev_disabled: set) -> tuple:
    """Decide which signals are disabled this run, and what changed since last."""
    disabled, newly_disabled, newly_reenabled = set(), [], []
    now_iso = datetime.datetime.utcnow().isoformat() + "Z"
    for sig, d in perf.items():
        was_disabled = sig in prev_disabled
        normal   = d["bets"] >= config.AUTO_DISABLE_MIN_BETS   and d["roi"] < config.AUTO_DISABLE_MAX_ROI
        severe   = d["bets"] >= config.SEVERE_LOSS_MIN_BETS    and d["roi"] < config.SEVERE_LOSS_MAX_ROI
        qualifies = normal or severe
        if was_disabled:
            if d["roi"] >= config.AUTO_REENABLE_MIN_ROI:
                newly_reenabled.append((sig, d["roi"]))
            else:
                disabled.add(sig)
        else:
            if qualifies:
                disabled.add(sig)
                newly_disabled.append((sig, d["roi"], d["bets"]))
    return disabled, newly_disabled, newly_reenabled, now_iso


def run_analysis() -> dict:
    """
    Main entry point — called from run_scan.py / run_morning.py / run_weekly.py.
    Updates data/models.json. Returns a summary for Discord reporting.
    """
    bets = completed_bets()
    if len(bets) < 30:
        log(f"Self-improve: only {len(bets)} completed bets (need 30) — skipping")
        return {}

    log(f"Self-improve: analyzing {len(bets)} completed bets")

    perf = _analyze_signals(bets)
    models_state  = _models.load()
    prev_disabled = set(models_state.get("disabled_signals", []))

    disabled, newly_disabled, newly_reenabled, now_iso = _update_blocklist(perf, prev_disabled)

    # Stamp disabled flag on every signal row for auditability
    for sig, d in perf.items():
        d["disabled"]       = sig in disabled
        if sig in disabled:
            d["disabled_reason"] = f"roi {d['roi']:+.1f}% over {d['bets']} bets"
        d["updated_at"] = now_iso

    # Persist
    models_state["signal_performance"] = perf
    models_state["disabled_signals"]   = sorted(disabled)
    models_state["last_analysis"] = {
        "total_bets": len(bets),
        "win_rate":   win_rate(bets),
        "roi":        roi(bets),
    }
    _models.save(models_state)

    # Keep legacy performance.json alive for the dashboard
    try:
        config.PERFORMANCE_JSON.write_text(json.dumps({
            "total_bets":    len(bets),
            "win_rate":      win_rate(bets),
            "roi":           roi(bets),
            "by_signal":     {k: v["roi"] for k, v in perf.items()},
            "best_signal":   max(perf, key=lambda k: perf[k]["roi"]) if perf else "N/A",
            "worst_signal":  min(perf, key=lambda k: perf[k]["roi"]) if perf else "N/A",
            "disabled":      sorted(disabled),
        }, indent=2))
    except Exception as exc:
        log(f"Self-improve: couldn't write performance.json: {exc}", "WARN")

    # Terse logs
    log(f"Perf: {win_rate(bets):.1f}% win | {roi(bets):+.1f}% ROI | signals active: "
        f"{len(perf) - len(disabled)}/{len(perf)}  (disabled: {sorted(disabled) or 'none'})")
    for sig, r, n in newly_disabled:
        log(f"🚫 DISABLED signal '{sig}' (roi {r:+.1f}% over {n} bets)", "WARN")
    for sig, r in newly_reenabled:
        log(f"✅ RE-ENABLED signal '{sig}' (roi recovered to {r:+.1f}%)")

    return {
        "total_bets":        len(bets),
        "win_rate":          win_rate(bets),
        "roi":               roi(bets),
        "by_signal":         {k: v["roi"] for k, v in perf.items()},
        "disabled":          sorted(disabled),
        "newly_disabled":    [s for s, _, _ in newly_disabled],
        "newly_reenabled":   [s for s, _ in newly_reenabled],
    }
