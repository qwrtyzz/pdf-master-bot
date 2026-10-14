import logging
import sqlite3
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, LabeledPrice
from telegram.ext import ContextTypes

logger = logging.getLogger(__name__)

# VIP menyu düymələri
async def vip_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    buttons = [
        [InlineKeyboardButton("📅 Monthly Subscription - 100 Stars", callback_data="buy_monthly")],
        [InlineKeyboardButton("🌟 Yearly Subscription - 500 Stars", callback_data="buy_yearly")],
    ]
    await update.message.reply_text(
        "💎 **VIP SUBSCRIPTION**\n\n"
        "Remove all daily limits with VIP status:\n"
        "✔️ Unlimited PDF conversions\n"
        "✔️ Unlimited translations\n"
        "✔️ Priority support\n\n"
        "Select your plan:",
        reply_markup=InlineKeyboardMarkup(buttons)
    )

# Plan seçildikdə ödəniş fakturasının (invoice) göndərilməsi
async def select_vip_plan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    chat_id = query.message.chat_id

    if query.data == "buy_monthly":
        title = "Monthly VIP Subscription"
        description = "Unlimited PDF conversions and translations for 1 month."
        payload = "monthly_vip"
        prices = [LabeledPrice("Monthly VIP", 100)]  # 100 Stars
    else:
        title = "Yearly VIP Subscription"
        description = "Unlimited PDF conversions and translations for 1 year."
        payload = "yearly_vip"
        prices = [LabeledPrice("Yearly VIP", 500)]  # 500 Stars

    try:
        await context.bot.send_invoice(
            chat_id=chat_id,
            title=title,
            description=description,
            payload=payload,
            currency="XTR",
            prices=prices,
            provider_token="",
        )
    except Exception as e:
        logger.error(f"Invoice error: {e}")
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"❌ Ödəniş xətası: {e}"
        )

# Ödənişdən əvvəl son təsdiq
async def pre_checkout_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.pre_checkout_query
    await query.answer(ok=True)

# Uğurlu ödənişdən sonra istifadəçiyə VIP statusunun verilməsi
async def successful_payment_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    conn = sqlite3.connect("users.db")
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET is_vip = 1 WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()

    await update.message.reply_text(
        "🎉 **Payment Successful!**\n\n"
        "Thank you! Your account has been automatically upgraded to **VIP** status. Enjoy unlimited access! 🚀"
    )
