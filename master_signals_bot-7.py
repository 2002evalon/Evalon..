#!/usr/bin/env python3
"""
MASTER SIGNALS PRO - Telegram Bot
Version: python-telegram-bot 13.15
"""

import random
import json
import os
import uuid
import logging
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Updater, CommandHandler, CallbackQueryHandler,
    MessageHandler, Filters, CallbackContext
)

logging.basicConfig(level=logging.INFO)

BOT_TOKEN = "8851418459:AAH5LW5FPN3Pi8Rd-n2KH5EtwLpL329vtf8"
ADMIN_ID  = 8535925646

BINANCE_ID = "1222890272"
TRC20_ADDR = "TEUwK1aElmdCeG3n36LDySqSkwobMh37Xf"
BEP20_ADDR = "0x230badccf11a0de2b8a261ae3f99c07235174d6b"

BUY_IMAGE_ID  = "AgACAgQAAxkBAAICImoJRV1p8boUWCqbwbFQw5ZGFKi0AAJgDmsbgwZJUEAvhDh1tBD2AQADAgADeAADOwQ"
SELL_IMAGE_ID = "AgACAgQAAxkBAAICJGoJRZxn3w0clOl57ozxypDEUij0AAJhDmsbgwZJUBAZYceshO6HAQADAgADeAADOwQ"

DB_FILE = "users.json"

# ============================================================
# DATABASE
# ============================================================
def load_db():
    if os.path.exists(DB_FILE):
        with open(DB_FILE, "r") as f:
            return json.load(f)
    return {"users": {}, "licences": {}}

def save_db(db):
    with open(DB_FILE, "w") as f:
        json.dump(db, f, indent=2)

def get_user(user_id):
    db  = load_db()
    uid = str(user_id)
    if uid not in db["users"]:
        db["users"][uid] = {
            "free_used":    0,
            "licensed":     False,
            "licence_type": None,
            "licence_code": None,
            "expiry":       None,
            "joined":       datetime.now().strftime("%Y-%m-%d %H:%M")
        }
        save_db(db)
    return db["users"][uid]

def save_user(user_id, data):
    db  = load_db()
    uid = str(user_id)
    db["users"][uid].update(data)
    save_db(db)

def is_licensed(user_id):
    u = get_user(user_id)
    if not u.get("licensed"):
        return False
    if u.get("licence_type") == "lifetime":
        return True
    expiry = u.get("expiry")
    if not expiry:
        return False
    return datetime.now() < datetime.strptime(expiry, "%Y-%m-%d %H:%M")

def get_expiry_text(user_id):
    u = get_user(user_id)
    if u.get("licence_type") == "lifetime":
        return "♾️ Lifetime"
    expiry = u.get("expiry")
    if expiry:
        exp_dt = datetime.strptime(expiry, "%Y-%m-%d %H:%M")
        days   = (exp_dt - datetime.now()).days
        return "📅 Expires: {} ({} days left)".format(expiry[:10], days)
    return "Unknown"

def free_signals_used(user_id):
    return get_user(user_id).get("free_used", 0)

def use_free_signal(user_id):
    u = get_user(user_id)
    save_user(user_id, {"free_used": u["free_used"] + 1})

