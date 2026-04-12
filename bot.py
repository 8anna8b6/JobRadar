import logging
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ContextTypes, ConversationHandler,
)
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from database import Database
from scraper import scrape_jobs
from config import BOT_TOKEN, DAILY_HOUR, DAILY_MINUTE

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Conversation states
CHOOSING_SENIORITY, CHOOSING_KEYWORD = range(2)

db = Database()

# ── /start ────────────────────────────────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    db.upsert_user(user.id, user.username or user.first_name)

    keyboard = [
        [InlineKeyboardButton("Intern",   callback_data="seniority_intern")],
        [InlineKeyboardButton("Junior",   callback_data="seniority_junior")],
        [InlineKeyboardButton("Mid-level",callback_data="seniority_mid")],
        [InlineKeyboardButton("Senior",   callback_data="seniority_senior")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        f"Hey {user.first_name}! I send you fresh LinkedIn jobs every day.\n\n"
        "First, what's your seniority level?",
        reply_markup=reply_markup,
    )
    return CHOOSING_SENIORITY


async def seniority_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    seniority = query.data.replace("seniority_", "")
    context.user_data["seniority"] = seniority

    await query.edit_message_text(
        f"Great, *{seniority}* level selected!\n\n"
        "Now send me the *job role or keyword* you're looking for.\n"
        "_(e.g. 'Python developer', 'Data Analyst', 'UX Designer')_",
        parse_mode="Markdown"
    )
    return CHOOSING_KEYWORD


async def keyword_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyword = update.message.text.strip()
    seniority = context.user_data.get("seniority", "junior")
    user = update.effective_user

    db.set_preferences(user.id, seniority, keyword)
    db.set_active(user.id, True)

    await update.message.reply_text(
        f"All set!\n\n"
        f"Role: *{keyword}*\n"
        f"Level: *{seniority}*\n\n"
        f"I'll send you fresh LinkedIn jobs every day at {DAILY_HOUR:02d}:{DAILY_MINUTE:02d} 🕐\n\n"
        "Commands:\n"
        "/update — change your preferences\n"
        "/fetch — get today's jobs right now\n"
        "/stop — pause daily updates\n"
        "/status — see your current settings",
        parse_mode="Markdown"
    )
    return ConversationHandler.END


# ── /fetch ────────────────────────────────────────────────────────────────

async def fetch_now(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    prefs = db.get_preferences(user_id)

    if not prefs:
        await update.message.reply_text(
            "You haven't set up yet! Use /start to configure your preferences."
        )
        return

    seniority, keyword = prefs
    msg = await update.message.reply_text(f"🔍 Searching for *{keyword}* ({seniority}) jobs...", parse_mode="Markdown")

    jobs = scrape_jobs(keyword, seniority, limit=10)

    if not jobs:
        await msg.edit_text("No new jobs found right now. Try again later!")
        return

    await msg.edit_text(f"Found *{len(jobs)}* jobs! Sending them now... 📬", parse_mode="Markdown")
    await send_jobs_to_user(context.bot, user_id, jobs, keyword, seniority)


# ── /stop & /start again ─────────────────────────────────────────────────

async def stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    db.set_active(update.effective_user.id, False)
    await update.message.reply_text(
        "⏸ Daily updates paused. Use /start to resume anytime."
    )


async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    prefs = db.get_preferences(user_id)
    is_active = db.is_active(user_id)

    if not prefs:
        await update.message.reply_text("No preferences set. Use /start to configure.")
        return

    seniority, keyword = prefs
    state = "✅ Active" if is_active else "⏸ Paused"

    await update.message.reply_text(
        f"📋 *Your settings:*\n\n"
        f"Role: *{keyword}*\n"
        f"Level: *{seniority}*\n"
        f"Status: {state}\n"
        f"Daily send: {DAILY_HOUR:02d}:{DAILY_MINUTE:02d}",
        parse_mode="Markdown"
    )


async def update_prefs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Restart the onboarding flow."""
    return await start(update, context)


# ── /admin ────────────────────────────────────────────────────────────────

async def admin_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Only works for the admin user ID set in config."""
    from config import ADMIN_USER_ID
    if update.effective_user.id != ADMIN_USER_ID:
        await update.message.reply_text("⛔ Admin only.")
        return

    stats = db.get_stats()
    await update.message.reply_text(
        f"*Bot Statistics*\n\n"
        f"Total users: *{stats['total']}*\n"
        f"Active users: *{stats['active']}*\n"
        f"Top keywords:\n" +
        "\n".join(f"  • {kw}: {count}" for kw, count in stats['top_keywords']) +
        f"\n\nTop seniority levels:\n" +
        "\n".join(f"  • {s}: {count}" for s, count in stats['seniority_dist']),
        parse_mode="Markdown"
    )


# ── Daily job sender ──────────────────────────────────────────────────────

async def send_jobs_to_user(bot, user_id: int, jobs: list, keyword: str, seniority: str):
    header = (
        f"🗓 *Daily Jobs: {keyword} ({seniority})*\n"
        f"─────────────────────\n\n"
    )
    await bot.send_message(chat_id=user_id, text=header, parse_mode="Markdown")

    for job in jobs:
        text = (
            f"*{job['title']}*\n"
            f"{job['company']}\n"
            f"{job['location']}\n"
            f"[Apply here]({job['url']})"
        )
        try:
            await bot.send_message(
                chat_id=user_id,
                text=text,
                parse_mode="Markdown",
                disable_web_page_preview=True
            )
            await asyncio.sleep(0.3)  # avoid flood limits
        except Exception as e:
            logger.warning(f"Failed to send job to {user_id}: {e}")


async def daily_send(app: Application):
    """Called by scheduler every day — sends jobs to all active users."""
    logger.info("Starting daily job send...")
    users = db.get_active_users()
    logger.info(f"Sending to {len(users)} active users")

    for user_id, seniority, keyword in users:
        try:
            jobs = scrape_jobs(keyword, seniority, limit=10)
            if jobs:
                await send_jobs_to_user(app.bot, user_id, jobs, keyword, seniority)
                logger.info(f"Sent {len(jobs)} jobs to user {user_id}")
            else:
                await app.bot.send_message(
                    chat_id=user_id,
                    text=f"No new *{keyword}* jobs found today. I'll check again tomorrow!",
                    parse_mode="Markdown"
                )
        except Exception as e:
            logger.error(f"Error sending to user {user_id}: {e}")

    logger.info("Daily send complete.")


# ── cancel ────────────────────────────────────────────────────────────────

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Cancelled. Use /start to begin again.")
    return ConversationHandler.END


# ── main ──────────────────────────────────────────────────────────────────

def main():
    app = Application.builder().token(BOT_TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[
            CommandHandler("start", start),
            CommandHandler("update", update_prefs),
        ],
        states={
            CHOOSING_SENIORITY: [CallbackQueryHandler(seniority_chosen, pattern="^seniority_")],
            CHOOSING_KEYWORD:   [MessageHandler(filters.TEXT & ~filters.COMMAND, keyword_received)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    app.add_handler(conv_handler)
    app.add_handler(CommandHandler("fetch",  fetch_now))
    app.add_handler(CommandHandler("stop",   stop))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(CommandHandler("admin",  admin_stats))

    # Scheduler
    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        daily_send,
        trigger="cron",
        hour=DAILY_HOUR,
        minute=DAILY_MINUTE,
        args=[app],
    )
    scheduler.start()

    logger.info(f"Bot started. Daily send at {DAILY_HOUR:02d}:{DAILY_MINUTE:02d}")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
