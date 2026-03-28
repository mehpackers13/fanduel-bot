# SETUP GUIDE — Complete Beginner Walkthrough

Follow these steps in order. Total time: ~15 minutes.

---

## Step 1: Get Your Free Odds API Key (2 minutes)

1. Go to [https://the-odds-api.com](https://the-odds-api.com)
2. Click **Get API Key** → enter your email → verify email
3. Your API key will be displayed on the dashboard (looks like: `abc123def456...`)
4. Copy it somewhere safe — you'll need it in Step 3

**Free tier gives you 500 requests/month.** The bot uses ~60–120/month depending on active sports seasons. You will not exceed the limit.

---

## Step 2: Create a Discord Webhook

You need a Discord server. If you don't have one:
1. Open Discord → click the **+** button in the left sidebar → Create My Own → For me and my friends → give it a name

Then create the webhook:
1. Right-click your server name → **Server Settings**
2. Left sidebar: **Integrations** → **Webhooks** → **New Webhook**
3. Name it: `Sports Alerts`
4. Select which channel to post in (e.g. `#general` or create a `#sports-alerts` channel)
5. Click **Copy Webhook URL** — it looks like: `https://discord.com/api/webhooks/123456789/abcdefg...`
6. Save this URL — you'll use it in Step 3

**Optional:** Repeat to create a second webhook for `#bot-health` (system status messages). You can use the same webhook URL for both if you want everything in one channel.

---

## Step 3: Fork the Repo and Add GitHub Secrets

### Fork the repo
1. Go to `https://github.com/mehpackers13/fanduel-bot`
2. Click **Fork** (top right) → **Create fork**
3. You now have your own copy at `https://github.com/YOUR_USERNAME/fanduel-bot`

### Add secrets
1. In your forked repo, click **Settings** (top menu)
2. Left sidebar: **Secrets and variables** → **Actions**
3. Click **New repository secret** — add these one at a time:

| Secret Name | Value |
|---|---|
| `ODDS_API_KEY` | Your key from Step 1 |
| `DISCORD_SPORTS_WEBHOOK` | Webhook URL from Step 2 |
| `DISCORD_HEALTH_WEBHOOK` | Same webhook URL (or separate health channel URL) |

Each time: type the name exactly as shown → paste the value → click **Add secret**.

---

## Step 4: Enable GitHub Actions

1. In your forked repo, click the **Actions** tab
2. You may see a banner saying "Workflows aren't running" → click **I understand my workflows, go ahead and enable them**
3. You should now see 5 workflows listed:
   - Sports Scan (every 2 hours)
   - Morning Briefing (7am daily)
   - Injury Scanner (every 30 minutes)
   - Weekly Report (Sunday 8pm)
   - Deploy Dashboard (auto-deploys on push)

---

## Step 5: Enable GitHub Pages

This gives you a live dashboard at `https://YOUR_USERNAME.github.io/fanduel-bot/`

1. In your repo, click **Settings**
2. Left sidebar: **Pages**
3. Under **Source**, select **GitHub Actions** (not "Deploy from a branch")
4. Click **Save**

The dashboard deploys automatically whenever `docs/` files change (which happens after every scan).

---

## Step 6: Trigger Your First Test Run

1. Click the **Actions** tab
2. Click **Sports Scan** in the left list
3. Click **Run workflow** → **Run workflow** (green button)
4. Watch it run — click the job to see live logs
5. After ~2 minutes it completes

If everything is configured correctly:
- You'll see a message in Discord (either a bet alert, or a morning briefing if no bets qualify)
- `bot.log` and `data/` files will be updated in the repo
- Your dashboard at `github.io` will show updated stats

**To send a test Discord message** without waiting for a scan, you can add this to a test script locally:
```python
from discord_alerts import send_test_alert
send_test_alert()
```

---

## Step 7: Update Your Bankroll

When your FanDuel balance changes, update `config.py`:

1. In your GitHub repo, navigate to `config.py`
2. Click the **pencil icon** (Edit this file)
3. Find line: `BANKROLL = 200.0`
4. Change `200.0` to your current balance
5. Scroll down → click **Commit changes** → **Commit changes**

The bot will automatically use the new bankroll for Kelly sizing on the next scan.

You can also adjust these settings in `config.py`:
- `MIN_EDGE_PCT = 5.0` — raise to 7.0 for fewer but higher-quality alerts
- `MIN_CONFIDENCE = 60` — raise to 70 for stricter filtering
- `KELLY_FRACTION = 0.25` — lower to 0.20 for even more conservative sizing

---

## Logging Your Bets (Important!)

After each game resolves:
1. In your repo, click `bets_log.csv`
2. Click the pencil icon to edit
3. Find the row for your bet
4. Fill in the `outcome` column: `W` for win, `L` for loss, `P` for push
5. Fill in `profit_loss`: your actual dollar profit/loss
   - Win: amount won (e.g., bet $10 at -150 → win = +$6.67)
   - Loss: negative amount risked (e.g., -$10)
6. Commit the changes

After 30 completed bets, the self-improvement engine activates during the weekly report.

---

## Troubleshooting

**No Discord messages**
- Check that `DISCORD_SPORTS_WEBHOOK` is set correctly in Secrets
- Go to Actions → run the scan manually → check the logs for "No Discord webhook configured"
- Make sure the webhook URL includes the full path (starts with `https://discord.com/api/webhooks/...`)

**"No ODDS_API_KEY" in logs**
- Check that `ODDS_API_KEY` secret is set correctly (no extra spaces)
- The bot will still run but only use cached data (which is empty on first run)

**Actions not running on schedule**
- GitHub may disable scheduled Actions on forked repos by default
- Go to Actions → enable each workflow manually using "Run workflow" once
- After manual triggers, scheduled runs activate automatically

**API budget exhausted**
- Check `data/api_usage.json` in your repo for current month count
- The bot will use cached data when budget runs out (not crash)
- Budget resets on the 1st of each month automatically

**Dashboard not updating**
- Go to Settings → Pages → make sure source is set to "GitHub Actions"
- Run the Deploy Dashboard workflow manually from the Actions tab

---

## Local Development (Optional)

To run locally:
```bash
cd ~/Desktop/fanduel-bot
pip install -r requirements.txt

# Set your keys
export ODDS_API_KEY="your_key_here"
export DISCORD_SPORTS_WEBHOOK="your_webhook_here"

# Run a scan
python run_scan.py

# Run morning briefing
python run_morning.py

# Regenerate dashboard data
python generate_data.py
```