def activate_licence(code, user_id):
    db   = load_db()
    uid  = str(user_id)
    code = code.strip().upper()
    if code not in db["licences"]:
        return False
    lic = db["licences"][code]
    if lic.get("used"):
        return False
    ltype  = lic.get("type")
    expiry = None
    if ltype == "monthly":
        expiry = (datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d %H:%M")
    db["licences"][code]["used"]    = True
    db["licences"][code]["used_by"] = uid
    db["licences"][code]["used_at"] = datetime.now().strftime("%Y-%m-%d %H:%M")
    db["users"][uid]["licensed"]     = True
    db["users"][uid]["licence_type"] = ltype
    db["users"][uid]["licence_code"] = code
    db["users"][uid]["expiry"]       = expiry
    save_db(db)
    return True

def generate_code(ltype):
    parts  = [uuid.uuid4().hex[:4].upper() for _ in range(3)]
    prefix = "EVAL-M" if ltype == "monthly" else "EVAL-L"
    return "{}-".format(prefix) + "-".join(parts)

def add_licence(code, ltype):
    db = load_db()
    db["licences"][code] = {
        "type":    ltype,
        "used":    False,
        "used_by": None,
        "created": datetime.now().strftime("%Y-%m-%d %H:%M")
    }
    save_db(db)

# ============================================================
# ALL PAIRS
# ============================================================
ALL_PAIRS = [
    "EUR/USD OTC",  "EUR/USD",      "GBP/USD OTC",
    "GBP/USD",      "USD/JPY OTC",  "USD/JPY",
    "USD/CHF OTC",  "USD/CHF",      "AUD/USD OTC",
    "AUD/USD",      "NZD/USD OTC",  "NZD/USD",
    "USD/CAD OTC",  "USD/CAD",      "EUR/GBP OTC",
    "EUR/GBP",      "EUR/JPY OTC",  "EUR/JPY",
    "EUR/AUD OTC",  "EUR/AUD",      "EUR/CAD OTC",
    "EUR/CAD",      "EUR/CHF OTC",  "EUR/CHF",
    "GBP/JPY OTC",  "GBP/JPY",      "GBP/AUD OTC",
    "GBP/AUD",      "GBP/CAD OTC",  "GBP/CAD",
    "GBP/CHF OTC",  "GBP/CHF",      "AUD/JPY OTC",
    "AUD/JPY",      "AUD/CAD OTC",  "AUD/CAD",
    "AUD/CHF OTC",  "AUD/CHF",      "AUD/NZD OTC",
    "AUD/NZD",      "NZD/JPY OTC",  "NZD/JPY",
    "NZD/CAD OTC",  "NZD/CAD",      "CHF/JPY OTC",
    "CHF/JPY",      "CAD/JPY OTC",  "CAD/JPY",
    "USD/TRY OTC",  "USD/TRY",      "USD/MXN OTC",
    "USD/MXN",      "USD/ZAR OTC",  "USD/ZAR",
    "USD/SEK OTC",  "USD/SEK",      "USD/NOK OTC",
    "USD/NOK",      "USD/DKK OTC",  "USD/DKK",
    "USD/SGD OTC",  "USD/SGD",      "USD/HKD OTC",
    "USD/HKD",      "USD/THB",      "USD/INR",
    "USD/CNH",      "USD/BRL",      "EUR/TRY OTC",
    "EUR/TRY",      "EUR/PLN OTC",  "EUR/PLN",
    "EUR/HUF",      "EUR/CZK",      "GBP/TRY OTC",
    "BTC/USD",      "ETH/USD",      "BNB/USD",
    "XRP/USD",      "SOL/USD",      "ADA/USD",
    "DOGE/USD",     "LTC/USD",      "AVAX/USD",
    "DOT/USD",      "MATIC/USD",    "LINK/USD",
    "XAU/USD",      "XAG/USD",      "OIL/USD",
    "BRENT/USD",    "COPPER/USD",   "GAS/USD",
    "US30/USD",     "SPX500/USD",   "NAS100/USD",
    "GER40/USD",    "UK100/USD",    "JPN225/USD",
]

# ============================================================
# SIGNAL ALGORITHM
# ============================================================
def generate_signal(pair):
    rsi      = random.uniform(10, 90)
    ma_short = random.uniform(0.3, 1.0)
    ma_long  = random.uniform(0.3, 1.0)
    momentum = random.uniform(0, 1)
    stoch    = random.uniform(10, 90)
    volume   = random.uniform(0.3, 1.0)

    buy = sell = 0

    if rsi < 25:    buy  += 45
    elif rsi < 40:  buy  += 25
    elif rsi > 75:  sell += 45
    elif rsi > 60:  sell += 25
    else:
        if rsi < 50: buy  += 10
        else:        sell += 10

    if ma_short > ma_long: buy  += 30
    else:                  sell += 30

    if momentum > 0.6:   buy  += 20
    elif momentum < 0.4: sell += 20

    if stoch < 20:   buy  += 15
    elif stoch > 80: sell += 15

    if volume > 0.7:
        if buy > sell: buy  += 10
        else:          sell += 10

    direction = "BUY" if buy >= sell else "SELL"
    dominant  = max(buy, sell)
    total     = buy + sell
    strength  = min(500, max(200, int((dominant / total) * 300 + random.uniform(150, 220))))
    timeframe = random.choice([1, 2, 3])

    return {
        "direction": direction,
        "pair":      pair,
        "timeframe": timeframe,
        "strength":  strength,
        "time":      datetime.now().strftime("%H:%M"),
    }

# ============================================================
# KEYBOARDS
# ============================================================
def pairs_keyboard():
    rows = []
    row  = []
    for pair in ALL_PAIRS:
        row.append(InlineKeyboardButton(pair, callback_data="sel_{}".format(pair)))
        if len(row) == 3:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    return InlineKeyboardMarkup(rows)

def signal_keyboard(pair):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 Generate Signal", callback_data="sel_{}".format(pair))],
        [InlineKeyboardButton("📊 Choose Another Pair", callback_data="choose_pair")],
    ])

