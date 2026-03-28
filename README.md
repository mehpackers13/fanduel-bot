# fanduel-bot — Sports Betting Edge Finder

Automated edge-detection bot covering 10 sports. Runs on GitHub Actions (free tier), sends alerts to Discord, tracks outcomes, and self-improves over time.

**Philosophy:** Most bettors lose because they bet on gut feel. This bot only fires when multiple independent signals stack on the same game — public fade + sharp money + late injury = high-confidence opportunity. Silence is the default. Quality over quantity.

---

## What It Does

Every 2 hours the bot:
1. Fetches live odds across 10 sports (NFL, NBA, MLB, NHL, MLS, EPL, La Liga, Bundesliga, Serie A, Ligue 1)
2. Checks 7 independent edge signals per game
3. Calculates a confidence score (0–100)
4. If ≥2 signals fire AND confidence ≥60 AND edge ≥5% → sends a Discord alert
5. Logs the opportunity to `bets_log.csv`

Every 30 minutes the injury scanner checks for new key-player outages and alerts you before lines fully adjust.

Every morning at 7am ET you get a briefing with the top 3 opportunities for the day.

Every Sunday at 8pm ET you get a full performance breakdown.

---

## Quick Start (5 Steps)

### Step 1: Get your free Odds API key
Go to [the-odds-api.com](https://the-odds-api.com) → Sign up → Copy your API key.
Free tier: 500 requests/month. The bot uses ~120/month (caching keeps it efficient).

### Step 2: Create a Discord webhook
1. Open Discord → your server → Edit Channel → Integrations → Webhooks → New Webhook
2. Name it "Sports Alerts", copy the URL

### Step 3: Fork this repo and add GitHub Secrets
Fork → Settings → Secrets and variables → Actions → New repository secret:
- `ODDS_API_KEY` — your odds API key
- `DISCORD_SPORTS_WEBHOOK` — your Discord webhook URL
- `DISCORD_HEALTH_WEBHOOK` — same URL, or a separate #bot-health channel (optional)

### Step 4: Enable GitHub Actions
Go to Actions tab → Enable workflows. They will run on schedule automatically.

### Step 5: Done
The bot is live. Run any workflow manually (Actions → workflow → Run workflow) to test immediately.

---

## The 7 Signals

Each signal has a weight. Signals stack to form a confidence score. You need ≥2 signals and ≥60 confidence for an alert.

| Signal | Weight | How it works |
|---|---|---|
| `sharp_money` | 25 | Line moves opposite to public betting % → sharps are on the other side |
| `public_fade` | 20 | 75%+ of public tickets on one side → fade the square bettors |
| `late_injury` | 30 | Key player (QB, PG, SP, etc.) ruled out within 24h → line may not have adjusted |
| `rest_disadvantage` | 15 | Team on back-to-back or 3rd game in 4 nights → fatigue affects performance |
| `travel_disadvantage` | 15 | Cross-country travel (3+ time zones) in last 48 hours |
| `weather_edge` | 20 | Wind >15mph (NFL/MLB outdoor) → hammers totals, negates passing games |
| `prop_historical` | 25 | Player prop vs historical matchup data (future expansion) |

### Example alert
```
NBA | Lakers @ Celtics
MONEYLINE — Celtics -145
Edge: 7.2% | Confidence: 85/100
Signals: sharp_money + rest_disadvantage + public_fade
Suggested: $10 (1.2% bankroll)
```
This means: 78% of public likes the Lakers. The line moved toward Celtics anyway (sharp money on Celtics). Lakers are on a back-to-back. Three independent signals all point the same direction.

---

## Logging Outcomes

After each game resolves, open `bets_log.csv` and fill in:
- `outcome`: `W` (win) / `L` (loss) / `P` (push)
- `profit_loss`: dollar amount (positive for wins, negative for losses)

Example: You bet $10 on the Celtics ML at -145. They win. Your profit = `+$6.90`.

After 30+ completed bets, the self-improvement engine activates automatically (runs with the weekly report).

---

## Self-Improvement System

`self_improve.py` runs after 30 completed bets. It:
1. Calculates ROI broken down by each signal type
2. Calculates ROI by sport
3. Identifies which signals have historically been most predictive
4. Saves results to `data/performance.json`
5. Surfaces best/worst signal in the weekly Discord report

Over time, this tells you which signal combinations to trust most in your specific bankroll context.

---

## How to Read Discord Alerts

- **Green embed** (confidence ≥80): Strong signal stack. High conviction.
- **Gold embed** (confidence 70–79): Medium signal stack. Solid opportunity.
- **Orange embed** (confidence 60–69): Minimum qualifying threshold. Smaller bet.

The suggested bet size uses fractional Kelly (1/4 Kelly, capped at 5% of bankroll). It automatically scales with your edge — stronger edges get larger bets.

**Silence = discipline.** Days with no alerts are the bot doing its job — protecting you from low-confidence bets.

---

## API Usage

The bot uses [The Odds API](https://the-odds-api.com) free tier (500 requests/month).

How it conserves requests:
- **2-hour cache**: Odds are cached for 110 minutes. 10 sports × ~4 refreshes/day = ~40 requests/day → ~1,200/month... BUT
- Only sports currently in season are fetched (422 response = skip)
- In practice: 3–5 active sports × 4 refreshes = ~60–80 requests/day → well within 500/month
- `data/api_usage.json` tracks your rolling monthly count
- At 50 requests remaining, the bot warns you in the log
- If the budget is exhausted, stale cache is used rather than crashing

ESPN (injuries, schedules, scoreboards) and wttr.in (weather) are completely free with no API keys required.

---

## Dashboard

After pushing to GitHub, enable Pages from the `docs/` folder. Your dashboard is at:
`https://YOUR_USERNAME.github.io/fanduel-bot/`

Shows: last scan time, all-time stats, recent bets table, performance by sport, performance by signal.

---

## File Reference

| File | Purpose |
|---|---|
| `config.py` | All settings — update `BANKROLL` when balance changes |
| `bets_log.csv` | Master bet log — fill in outcome/P&L manually |
| `data/api_usage.json` | API request counter |
| `data/performance.json` | Self-improvement analysis output |
| `data/odds_cache.json` | Cached odds to conserve API budget |
| `bot.log` | Full run history |
