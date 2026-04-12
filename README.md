# LinkedIn Jobs Telegram Bot

Sends daily LinkedIn job listings to subscribers based on their seniority level and keyword preference.

---

## Features

- 👥 Multi-user — anyone can subscribe
- 📅 Daily automatic send (configurable time)
- 🎯 Per-user seniority filter (Intern / Junior / Mid / Senior)
- 🔍 Per-user keyword/role filter
- ⚡ `/fetch` to get jobs on demand
- 📊 `/admin` command for user stats (owner only)
- 💾 SQLite — zero external dependencies

---

## Setup (5 minutes)

### 1. Create a Telegram Bot

1. Open Telegram → search for **@BotFather**
2. Send `/newbot`
3. Follow prompts — you'll get a **token** like `7123456789:AAF...`
4. Copy it

### 2. Get Your User ID

1. Open Telegram → search for **@userinfobot**
2. Send `/start` — it will reply with your numeric user ID
3. Copy it (you'll need it for admin access)

### 3. Install & Configure

```bash
# Clone or download this folder, then:
cd linkedin_jobs_bot

pip install -r requirements.txt

# Edit config.py — set your BOT_TOKEN and ADMIN_USER_ID
# Or set environment variables:
export BOT_TOKEN="your_token_here"
export ADMIN_USER_ID="your_user_id_here"
export DAILY_HOUR=8       # UTC hour to send daily jobs
export DAILY_MINUTE=0
```

### 4. Run

```bash
python bot.py
```

That's it! Open Telegram and send `/start` to your bot.

---

## Commands

| Command    | Description                        |
|------------|------------------------------------|
| `/start`   | Onboarding: choose seniority + keyword |
| `/update`  | Change your preferences            |
| `/fetch`   | Get today's jobs right now         |
| `/stop`    | Pause daily updates                |
| `/status`  | See your current settings          |
| `/admin`   | Stats (owner only)                 |

---

## Hosting for Free

### Option A — Render.com (recommended)

1. Push this folder to a GitHub repo
2. Go to [render.com](https://render.com) → New → **Web Service**
3. Connect your repo
4. Set:
   - **Runtime**: Python 3
   - **Build command**: `pip install -r requirements.txt`
   - **Start command**: `python bot.py`
5. Add environment variables: `BOT_TOKEN`, `ADMIN_USER_ID`, `DAILY_HOUR`, `DAILY_MINUTE`
6. Deploy

> ⚠️ Render free tier sleeps after 15 min of inactivity. For a bot using polling this is fine — the bot wakes up when it gets a message. But the scheduler may miss the daily send if no one has messaged recently. To fix this, add a free uptime monitor at **uptimerobot.com** pointing to your Render URL.

### Option B — Railway.app

Same steps as Render. Railway gives 500 free hours/month on the free plan.

### Option C — Your own machine / VPS

Just run `python bot.py` in a `screen` or `tmux` session, or use `systemd`.

---

## File Structure

```
linkedin_jobs_bot/
├── bot.py          # Telegram bot handlers + scheduler
├── scraper.py      # LinkedIn scraper (requests + BS4)
├── database.py     # SQLite user storage
├── config.py       # Token + schedule settings
├── requirements.txt
└── README.md
```

---

## Notes on LinkedIn Scraping

- The scraper uses `requests` + `BeautifulSoup` — no Chrome/Selenium needed
- It filters by `f_TPR=r86400` (last 24 hours) and seniority level (`f_E`)
- LinkedIn occasionally changes their HTML structure; if jobs stop showing up, inspect the CSS selectors in `scraper.py → parse_jobs()`
- If you get blocked, add a proxy or increase the sleep delay in `scraper.py`