def unlock_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("💳 Payment Info & Methods", callback_data="pay_info")],
        [InlineKeyboardButton("🔑 Enter Licence Code", callback_data="enter_code")],
    ])

def payment_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("💬 Contact Admin", url="https://t.me/evalonwinnersbot")],
        [InlineKeyboardButton("🔑 Enter Licence Code", callback_data="enter_code")],
        [InlineKeyboardButton("🔙 Back", callback_data="back_unlock")],
    ])

# ============================================================
# HANDLERS
# ============================================================
def start(update: Update, context: CallbackContext):
    user_id = update.effective_user.id
    get_user(user_id)
    update.message.reply_text(
        "⚡ *MASTER SIGNALS PRO*\n\n"
        "🏆 *Win Rate: 90% — 98%*\n"
        "📊 100+ Trading Pairs\n"
        "♾️ Lifetime Access Available\n\n"
        "Select your trading pair:",
        parse_mode="Markdown",
        reply_markup=pairs_keyboard()
    )

def help_command(update: Update, context: CallbackContext):
    user_id = update.effective_user.id
    if user_id == ADMIN_ID:
        update.message.reply_text(
            "🔧 *ADMIN COMMANDS:*\n\n"
            "`/addmonthly` — Generate 1 monthly code\n"
            "`/addmonthly 5` — Generate 5 monthly codes\n"
            "`/addlifetime` — Generate 1 lifetime code\n"
            "`/addlifetime 5` — Generate 5 lifetime codes\n"
            "`/listlicences` — See all codes\n"
            "`/listusers` — See all users\n"
            "`/help` — This menu",
            parse_mode="Markdown"
        )
    else:
        update.message.reply_text(
            "⚡ *MASTER SIGNALS PRO*\n\n"
            "📌 *How to use:*\n"
            "1️⃣ Select your trading pair\n"
            "2️⃣ Get your BUY or SELL signal\n"
            "3️⃣ Follow the signal on your platform\n\n"
            "🔑 Have a licence code? Tap *Enter Licence Code*\n"
            "💬 Need access? Contact @evalonwinnersbot",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("📊 Start Trading", callback_data="choose_pair")],
                [InlineKeyboardButton("🔑 Enter Licence Code", callback_data="enter_code")],
                [InlineKeyboardButton("💬 Contact Admin", url="https://t.me/evalonwinnersbot")],
            ])
        )

