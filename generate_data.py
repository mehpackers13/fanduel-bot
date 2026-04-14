"""
generate_data.py
================
Converts bets_log.csv and performance.json into docs/data.json
for the GitHub Pages dashboard.
"""
import csv, json
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

BASE = Path(__file__).parent
DOCS = BASE / "docs"
DATA = BASE / "data"
DOCS.mkdir(exist_ok=True)


def read_bets():
    path = BASE / "bets_log.csv"
    if not path.exists():
        return []
    with open(path, newline="") as f:
        return [r for r in csv.DictReader(f) if r.get("timestamp")]


def read_performance():
    path = DATA / "performance.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except Exception:
        return {}


def read_last_scan():
    """Returns (last_scan_str, last_scan_iso) by parsing bot.log."""
    path = BASE / "bot.log"
    if not path.exists():
        return "Never", None
    lines = [l for l in path.read_text().splitlines() if l.strip()]
    for line in reversed(lines):
        if any(kw in line.lower() for kw in ["scan complete", "starting", "scan"]):
            try:
                ts_str = line.split("]")[0].lstrip("[").strip()
                return ts_str, ts_str
            except Exception:
                pass
    if lines:
        ts_str = lines[-1].split("]")[0].lstrip("[").strip()
        return ts_str, ts_str
    return "Unknown", None


def calc_stats(bets):
    done  = [b for b in bets if b.get("outcome") in ("W","L","P")]
    wins  = [b for b in done  if b.get("outcome") == "W"]
    total_pl = sum(float(b.get("profit_loss") or 0) for b in done)
    by_sport = defaultdict(lambda: {"bets":0,"wins":0,"pl":0})
    by_signal= defaultdict(lambda: {"bets":0,"wins":0})
    for b in done:
        s = b.get("sport","?")
        by_sport[s]["bets"] += 1
        by_sport[s]["wins"] += int(b.get("outcome")=="W")
        by_sport[s]["pl"]   += float(b.get("profit_loss") or 0)
        for sig in b.get("signals","").split(" + "):
            sig = sig.strip()
            if sig:
                by_signal[sig]["bets"] += 1
                by_signal[sig]["wins"] += int(b.get("outcome")=="W")
    return {
        "total_alerts":   len(bets),
        "completed_bets": len(done),
        "win_rate":        round(len(wins)/len(done)*100,1) if done else None,
        "total_pl":        round(total_pl, 2),
        "by_sport":        dict(by_sport),
        "by_signal":       dict(by_signal),
    }


UNIT_SIZE = 10.0   # 1 unit = 1% of $1000 bankroll = $10


def calc_unit_total(bets):
    """Sum units P&L from all resolved bets. 1u = $10."""
    total = 0.0
    for b in bets:
        if b.get("outcome") not in ("W", "L", "P"):
            continue
        pl = float(b.get("profit_loss") or 0)
        total += pl / UNIT_SIZE
    return round(total, 2)


def read_today_bets(bets):
    """Return bets logged in the last 24 hours."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    today = []
    for b in bets:
        ts_str = b.get("timestamp", "")
        try:
            # timestamps stored as "2026-04-13 07:42 ET" — parse date part
            ts = datetime.strptime(ts_str[:16], "%Y-%m-%d %H:%M")
            # treat as UTC-4 (ET) for comparison — close enough
            if ts >= cutoff.replace(tzinfo=None) - timedelta(hours=4):
                today.append(b)
        except Exception:
            pass
    return list(reversed(today))


def main():
    bets  = read_bets()
    stats = calc_stats(bets)
    perf  = read_performance()
    recent = list(reversed(bets[-50:]))
    last_scan_str, last_scan_ts = read_last_scan()
    unit_total  = calc_unit_total(bets)
    today_bets  = read_today_bets(bets)
    generated   = datetime.utcnow().isoformat() + "Z"
    data  = {
        "generated_at":  generated,
        "last_scan":     last_scan_str,
        "last_scan_ts":  generated,   # use generation time as reliable proxy
        "stats":         stats,
        "unit_total":    unit_total,
        "today_bets":    today_bets,
        "performance":   perf,
        "recent_bets":   recent,
    }
    (DOCS/"data.json").write_text(json.dumps(data, indent=2))
    u_sign = "+" if unit_total >= 0 else ""
    print(f"docs/data.json written — {len(recent)} bets, {stats['completed_bets']} completed, units: {u_sign}{unit_total}u")


if __name__ == "__main__":
    main()
