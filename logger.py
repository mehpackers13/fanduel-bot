"""Simple timestamped logger that writes to bot.log and stdout."""
import datetime, sys
from pathlib import Path
import config

def log(msg: str, level: str = "INFO") -> None:
    try:
        tz = datetime.timezone(datetime.timedelta(hours=-4))  # ET approx
        ts = datetime.datetime.now(tz).strftime("%Y-%m-%d %H:%M:%S ET")
    except Exception:
        ts = datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
    line = f"[{ts}] [{level}] {msg}"
    print(line, flush=True)
    try:
        config.BOT_LOG.parent.mkdir(exist_ok=True)
        with open(config.BOT_LOG, "a") as f:
            f.write(line + "\n")
    except Exception:
        pass