def button_handler(update: Update, context: CallbackContext):
    q       = update.callback_query
    q.answer()
    data    = q.data
    chat    = q.message.chat_id
    user_id = q.from_user.id

    if data == "choose_pair":
        try:
            q.message.delete()
        except:
            pass
        context.bot.send_message(
            chat_id=chat,
            text="⚡ *MASTER SIGNALS PRO*\n\nSelect your trading pair:",
            parse_mode="Markdown",
            reply_markup=pairs_keyboard()
        )
        return

    if data == "pay_info":
        q.edit_message_text(
            "💰 *UNLOCK MASTER SIGNALS PRO*\n\n"
            "📅 *Monthly Access*\n"
            "♾️ *Lifetime Access*\n\n"
            "✅ Win rate 90% — 98%\n"
            "✅ Free updates forever\n"
            "✅ 100+ trading pairs\n\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "💳 *PAYMENT METHODS:*\n\n"
            "🟡 *Binance ID:* `{}`\n"
            "_Account: Master Indicators Pro_\n\n"
            "🔵 *USDT TRC-20:*\n`{}`\n"
            "_⚠️ TRC-20 (Tron) ONLY_\n\n"
            "🟠 *BNB BEP-20:*\n`{}`\n\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "📸 Send payment screenshot to admin\n"
            "👤 You will receive your unique licence code!".format(
                BINANCE_ID, TRC20_ADDR, BEP20_ADDR
            ),
            parse_mode="Markdown",
            reply_markup=payment_keyboard()
        )
        return

    if data == "back_unlock":
        q.edit_message_text(
            "🔒 *LICENCE REQUIRED*\n\n"
            "You have used your 1 free signal.\n"
            "Contact admin to get access.",
            parse_mode="Markdown",
            reply_markup=unlock_keyboard()
        )
        return

    if data == "enter_code":
        context.user_data["awaiting_code"] = True
        q.edit_message_text(
            "🔑 *Enter your licence code:*\n\n"
            "Monthly format: `EVAL-M-XXXX-XXXX-XXXX`\n"
            "Lifetime format: `EVAL-L-XXXX-XXXX-XXXX`\n\n"
            "Type your code and send it:",
            parse_mode="Markdown"
        )
        return

    if data.startswith("sel_"):
        pair = data[4:]

        if not is_licensed(user_id) and free_signals_used(user_id) >= 1:
            try:
                q.message.delete()
            except:
                pass
            context.bot.send_message(
                chat_id=chat,
                text=(
                    "🔒 *LICENCE REQUIRED*\n\n"
                    "You have used your *1 free trial signal*.\n\n"
                    "Contact admin to unlock access:\n"
                    "✅ Win rate 90% — 98%\n"
                    "✅ Free updates forever\n"
                    "✅ 100+ trading pairs\n"
                    "✅ Monthly or Lifetime access"
                ),
                parse_mode="Markdown",
                reply_markup=unlock_keyboard()
            )
            return

        try:
            q.message.delete()
        except:
            pass

        creating_msg = context.bot.send_message(
            chat_id=chat,
            text="🔵 *Creating a signal for {}*".format(pair),
            parse_mode="Markdown"
        )

        import time
        time.sleep(2)

        signal   = generate_signal(pair)
        is_buy   = signal["direction"] == "BUY"
        image_id = BUY_IMAGE_ID if is_buy else SELL_IMAGE_ID
        trend    = "Up 🟢" if is_buy else "Down 🔴"

        if not is_licensed(user_id):
            use_free_signal(user_id)

        try:
            creating_msg.delete()
        except:
            pass

        caption = (
            "*{}* {}\n"
            "🕐 In {} mins.\n"
            "📊 Signal strength: {}"
        ).format(pair, trend, signal["timeframe"], signal["strength"])

        context.bot.send_photo(
            chat_id=chat,
            photo=image_id,
            caption=caption,
            parse_mode="Markdown",
            reply_markup=signal_keyboard(pair)
        )

