"""
generate_data.py
================
Converts bets_log.csv and performance.json into docs/data.json
for the GitHub Pages dashboard.
"""
import csv, json
from collections import defaultdict
from datetime import datetime
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
    path = BASE / "bot.log"
    if not path.exists():
        return "Never"
    lines = [l for l in path.read_text().splitlines() if l.strip()]
    for line in reversed(lines):
        if "scan" in line.lower():
            try:
                return line.split("]")[0].lstrip("[").strip()
            except Exception:
                pass
    return lines[-1].split("]")[0].lstrip("[").strip() if lines else "Unknown"


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


def main():
    bets  = read_bets()
    stats = calc_stats(bets)
    perf  = read_performance()
    recent= list(reversed(bets[-50:]))
    data  = {
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "last_scan":    read_last_scan(),
        "stats":        stats,
        "performance":  perf,
        "recent_bets":  recent,
    }
    (DOCS/"data.json").write_text(json.dumps(data, indent=2))
    print(f"docs/data.json written — {len(recent)} bets, stats: {stats['completed_bets']} completed")


if __name__ == "__main__":
    main()
