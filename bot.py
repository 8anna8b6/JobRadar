"""
LinkedIn Jobs Telegram Bot — JobRadar
Multi-select seniority + roles, immediate first scrape, daily at 1am Israel time.
Direct company apply links via two-pass scraping.
"""

import logging
import asyncio
import json
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    ContextTypes, ConversationHandler,
)
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
import pytz

from database import Database
from scraper import scrape_jobs_multi
from config import BOT_TOKEN, ADMIN_USER_ID

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

ISRAEL_TZ = pytz.timezone("Asia/Jerusalem")

# ── Conversation states ───────────────────────────────────────────────────
CHOOSING_SENIORITY, CHOOSING_ROLES = range(2)

# ── Options ───────────────────────────────────────────────────────────────
SENIORITY_OPTIONS = [
    ("Intern",    "intern"),
    ("Junior",    "junior"),
    ("Mid-level", "mid"),
    ("Senior",    "senior"),
]

ROLE_OPTIONS = [
    ("Software Engineer",    "software_engineer"),
    ("Frontend Developer",   "frontend_developer"),
    ("Backend Developer",    "backend_developer"),
    ("Full Stack Developer", "fullstack_developer"),
    ("Mobile Developer",     "mobile_developer"),
    ("Data Scientist",       "data_scientist"),
    ("Data Analyst",         "data_analyst"),
    ("ML Engineer",          "ml_engineer"),
    ("AI / GenAI Engineer",  "ai_engineer"),
    ("DevOps / SRE",         "devops_sre"),
    ("QA Engineer",          "qa_engineer"),
    ("Product Manager",      "product_manager"),
    ("UX / UI Designer",     "ux_ui_designer"),
    ("Cybersecurity",        "cybersecurity"),
    ("Data Engineer",        "data_engineer"),
    ("Cloud Engineer",       "cloud_engineer"),
    ("Embedded / Firmware",  "embedded_engineer"),
    ("Game Developer",       "game_developer"),
    ("Business Analyst",     "business_analyst"),
    ("Network Engineer",     "network_engineer"),
]

ROLE_KEYWORDS = {
    "software_engineer":   "Software Engineer",
    "frontend_developer":  "Frontend Developer",
    "backend_developer":   "Backend Developer",
    "fullstack_developer": "Full Stack Developer",
    "mobile_developer":    "Mobile Developer",
    "data_scientist":      "Data Scientist",
    "data_analyst":        "Data Analyst",
    "ml_engineer":         "Machine Learning Engineer",
    "ai_engineer":         "AI Engineer",
    "devops_sre":          "DevOps",
    "qa_engineer":         "QA Engineer",
    "product_manager":     "Product Manager",
    "ux_ui_designer":      "UX Designer",
    "cybersecurity":       "Cybersecurity",
    "data_engineer":       "Data Engineer",
    "cloud_engineer":      "Cloud Engineer",
    "embedded_engineer":   "Embedded Software Engineer",
    "game_developer":      "Game Developer",
    "business_analyst":    "Business Analyst",
    "network_engineer":    "Network Engineer",
}

# key → display label (fixed: was reversed before)
ROLE_LABEL = {key: label for label, key in ROLE_OPTIONS}

db = Database()


# ── Keyboard builders ─────────────────────────────────────────────────────

def seniority_keyboard(selected: list) -> InlineKeyboardMarkup:
    rows = []
    for label, key in SENIORITY_OPTIONS:
        tick = "✅ " if key in selected else "◻️ "
        rows.append([InlineKeyboardButton(f"{tick}{label}", callback_data=f"sen_{key}")])
    rows.append([InlineKeyboardButton("Continue ➡️", callback_data="sen_done")])
    return InlineKeyboardMarkup(rows)


def roles_keyboard(selected: list) -> InlineKeyboardMarkup:
    rows = []
    for i in range(0, len(ROLE_OPTIONS), 2):
        row = []
        for label, key in ROLE_OPTIONS[i:i+2]:
            tick = "✅ " if key in selected else "◻️ "
            row.append(InlineKeyboardButton(f"{tick}{label}", callback_data=f"role_{key}"))
        rows.append(row)
    rows.append([InlineKeyboardButton("✅  Finish Setup", callback_data="role_done")])
    return InlineKeyboardMarkup(rows)


# ── /start ────────────────────────────────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    db.upsert_user(user.id, user.username or user.first_name)
    context.user_data["seniority"] = []
    context.user_data["roles"] = []

    text = (
        f"👋 *Welcome to JobRadar, {user.first_name}!*\n\n"
        "I scan LinkedIn Israel every day and send you the freshest job listings\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "*Step 1 of 2 — Seniority Level*\n"
        "Select all levels that apply to you:\n"
        "_(tap to toggle, then press Continue)_"
    )

    if update.message:
        await update.message.reply_text(text, parse_mode="Markdown", reply_markup=seniority_keyboard([]))
    else:
        await update.callback_query.edit_message_text(text, parse_mode="Markdown", reply_markup=seniority_keyboard([]))

    return CHOOSING_SENIORITY