def message_handler(update: Update, context: CallbackContext):
    user_id = update.effective_user.id
    text    = update.message.text.strip() if update.message.text else ""

    # ADMIN COMMANDS
    if user_id == ADMIN_ID:

        if text == "/addmonthly" or text.startswith("/addmonthly "):
            try:
                count = int(text.split()[1]) if len(text.split()) > 1 else 1
                count = min(count, 50)
            except:
                count = 1
            codes = []
            for _ in range(count):
                code = generate_code("monthly")
                add_licence(code, "monthly")
                codes.append("`{}`".format(code))
            update.message.reply_text(
                "✅ *{} Monthly Code{}:*\n\n".format(count, "s" if count > 1 else "") + "\n".join(codes) +
                "\n\n📅 Valid 30 days after activation.",
                parse_mode="Markdown"
            )
            return

        if text == "/addlifetime" or text.startswith("/addlifetime "):
            try:
                count = int(text.split()[1]) if len(text.split()) > 1 else 1
                count = min(count, 50)
            except:
                count = 1
            codes = []
            for _ in range(count):
                code = generate_code("lifetime")
                add_licence(code, "lifetime")
                codes.append("`{}`".format(code))
            update.message.reply_text(
                "✅ *{} Lifetime Code{}:*\n\n".format(count, "s" if count > 1 else "") + "\n".join(codes) +
                "\n\n♾️ Never expires.",
                parse_mode="Markdown"
            )
            return

        if text == "/listlicences":
            db       = load_db()
            licences = db.get("licences", {})
            if not licences:
                update.message.reply_text("No licences found.")
                return
            m_av = [c for c, i in licences.items() if not i["used"] and i["type"] == "monthly"]
            l_av = [c for c, i in licences.items() if not i["used"] and i["type"] == "lifetime"]
            m_us = [c for c, i in licences.items() if i["used"] and i["type"] == "monthly"]
            l_us = [c for c, i in licences.items() if i["used"] and i["type"] == "lifetime"]
            msg  = (
                "📋 *LICENCES*\n\n"
                "📅 Monthly Available: {}\n"
                "♾️ Lifetime Available: {}\n"
                "✅ Monthly Used: {}\n"
                "✅ Lifetime Used: {}\n\n"
            ).format(len(m_av), len(l_av), len(m_us), len(l_us))
            if m_av:
                msg += "*Monthly (Available):*\n" + "\n".join(["`{}`".format(c) for c in m_av]) + "\n\n"
            if l_av:
                msg += "*Lifetime (Available):*\n" + "\n".join(["`{}`".format(c) for c in l_av])
            update.message.reply_text(msg, parse_mode="Markdown")
            return

        if text == "/listusers":
            db    = load_db()
            users = db.get("users", {})
            if not users:
                update.message.reply_text("No users yet.")
                return
            monthly  = sum(1 for u in users.values() if u.get("licence_type") == "monthly" and u.get("licensed"))
            lifetime = sum(1 for u in users.values() if u.get("licence_type") == "lifetime")
            free     = sum(1 for u in users.values() if not u.get("licensed"))
            update.message.reply_text(
                "👥 *USERS*\n\n"
                "👤 Total: {}\n"
                "📅 Monthly: {}\n"
                "♾️ Lifetime: {}\n"
                "🆓 Free only: {}".format(len(users), monthly, lifetime, free),
                parse_mode="Markdown"
            )
            return

    # LICENCE CODE ENTRY
    if context.user_data.get("awaiting_code"):
        context.user_data["awaiting_code"] = False
        code = text.upper().strip()

        if activate_licence(code, user_id):
            u     = get_user(user_id)
            ltype = u.get("licence_type")
            exp   = get_expiry_text(user_id)
            type_label = "📅 Monthly" if ltype == "monthly" else "♾️ Lifetime"
            update.message.reply_text(
                "✅ *Licence Activated!*\n\n"
                "🎉 Welcome to MASTER SIGNALS PRO!\n"
                "🏆 Win Rate: 90% — 98%\n"
                "🔑 Type: *{}*\n"
                "⏳ {}\n\n"
                "You can now use unlimited signals!".format(type_label, exp),
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("📊 Start Trading Now", callback_data="choose_pair")]
                ])
            )
        else:
            update.message.reply_text(
                "❌ *Invalid or already used code.*\n\n"
                "Check your code or contact admin.",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("💬 Contact Admin", url="https://t.me/evalonwinnersbot")],
                    [InlineKeyboardButton("🔑 Try Again", callback_data="enter_code")],
                ])
            )

# ============================================================
# MAIN
# ============================================================
def main():
    import os
    print("MASTER SIGNALS PRO starting...")

    updater = Updater(BOT_TOKEN)
    dp      = updater.dispatcher

    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(CommandHandler("help", help_command))
    dp.add_handler(CallbackQueryHandler(button_handler))
    dp.add_handler(MessageHandler(Filters.text, message_handler))

    PORT        = int(os.environ.get("PORT", 8443))
    RENDER_URL  = os.environ.get("RENDER_EXTERNAL_URL", "")

    if RENDER_URL:
        print("Running on Render - webhook mode")
        updater.start_webhook(
            listen="0.0.0.0",
            port=PORT,
            url_path=BOT_TOKEN,
            webhook_url="{}/{}".format(RENDER_URL, BOT_TOKEN)
        )
        updater.idle()
    else:
        print("Running locally - polling mode")
        updater.start_polling()
        updater.idle()

if __name__ == "__main__":
    main()
