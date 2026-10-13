import os
import asyncio
import logging
import sqlite3
from datetime import datetime
from io import BytesIO

from PIL import Image
from dotenv import load_dotenv
from deep_translator import MyMemoryTranslator

from telegram import (
    Update,
    BotCommand,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
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

def get_vip_status(user_id: int):
    conn = sqlite3.connect("users.db")
    cursor = conn.cursor()
    cursor.execute("SELECT is_vip FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    conn.close()
    return row and row[0] == 1


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
        "📊 **Pulsuz Limit:** Günlük 3 PDF və 3 Tərcümə.\n"
        "⭐ Limitsiz istifadə üçün /vip əmrini seçin.\n\n"
        "Use the / command menu to choose a feature."
    )


async def vip_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    buttons = [
        [InlineKeyboardButton("📅 Aylıq Abunə - $1.99", callback_data="buy_monthly")],
        [InlineKeyboardButton("🌟 İllik Abunə - $20.00", callback_data="buy_yearly")],
    ]
    await update.message.reply_text(
        "💎 **VIP ABUNƏLİK**\n\n"
        "VIP statusu ilə bütün günlük limitləri qaldırın:\n"
        "✔️ Sərhədsiz PDF çevirmə\n"
        "✔️ Sərhədsiz tərcümə\n"
        "✔️ Prioritet dəstək\n\n"
        "Plan seçin:",
        reply_markup=InlineKeyboardMarkup(buttons)
    )


async def select_vip_plan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    plan = "Aylıq ($1.99)" if query.data == "buy_monthly" else "İllik ($20.00)"
    
    await query.edit_message_text(
        f"💳 Seçdiyiniz plan: **{plan}**\n\n"
        "Ödəniş etmək və ya test məqsədilə VIP statusu aktivləşdirmək üçün adminlə əlaqə saxlayın:\n"
        "👉 @AdminAcarSoz (və ya ödəniş kartı məlumatlarını bura daxil edə bilərsiniz)."
    )


async def single(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["mode"] = "single"
    context.user_data["images"] = []

    await update.message.reply_text(
        "🖼️ Send one photo to convert it into a PDF.\n\n"
        "If you send a photo album, its images will be combined "
        "into one PDF."
    )


async def multiple(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["mode"] = "multiple"
    context.user_data["images"] = []

    await update.message.reply_text(
        "📚 Multiple Images Mode\n\n"
        "Send photos one by one or as an album.\n"
        "When finished, use /create.\n\n"
        "All collected images will be combined into ONE PDF."
    )


async def translate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["mode"] = "translate"
    context.user_data["target"] = None

    buttons = [
        [
            InlineKeyboardButton("🇬🇧 English", callback_data="lang_en"),
            InlineKeyboardButton("🇩🇪 German", callback_data="lang_de"),
        ],
        [
            InlineKeyboardButton("🇷🇺 Russian", callback_data="lang_ru"),
            InlineKeyboardButton("🇦🇿 Azerbaijani", callback_data="lang_az"),
        ],
        [
            InlineKeyboardButton("🇹🇷 Turkish", callback_data="lang_tr"),
            InlineKeyboardButton("🇮🇩 Indonesian", callback_data="lang_id"),
        ],
        [
            InlineKeyboardButton("🇸🇦 Arabic", callback_data="lang_ar"),
        ],
    ]

    await update.message.reply_text(
        "🌐 Choose the language for your translations:",
        reply_markup=InlineKeyboardMarkup(buttons),
    )


async def select_language(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    code = query.data.replace("lang_", "")

    if code not in LANGUAGES:
        await query.edit_message_text("Unknown language. Try /translate again.")
        return

    context.user_data["mode"] = "translate"
    context.user_data["target"] = code

    await query.edit_message_text(
        f"✅ Target language: {LANGUAGES[code][0]}\n\n"
        "Send any text message, and I will translate it into this language.\n"
        "Every new text message will be translated until you change mode.\n"
        "Use /translate to choose another language."
    )


def make_pdf(image_data):
    converted = []
    try:
        for data in image_data:
            with Image.open(BytesIO(data)) as image:
                if image.mode in ("RGBA", "P"):
                    image = image.convert("RGB")
                else:
                    image = image.copy()
                converted.append(image)

        if not converted:
            raise ValueError("No images received")

        output = BytesIO()
        converted[0].save(
            output,
            format="PDF",
            save_all=True,
            append_images=converted[1:],
        )
        output.seek(0)
        return output

    finally:
        for image in converted:
            image.close()


async def send_pdf(context, chat_id, user_id, image_data):
    allowed, status = check_and_update_limit(user_id, "pdf")
    if not allowed:
        await context.bot.send_message(
            chat_id=chat_id,
            text="❌ Günlük pulsuz PDF limitiniz bitdi (3/3)!\n"
                 "Sərhədsiz istifadə üçün /vip abunəliyinə keçin."
        )
        return

    output = make_pdf(image_data)
    await context.bot.send_document(
        chat_id=chat_id,
        document=output,
        filename="pdf-master.pdf",
        caption=f"✅ One PDF created with {len(image_data)} image(s).",
    )


async def process_album(context: ContextTypes.DEFAULT_TYPE, chat_id: int, user_id: int, album_key: tuple):
    await asyncio.sleep(2)

    batches = context.bot_data.get("album_batches", {})
    batch = batches.pop(album_key, None)

    if not batch:
        return

    user_data = context.application.user_data.get(user_id, {})
    mode = user_data.get("mode")

    try:
        image_data = []

        for file_id in batch["file_ids"]:
            telegram_file = await context.bot.get_file(file_id)
            data = BytesIO()
            await telegram_file.download_to_memory(out=data)
            image_data.append(data.getvalue())

        if mode == "multiple":
            allowed, status = check_and_update_limit(user_id, "pdf")
            if not allowed:
                await context.bot.send_message(
                    chat_id=chat_id,
                    text="❌ Günlük pulsuz PDF limitiniz bitdi (3/3)!\n"
                         "Sərhədsiz istifadə üçün /vip abunəliyinə keçin."
                )
                return

            user_data.setdefault("images", []).extend(image_data)

            await context.bot.send_message(
                chat_id=chat_id,
                text=(
                    f"✅ Album added: {len(image_data)} images.\n"
                    f"Total collected: {len(user_data['images'])} images.\n\n"
                    "Send more photos or use /create to make ONE PDF."
                ),
            )

        elif mode == "single":
            await send_pdf(context, chat_id, user_id, image_data)

        else:
            await context.bot.send_message(
                chat_id=chat_id,
                text="Please choose /single or /multiple before sending photos.",
            )

    except Exception as error:
        logger.error(f"Album processing failed: {error}")
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"❌ Album processing failed: {type(error).__name__}: {error}",
        )


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.effective_message
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    mode = context.user_data.get("mode")

    if mode == "translate":
        await message.reply_text("Please send text to translate, not a photo.")
        return

    if mode not in ("single", "multiple"):
        await message.reply_text("Choose /single or /multiple first.")
        return

    if message.media_group_id:
        album_key = (chat_id, message.media_group_id)
        batches = context.bot_data.setdefault("album_batches", {})

        if album_key not in batches:
            batches[album_key] = {"file_ids": []}
            asyncio.create_task(process_album(context, chat_id, user_id, album_key))

        batches[album_key]["file_ids"].append(message.photo[-1].file_id)
        return

    try:
        telegram_file = await context.bot.get_file(message.photo[-1].file_id)
        data = BytesIO()
        await telegram_file.download_to_memory(out=data)
        image_bytes = data.getvalue()

        if mode == "multiple":
            user_data = context.user_data
            user_data.setdefault("images", []).append(image_bytes)
            await message.reply_text(
                f"✅ Image added. Total collected: {len(user_data['images'])}.\n"
                "Send more images or use /create."
            )
        else:
            await send_pdf(context, chat_id, user_id, [image_bytes])

    except Exception as error:
        logger.error(f"Image processing failed: {error}")
        await message.reply_text(
            f"❌ Image processing failed: {type(error).__name__}: {error}"
        )


async def create_pdf(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get("mode") != "multiple":
        await update.message.reply_text("First use /multiple.")
        return

    images = context.user_data.get("images", [])

    if not images:
        await update.message.reply_text(
            "No images collected yet. Send your photos first."
        )
        return

    try:
        chat_id = update.effective_chat.id
        user_id = update.effective_user.id
        
        await send_pdf(context, chat_id, user_id, images)
        context.user_data["images"] = []
        context.user_data["mode"] = None

    except Exception as error:
        logger.error(f"PDF creation failed: {error}")
        await update.message.reply_text(
            f"❌ PDF creation failed: {type(error).__name__}: {error}"
        )


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    user_id = update.effective_user.id
    mode = context.user_data.get("mode")

    if mode == "translate":
        target = context.user_data.get("target")

        if not target:
            await update.message.reply_text(
                "Choose a language first using /translate."
            )
            return

        # Limit yoxlanışı
        allowed, status = check_and_update_limit(user_id, "translate")
        if not allowed:
            await update.message.reply_text(
                "❌ Günlük pulsuz tərcümə limitiniz bitdi (3/3)!\n"
                "Sərhədsiz istifadə üçün /vip abunəliyinə keçin."
            )
            return

        status_msg = await update.message.reply_text("🌐 Translating...")

        try:
            url = "https://api.mymemory.translated.net/get"
            params = {
                "q": text,
                "langpair": f"autodetect|{target}"
            }

            async with httpx.AsyncClient(timeout=4.0) as client:
                response = await client.get(url, params=params)
                data = response.json()
                result = data.get("responseData", {}).get("translatedText", "")

            if not result:
                result = "Translation not found."

            await status_msg.edit_text(
                f"🌐 {LANGUAGES[target][0]} translation:\n\n{result}"
            )

        except httpx.TimeoutError:
            await status_msg.edit_text(
                "❌ Translation timed out.\n"
                "Server did not respond in time, please try again."
            )

        except Exception as error:
            logger.error(f"Translation failed: {error}")
            await status_msg.edit_text(
                "❌ Translation failed.\n"
                f"Error: {type(error).__name__}: {error}"
            )
        return

    if mode == "multiple":
        await update.message.reply_text(
            "Your images are being collected. Use /create when finished."
        )
        return

    await update.message.reply_text(
        "Use /single, /multiple, or /translate from the command menu."
    )


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["mode"] = None
    context.user_data["images"] = []
    context.user_data["target"] = None

    await update.message.reply_text(
        "✅ Operation cancelled. Use /start to begin again."
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📖 PDF MASTER HELP\n\n"
        "/start - Start the bot\n"
        "/single - Convert one image to PDF\n"
        "/multiple - Collect photos into one PDF\n"
        "/create - Create one PDF from collected photos\n"
        "/translate - Choose a translation language\n"
        "/vip - Buy VIP status ($1.99/mo or $20/yr)\n"
        "/cancel - Cancel the current operation\n"
        "/help - Show help"
    )


# Admin əmri: İstənilən istifadəçiyə VIP vermək üçün: /makevip İSTİFADƏÇİ_ID
async def make_vip(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Öz Telegram ID-ni buraya yaza bilərsən ki, yalnız sən işlədə biləsən
    if not context.args:
        await update.message.reply_text("İstifadəsi: /makevip <user_id>")
        return
    
    target_id = int(context.args[0])
    conn = sqlite3.connect("users.db")
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET is_vip = 1 WHERE user_id = ?", (target_id,))
    conn.commit()
    conn.close()
    
    await update.message.reply_text(f"✅ User {target_id} uğurla VIP edildi!")


def main():
    if not TOKEN:
        raise RuntimeError(
            "PDF_MASTER_TOKEN is missing. Make sure your .env file is configured correctly."
        )

    app = (
        Application.builder()
        .token(TOKEN)
        .post_init(setup_commands)
        .build()
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("single", single))
    app.add_handler(CommandHandler("multiple", multiple))
    app.add_handler(CommandHandler.from_user(create_pdf, command="create") if hasattr(CommandHandler, "from_user") else CommandHandler("create", create_pdf))
    app.add_handler(CommandHandler("translate", translate))
    app.add_handler(CommandHandler("vip", vip_command))
    app.add_handler(CommandHandler("makevip", make_vip))
    app.add_handler(CommandHandler("cancel", cancel))
    app.add_handler(CommandHandler("help", help_command))

    app.add_handler(CallbackQueryHandler(select_vip_plan, pattern=r"^buy_"))
    app.add_handler(CallbackQueryHandler(select_language, pattern=r"^lang_"))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    logger.info("PDF Master with monetization limits is running...")
    app.run_polling()


if __name__ == "__main__":
    main()