async def seniority_toggle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "sen_done":
        selected = context.user_data.get("seniority", [])
        if not selected:
            await query.answer("⚠️ Please select at least one level.", show_alert=True)
            return CHOOSING_SENIORITY
        context.user_data["roles"] = []
        await query.edit_message_text(
            "━━━━━━━━━━━━━━━━━━━━\n"
            "*Step 2 of 2 — Job Roles*\n\n"
            "Pick every role you're interested in:\n"
            "_(tap to toggle, then press Finish)_",
            parse_mode="Markdown",
            reply_markup=roles_keyboard([]),
        )
        return CHOOSING_ROLES

    key = query.data.replace("sen_", "")
    selected = context.user_data.get("seniority", [])
    if key in selected:
        selected.remove(key)
    else:
        selected.append(key)
    context.user_data["seniority"] = selected
    await query.edit_message_reply_markup(reply_markup=seniority_keyboard(selected))
    return CHOOSING_SENIORITY


async def role_toggle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "role_done":
        selected_roles = context.user_data.get("roles", [])
        selected_sen   = context.user_data.get("seniority", [])

        if not selected_roles:
            await query.answer("⚠️ Please select at least one role.", show_alert=True)
            return CHOOSING_ROLES

        db.set_preferences(query.from_user.id, json.dumps(selected_sen), json.dumps(selected_roles))
        db.set_active(query.from_user.id, True)

        sen_display   = " · ".join(s.capitalize() for s in selected_sen)
        roles_display = "\n".join(f"  • {ROLE_LABEL.get(r, r)}" for r in selected_roles)

        await query.edit_message_text(
            "🎉 *Profile saved!*\n\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            f"📊 *Seniority:* {sen_display}\n\n"
            f"💼 *Roles:*\n{roles_display}\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            "🔍 Scanning LinkedIn for your first matches...\n"
            "_This takes about 20–30 seconds_",
            parse_mode="Markdown",
        )

        asyncio.create_task(
            run_first_scrape(context.bot, query.from_user.id, selected_sen, selected_roles)
        )
        return ConversationHandler.END

    key = query.data.replace("role_", "")
    selected = context.user_data.get("roles", [])
    if key in selected:
        selected.remove(key)
    else:
        selected.append(key)
    context.user_data["roles"] = selected
    await query.edit_message_reply_markup(reply_markup=roles_keyboard(selected))
    return CHOOSING_ROLES


async def run_first_scrape(bot, user_id: int, seniorities: list, roles: list):
    try:
        jobs = await asyncio.to_thread(scrape_jobs_multi, roles, seniorities, ROLE_KEYWORDS, limit=15)
        if jobs:
            await send_jobs_to_user(bot, user_id, jobs, is_first=True)
        else:
            await bot.send_message(
                chat_id=user_id,
                text=(
                    "🔍 *First scan complete*\n\n"
                    "No matching jobs found on LinkedIn right now — the market may be quiet today.\n\n"
                    "I'll send your first batch tonight at *1:00 AM* 🌙"
                ),
                parse_mode="Markdown"
            )
    except Exception as e:
        logger.error(f"First scrape failed for {user_id}: {e}")


# ── /stop ─────────────────────────────────────────────────────────────────

async def stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    db.set_active(update.effective_user.id, False)
    await update.message.reply_text(
        "⏸ *Daily updates paused.*\n\n"
        "You won't receive morning alerts until you resume.\n"
        "Send /start anytime to turn them back on.",
        parse_mode="Markdown"
    )


# ── /status ───────────────────────────────────────────────────────────────

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    prefs = db.get_preferences(user_id)
    is_active = db.is_active(user_id)

    if not prefs:
        await update.message.reply_text(
            "⚙️ No profile set up yet.\nUse /start to get started.",
            parse_mode="Markdown"
        )
        return

    seniorities, roles = prefs
    state         = "🟢 Active" if is_active else "⏸ Paused"
    sen_display   = " · ".join(s.capitalize() for s in seniorities)
    roles_display = "\n".join(f"  • {ROLE_LABEL.get(r, r)}" for r in roles)

    await update.message.reply_text(
        "📋 *Your JobRadar Profile*\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"📊 *Seniority:* {sen_display}\n\n"
        f"💼 *Roles:*\n{roles_display}\n\n"
        f"📡 *Status:* {state}\n"
        f"🕐 *Daily send:* 1:00 AM Israel time\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "/update — change your preferences\n"
        "/stop — pause daily updates",
        parse_mode="Markdown"
    )


