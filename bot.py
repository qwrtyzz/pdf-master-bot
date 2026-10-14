import os
import asyncio
import logging
import sqlite3
from datetime import datetime
from io import BytesIO

from PIL import Image
from dotenv import load_dotenv
from deep_translator import GoogleTranslator

from telegram import (
    Update,
    BotCommand,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    LabeledPrice,
)
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    PreCheckoutQueryHandler,
    ContextTypes,
    filters,
)

# .env faylından dəyişənləri oxumaq
load_dotenv()

# Loqlaşdırma tənzimləməsi
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

TOKEN = os.getenv("PDF_MASTER_TOKEN")

LANGUAGES = {
    "en": ("English", "en"),
    "de": ("German", "de"),
    "ru": ("Russian", "ru"),
    "az": ("Azerbaijani", "az"),
    "tr": ("Turkish", "tr"),
    "id": ("Indonesian", "id"),
    "ar": ("Arabic", "ar"),
    "fr": ("French", "fr"),
    "es": ("Spanish", "es"),
}

# --- BAZA (DATABASE) TƏNZİMLƏMƏLƏRİ ---
def init_db():
    conn = sqlite3.connect("users.db")
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            pdf_count INTEGER DEFAULT 0,
            translate_count INTEGER DEFAULT 0,
            last_date TEXT,
            is_vip INTEGER DEFAULT 0
        )
    """)
    conn.commit()
    conn.close()

init_db()

def check_and_update_limit(user_id: int, action: str):
    today = datetime.now().strftime("%Y-%m-%d")
    conn = sqlite3.connect("users.db")
    cursor = conn.cursor()
    
    cursor.execute("SELECT pdf_count, translate_count, last_date, is_vip FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    
    if not row:
        cursor.execute("INSERT INTO users (user_id, pdf_count, translate_count, last_date, is_vip) VALUES (?, 0, 0, ?, 0)", (user_id, today))
        conn.commit()
        pdf_c, trans_c, last_d, is_vip = 0, 0, today, 0
    else:
        pdf_c, trans_c, last_d, is_vip = row
        if last_d != today:
            pdf_c, trans_c = 0, 0
            cursor.execute("UPDATE users SET pdf_count = 0, translate_count = 0, last_date = ? WHERE user_id = ?", (today, user_id))
            conn.commit()

    if is_vip == 1:
        conn.close()
        return True, "VIP"

    if action == "pdf":
        if pdf_c >= 3:
            conn.close()
            return False, "Limit"
        cursor.execute("UPDATE users SET pdf_count = pdf_count + 1 WHERE user_id = ?", (user_id,))
    elif action == "translate":
        if trans_c >= 3:
            conn.close()
            return False, "Limit"
        cursor.execute("UPDATE users SET translate_count = translate_count + 1 WHERE user_id = ?", (user_id,))

    conn.commit()
    conn.close()
    return True, "OK"


async def setup_commands(app):
    await app.bot.delete_my_commands()
    await app.bot.set_my_commands([
        BotCommand("start", "start"),
        BotCommand("single", "single photo to pdf"),
        BotCommand("multiple", "multiple photos"),
        BotCommand("create", "create pdf"),
        BotCommand("translate", "translate"),
        BotCommand("vip", "buy VIP status"),
        BotCommand("cancel", "cancel"),
        BotCommand("help", "help"),
    ])


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["mode"] = None
    context.user_data["images"] = []
    context.user_data["target"] = None

    await update.message.reply_text(
        "🌍 Welcome to PDF Master!\n\n"
        "📊 **Free Limits:** 3 PDFs and 3 Translations per day.\n"
        "⭐ Use /vip for unlimited access.\n\n"
        "Use the / command menu to choose a feature."
    )


async def vip_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    buttons = [
        [InlineKeyboardButton("📅 Monthly Subscription - 100 Stars ($1.99)", callback_data="buy_monthly")],
        [InlineKeyboardButton("🌟 Yearly Subscription - 999 Stars ($20.00)", callback_data="buy_yearly")],
    ]
    await update.message.reply_text(
        "💎 **VIP SUBSCRIPTION**\n\n"
        "Remove all daily limits with VIP status:\n"
        "✔️ Unlimited PDF conversions\n"
        "✔️ Unlimited translations\n"
        "✔️ Priority support\n\n"
        "Select your plan:",
        reply
