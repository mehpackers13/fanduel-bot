# ⚠️ MIGRATION NOTICE — 2026-10-15

**Strategy migrated to [kalshi-bot](https://github.com/mehpackers13/kalshi-bot).**

## Why

This bot was alert-only against FanDuel/DraftKings/BetMGM/Caesars which
have **no retail trading API** — you had to manually place every bet
after seeing a Discord alert. Kalshi has a real API and now offers sports
markets including moneylines, spreads, totals, and multi-leg parlays, so
the entire strategy has been moved there where it can auto-execute.

## What transferred

- ✅ **`weather_edge`** (the +10.4% ROI winning signal) — ported to
  `kalshi-bot/sports_models.py` as the totals model. Hits NFL/MLB
  totals markets on outdoor venues when wind >15mph, rain >2mm, or
  cold affects scoring.
- ✅ **ESPN power ratings + log5** — ported for Kalshi moneyline markets
  (NFL/NBA/MLB/NHL/MMA/MLS/EPL).
- ✅ **Self-improvement loop** — Kalshi's existing per-category
  confidence multipliers now apply to Sports too.
- ✅ **Jarvis cross-bot auditing** — overseer's threshold_tuner already
  watches Kalshi's models.json.

## What's still in this repo (frozen as reference)

- `bets_log.csv` — 319 historical FanDuel alerts, 296 regraded with
  real ESPN scores. True record: 144W / 151L / 1 push (48.8% win rate,
  −269 units)
- `data/models.json` — final frozen state of auto-disabled signals
- `self_improve.py` — kept so analysis can run manually if useful
- Discord webhooks still live if you want to use workflow_dispatch for
  one-off historical runs

## What's disabled

Every workflow's `cron:` schedule has been removed. All workflows now
only run via `workflow_dispatch` (manual trigger from GitHub Actions
tab). The repo won't scan on its own anymore.

## To re-activate (unlikely)

Un-decommission by restoring the `cron:` lines in `.github/workflows/*.yml`.
Easier: just use kalshi-bot where the strategy lives now.