# ── /update ───────────────────────────────────────────────────────────────

async def update_prefs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    return await start(update, context)


# ── /admin ────────────────────────────────────────────────────────────────

async def admin_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_USER_ID:
        await update.message.reply_text("⛔ Admin only.")
        return

    stats = db.get_stats()
    top_roles = "\n".join(
        f"  • {ROLE_LABEL.get(r, r)}: {c}" for r, c in stats["top_roles"]
    ) or "  None yet"
    sen_dist = "\n".join(
        f"  • {s.capitalize()}: {c}" for s, c in stats["seniority_dist"]
    ) or "  None yet"

    await update.message.reply_text(
        "📊 *JobRadar — Admin Dashboard*\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"👥 Total users: *{stats['total']}*\n"
        f"🟢 Active users: *{stats['active']}*\n\n"
        f"💼 *Top roles:*\n{top_roles}\n\n"
        f"📊 *Seniority breakdown:*\n{sen_dist}\n"
        "━━━━━━━━━━━━━━━━━━━━",
        parse_mode="Markdown"
    )


# ── Job message sender ────────────────────────────────────────────────────

async def send_jobs_to_user(bot, user_id: int, jobs: list, is_first: bool = False):
    header = "🎉 *Your first job matches are here!*" if is_first else "🌅 *Good morning! Fresh jobs just for you:*"

    await bot.send_message(
        chat_id=user_id,
        text=(
            f"{header}\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            f"Found *{len(jobs)}* matching positions 🇮🇱\n"
            "_All links go directly to the company's application page_"
        ),
        parse_mode="Markdown"
    )

    for i, job in enumerate(jobs, 1):
        link_label = "Apply Directly →" if job.get("has_direct_link") else "View on LinkedIn →"
        try:
            await bot.send_message(
                chat_id=user_id,
                text=(
                    f"*{i}.* *{job['title']}*\n"
                    f"🏢  {job['company']}\n"
                    f"📍  {job['location']}\n"
                    f"🔗  [{link_label}]({job['url']})"
                ),
                parse_mode="Markdown",
                disable_web_page_preview=True
            )
            await asyncio.sleep(0.3)
        except Exception as e:
            logger.warning(f"Failed to send job to {user_id}: {e}")

    await bot.send_message(
        chat_id=user_id,
        text=(
            "━━━━━━━━━━━━━━━━━━━━\n"
            "💪 *Good luck with your applications!*\n\n"
            "/update — change preferences\n"
            "/stop — pause daily alerts"
        ),
        parse_mode="Markdown"
    )


# ── Daily scheduler ───────────────────────────────────────────────────────

async def daily_send(app: Application):
    logger.info("Starting daily job send...")
    users = db.get_active_users()
    logger.info(f"Sending to {len(users)} active users")

    for user_id, seniorities, roles in users:
        try:
            jobs = await asyncio.to_thread(scrape_jobs_multi, roles, seniorities, ROLE_KEYWORDS, limit=15)
            if jobs:
                await send_jobs_to_user(app.bot, user_id, jobs)
                logger.info(f"Sent {len(jobs)} jobs to {user_id}")
            else:
                await app.bot.send_message(
                    chat_id=user_id,
                    text=(
                        "🌅 *Good morning!*\n\n"
                        "No new matching jobs were posted in the last 24 hours.\n"
                        "I'll check again tomorrow at *1:00 AM* 🌙"
                    ),
                    parse_mode="Markdown"
                )
        except Exception as e:
            logger.error(f"Error sending to {user_id}: {e}")

    logger.info("Daily send complete.")


# ── cancel ────────────────────────────────────────────────────────────────

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ Setup cancelled.\nSend /start whenever you're ready.")
    return ConversationHandler.END


# ── main ──────────────────────────────────────────────────────────────────

def main():
    app = Application.builder().token(BOT_TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[
            CommandHandler("start",  start),
            CommandHandler("update", update_prefs),
        ],
        states={
            CHOOSING_SENIORITY: [CallbackQueryHandler(seniority_toggle, pattern="^sen_")],
            CHOOSING_ROLES:     [CallbackQueryHandler(role_toggle,      pattern="^role_")],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        per_message=False,
    )

    app.add_handler(conv_handler)
    app.add_handler(CommandHandler("stop",   stop))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(CommandHandler("admin",  admin_stats))

    scheduler = AsyncIOScheduler(timezone=ISRAEL_TZ)
    scheduler.add_job(
        daily_send,
        trigger=CronTrigger(hour=1, minute=0, timezone=ISRAEL_TZ),
        args=[app],
    )
    scheduler.start()

    logger.info("Bot started. Daily send at 01:00 AM Israel time.")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()