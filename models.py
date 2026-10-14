"""
PERSISTENT MODEL STATE
======================
models.json stores signal performance + the auto-generated blocklist so the
scanner starts every scan with everything the bot has learned so far.

Schema:
{
  "signal_performance": {
    "<signal_name>": {
      "bets": N, "wins": N, "pl": $, "roi": pct,
      "disabled": bool, "disabled_reason": str, "updated_at": "..."
    }
  },
  "disabled_signals": ["signal_name", ...],   # convenience view
  "last_updated": "<iso>",
  "last_analysis": { "total_bets": N, "win_rate": pct, "roi": pct }
}
"""
import json
import datetime
from typing import Optional

import config


_DEFAULT = {
    "signal_performance": {},
    "disabled_signals":   [],
    "last_updated":       "",
    "last_analysis":      {},
}


def load() -> dict:
    config.DATA_DIR.mkdir(exist_ok=True)
    if not config.MODELS_JSON.exists():
        return dict(_DEFAULT, signal_performance={}, disabled_signals=[])
    try:
        d = json.loads(config.MODELS_JSON.read_text())
        # Backward-compat: ensure required keys
        d.setdefault("signal_performance", {})
        d.setdefault("disabled_signals",   [])
        return d
    except Exception:
        return dict(_DEFAULT, signal_performance={}, disabled_signals=[])


def save(models: dict) -> None:
    config.DATA_DIR.mkdir(exist_ok=True)
    models["last_updated"] = datetime.datetime.utcnow().isoformat() + "Z"
    config.MODELS_JSON.write_text(json.dumps(models, indent=2))


def is_disabled(signal_name: str, models: Optional[dict] = None) -> bool:
    """Fast check: is this signal currently blocked by the self-improve loop?"""
    if models is None:
        models = load()
    return signal_name in models.get("disabled_signals", [])


def disabled_signals() -> set:
    """Return the current set of blocked signal names. Call once per scan."""
    return set(load().get("disabled_signals", []))
