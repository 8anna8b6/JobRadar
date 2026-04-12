"""
Configuration — values are loaded from .env file or environment variables.
"""

import os
from pathlib import Path

# Load .env file manually (no extra dependency needed)
env_path = Path(__file__).parent / ".env"
if env_path.exists():
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip())

# ── Required ──────────────────────────────────────────────────────────────

# Your Telegram bot token from @BotFather
BOT_TOKEN = os.getenv("BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")

# Your personal Telegram user ID (get it from @userinfobot)
# Only this user can run /admin
ADMIN_USER_ID = int(os.getenv("ADMIN_USER_ID", "0"))

# ── Schedule ──────────────────────────────────────────────────────────────

# Time to send daily jobs (24-hour format, UTC)
DAILY_HOUR   = int(os.getenv("DAILY_HOUR",   "8"))
DAILY_MINUTE = int(os.getenv("DAILY_MINUTE", "0"))
