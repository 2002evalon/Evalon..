"""
╔══════════════════════════════════════════════════════════════╗
║         EVALON WINNERS — TELEGRAM SUPPORT BOT v5.0          ║
║                                                              ║
║  Features:                                                   ║
║  ✅ Delete-then-Send (messages "melt away")                  ║
║  ✅ 24h cooldown → Start button reminder                     ║
║  ✅ Join channel check before any service                    ║
║  ✅ Contact Support — NO username shown                      ║
║  ✅ 10+ random replies + random images per service           ║
║  ✅ Two-way messaging (forward + reply with typing)          ║
║  ✅ Broadcast (text, photo, video, voice, document)          ║
║  ✅ Admin approve/decline join requests                      ║
║  ✅ 12 languages                                             ║
║  ✅ PostgreSQL database (Railway persistent)                 ║
║  ✅ /getid  /sessions  /stats commands                       ║
║  ✅ NEW: Referral system (link + rewards)                    ║
║  ✅ NEW: Urgency/countdown messages                          ║
║  ✅ NEW: Testimonials / social proof                         ║
║  ✅ NEW: Welcome bonus for new users                         ║
║  ✅ NEW: Daily stats report to admin (8AM)                   ║
╚══════════════════════════════════════════════════════════════╝
"""

import logging
import asyncio
import random
import json
import os
import psycopg2
import psycopg2.extras
from datetime import datetime, timedelta
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup,
)
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, ChatJoinRequestHandler,
    ContextTypes, filters, JobQueue,
)
from telegram.constants import ChatAction
from telegram.error import TelegramError, BadRequest

# ══════════════════════════════════════════════════════════════
#  CONFIGURATION
# ══════════════════════════════════════════════════════════════

BOT_TOKEN         = os.environ.get("BOT_TOKEN", "8663696851:AAFCjW_0GtIIq-N6fw1xCYMYDE550nwr0Uo")
BUSINESS_NAME     = "EVALON WINNERS"
ADMIN_IDS         = [8535925646]
WEBSITE_URL       = "https://evalon-winners-traders.netlify.app/"
MAIN_CHANNEL_ID   = -1003403743370
MAIN_CHANNEL_LINK = "https://t.me/+mRNfGaNhz3RkZGRk"
INDICATOR_CHANNEL = "https://t.me/+Px5zPQnChsE2OTg0"
DATABASE_URL      = os.environ.get("DATABASE_URL", "")  # Set on Railway
COOLDOWN_MINUTES  = 24 * 60   # 24 hours

# Referral rewards threshold (how many referrals = reward)
REFERRAL_REWARD_COUNT = 3

# Bot username (update this to your actual bot username)
BOT_USERNAME = "evalonwinnersbot"

# ══════════════════════════════════════════════════════════════
#  LOGGING
# ══════════════════════════════════════════════════════════════

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ══════════════════════════════════════════════════════════════
#  STATE
# ══════════════════════════════════════════════════════════════

pending_requests: dict = {}
reply_map: dict        = {}
active_support: dict   = {}

# ══════════════════════════════════════════════════════════════
#  DATABASE — PostgreSQL (Railway persistent)
# ══════════════════════════════════════════════════════════════

def get_conn():
    """Get PostgreSQL connection from DATABASE_URL env variable."""
    return psycopg2.connect(DATABASE_URL, sslmode="require")

def init_db():
    """Create tables if they don't exist."""
    conn = get_conn()
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id          BIGINT PRIMARY KEY,
            name        TEXT,
            username    TEXT,
            joined      TEXT,
            last_seen   TEXT,
            referred_by BIGINT DEFAULT NULL,
            referrals   INTEGER DEFAULT 0
        )
    """)
    conn.commit()
    conn.close()

def register_user(user, referred_by: int = None):
    conn = get_conn()
    c = conn.cursor()
    now = datetime.now().strftime("%d/%m/%Y %H:%M")
    c.execute("SELECT id FROM users WHERE id = %s", (user.id,))
    exists = c.fetchone()
    if exists:
        c.execute("""
            UPDATE users SET name=%s, username=%s, last_seen=%s
            WHERE id=%s
        """, (user.full_name, user.username or "", now, user.id))
    else:
        c.execute("""
            INSERT INTO users (id, name, username, joined, last_seen, referred_by, referrals)
            VALUES (%s, %s, %s, %s, %s, %s, 0)
        """, (user.id, user.full_name, user.username or "", now, now, referred_by))
        if referred_by:
            c.execute("UPDATE users SET referrals = referrals + 1 WHERE id = %s", (referred_by,))
    conn.commit()
    conn.close()

def is_new_user(user_id: int) -> bool:
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT id FROM users WHERE id = %s", (user_id,))
    exists = c.fetchone()
    conn.close()
    return exists is None

def get_all_user_ids() -> list:
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT id FROM users")
    rows = c.fetchall()
    conn.close()
    return [row[0] for row in rows]

def get_user_count() -> int:
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM users")
    count = c.fetchone()[0]
    conn.close()
    return count

def get_active_users(days: int) -> int:
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT last_seen FROM users")
    rows = c.fetchall()
    conn.close()
    now = datetime.now()
    count = 0
    for (last_seen,) in rows:
        try:
            last = datetime.strptime(last_seen, "%d/%m/%Y %H:%M")
            if (now - last).days <= days:
                count += 1
        except Exception:
            pass
    return count

def get_user_info(uid: int) -> dict:
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT id, name, username, referrals FROM users WHERE id=%s", (uid,))
    row = c.fetchone()
    conn.close()
    if row:
        return {"id": row[0], "name": row[1], "username": row[2], "referrals": row[3]}
    return {"id": uid, "name": str(uid), "username": "", "referrals": 0}

def get_referral_count(uid: int) -> int:
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT referrals FROM users WHERE id=%s", (uid,))
    row = c.fetchone()
    conn.close()
    return row[0] if row else 0

def get_new_users_today() -> int:
    conn = get_conn()
    c = conn.cursor()
    today = datetime.now().strftime("%d/%m/%Y")
    c.execute("SELECT COUNT(*) FROM users WHERE joined LIKE %s", (f"{today}%",))
    count = c.fetchone()[0]
    conn.close()
    return count

def is_admin(uid: int) -> bool:
    return uid in ADMIN_IDS

# ══════════════════════════════════════════════════════════════
#  DELETE HELPER
# ══════════════════════════════════════════════════════════════

async def safe_delete(context, chat_id: int, message_id: int):
    try:
        await context.bot.delete_message(chat_id=chat_id, message_id=message_id)
    except (BadRequest, TelegramError):
        pass

# ══════════════════════════════════════════════════════════════
#  CHANNEL MEMBERSHIP CHECK
# ══════════════════════════════════════════════════════════════

async def is_member(context, user_id: int) -> bool:
    try:
        member = await context.bot.get_chat_member(
            chat_id=MAIN_CHANNEL_ID, user_id=user_id)
        if member.status in ("member", "administrator", "creator", "restricted"):
            return True
        if member.status == "left" and user_id in pending_requests:
            return True
    except Exception:
        if user_id in pending_requests:
            return True
    if user_id in pending_requests:
        return True
    return False

# ══════════════════════════════════════════════════════════════
#  SERVICE IMAGES (Telegram file_ids)
# ══════════════════════════════════════════════════════════════

FID_R1 = "AgACAgQAAxkBAAICOWn2t8kbk7D0CSqTta7bWCxD9nMZAAJ2HWsbJyi4U3LLcWNxG32ZAQADAgADeQADOwQ"
FID_R2 = "AgACAgQAAxkBAAICOmn2t8kLmMXB2e_EzpLesS_ubn5mAAJ3HWsbJyi4U84q9UTVqWciAQADAgADeAADOwQ"
FID_R3 = "AgACAgQAAxkBAAICO2n2t8nqXr3K5IvDf_HAsDkY57TLAAJ4HWsbJyi4U01YUsaRt3dhAQADAgADeQADOwQ"
FID_R4 = "AgACAgQAAxkBAAICPGn2t8mhWfnHnqk11M9akdWazV2fAAJ5HWsbJyi4U0YOOb5J6d4QAQADAgADeAADOwQ"
FID_R5 = "AgACAgQAAxkBAAICPWn2t8kamp2htmFhtXUDupj9A9lVAAJ6HWsbJyi4Uz5AhpgRbDi8AQADAgADeQADOwQ"
FID_R6 = "AgACAgQAAxkBAAICPmn2t8lucgNQTxXYkbdiewVHlhpFAAJ7HWsbJyi4U6VN5xhXuPzGAQADAgADeQADOwQ"
FID_R7 = "AgACAgQAAxkBAAICP2n2t8lZGXGbGjZ3Rf4biEJxSS3nAAJ8HWsbJyi4U_fHQy_YJY0nAQADAgADeQADOwQ"
FID_R8 = "AgACAgQAAxkBAAIChmn2vpBNuThedUsVsq4eOwABBgABdQYAAoEdaxsnKLhTdv1g8ph5aywBAAMCAAN4AAM7BA"
FID_B1 = "AgACAgQAAxkBAAICQWn2t8k48VaNz9aCJlNgCkPPeyGRAAJ-HWsbJyi4UxA2121dWYUuAQADAgADeQADOwQ"
FID_B2 = "AgACAgQAAxkBAAICQGn2t8l7RqEZnwg3g-SzRkA-eVAtAAJ9HWsbJyi4U-S2jzmXIhNjAQADAgADeQADOwQ"
FID_CH = "AgACAgQAAxkBAAICNGn2t2tsr33eCZuBmCs-V3yrU88nAAJ1HWsbJyi4U_zDUYHTeE0YAQADAgADeQADOwQ"
FID_IN = "AgACAgQAAxkBAAIChGn2vmOzjIdezdPpJKuyOXs_vLJcAAKAHWsbJyi4U31VxMZCqXg2AQADAgADeAADOwQ"

IMGS_SIGNALS   = [FID_R1, FID_R2, FID_R3, FID_R4, FID_R5, FID_R6, FID_R7, FID_R8, FID_CH]
IMGS_SOCIAL    = [FID_R1, FID_R3, FID_R5, FID_R6, FID_R7, FID_R8, FID_CH]
IMGS_INDICATOR = [FID_IN, FID_R1, FID_R2, FID_R4, FID_R5, FID_R8]
IMGS_AUTOBOT   = [FID_B1, FID_B2, FID_R6, FID_R7, FID_R8, FID_CH]

def rand_img(pool: list, user_data: dict, key: str) -> str:
    last = user_data.get(key)
    available = [x for x in pool if x != last] or pool
    chosen = random.choice(available)
    user_data[key] = chosen
    return chosen

# ══════════════════════════════════════════════════════════════
#  URGENCY MESSAGES (rotate daily)
# ══════════════════════════════════════════════════════════════

URGENCY_EN = [
    "⚠️ *LIMITED SLOTS!* Only a few VIP spots left today!",
    "🔥 *HIGH DEMAND!* 12 traders joined in the last hour!",
    "⏰ *TODAY ONLY!* Special offer expires at midnight!",
    "🚨 *ALMOST FULL!* VIP channel closing new members soon!",
    "💥 *LAST CHANCE!* Don't miss today's winning signals!",
]
URGENCY_SW = [
    "⚠️ *NAFASI CHACHE!* Nafasi chache za VIP zimebaki leo!",
    "🔥 *MAHITAJI MAKUBWA!* Wafanyabiashara 12 walijiunga saa moja iliyopita!",
    "⏰ *LEO TU!* Ofa maalum inaisha usiku wa manane!",
    "🚨 *KARIBU KUJAA!* Channel ya VIP itafunga wanachama wapya hivi karibuni!",
    "💥 *NAFASI YA MWISHO!* Usikose signals za kushinda za leo!",
]

def get_urgency(lang: str) -> str:
    pool = URGENCY_SW if lang == "sw" else URGENCY_EN
    # Pick based on day of week so it's consistent within same day
    idx = datetime.now().weekday() % len(pool)
    return pool[idx]

# ══════════════════════════════════════════════════════════════
#  TESTIMONIALS / SOCIAL PROOF
# ══════════════════════════════════════════════════════════════

TESTIMONIALS_EN = [
    "⭐⭐⭐⭐⭐ *\"Made $340 in my first week!\"* — John K., Nigeria",
    "⭐⭐⭐⭐⭐ *\"Best signals I've ever used. 9/10 wins today!\"* — Maria S., Brazil",
    "⭐⭐⭐⭐⭐ *\"The auto bot made $180 while I was sleeping!\"* — Ahmed R., Egypt",
    "⭐⭐⭐⭐⭐ *\"Copy trading gave me +47% this month!\"* — Linda T., Kenya",
    "⭐⭐⭐⭐⭐ *\"Finally a bot that actually works. 10/10!\"* — James O., Ghana",
    "⭐⭐⭐⭐⭐ *\"Turned $50 into $320 in 3 days with VIP signals!\"* — Priya M., India",
    "⭐⭐⭐⭐⭐ *\"The indicator is amazing — super accurate!\"* — Carlos V., Mexico",
    "⭐⭐⭐⭐⭐ *\"I was skeptical but now I'm a believer. Profits daily!\"* — Fatima A., Morocco",
]
TESTIMONIALS_SW = [
    "⭐⭐⭐⭐⭐ *\"Nilipata $340 katika wiki yangu ya kwanza!\"* — John K., Nigeria",
    "⭐⭐⭐⭐⭐ *\"Signals bora nilizowahi tumia. Ushindi 9/10 leo!\"* — Maria S., Brazil",
    "⭐⭐⭐⭐⭐ *\"Bot ya auto ilifanya $180 nilipokuwa nasinzia!\"* — Ahmed R., Egypt",
    "⭐⭐⭐⭐⭐ *\"Copy trading ilinipa +47% mwezi huu!\"* — Linda T., Kenya",
    "⭐⭐⭐⭐⭐ *\"Hatimaye bot inayofanya kazi kweli kweli!\"* — James O., Ghana",
    "⭐⭐⭐⭐⭐ *\"Nilibadilisha $50 kuwa $320 kwa siku 3!\"* — Priya M., India",
]

def get_testimonial(lang: str) -> str:
    pool = TESTIMONIALS_SW if lang == "sw" else TESTIMONIALS_EN
    return random.choice(pool)

# ══════════════════════════════════════════════════════════════
#  WELCOME BONUS MESSAGE
# ══════════════════════════════════════════════════════════════

WELCOME_BONUS = {
    "en": (
        "🎁 *WELCOME BONUS — SPECIAL OFFER!*\n\n"
        "As a NEW member of EVALON WINNERS, you get:\n\n"
        "✅ FREE access to our indicator channel\n"
        "✅ 1 FREE signal trial (contact support)\n"
        "✅ Exclusive new member discount on VIP\n\n"
        "⏰ This offer is valid for *24 hours only!*\n\n"
        "👇 Claim your bonus now:"
    ),
    "sw": (
        "🎁 *BONASI YA KARIBU — OFA MAALUM!*\n\n"
        "Kama mwanachama MPYA wa EVALON WINNERS, unapata:\n\n"
        "✅ Ufikiaji BURE wa channel ya indicator\n"
        "✅ Jaribio BURE la signal 1 (wasiliana na support)\n"
        "✅ Punguzo la kipekee kwa wanachama wapya kwenye VIP\n\n"
        "⏰ Ofa hii ni halali kwa *masaa 24 tu!*\n\n"
        "👇 Dai bonasi yako sasa:"
    ),
}

# ══════════════════════════════════════════════════════════════
#  SERVICE REPLIES
# ══════════════════════════════════════════════════════════════

SIGNALS_EN = [
    "📊 *VIP SIGNALS — EVALON WINNERS* 🎯\n\nWelcome to the most accurate signal service!\n\n✅ 80–95% Win Rate\n✅ 3–10 signals daily\n✅ Real-time Telegram alerts\n✅ Forex & Binary pairs\n✅ Entry, TP & SL included\n✅ 24/7 active team\n\n🔥 Join hundreds of winning traders!\n\n👇 Visit our website for pricing:",
    "📊 *VIP SIGNALS — Your Edge in the Market* 💰\n\nStop guessing. Start winning!\n\n🏆 What you get:\n• Premium buy/sell signals\n• Exact entry price & expiry time\n• Daily market analysis\n• Private VIP channel access\n\n⚡ Works on: Pocket Option | Quotex | IQ Option | Olymp Trade | Deriv\n\n🌐 See plans on our website:",
    "💎 *EVALON VIP SIGNALS* 🚀\n\nJoin the winning side of trading!\n\n📈 Why we're different:\n• AI-assisted market analysis\n• Real price action based\n• Highest probability setups\n• Instant Telegram delivery\n\n📊 Pairs: EUR/USD | GBP/USD | USD/JPY | OTC & more\n\n👇 Ready to start winning?",
    "🎯 *PRECISION SIGNALS — EVALON* ⚡\n\nEvery signal carefully analyzed!\n\n🔑 Each signal includes:\n• Asset name\n• Direction (CALL / PUT)\n• Entry time & expiry\n• Confidence level\n\n💯 1,000+ traders trust us daily!\n\n👇 Get access now:",
    "📡 *LIVE TRADING SIGNALS* 🔥\n\nReal signals from real traders!\n\n✨ Benefits:\n• Consistent daily profits\n• Works for beginners\n• No experience required\n• 50+ countries\n\n👇 Learn more & subscribe:",
    "🚀 *VIP SIGNALS — LIMITED SLOTS* ⚠️\n\n📊 This week's performance:\n• Win rate: 87%\n• Signals: 24 | Wins: 21 | Losses: 3\n\nResults speak for themselves! 💪\n\n👇 Secure your slot:",
    "💰 *TRADE SMARTER WITH EVALON* 🧠\n\n📌 Signal delivery:\n• Pre-market morning analysis\n• Live signals during sessions\n• Post-session performance report\n\n🕐 London | New York | Asian | OTC 24/7\n\n📈 Start your journey 👇",
    "⚡ *HIGH ACCURACY SIGNALS* 🎯\n\n🔥 This month:\n• 200+ signals sent\n• 175+ winners\n• Consistent profits\n\n🌍 Worldwide | 📱 Any device\n\n👇 Check pricing:",
    "📊 *BINARY & FOREX VIP SIGNALS* 🌟\n\n✅ Professional traders\n✅ Risk-managed approach\n✅ Transparent records\n✅ Active winners community\n\n🔐 Join EVALON WINNERS 👇",
    "🏆 *JOIN THE WINNING TRADERS CLUB* 💎\n\n📈 For all levels:\n• Beginners (step-by-step)\n• Intermediate (boost accuracy)\n• Advanced (confirm analysis)\n\n⚙️ Pocket Option | Quotex | Deriv | IQ Option | Olymp Trade | Binomo | ExpertOption\n\n🌐 Get started 👇",
]
SIGNALS_SW = [
    "📊 *VIP SIGNALS — EVALON WINNERS* 🎯\n\nKaribu kwenye huduma bora ya signals!\n\n✅ Usahihi 80–95%\n✅ Signals 3–10 kila siku\n✅ Alerts za muda halisi\n✅ Forex & Binary\n✅ Entry, TP & SL\n✅ Timu 24/7\n\n👇 Tembelea website kwa bei:",
    "💎 *EVALON VIP SIGNALS* 🚀\n\nAcha kukisia. Anza kushinda!\n\n🏆 Utapata:\n• Signals za premium\n• Bei halisi ya kuingia\n• Uchambuzi wa kila siku\n• Channel ya VIP\n\n👇 Angalia bei:",
    "🚀 *SIGNALS ZA VIP — NAFASI CHACHE* ⚠️\n\n📊 Wiki hii: Usahihi 87%\nWins 21 | Losses 3\n\nMatokeo yanasema yenyewe! 💪\n\n👇 Hifadhi nafasi yako:",
    "🎯 *SIGNALS ZA USAHIHI* ⚡\n\nKila signal inachunguzwa kwa makini!\n\n🔑 Signal inajumuisha:\n• Jina la asset\n• Mwelekeo (CALL/PUT)\n• Wakati wa kuingia\n• Muda wa kumalizika\n\n👇 Pata ufikiaji sasa:",
    "💰 *BIASHARA KWA AKILI NA EVALON* 🧠\n\n📌 Delivery ya signals:\n• Uchambuzi wa asubuhi\n• Signals za muda halisi\n• Ripoti ya utendaji\n\n🕐 London | New York | Asian | OTC 24/7\n\n👇 Anza safari yako:",
]
SIGNALS_REPLIES = {
    "en": SIGNALS_EN, "sw": SIGNALS_SW,
    "ar": ["📊 *إشارات VIP — EVALON* 🎯\n\n✅ دقة 80–95%\n✅ 3–10 إشارات يومياً\n✅ تنبيهات فورية\n\n👇 زر موقعنا:", "💎 *إشارات EVALON VIP* 🚀\n\nتوقف عن التخمين. ابدأ الفوز!\n\n👇 انضم الآن:"],
    "zh": ["📊 *VIP信号 — EVALON* 🎯\n\n✅ 80–95%胜率\n✅ 每日3–10信号\n✅ 实时提醒\n\n👇 访问网站:", "💎 *EVALON VIP 信号* 🚀\n\n停止猜测，开始获胜！\n\n👇 立即加入:"],
    "hi": ["📊 *VIP सिग्नल — EVALON* 🎯\n\n✅ 80–95% जीत दर\n✅ प्रतिदिन 3–10 सिग्नल\n\n👇 वेबसाइट देखें:", "💎 *EVALON VIP सिग्नल* 🚀\n\nअनुमान लगाना बंद करें। जीतना शुरू करें!\n\n👇 अभी जुड़ें:"],
    "ru": ["📊 *VIP СИГНАЛЫ — EVALON* 🎯\n\n✅ Точность 80–95%\n✅ 3–10 сигналов в день\n\n👇 Посетите сайт:", "💎 *EVALON VIP СИГНАЛЫ* 🚀\n\nПерестань угадывать. Начни побеждать!\n\n👇 Присоединяйся:"],
    "es": ["📊 *SEÑALES VIP — EVALON* 🎯\n\n✅ 80–95% precisión\n✅ 3–10 señales diarias\n\n👇 Visita la web:", "💎 *EVALON VIP SEÑALES* 🚀\n\n¡Deja de adivinar. Empieza a ganar!\n\n👇 Únete ahora:"],
    "fr": ["📊 *SIGNAUX VIP — EVALON* 🎯\n\n✅ Précision 80–95%\n✅ 3–10 signaux/jour\n\n👇 Visitez le site:", "💎 *EVALON VIP SIGNAUX* 🚀\n\nArrêtez de deviner. Commencez à gagner!\n\n👇 Rejoignez-nous:"],
    "pt": ["📊 *SINAIS VIP — EVALON* 🎯\n\n✅ 80–95% precisão\n✅ 3–10 sinais diários\n\n👇 Visite o site:", "💎 *EVALON VIP SINAIS* 🚀\n\nPare de adivinhar. Comece a ganhar!\n\n👇 Junte-se agora:"],
    "de": ["📊 *VIP-SIGNALE — EVALON* 🎯\n\n✅ 80–95% Genauigkeit\n✅ 3–10 Signale täglich\n\n👇 Website besuchen:", "💎 *EVALON VIP SIGNALE* 🚀\n\nHör auf zu raten. Fang an zu gewinnen!\n\n👇 Jetzt beitreten:"],
    "ur": ["📊 *VIP سگنلز — EVALON* 🎯\n\n✅ 80–95% درستگی\n✅ روزانہ 3–10 سگنلز\n\n👇 ویب سائٹ دیکھیں:", "💎 *EVALON VIP سگنلز* 🚀\n\nاندازہ لگانا بند کریں۔ جیتنا شروع کریں!\n\n👇 ابھی شامل ہوں:"],
    "ja": ["📊 *VIPシグナル — EVALON* 🎯\n\n✅ 80–95%勝率\n✅ 毎日3–10シグナル\n\n👇 ウェブサイトを見る:", "💎 *EVALON VIP シグナル* 🚀\n\n推測をやめて、勝ち始めよう！\n\n👇 今すぐ参加:"],
}

SOCIAL_EN = [
    "👥 *POCKET SOCIAL TRADING — EVALON* 🔄\n\nCopy the best traders automatically!\n\n✅ Auto-copy top performers\n✅ Live performance tracking\n✅ Works on Pocket Option\n✅ No experience needed\n✅ Full transparency\n✅ Start & stop anytime\n\n👇 Learn more on our website:",
    "🔄 *SOCIAL TRADING — COPY & PROFIT* 💰\n\n🏆 How it works:\n1️⃣ Connect Pocket Option account\n2️⃣ Choose a top trader\n3️⃣ Trades copy automatically\n4️⃣ You earn when they earn!\n\n📊 Top traders: 30–80% monthly\n\n👇 Get started:",
    "👥 *POCKET SOCIAL — TRADE SMART* 🤝\n\nWhy trade alone when you can copy the best?\n\n✨ Real-time copy | Risk settings | Multiple traders | 24/7 automated\n\n⚡ Works while you sleep!\n\n👇 Website:",
    "💎 *SOCIAL TRADING — EVALON EXCLUSIVE* 📈\n\nNo charts. No strategy. Just profit!\n\n✅ Your funds stay in YOUR account\n✅ Copy multiple traders at once\n✅ Full control always\n\n👇 Learn more:",
    "🚀 *COPY TRADING — START EARNING* 🌟\n\n📊 Our traders:\n• Pocket Option certified\n• 6+ months verified history\n• Transparent win/loss records\n\n👇 Full details on website:",
    "🤝 *POCKET SOCIAL TRADING* 🎓\n\n✅ Step-by-step setup guide\n✅ Any budget\n✅ Withdraw anytime\n✅ No hidden fees\n\n🏅 500+ EVALON members\n\n👇 See pricing:",
    "📈 *SOCIAL — PASSIVE INCOME* 💤💰\n\nYour account grows even offline!\n\n🔥 Handpicked traders | Easy setup (5 min) | Cancel anytime\n\n⚙️ Pocket Option only\n\n👇 Visit website:",
    "💰 *COPY TRADES — EARN LIKE A PRO* 🔓\n\n🏆 5+ verified master traders\n• Analytics dashboard\n• Risk score per trader\n• 1000+ community\n• Weekly reports\n\n👇 Website:",
    "⚡ *SETUP IN 5 MINUTES* ⏱️\n\n📋 Need: Pocket Option account + our subscription\n\n🌍 Works in ALL countries\n\n👇 Get started today:",
    "🎯 *TRADE SMARTER, NOT HARDER* 📊\n\n📈 Average results:\n• Month 1: +15–30%\n• Month 2: +30–60%\n• Month 3+: Consistent profits\n\n👇 Join smart traders:",
]
SOCIAL_SW = [
    "👥 *POCKET SOCIAL TRADING — EVALON* 🔄\n\nNakili wafanyabiashara bora!\n\n✅ Nakili otomatiki\n✅ Pocket Option\n✅ Huhitaji uzoefu\n\n👇 Website:",
    "🔄 *NAKILI & PATA FAIDA* 💰\n\n1️⃣ Unganisha akaunti\n2️⃣ Chagua mfanyabiashara\n3️⃣ Biashara zinakiliwa otomatiki\n4️⃣ Pata faida!\n\n👇 Anza leo:",
    "👥 *POCKET SOCIAL — BIASHARA KWA AKILI* 🤝\n\nKwa nini ufanye biashara peke yako?\n\n✨ Nakili muda halisi | Mipangilio ya hatari | Wafanyabiashara wengi | Otomatiki 24/7\n\n⚡ Inafanya kazi unapolala!\n\n👇 Website:",
    "💎 *SOCIAL TRADING — EVALON EXCLUSIVE* 📈\n\nHahitaji chati. Hahitaji mkakati. Faida tu!\n\n✅ Fedha zako zinabaki kwenye akaunti YAKO\n✅ Nakili wafanyabiashara wengi\n\n👇 Jifunze zaidi:",
    "🚀 *NAKILI BIASHARA — ANZA KUPATA* 🌟\n\n📊 Wafanyabiashara wetu:\n• Wamethibitishwa na Pocket Option\n• Historia ya miezi 6+\n• Rekodi wazi za kushinda/kushindwa\n\n👇 Maelezo kamili kwenye website:",
]
SOCIAL_REPLIES = {
    "en": SOCIAL_EN, "sw": SOCIAL_SW,
    "ar": ["👥 *التداول الاجتماعي — EVALON* 🔄\n\n✅ نسخ تلقائي\n✅ Pocket Option\n✅ لا خبرة مطلوبة\n\n👇 زر موقعنا:", "🔄 *انسخ واربح* 💰\n\n1️⃣ اربط حسابك\n2️⃣ اختر متداولاً\n3️⃣ تُنسخ الصفقات تلقائياً\n4️⃣ اربح معهم!\n\n👇 ابدأ الآن:"],
    "zh": ["👥 *社交交易 — EVALON* 🔄\n\n✅ 自动复制\n✅ Pocket Option\n✅ 无需经验\n\n👇 访问网站:", "🔄 *复制并获利* 💰\n\n1️⃣ 连接账户\n2️⃣ 选择交易者\n3️⃣ 自动复制交易\n4️⃣ 跟着赚钱！\n\n👇 立即开始:"],
    "hi": ["👥 *सोशल ट्रेडिंग — EVALON* 🔄\n\n✅ ऑटो-कॉपी\n✅ Pocket Option\n\n👇 वेबसाइट:", "🔄 *कॉपी करें और कमाएं* 💰\n\n✅ शीर्ष ट्रेडर्स को कॉपी करें\n✅ स्वचालित लाभ\n\n👇 शुरू करें:"],
    "ru": ["👥 *СОЦИАЛЬНЫЙ ТРЕЙДИНГ — EVALON* 🔄\n\n✅ Авто-копирование\n✅ Pocket Option\n\n👇 Сайт:", "🔄 *КОПИРУЙ И ЗАРАБАТЫВАЙ* 💰\n\n✅ Копируй топ трейдеров\n✅ Автоматическая прибыль\n\n👇 Начни:"],
    "es": ["👥 *TRADING SOCIAL — EVALON* 🔄\n\n✅ Auto-copia\n✅ Pocket Option\n\n👇 Web:", "🔄 *COPIA Y GANA* 💰\n\n✅ Copia a los mejores traders\n✅ Ganancias automáticas\n\n👇 Empieza:"],
    "fr": ["👥 *TRADING SOCIAL — EVALON* 🔄\n\n✅ Auto-copie\n✅ Pocket Option\n\n👇 Site:", "🔄 *COPIEZ ET GAGNEZ* 💰\n\n✅ Copiez les meilleurs traders\n✅ Profits automatiques\n\n👇 Commencez:"],
    "pt": ["👥 *TRADING SOCIAL — EVALON* 🔄\n\n✅ Auto-cópia\n✅ Pocket Option\n\n👇 Site:", "🔄 *COPIE E GANHE* 💰\n\n✅ Copie os melhores traders\n✅ Lucros automáticos\n\n👇 Comece:"],
    "de": ["👥 *SOCIAL TRADING — EVALON* 🔄\n\n✅ Auto-Kopie\n✅ Pocket Option\n\n👇 Website:", "🔄 *KOPIEREN UND VERDIENEN* 💰\n\n✅ Beste Trader kopieren\n✅ Automatische Gewinne\n\n👇 Starten:"],
    "ur": ["👥 *سوشل ٹریڈنگ — EVALON* 🔄\n\n✅ آٹو کاپی\n✅ Pocket Option\n\n👇 ویب سائٹ:", "🔄 *کاپی کریں اور کمائیں* 💰\n\n✅ بہترین ٹریڈرز کاپی کریں\n✅ خودکار منافع\n\n👇 شروع کریں:"],
    "ja": ["👥 *ソーシャルトレード — EVALON* 🔄\n\n✅ 自動コピー\n✅ Pocket Option\n\n👇 ウェブサイト:", "🔄 *コピーして稼ぐ* 💰\n\n✅ トップトレーダーをコピー\n✅ 自動利益\n\n👇 始める:"],
}

INDICATOR_EN = [
    "📈 *FREE INDICATOR — EVALON WINNERS* 🎁\n\nYES — 100% FREE!\n\n✅ Buy/sell arrows on chart\n✅ All binary platforms\n✅ All timeframes (1m–1h)\n✅ No repaint\n✅ MT4, MT5 & web\n✅ Easy install + guide\n\n📲 Join FREE channel to get it:",
    "🆓 *FREE INDICATOR — NO PAYMENT* 💎\n\nProfessional signals FREE!\n\n🔧 Non-repainting | Price action + volume | 20+ pairs | OTC supported\n\n👇 Get FREE from our channel:",
    "📊 *EVALON INDICATOR — YOUR EDGE* 👁️\n\n🎯 Strong BUY ↑ (green) | Strong SELL ↓ (red)\n✅ Trend filter included\n⚡ Community: +25% win rate improvement\n\n🆓 FREE — tap channel link:",
    "💡 *WHY TRADERS LOVE OUR INDICATOR* 🏆\n\nSimple. Accurate. Free!\n\n📌 Visual arrows | Sound alerts | OTC 24/7 | Beginner-friendly\n\n🔥 Combine with VIP Signals!\n\n📲 Join FREE channel:",
    "🎁 *EVALON FREE INDICATOR* ❤️\n\n✅ Download link\n✅ Video + text install guide\n✅ Live examples\n✅ Community support\n\nPocket Option | Quotex | MT4 | MT5 | IQ Option | Deriv\n\n⬇️ Free channel:",
    "⚡ *PROFESSIONAL — ZERO COST* 💰\n\nOthers charge hundreds — we give FREE!\n\n🔬 Real-time scanning | Filters weak signals | Instant alert\n\n🏅 3,000+ traders use it\n\n👇 Get FREE:",
    "📱 *MOBILE & PC COMPATIBLE* 🌍\n\nTrade anywhere!\n\n📲 Mobile: Download → Install → Trade!\n💻 PC: MT4/MT5 + template included\n⏱️ 5-minute setup\n\n🎓 Tutorial in free channel 👇",
    "🏆 *#1 FREE BINARY INDICATOR* 🌟\n\n📊 2,000+ users | Average 76% win rate | Best: 91%\n\n🔥 Stop losing — get the edge!\n\n📲 Free channel:",
    "🎯 *INDICATOR + VIP SIGNALS = UNSTOPPABLE* 💎\n\n✅ Double confirmation = higher accuracy\n✅ Risk reduced significantly\n\n🆓 Indicator: FREE | 💎 VIP Signals: Premium\n\n📲 Get FREE indicator:",
    "🚀 *TRADE WITH CONFIDENCE* 🎯\n\nKnow WHEN to enter | WHICH direction | HOW LONG to hold\n\n💡 Binary (60s–15min) | Forex | OTC weekend\n\n📲 FREE — join channel:",
]
INDICATOR_SW = [
    "📈 *INDICATOR YA BURE — EVALON* 🎁\n\nNDIO — BURE KABISA!\n\n✅ Mishale ya kununua/kuuza\n✅ Majukwaa yote ya binary\n✅ Vipindi vyote (1m–1h)\n✅ Rahisi kusakinisha\n\n📲 Jiunge na channel ya BURE:",
    "🆓 *INDICATOR YA BURE — BILA MALIPO* 💎\n\nSignals za kitaalamu BURE!\n\n🔧 Haibadilishi | Bei halisi + kiasi | Jozi 20+ | OTC inasaidiwa\n\n👇 Ipate BURE kutoka channel yetu:",
    "📊 *EVALON INDICATOR — FAIDA YAKO* 👁️\n\n🎯 NUNUA kwa nguvu ↑ (kijani) | UUZA kwa nguvu ↓ (nyekundu)\n✅ Kichujio cha mwelekeo kimejumuishwa\n⚡ Jamii: uboreshaji wa kiwango cha kushinda +25%\n\n🆓 BURE — gonga kiungo cha channel:",
    "💡 *KWA NINI WAFANYABIASHARA WANAPENDA INDICATOR YETU* 🏆\n\nRahisi. Sahihi. Bure!\n\n📌 Mishale inayoonekana | Tahadhari za sauti | OTC 24/7 | Rafiki kwa wanaoanza\n\n📲 Jiunge na channel ya BURE:",
    "🎁 *EVALON INDICATOR YA BURE* ❤️\n\n✅ Kiungo cha kupakua\n✅ Mwongozo wa video + maandishi\n✅ Mifano ya moja kwa moja\n✅ Msaada wa jamii\n\n⬇️ Channel ya bure:",
]
INDICATOR_REPLIES = {
    "en": INDICATOR_EN, "sw": INDICATOR_SW,
    "ar": ["📈 *مؤشر مجاني — EVALON* 🎁\n\n✅ أسهم الشراء/البيع\n✅ جميع المنصات\n✅ مجاني 100%\n\n📲 انضم للقناة المجانية:", "🆓 *مؤشر مجاني — بدون دفع* 💎\n\nإشارات احترافية مجانية!\n\n👇 احصل عليه مجانًا:"],
    "zh": ["📈 *免费指标 — EVALON* 🎁\n\n✅ 买卖箭头\n✅ 所有平台\n✅ 100%免费\n\n📲 加入免费频道:", "🆓 *免费指标 — 无需付款* 💎\n\n专业信号免费！\n\n👇 免费获取:"],
    "hi": ["📈 *मुफ्त इंडिकेटर — EVALON* 🎁\n\n✅ खरीद/बिक्री तीर\n✅ सभी प्लेटफॉर्म\n✅ 100% मुफ्त\n\n📲 मुफ्त चैनल:", "🆓 *मुफ्त इंडिकेटर — कोई भुगतान नहीं* 💎\n\nपेशेवर सिग्नल मुफ्त!\n\n👇 मुफ्त में पाएं:"],
    "ru": ["📈 *БЕСПЛАТНЫЙ ИНДИКАТОР — EVALON* 🎁\n\n✅ Стрелки купить/продать\n✅ Все платформы\n✅ 100% бесплатно\n\n📲 Бесплатный канал:", "🆓 *БЕСПЛАТНЫЙ ИНДИКАТОР* 💎\n\nПрофессиональные сигналы бесплатно!\n\n👇 Получить бесплатно:"],
    "es": ["📈 *INDICADOR GRATIS — EVALON* 🎁\n\n✅ Flechas compra/venta\n✅ Todas las plataformas\n✅ 100% gratis\n\n📲 Canal gratuito:", "🆓 *INDICADOR GRATIS* 💎\n\n¡Señales profesionales gratis!\n\n👇 Obtener gratis:"],
    "fr": ["📈 *INDICATEUR GRATUIT — EVALON* 🎁\n\n✅ Flèches achat/vente\n✅ Toutes les plateformes\n✅ 100% gratuit\n\n📲 Canal gratuit:", "🆓 *INDICATEUR GRATUIT* 💎\n\nSignaux professionnels gratuits!\n\n👇 Obtenir gratuitement:"],
    "pt": ["📈 *INDICADOR GRÁTIS — EVALON* 🎁\n\n✅ Setas compra/venda\n✅ Todas as plataformas\n✅ 100% grátis\n\n📲 Canal gratuito:", "🆓 *INDICADOR GRÁTIS* 💎\n\nSinais profissionais grátis!\n\n👇 Obter grátis:"],
    "de": ["📈 *KOSTENLOSER INDIKATOR — EVALON* 🎁\n\n✅ Kauf/Verkauf-Pfeile\n✅ Alle Plattformen\n✅ 100% kostenlos\n\n📲 Kostenloser Kanal:", "🆓 *KOSTENLOSER INDIKATOR* 💎\n\nProfessionelle Signale kostenlos!\n\n👇 Kostenlos erhalten:"],
    "ur": ["📈 *مفت انڈیکیٹر — EVALON* 🎁\n\n✅ خرید/فروخت تیر\n✅ تمام پلیٹ فارم\n✅ 100% مفت\n\n📲 مفت چینل:", "🆓 *مفت انڈیکیٹر* 💎\n\nپیشہ ورانہ سگنلز مفت!\n\n👇 مفت میں حاصل کریں:"],
    "ja": ["📈 *無料インジケーター — EVALON* 🎁\n\n✅ 買い/売り矢印\n✅ すべてのプラットフォーム\n✅ 100%無料\n\n📲 無料チャンネル:", "🆓 *無料インジケーター* 💎\n\nプロのシグナル無料！\n\n👇 無料で入手:"],
}

AUTOBOT_EN = [
    "🤖 *AUTO TRADING BOT — EVALON WINNERS* 💎\n\nTired of watching charts all day?\n\n✅ ALL binary brokers\n✅ Forex & OTC pairs\n✅ Runs 24/7\n✅ No screen watching\n✅ Beginner-friendly\n✅ Real market data\n\n🏦 Pocket Option | Quotex | IQ Option | Olymp Trade | Deriv | Binomo | ExpertOption | Binary.com | Raceoption | Videforex\n\n👇 Get it now:",
    "⚡ *EVALON AUTO BOT — 24/7* 🚀\n\nYou focus on life — bot focuses on profits!\n\n🔧 AI entry detection | Auto martingale | Stop-loss automation | Mobile notifications | Remote on/off\n\n⚠️ Limited slots!\n\n👇 Website:",
    "💰 *MAKE MONEY WHILE YOU SLEEP* 🌙\n\n🤖 Steps:\n1️⃣ Purchase license\n2️⃣ Install (guide provided)\n3️⃣ Connect broker\n4️⃣ Set risk level\n5️⃣ Collect profits!\n\n👇 Start automating:",
    "🏆 *TRUSTED BY 1000+ TRADERS* 🌍\n\n🎯 Win rate: 70–85% | Daily trades: 15–30 | Uptime: 99.9%\n\n🔐 Funds stay in YOUR broker account\n💻 Windows, Mac & VPS | 📱 Mobile monitoring\n\n👇 Details:",
    "🚀 *ALL BROKERS SUPPORTED* 🌐\n\n✅ Pocket Option | Quotex | IQ Option | Olymp Trade | Deriv | Binomo | ExpertOption | Raceoption | Videforex | And more!\n\n💡 ONE license = any broker\n\n👇 Get yours:",
    "🧠 *SMART AUTO BOT — EVALON TECH* 🤖\n\n⚙️ Multi-currency scanning | Auto time-filter | News filter | Smart lot sizing | Compounding mode\n\n📊 Conservative | Balanced | Aggressive\n\n👇 Full specs:",
    "💎 *EVALON AUTO BOT — PREMIUM* 🏅\n\n🔥 Regular updates | Community group | Monthly reports | Developer support | Money-back guarantee\n\n⚡ Limited licenses!\n\n👇 Secure yours:",
    "⏰ *24/7 AUTOMATED PROFITS* ⌚\n\n📊 6AM London | 12PM New York | 8PM Evening | 2AM Asian\n\n🌍 Every timezone | 😊 Live your life!\n\n👇 Start today:",
    "🎯 *STOP LOSING — START AUTOMATING* 🧠\n\n🤖 No fear | No greed | Follows rules 100% | Never overtrades | Instant entries\n\nConsistent + disciplined = profitable!\n\n👇 Learn more:",
    "🌟 *START SMALL, GROW BIG* 💡\n\n💵 Small: Conservative | 📈 Medium: Balanced | 🔥 Large: Full optimization\n\n🔄 Compound monthly | 📲 Monitor anywhere\n\n👇 All plans:",
]
AUTOBOT_SW = [
    "🤖 *AUTO TRADING BOT — EVALON* 💎\n\nChoka kutazama chati siku nzima?\n\n✅ Mawakala WOTE wa binary\n✅ Forex & OTC\n✅ Inafanya kazi 24/7\n\n🏦 Pocket Option | Quotex | IQ Option | Olymp Trade | Deriv | Binomo | ExpertOption\n\n👇 Ipate sasa:",
    "⚡ *EVALON AUTO BOT — 24/7* 🚀\n\nWewe zingatia maisha — bot izingatie faida!\n\n⚠️ Nafasi chache — wafanyabiashara wazito tu!\n\n👇 Website:",
    "💰 *PATA PESA UNAPOLALA* 🌙\n\n🤖 Hatua:\n1️⃣ Nunua leseni\n2️⃣ Sakinisha (mwongozo hutolewa)\n3️⃣ Unganisha broker\n4️⃣ Weka kiwango cha hatari\n5️⃣ Kusanya faida!\n\n👇 Anza otomatiki:",
    "🏆 *INAAMINIWA NA WAFANYABIASHARA 1000+* 🌍\n\n🎯 Kiwango cha kushinda: 70–85% | Biashara za kila siku: 15–30 | Uptime: 99.9%\n\n🔐 Fedha zinabaki kwenye akaunti YAKO ya broker\n\n👇 Maelezo:",
    "🚀 *MAWAKALA WOTE YANASAIDIWA* 🌐\n\n✅ Pocket Option | Quotex | IQ Option | Olymp Trade | Deriv | Binomo | ExpertOption | Raceoption | Videforex | Na zaidi!\n\n💡 Leseni MOJA = broker yoyote\n\n👇 Pata yako:",
]
AUTOBOT_REPLIES = {
    "en": AUTOBOT_EN, "sw": AUTOBOT_SW,
    "ar": ["🤖 *بوت التداول — EVALON* 💎\n\n✅ جميع وسطاء الثنائيات\n✅ يعمل 24/7\n✅ لا مراقبة للشاشة\n\n🏦 Pocket Option | Quotex | وأكثر\n\n👇 احصل عليه:", "⚡ *EVALON AUTO BOT — 24/7* 🚀\n\nركز على حياتك — البوت يركز على الأرباح!\n\n⚠️ مقاعد محدودة!\n\n👇 الموقع:"],
    "zh": ["🤖 *自动交易机器人 — EVALON* 💎\n\n✅ 所有二元经纪商\n✅ 24/7运行\n✅ 无需盯盘\n\n👇 立即获取:", "⚡ *EVALON 自动机器人 — 24/7* 🚀\n\n你专注生活——机器人专注盈利！\n\n⚠️ 名额有限！\n\n👇 网站:"],
    "hi": ["🤖 *ऑटो ट्रेडिंग बॉट — EVALON* 💎\n\n✅ सभी बाइनरी ब्रोकर\n✅ 24/7 चलता है\n\n👇 अभी प्राप्त करें:", "⚡ *EVALON ऑटो बॉट — 24/7* 🚀\n\nआप जीवन पर ध्यान दें — बॉट मुनाफे पर!\n\n⚠️ सीमित स्लॉट!\n\n👇 वेबसाइट:"],
    "ru": ["🤖 *АВТО БОТ — EVALON* 💎\n\n✅ Все бинарные брокеры\n✅ Работает 24/7\n\n👇 Получить:", "⚡ *EVALON АВТО БОТ — 24/7* 🚀\n\nТы занимаешься жизнью — бот занимается прибылью!\n\n⚠️ Ограниченное количество мест!\n\n👇 Сайт:"],
    "es": ["🤖 *BOT AUTOMÁTICO — EVALON* 💎\n\n✅ Todos los brokers binarios\n✅ Funciona 24/7\n\n👇 Obtener:", "⚡ *EVALON AUTO BOT — 24/7* 🚀\n\n¡Tú te enfocas en la vida — el bot en las ganancias!\n\n⚠️ ¡Plazas limitadas!\n\n👇 Web:"],
    "fr": ["🤖 *BOT AUTO — EVALON* 💎\n\n✅ Tous les brokers binaires\n✅ Fonctionne 24/7\n\n👇 Obtenir:", "⚡ *EVALON AUTO BOT — 24/7* 🚀\n\nVous vous concentrez sur la vie — le bot sur les profits!\n\n⚠️ Places limitées!\n\n👇 Site:"],
    "pt": ["🤖 *BOT AUTOMÁTICO — EVALON* 💎\n\n✅ Todos os brokers binários\n✅ Funciona 24/7\n\n👇 Obter:", "⚡ *EVALON AUTO BOT — 24/7* 🚀\n\nVocê foca na vida — o bot foca nos lucros!\n\n⚠️ Vagas limitadas!\n\n👇 Site:"],
    "de": ["🤖 *AUTO-BOT — EVALON* 💎\n\n✅ Alle Binär-Broker\n✅ Läuft 24/7\n\n👇 Holen:", "⚡ *EVALON AUTO BOT — 24/7* 🚀\n\nSie konzentrieren sich auf das Leben — der Bot auf Gewinne!\n\n⚠️ Begrenzte Plätze!\n\n👇 Website:"],
    "ur": ["🤖 *آٹو بوٹ — EVALON* 💎\n\n✅ تمام بائنری بروکرز\n✅ 24/7 چلتا ہے\n\n👇 حاصل کریں:", "⚡ *EVALON آٹو بوٹ — 24/7* 🚀\n\nآپ زندگی پر توجہ دیں — بوٹ منافع پر!\n\n⚠️ محدود نشستیں!\n\n👇 ویب سائٹ:"],
    "ja": ["🤖 *自動ボット — EVALON* 💎\n\n✅ すべてのバイナリーブローカー\n✅ 24/7稼働\n\n👇 入手:", "⚡ *EVALON 自動ボット — 24/7* 🚀\n\nあなたは人生に集中 — ボットは利益に集中！\n\n⚠️ 限定スロット！\n\n👇 ウェブサイト:"],
}

# ══════════════════════════════════════════════════════════════
#  UI TRANSLATIONS
# ══════════════════════════════════════════════════════════════

UI = {
    "en": {
        "btn_signals":"📊 VIP Signals","btn_social":"👥 Social Trading",
        "btn_indicator":"📈 Free Indicator","btn_autobot":"🤖 Auto Bot",
        "btn_website":"🌐 Website & Pricing","btn_support":"💬 Contact Support",
        "btn_language":"🌍 Change Language","btn_free_indicator":"📲 Get FREE Indicator",
        "btn_back":"⬅️ Back to Menu","btn_join":"📢 Join Our Channel First",
        "btn_start_again":"🚀 Start Again","btn_referral":"🎁 Invite Friends & Earn",
        "btn_testimonials":"⭐ Success Stories",
        "join_msg":"⚠️ *Please join our channel first!*\n\nYou need to be a member to access our services.\n\nJoin now and come back! 👇",
        "support_msg":"💬 *Support Request Received!* ✅\n\nThank you for reaching out!\n\nPlease wait — our team will connect with you *within 5 hours.* ⏳\n\nPlease keep the bot open and stay available. We will reach out to you here! 🙏",
        "price_msg":"💰 *Pricing & Plans*\n\nVisit our website for latest pricing 👇\n{website}",
        "thanks_msg":"😊 Thank you, {name}! Always here for you. 🚀",
        "fallback_msg":"🤔 I didn't catch that.\n\nPlease choose from the menu 👇",
        "join_pending":"⏳ *Request received!*\n\nAdmin will approve shortly. Thank you! 🙏",
        "cooldown_msg":"👋 *Still there, {name}?*\n\nTap below to continue exploring our services! 🚀",
        "msg_received":"📨 Message received! Our support team will reply shortly. 🙏",
        "referral_msg":"🎁 *YOUR REFERRAL LINK*\n\n👥 Invite friends and earn rewards!\n\n🔗 Your link:\n`https://t.me/{bot}?start=ref{uid}`\n\n📊 Your referrals so far: *{count}*\n🎯 Refer *{needed}* more to unlock your reward!\n\n✅ Every time a friend joins using your link, you get credit!\n\n📲 Share your link now 👆",
        "referral_reward":"🏆 *CONGRATULATIONS {name}!*\n\nYou have referred *{count}* friends!\n\n🎁 Your reward is ready — contact support to claim it!\n\n💬 Tap Contact Support below 👇",
        "testimonials_msg":"⭐ *WHAT OUR TRADERS SAY*\n\nReal results from real members:\n\n{testimonial}\n\n━━━━━━━━━━━━━━\n\n🔥 Join thousands of successful traders today!\n\n👇 Get started:",
    },
    "sw": {
        "btn_signals":"📊 VIP Signals","btn_social":"👥 Social Trading",
        "btn_indicator":"📈 Indicator ya Bure","btn_autobot":"🤖 Auto Bot",
        "btn_website":"🌐 Website & Bei","btn_support":"💬 Wasiliana na Support",
        "btn_language":"🌍 Badilisha Lugha","btn_free_indicator":"📲 Pata Indicator BURE",
        "btn_back":"⬅️ Rudi Menyu","btn_join":"📢 Jiunge na Channel Kwanza",
        "btn_start_again":"🚀 Anza Upya","btn_referral":"🎁 Alika Marafiki & Pata Zawadi",
        "btn_testimonials":"⭐ Hadithi za Mafanikio",
        "join_msg":"⚠️ *Tafadhali jiunge na channel yetu kwanza!*\n\nUnahitaji kuwa mwanachama ili kupata huduma zetu.\n\nJiunge sasa na urudi! 👇",
        "support_msg":"💬 *Ombi la Msaada Limepokelewa!* ✅\n\nAsante kwa kuwasiliana nasi!\n\nTafadhali subiri — timu yetu itawasiliana nawe *ndani ya masaa 5.* ⏳\n\nTafadhali kaa na bot wazi na uwe tayari. Tutakufikia hapa! 🙏",
        "price_msg":"💰 *Bei na Mipango*\n\nTembelea website kwa bei 👇\n{website}",
        "thanks_msg":"😊 Asante, {name}! Tuko hapa kila wakati. 🚀",
        "fallback_msg":"🤔 Sijaelewa. Chagua kutoka menyu 👇",
        "join_pending":"⏳ *Ombi limepokelewa!*\n\nAdmin atakuidhibitisha hivi karibuni. Asante! 🙏",
        "cooldown_msg":"👋 *Bado uko hapo, {name}?*\n\nBonyeza hapa chini kuendelea! 🚀",
        "msg_received":"📨 Ujumbe umepokelewa! Timu yetu ya msaada itajibu hivi karibuni. 🙏",
        "referral_msg":"🎁 *KIUNGO CHAKO CHA RUFAA*\n\n👥 Alika marafiki na upate zawadi!\n\n🔗 Kiungo chako:\n`https://t.me/{bot}?start=ref{uid}`\n\n📊 Rufaa zako hadi sasa: *{count}*\n🎯 Alika *{needed}* zaidi kufungua zawadi yako!\n\n✅ Kila wakati rafiki anajiunga kupitia kiungo chako, unapata mkopo!\n\n📲 Shiriki kiungo chako sasa 👆",
        "referral_reward":"🏆 *HONGERA {name}!*\n\nUmealika marafiki *{count}*!\n\n🎁 Zawadi yako iko tayari — wasiliana na support kuidai!\n\n💬 Bonyeza Wasiliana na Support hapa chini 👇",
        "testimonials_msg":"⭐ *WANACHAMA WETU WANASEMA NINI*\n\nMatokeo halisi kutoka kwa wanachama halisi:\n\n{testimonial}\n\n━━━━━━━━━━━━━━\n\n🔥 Jiunge na maelfu ya wafanyabiashara waliofanikiwa leo!\n\n👇 Anza:",
    },
    "ar": {"btn_signals":"📊 إشارات VIP","btn_social":"👥 التداول الاجتماعي","btn_indicator":"📈 مؤشر مجاني","btn_autobot":"🤖 بوت تلقائي","btn_website":"🌐 الموقع والأسعار","btn_support":"💬 تواصل مع الدعم","btn_language":"🌍 تغيير اللغة","btn_free_indicator":"📲 احصل على المؤشر","btn_back":"⬅️ العودة","btn_join":"📢 انضم لقناتنا أولاً","btn_start_again":"🚀 ابدأ من جديد","btn_referral":"🎁 ادعُ أصدقاء واربح","btn_testimonials":"⭐ قصص النجاح","join_msg":"⚠️ *يرجى الانضمام إلى قناتنا أولاً!*\n\nانضم الآن وعد! 👇","support_msg":"💬 *تم استلام طلب الدعم!* ✅\n\nشكراً على تواصلك!\n\nيرجى الانتظار — سيتواصل فريقنا معك *خلال 5 ساعات.* ⏳\n\nيرجى الإبقاء على البوت مفتوحاً. سنصل إليك هنا! 🙏","price_msg":"💰 *الأسعار*\n\n{website}","thanks_msg":"😊 شكراً، {name}! 🚀","fallback_msg":"🤔 اختر من القائمة 👇","join_pending":"⏳ *تم الاستلام!* 🙏","cooldown_msg":"👋 *لا تزال هناك، {name}?*\n\nاضغط للمتابعة! 🚀","msg_received":"📨 تم استلام الرسالة! 🙏","referral_msg":"🎁 *رابط الإحالة الخاص بك*\n\n`https://t.me/{bot}?start=ref{uid}`\n\n📊 إحالاتك: *{count}*\n🎯 أحل *{needed}* أكثر لفتح مكافأتك!","referral_reward":"🏆 *تهانينا {name}!*\n\nأحلت *{count}* أصدقاء!\n\n🎁 مكافأتك جاهزة — تواصل مع الدعم!","testimonials_msg":"⭐ *ما يقوله متداولونا*\n\n{testimonial}\n\n🔥 انضم اليوم!\n\n👇 ابدأ:"},
    "zh": {"btn_signals":"📊 VIP信号","btn_social":"👥 社交交易","btn_indicator":"📈 免费指标","btn_autobot":"🤖 自动机器人","btn_website":"🌐 网站和价格","btn_support":"💬 联系客服","btn_language":"🌍 更换语言","btn_free_indicator":"📲 获取免费指标","btn_back":"⬅️ 返回","btn_join":"📢 先加入我们的频道","btn_start_again":"🚀 重新开始","btn_referral":"🎁 邀请好友赚奖励","btn_testimonials":"⭐ 成功案例","join_msg":"⚠️ *请先加入我们的频道！*\n\n现在加入然后回来！👇","support_msg":"💬 *支持请求已收到！* ✅\n\n感谢您联系我们！\n\n请等待 — 我们的团队将在 *5小时内* 与您联系。⏳","price_msg":"💰 *价格*\n\n{website}","thanks_msg":"😊 谢谢，{name}！🚀","fallback_msg":"🤔 请从菜单选择 👇","join_pending":"⏳ *已收到！* 🙏","cooldown_msg":"👋 *还在吗，{name}?*\n\n点击继续！🚀","msg_received":"📨 消息已收到！🙏","referral_msg":"🎁 *您的推荐链接*\n\n`https://t.me/{bot}?start=ref{uid}`\n\n📊 您的推荐: *{count}*\n🎯 再推荐 *{needed}* 位解锁奖励！","referral_reward":"🏆 *恭喜 {name}！*\n\n您已推荐 *{count}* 位好友！\n\n🎁 您的奖励已准备好 — 联系支持领取！","testimonials_msg":"⭐ *我们的交易者说*\n\n{testimonial}\n\n🔥 今天就加入！\n\n👇 开始:"},
    "es": {"btn_signals":"📊 Señales VIP","btn_social":"👥 Trading Social","btn_indicator":"📈 Indicador Gratis","btn_autobot":"🤖 Bot Automático","btn_website":"🌐 Web y Precios","btn_support":"💬 Contactar Soporte","btn_language":"🌍 Cambiar Idioma","btn_free_indicator":"📲 Indicador Gratis","btn_back":"⬅️ Volver","btn_join":"📢 Únete a nuestro canal primero","btn_start_again":"🚀 Empezar de nuevo","btn_referral":"🎁 Invita Amigos y Gana","btn_testimonials":"⭐ Historias de Éxito","join_msg":"⚠️ *¡Por favor únete a nuestro canal primero!*\n\n¡Únete ahora y vuelve! 👇","support_msg":"💬 *¡Solicitud de soporte recibida!* ✅\n\n¡Gracias por contactarnos!\n\nPor favor espera — nuestro equipo te contactará *dentro de 5 horas.* ⏳","price_msg":"💰 *Precios*\n\n{website}","thanks_msg":"😊 ¡Gracias, {name}! 🚀","fallback_msg":"🤔 Elige del menú 👇","join_pending":"⏳ *¡Recibido!* 🙏","cooldown_msg":"👋 *¿Sigues ahí, {name}?*\n\n¡Toca para continuar! 🚀","msg_received":"📨 ¡Mensaje recibido! 🙏","referral_msg":"🎁 *TU ENLACE DE REFERIDO*\n\n`https://t.me/{bot}?start=ref{uid}`\n\n📊 Tus referidos: *{count}*\n🎯 ¡Refiere *{needed}* más para desbloquear tu recompensa!","referral_reward":"🏆 *¡Felicidades {name}!*\n\n¡Has referido *{count}* amigos!\n\n🎁 Tu recompensa está lista — ¡contacta soporte!","testimonials_msg":"⭐ *LO QUE DICEN NUESTROS TRADERS*\n\n{testimonial}\n\n🔥 ¡Únete hoy!\n\n👇 Empieza:"},
    "fr": {"btn_signals":"📊 Signaux VIP","btn_social":"👥 Trading Social","btn_indicator":"📈 Indicateur Gratuit","btn_autobot":"🤖 Bot Auto","btn_website":"🌐 Site & Tarifs","btn_support":"💬 Support","btn_language":"🌍 Langue","btn_free_indicator":"📲 Indicateur Gratuit","btn_back":"⬅️ Retour","btn_join":"📢 Rejoignez notre chaîne d'abord","btn_start_again":"🚀 Recommencer","btn_referral":"🎁 Invitez des Amis et Gagnez","btn_testimonials":"⭐ Histoires de Succès","join_msg":"⚠️ *Veuillez rejoindre notre chaîne d'abord!*\n\nRejoignez maintenant et revenez! 👇","support_msg":"💬 *Demande de support reçue!* ✅\n\nMerci de nous avoir contacté!\n\nVeuillez attendre — notre équipe vous contactera *dans 5 heures.* ⏳","price_msg":"💰 *Tarifs*\n\n{website}","thanks_msg":"😊 Merci, {name}! 🚀","fallback_msg":"🤔 Choisissez dans le menu 👇","join_pending":"⏳ *Reçu!* 🙏","cooldown_msg":"👋 *Toujours là, {name}?*\n\nAppuyez pour continuer! 🚀","msg_received":"📨 Message reçu! 🙏","referral_msg":"🎁 *VOTRE LIEN DE PARRAINAGE*\n\n`https://t.me/{bot}?start=ref{uid}`\n\n📊 Vos parrainages: *{count}*\n🎯 Parrainez *{needed}* de plus pour débloquer votre récompense!","referral_reward":"🏆 *Félicitations {name}!*\n\nVous avez parrainé *{count}* amis!\n\n🎁 Votre récompense est prête — contactez le support!","testimonials_msg":"⭐ *CE QUE DISENT NOS TRADERS*\n\n{testimonial}\n\n🔥 Rejoignez-nous aujourd'hui!\n\n👇 Commencez:"},
    "hi": {"btn_signals":"📊 VIP सिग्नल","btn_social":"👥 सोशल ट्रेडिंग","btn_indicator":"📈 मुफ्त इंडिकेटर","btn_autobot":"🤖 ऑटो बॉट","btn_website":"🌐 वेबसाइट","btn_support":"💬 सपोर्ट","btn_language":"🌍 भाषा","btn_free_indicator":"📲 मुफ्त इंडिकेटर","btn_back":"⬅️ वापस","btn_join":"📢 पहले हमारे चैनल से जुड़ें","btn_start_again":"🚀 फिर से शुरू करें","btn_referral":"🎁 दोस्तों को आमंत्रित करें","btn_testimonials":"⭐ सफलता की कहानियाँ","join_msg":"⚠️ *कृपया पहले हमारे चैनल से जुड़ें!*\n\nअभी जुड़ें और वापस आएं! 👇","support_msg":"💬 *सपोर्ट अनुरोध प्राप्त हुआ!* ✅\n\nहमसे संपर्क करने के लिए धन्यवाद!\n\nकृपया प्रतीक्षा करें — हमारी टीम *5 घंटों के भीतर* आपसे संपर्क करेगी। ⏳","price_msg":"💰 *मूल्य*\n\n{website}","thanks_msg":"😊 धन्यवाद, {name}! 🚀","fallback_msg":"🤔 मेनू से चुनें 👇","join_pending":"⏳ *प्राप्त!* 🙏","cooldown_msg":"👋 *अभी भी वहाँ हैं, {name}?*\n\nजारी रखने के लिए टैप करें! 🚀","msg_received":"📨 संदेश प्राप्त हुआ! 🙏","referral_msg":"🎁 *आपका रेफरल लिंक*\n\n`https://t.me/{bot}?start=ref{uid}`\n\n📊 आपके रेफरल: *{count}*\n🎯 इनाम के लिए *{needed}* और रेफर करें!","referral_reward":"🏆 *बधाई {name}!*\n\nआपने *{count}* दोस्तों को रेफर किया!\n\n🎁 आपका इनाम तैयार है — सपोर्ट से संपर्क करें!","testimonials_msg":"⭐ *हमारे ट्रेडर्स क्या कहते हैं*\n\n{testimonial}\n\n🔥 आज जुड़ें!\n\n👇 शुरू करें:"},
    "ru": {"btn_signals":"📊 VIP Сигналы","btn_social":"👥 Соц. Трейдинг","btn_indicator":"📈 Бесплатный Индикатор","btn_autobot":"🤖 Авто Бот","btn_website":"🌐 Сайт","btn_support":"💬 Поддержка","btn_language":"🌍 Язык","btn_free_indicator":"📲 Бесплатный Индикатор","btn_back":"⬅️ Назад","btn_join":"📢 Сначала вступите в наш канал","btn_start_again":"🚀 Начать заново","btn_referral":"🎁 Пригласи Друзей и Заработай","btn_testimonials":"⭐ Истории Успеха","join_msg":"⚠️ *Пожалуйста, сначала вступите в наш канал!*\n\nВступите сейчас и возвращайтесь! 👇","support_msg":"💬 *Запрос на поддержку получен!* ✅\n\nСпасибо за обращение!\n\nПожалуйста, подождите — наша команда свяжется с вами *в течение 5 часов.* ⏳","price_msg":"💰 *Цены*\n\n{website}","thanks_msg":"😊 Спасибо, {name}! 🚀","fallback_msg":"🤔 Выберите из меню 👇","join_pending":"⏳ *Получено!* 🙏","cooldown_msg":"👋 *Всё ещё здесь, {name}?*\n\nНажмите, чтобы продолжить! 🚀","msg_received":"📨 Сообщение получено! 🙏","referral_msg":"🎁 *ВАША РЕФЕРАЛЬНАЯ ССЫЛКА*\n\n`https://t.me/{bot}?start=ref{uid}`\n\n📊 Ваши рефералы: *{count}*\n🎯 Пригласите ещё *{needed}* для разблокировки награды!","referral_reward":"🏆 *Поздравляем {name}!*\n\nВы пригласили *{count}* друзей!\n\n🎁 Ваша награда готова — свяжитесь с поддержкой!","testimonials_msg":"⭐ *ЧТО ГОВОРЯТ НАШИ ТРЕЙДЕРЫ*\n\n{testimonial}\n\n🔥 Присоединяйтесь сегодня!\n\n👇 Начать:"},
    "pt": {"btn_signals":"📊 Sinais VIP","btn_social":"👥 Trading Social","btn_indicator":"📈 Indicador Grátis","btn_autobot":"🤖 Bot Auto","btn_website":"🌐 Site","btn_support":"💬 Suporte","btn_language":"🌍 Idioma","btn_free_indicator":"📲 Indicador Grátis","btn_back":"⬅️ Voltar","btn_join":"📢 Junte-se ao nosso canal primeiro","btn_start_again":"🚀 Começar de novo","btn_referral":"🎁 Convide Amigos e Ganhe","btn_testimonials":"⭐ Histórias de Sucesso","join_msg":"⚠️ *Por favor, junte-se ao nosso canal primeiro!*\n\nJunte-se agora e volte! 👇","support_msg":"💬 *Solicitação de suporte recebida!* ✅\n\nObrigado por entrar em contato!\n\nPor favor aguarde — nossa equipe entrará em contato *em até 5 horas.* ⏳","price_msg":"💰 *Preços*\n\n{website}","thanks_msg":"😊 Obrigado, {name}! 🚀","fallback_msg":"🤔 Escolha no menu 👇","join_pending":"⏳ *Recebido!* 🙏","cooldown_msg":"👋 *Ainda aí, {name}?*\n\nToque para continuar! 🚀","msg_received":"📨 Mensagem recebida! 🙏","referral_msg":"🎁 *SEU LINK DE REFERRAL*\n\n`https://t.me/{bot}?start=ref{uid}`\n\n📊 Seus referrals: *{count}*\n🎯 Refira mais *{needed}* para desbloquear sua recompensa!","referral_reward":"🏆 *Parabéns {name}!*\n\nVocê referiu *{count}* amigos!\n\n🎁 Sua recompensa está pronta — contate o suporte!","testimonials_msg":"⭐ *O QUE NOSSOS TRADERS DIZEM*\n\n{testimonial}\n\n🔥 Junte-se hoje!\n\n👇 Comece:"},
    "de": {"btn_signals":"📊 VIP-Signale","btn_social":"👥 Social Trading","btn_indicator":"📈 Kostenloser Indikator","btn_autobot":"🤖 Auto-Bot","btn_website":"🌐 Website","btn_support":"💬 Support","btn_language":"🌍 Sprache","btn_free_indicator":"📲 Kostenloser Indikator","btn_back":"⬅️ Zurück","btn_join":"📢 Treten Sie zuerst unserem Kanal bei","btn_start_again":"🚀 Neu starten","btn_referral":"🎁 Freunde einladen und verdienen","btn_testimonials":"⭐ Erfolgsgeschichten","join_msg":"⚠️ *Bitte treten Sie zuerst unserem Kanal bei!*\n\nJetzt beitreten und zurückkommen! 👇","support_msg":"💬 *Support-Anfrage erhalten!* ✅\n\nDanke für Ihre Kontaktaufnahme!\n\nBitte warten Sie — unser Team wird sich *innerhalb von 5 Stunden* melden. ⏳","price_msg":"💰 *Preise*\n\n{website}","thanks_msg":"😊 Danke, {name}! 🚀","fallback_msg":"🤔 Wählen Sie aus dem Menü 👇","join_pending":"⏳ *Erhalten!* 🙏","cooldown_msg":"👋 *Noch da, {name}?*\n\nTippen Sie um fortzufahren! 🚀","msg_received":"📨 Nachricht erhalten! 🙏","referral_msg":"🎁 *IHR EMPFEHLUNGSLINK*\n\n`https://t.me/{bot}?start=ref{uid}`\n\n📊 Ihre Empfehlungen: *{count}*\n🎯 Empfehlen Sie *{needed}* mehr für Ihre Belohnung!","referral_reward":"🏆 *Glückwunsch {name}!*\n\nSie haben *{count}* Freunde empfohlen!\n\n🎁 Ihre Belohnung ist bereit — kontaktieren Sie den Support!","testimonials_msg":"⭐ *WAS UNSERE TRADER SAGEN*\n\n{testimonial}\n\n🔥 Treten Sie heute bei!\n\n👇 Starten:"},
    "ur": {"btn_signals":"📊 VIP سگنلز","btn_social":"👥 سوشل ٹریڈنگ","btn_indicator":"📈 مفت انڈیکیٹر","btn_autobot":"🤖 آٹو بوٹ","btn_website":"🌐 ویب سائٹ","btn_support":"💬 سپورٹ","btn_language":"🌍 زبان","btn_free_indicator":"📲 مفت انڈیکیٹر","btn_back":"⬅️ واپس","btn_join":"📢 پہلے ہمارے چینل میں شامل ہوں","btn_start_again":"🚀 دوبارہ شروع کریں","btn_referral":"🎁 دوستوں کو مدعو کریں","btn_testimonials":"⭐ کامیابی کی کہانیاں","join_msg":"⚠️ *براہ کرم پہلے ہمارے چینل میں شامل ہوں!*\n\nابھی شامل ہوں اور واپس آئیں! 👇","support_msg":"💬 *سپورٹ کی درخواست موصول ہوئی!* ✅\n\nرابطہ کرنے کا شکریہ!\n\nبراہ کرم انتظار کریں — ہماری ٹیم *5 گھنٹوں کے اندر* آپ سے رابطہ کرے گی۔ ⏳","price_msg":"💰 *قیمتیں*\n\n{website}","thanks_msg":"😊 شکریہ، {name}! 🚀","fallback_msg":"🤔 مینو سے انتخاب کریں 👇","join_pending":"⏳ *موصول!* 🙏","cooldown_msg":"👋 *ابھی بھی وہاں ہیں، {name}?*\n\nجاری رکھنے کے لیے ٹیپ کریں! 🚀","msg_received":"📨 پیغام موصول ہوا! 🙏","referral_msg":"🎁 *آپ کا ریفرل لنک*\n\n`https://t.me/{bot}?start=ref{uid}`\n\n📊 آپ کے ریفرلز: *{count}*\n🎯 انعام کے لیے *{needed}* مزید ریفر کریں!","referral_reward":"🏆 *مبارک ہو {name}!*\n\nآپ نے *{count}* دوستوں کو ریفر کیا!\n\n🎁 آپ کا انعام تیار ہے — سپورٹ سے رابطہ کریں!","testimonials_msg":"⭐ *ہمارے ٹریڈرز کیا کہتے ہیں*\n\n{testimonial}\n\n🔥 آج شامل ہوں!\n\n👇 شروع کریں:"},
    "ja": {"btn_signals":"📊 VIPシグナル","btn_social":"👥 ソーシャルトレード","btn_indicator":"📈 無料インジケーター","btn_autobot":"🤖 自動ボット","btn_website":"🌐 ウェブサイト","btn_support":"💬 サポート","btn_language":"🌍 言語","btn_free_indicator":"📲 無料インジケーター","btn_back":"⬅️ 戻る","btn_join":"📢 まず私たちのチャンネルに参加","btn_start_again":"🚀 もう一度始める","btn_referral":"🎁 友達を招待して稼ぐ","btn_testimonials":"⭐ 成功ストーリー","join_msg":"⚠️ *まず私たちのチャンネルに参加してください！*\n\n今すぐ参加して戻ってきてください！👇","support_msg":"💬 *サポートリクエストを受け取りました！* ✅\n\nご連絡いただきありがとうございます！\n\nお待ちください — チームが *5時間以内* にご連絡します。⏳","price_msg":"💰 *料金*\n\n{website}","thanks_msg":"😊 ありがとう、{name}！🚀","fallback_msg":"🤔 メニューから選んでください 👇","join_pending":"⏳ *受信！* 🙏","cooldown_msg":"👋 *まだいますか、{name}?*\n\n続けるにはタップしてください！🚀","msg_received":"📨 メッセージを受け取りました！🙏","referral_msg":"🎁 *あなたの紹介リンク*\n\n`https://t.me/{bot}?start=ref{uid}`\n\n📊 あなたの紹介: *{count}*\n🎯 報酬のためにあと *{needed}* 人紹介してください！","referral_reward":"🏆 *おめでとう {name}！*\n\n*{count}* 人の友達を紹介しました！\n\n🎁 報酬の準備ができました — サポートに連絡してください！","testimonials_msg":"⭐ *私たちのトレーダーが言うこと*\n\n{testimonial}\n\n🔥 今日参加！\n\n👇 始める:"},
}

WELCOME = {
    "en": ["👋 Welcome back, *{name}!*\n\n🏆 *{business}* — Your trading success starts here!\n\nHow can we help you today? 👇","🚀 Hey *{name}!* Ready to level up your trading?\n\n💎 *{business}* has everything you need!\n\nChoose a service below 👇","💰 Hello *{name}!* Smart traders choose *{business}!*\n\nPick your weapon 👇","🌟 Welcome, *{name}!* — Where winners trade! 🏅\n\nHow can we assist? 👇","⚡ *{name}*, you're in the right place!\n\n*{business}* powers thousands worldwide 🌍\n\nExplore 👇"],
    "sw": ["👋 Karibu tena, *{name}!*\n\n🏆 *{business}* — Mafanikio yako yanaanza hapa!\n\nTunakusaidiaje? 👇","🚀 Habari *{name}!* Uko tayari?\n\n💎 *{business}* ina kila kitu!\n\nChagua 👇","💰 Hujambo *{name}!* Wafanyabiashara werevu wanachagua *{business}!*\n\nChagua zana 👇","🌟 Karibu, *{name}!* — Mahali pa washindi! 🏅\n\nTunasaidiaje? 👇","⚡ *{name}*, umefika mahali pazuri!\n\n*{business}* inasaidia maelfu 🌍\n\nGundua 👇"],
    "ar": ["👋 مرحباً، *{name}!*\n\n🏆 *{business}* — نجاحك يبدأ هنا!\n\nكيف نساعدك؟ 👇","🚀 أهلاً *{name}!*\n\n💎 اختر خدمة 👇"],
    "zh": ["👋 欢迎，*{name}!*\n\n🏆 *{business}* — 成功从这里开始！\n\n今天能帮您什么？👇","🚀 嗨 *{name}!* 选择服务 👇"],
    "es": ["👋 ¡Bienvenido, *{name}!*\n\n🏆 *{business}* — ¡Tu éxito empieza aquí!\n\n¿En qué podemos ayudar? 👇","🚀 ¡Hola *{name}!* Elige 👇"],
    "fr": ["👋 Bienvenue, *{name}!*\n\n🏆 *{business}* — Votre succès commence ici!\n\nComment vous aider? 👇","🚀 Salut *{name}!* Choisissez 👇"],
    "hi": ["👋 स्वागत है, *{name}!*\n\n🏆 *{business}* — सफलता यहाँ से!\n\nकैसे मदद करें? 👇"],
    "ru": ["👋 Добро пожаловать, *{name}!*\n\n🏆 *{business}* — Успех начинается здесь!\n\nЧем помочь? 👇","🚀 Привет *{name}!* Выбери 👇"],
    "pt": ["👋 Bem-vindo, *{name}!*\n\n🏆 *{business}* — Seu sucesso começa aqui!\n\nComo podemos ajudar? 👇"],
    "de": ["👋 Willkommen, *{name}!*\n\n🏆 *{business}* — Ihr Erfolg beginnt hier!\n\nWie können wir helfen? 👇"],
    "ur": ["👋 خوش آمدید، *{name}!*\n\n🏆 *{business}* — کامیابی یہاں سے!\n\nکیسے مدد کریں؟ 👇"],
    "ja": ["👋 ようこそ、*{name}!*\n\n🏆 *{business}* — 成功はここから！\n\nどのようにお手伝い？👇"],
}

# ══════════════════════════════════════════════════════════════
#  HELPER FUNCTIONS
# ══════════════════════════════════════════════════════════════

def ui(key, lang):
    return UI.get(lang, UI["en"]).get(key, UI["en"].get(key, key))

def get_lang(context):
    return context.user_data.get("lang", "en")

def get_replies(pool, lang):
    return pool.get(lang) or pool.get("en", ["Coming soon!"])

async def typing_action(chat_id, context, seconds=1.5):
    await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
    await asyncio.sleep(seconds)

async def notify_new_user(context, user):
    now = datetime.now().strftime("%d/%m/%Y %H:%M")
    text = (
        f"🆕 *New User!*\n\n"
        f"👤 {user.full_name}\n"
        f"🔗 @{user.username or 'N/A'}\n"
        f"🆔 `{user.id}`\n"
        f"🕐 {now}"
    )
    for aid in ADMIN_IDS:
        try:
            await context.bot.send_message(chat_id=aid, text=text, parse_mode="Markdown")
        except Exception as e:
            logger.warning(f"New user notify failed: {e}")

async def notify_support_request(context, user, lang: str):
    now = datetime.now().strftime("%d/%m/%Y %H:%M")
    text = (
        f"🆘 *Support Request*\n\n"
        f"👤 {user.full_name}\n"
        f"🔗 @{user.username or 'N/A'}\n"
        f"🆔 `{user.id}`\n"
        f"🕐 {now}\n"
        f"🌍 Lang: {lang}\n\n"
        f"_(Reply to forwarded message to respond)_"
    )
    uid = user.id
    btns = InlineKeyboardMarkup([[
        InlineKeyboardButton("🟢 Connect", callback_data=f"con:{uid}:{lang}"),
        InlineKeyboardButton("🔴 End Chat", callback_data=f"dis:{uid}:{lang}"),
    ]])
    for aid in ADMIN_IDS:
        try:
            await context.bot.send_message(
                chat_id=aid, text=text,
                parse_mode="Markdown", reply_markup=btns)
        except Exception as e:
            logger.warning(f"Support notify failed: {e}")

async def notify_user_blocked(context, user):
    now = datetime.now().strftime("%d/%m/%Y %H:%M")
    text = (
        f"🚫 *User Blocked Bot*\n\n"
        f"👤 {user.full_name}\n"
        f"🔗 @{user.username or 'N/A'}\n"
        f"🆔 `{user.id}`\n"
        f"🕐 {now}"
    )
    for aid in ADMIN_IDS:
        try:
            await context.bot.send_message(chat_id=aid, text=text, parse_mode="Markdown")
        except Exception as e:
            logger.warning(f"Block notify failed: {e}")

# ══════════════════════════════════════════════════════════════
#  KEYBOARDS
# ══════════════════════════════════════════════════════════════

def lang_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🇬🇧 English", callback_data="lang_en"),
         InlineKeyboardButton("🇨🇳 中文", callback_data="lang_zh"),
         InlineKeyboardButton("🇪🇸 Español", callback_data="lang_es")],
        [InlineKeyboardButton("🇫🇷 Français", callback_data="lang_fr"),
         InlineKeyboardButton("🇸🇦 العربية", callback_data="lang_ar"),
         InlineKeyboardButton("🇮🇳 हिन्दी", callback_data="lang_hi")],
        [InlineKeyboardButton("🇷🇺 Русский", callback_data="lang_ru"),
         InlineKeyboardButton("🇹🇿 Swahili", callback_data="lang_sw"),
         InlineKeyboardButton("🇧🇷 Português", callback_data="lang_pt")],
        [InlineKeyboardButton("🇩🇪 Deutsch", callback_data="lang_de"),
         InlineKeyboardButton("🇵🇰 اردو", callback_data="lang_ur"),
         InlineKeyboardButton("🇯🇵 日本語", callback_data="lang_ja")],
    ])

def main_menu(lang):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(ui("btn_signals", lang), callback_data="svc_signals"),
         InlineKeyboardButton(ui("btn_social", lang), callback_data="svc_social")],
        [InlineKeyboardButton(ui("btn_indicator", lang), callback_data="svc_indicator"),
         InlineKeyboardButton(ui("btn_autobot", lang), callback_data="svc_autobot")],
        [InlineKeyboardButton(ui("btn_website", lang), url=WEBSITE_URL)],
        [InlineKeyboardButton(ui("btn_support", lang), callback_data="do_support")],
        [InlineKeyboardButton(ui("btn_referral", lang), callback_data="do_referral"),
         InlineKeyboardButton(ui("btn_testimonials", lang), callback_data="do_testimonials")],
        [InlineKeyboardButton(ui("btn_language", lang), callback_data="change_lang")],
    ])

def svc_keyboard(lang, indicator=False):
    rows = [
        [InlineKeyboardButton(ui("btn_website", lang), url=WEBSITE_URL)],
        [InlineKeyboardButton(ui("btn_support", lang), callback_data="do_support")],
        [InlineKeyboardButton(ui("btn_back", lang), callback_data="main_menu")],
    ]
    if indicator:
        rows.insert(1, [InlineKeyboardButton(
            ui("btn_free_indicator", lang), url=INDICATOR_CHANNEL)])
    return InlineKeyboardMarkup(rows)

def join_keyboard(lang):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(ui("btn_join", lang), url=MAIN_CHANNEL_LINK)],
        [InlineKeyboardButton("✅ I've Sent a Request!", callback_data="check_join")],
    ])

def cooldown_keyboard(lang):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(ui("btn_start_again", lang), callback_data="restart")],
    ])

# ══════════════════════════════════════════════════════════════
#  DAILY STATS JOB — Sends report to admin every day at 8AM
# ══════════════════════════════════════════════════════════════

async def daily_stats_job(context: ContextTypes.DEFAULT_TYPE):
    total    = get_user_count()
    active7  = get_active_users(7)
    active30 = get_active_users(30)
    new_today = get_new_users_today()
    now = datetime.now().strftime("%d/%m/%Y %H:%M")

    text = (
        f"📊 *DAILY REPORT — {BUSINESS_NAME}*\n"
        f"🕐 {now}\n\n"
        f"👥 Total users: *{total}*\n"
        f"🆕 New today: *{new_today}*\n"
        f"🟢 Active (7 days): *{active7}*\n"
        f"📅 Active (30 days): *{active30}*\n"
        f"🆘 Active support sessions: *{len(active_support)}*\n\n"
        f"💡 Keep up the great work!"
    )
    for aid in ADMIN_IDS:
        try:
            await context.bot.send_message(chat_id=aid, text=text, parse_mode="Markdown")
        except Exception as e:
            logger.warning(f"Daily stats failed: {e}")

# ══════════════════════════════════════════════════════════════
#  COOLDOWN JOB
# ══════════════════════════════════════════════════════════════

async def send_cooldown_reminder(context: ContextTypes.DEFAULT_TYPE):
    job_data = context.job.data
    chat_id  = job_data["chat_id"]
    name     = job_data["name"]
    lang     = job_data.get("lang", "en")

    try:
        await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
        await asyncio.sleep(1.0)
        await context.bot.send_message(
            chat_id=chat_id,
            text=ui("cooldown_msg", lang).format(name=name),
            parse_mode="Markdown",
            reply_markup=cooldown_keyboard(lang),
        )
    except Exception as e:
        logger.warning(f"Cooldown reminder failed: {e}")

def schedule_cooldown(context, chat_id, name, lang):
    job_name = f"cooldown_{chat_id}"
    current_jobs = context.job_queue.get_jobs_by_name(job_name)
    for job in current_jobs:
        job.schedule_removal()
    context.job_queue.run_once(
        send_cooldown_reminder,
        when=COOLDOWN_MINUTES * 60,
        data={"chat_id": chat_id, "name": name, "lang": lang},
        name=job_name,
    )

# ══════════════════════════════════════════════════════════════
#  JOIN REQUEST HANDLER
# ══════════════════════════════════════════════════════════════

async def handle_join_request(update: Update, context: ContextTypes.DEFAULT_TYPE):
    req  = update.chat_join_request
    user = req.from_user
    chat = req.chat
    now  = datetime.now().strftime("%d/%m/%Y %H:%M")

    pending_requests[user.id] = {
        "chat_id": chat.id, "chat_title": chat.title,
        "user": user, "time": now,
    }

    btns = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Approve", callback_data=f"approve_{user.id}"),
        InlineKeyboardButton("❌ Decline", callback_data=f"decline_{user.id}"),
    ]])
    msg = (
        f"📨 *New Join Request*\n\n"
        f"👤 {user.full_name}\n🔗 @{user.username or 'N/A'}\n"
        f"🆔 `{user.id}`\n📢 {chat.title}\n🕐 {now}"
    )
    for aid in ADMIN_IDS:
        try:
            await context.bot.send_message(
                chat_id=aid, text=msg, parse_mode="Markdown", reply_markup=btns)
        except Exception as e:
            logger.warning(f"Join notify failed: {e}")

    lang = context.user_data.get("lang", "en")
    try:
        await context.bot.send_message(
            chat_id=user.id,
            text=ui("join_pending", lang),
            parse_mode="Markdown",
        )
    except Exception:
        pass

# ══════════════════════════════════════════════════════════════
#  /start — handles referral links too
# ══════════════════════════════════════════════════════════════

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    cid  = update.effective_chat.id

    # Check for referral in start args
    referred_by = None
    if context.args and context.args[0].startswith("ref"):
        try:
            referred_by = int(context.args[0][3:])
            if referred_by == user.id:
                referred_by = None  # Can't refer yourself
        except ValueError:
            referred_by = None

    new_user = is_new_user(user.id)
    register_user(user, referred_by=referred_by)

    if new_user:
        await notify_new_user(context, user)
        # Check if referrer hit reward threshold
        if referred_by:
            ref_count = get_referral_count(referred_by)
            if ref_count >= REFERRAL_REWARD_COUNT:
                ref_info = get_user_info(referred_by)
                reward_text = (
                    f"🏆 *REFERRAL REWARD!*\n\n"
                    f"👤 {ref_info['name']} has reached {ref_count} referrals!\n"
                    f"🎁 Please reward them accordingly."
                )
                for aid in ADMIN_IDS:
                    try:
                        await context.bot.send_message(chat_id=aid, text=reward_text, parse_mode="Markdown")
                    except Exception:
                        pass
                try:
                    lang_ref = "en"
                    await context.bot.send_message(
                        chat_id=referred_by,
                        text=ui("referral_reward", lang_ref).format(
                            name=ref_info["name"], count=ref_count),
                        parse_mode="Markdown",
                        reply_markup=InlineKeyboardMarkup([[
                            InlineKeyboardButton(ui("btn_support", lang_ref), callback_data="do_support")
                        ]])
                    )
                except Exception:
                    pass

    old_id = context.user_data.get("last_bot_msg_id")
    if old_id:
        await safe_delete(context, cid, old_id)

    await typing_action(cid, context, 1.2)

    if not context.user_data.get("lang"):
        msg = await context.bot.send_message(
            chat_id=cid,
            text="🌍 *Welcome to EVALON WINNERS!*\n\nChoose your language / Chagua lugha yako:",
            parse_mode="Markdown",
            reply_markup=lang_keyboard(),
        )
        context.user_data["last_bot_msg_id"] = msg.message_id
        return

    lang = get_lang(context)

    if not await is_member(context, user.id):
        msg = await context.bot.send_message(
            chat_id=cid,
            text=ui("join_msg", lang),
            parse_mode="Markdown",
            reply_markup=join_keyboard(lang),
        )
        context.user_data["last_bot_msg_id"] = msg.message_id
        return

    # Welcome bonus for brand new users
    if new_user:
        await typing_action(cid, context, 1.0)
        bonus_text = WELCOME_BONUS.get(lang, WELCOME_BONUS["en"])
        bonus_msg = await context.bot.send_message(
            chat_id=cid,
            text=bonus_text,
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(ui("btn_free_indicator", lang), url=INDICATOR_CHANNEL)],
                [InlineKeyboardButton(ui("btn_support", lang), callback_data="do_support")],
            ])
        )
        await asyncio.sleep(3)
        await safe_delete(context, cid, bonus_msg.message_id)

    urgency = get_urgency(lang)
    welcome_text = random.choice(WELCOME.get(lang, WELCOME["en"])).format(
        name=user.first_name, business=BUSINESS_NAME)
    full_text = f"{urgency}\n\n{welcome_text}"

    msg = await context.bot.send_message(
        chat_id=cid,
        text=full_text,
        parse_mode="Markdown",
        reply_markup=main_menu(lang),
    )
    context.user_data["last_bot_msg_id"] = msg.message_id
    schedule_cooldown(context, cid, user.first_name, lang)

# ══════════════════════════════════════════════════════════════
#  BROADCAST & ADMIN COMMANDS
# ══════════════════════════════════════════════════════════════

async def broadcast_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return

    all_users = get_all_user_ids()
    total     = len(all_users)
    sent = failed = 0
    replied_msg = update.message.reply_to_message

    await update.message.reply_text(
        f"📢 Broadcasting to *{total}* users...", parse_mode="Markdown")

    for uid in all_users:
        try:
            if replied_msg and replied_msg.photo:
                await context.bot.send_photo(chat_id=uid, photo=replied_msg.photo[-1].file_id, caption=replied_msg.caption or "", parse_mode="Markdown")
            elif replied_msg and replied_msg.video:
                await context.bot.send_video(chat_id=uid, video=replied_msg.video.file_id, caption=replied_msg.caption or "", parse_mode="Markdown")
            elif replied_msg and replied_msg.voice:
                await context.bot.send_voice(chat_id=uid, voice=replied_msg.voice.file_id)
            elif replied_msg and replied_msg.document:
                await context.bot.send_document(chat_id=uid, document=replied_msg.document.file_id, caption=replied_msg.caption or "", parse_mode="Markdown")
            elif replied_msg and replied_msg.text:
                await context.bot.send_message(chat_id=uid, text=replied_msg.text, parse_mode="Markdown")
            elif context.args:
                await context.bot.send_message(chat_id=uid, text=" ".join(context.args), parse_mode="Markdown")
            else:
                await update.message.reply_text("⚠️ No content.\n\nUsage:\n• `/broadcast Your message`\n• Reply to media + `/broadcast`", parse_mode="Markdown")
                return
            sent += 1
            await asyncio.sleep(0.05)
        except TelegramError as e:
            err = str(e).lower()
            if "blocked" in err or "deactivated" in err or "not found" in err:
                u_data = get_user_info(uid)
                class FakeUser:
                    id = uid
                    full_name = u_data.get("name", str(uid))
                    username = u_data.get("username", None)
                await notify_user_blocked(context, FakeUser())
            failed += 1
            logger.warning(f"Broadcast failed {uid}: {e}")

    await update.message.reply_text(
        f"✅ *Broadcast Complete!*\n\n📤 Sent: {sent}\n❌ Failed: {failed}\n👥 Total: {total}",
        parse_mode="Markdown")

async def getid_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    msg = update.message
    if msg.photo:
        file_id = msg.photo[-1].file_id
        await msg.reply_text(f"📸 *Photo file\\_id:*\n\n`{file_id}`", parse_mode="Markdown")
    elif msg.video:
        await msg.reply_text(f"🎥 *Video file\\_id:*\n\n`{msg.video.file_id}`", parse_mode="Markdown")
    elif msg.document:
        await msg.reply_text(f"📄 *Document file\\_id:*\n\n`{msg.document.file_id}`", parse_mode="Markdown")
    else:
        await msg.reply_text("📸 Send me a photo (or reply to one) and I'll give you the file\\_id.", parse_mode="Markdown")

async def support_sessions_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    if not active_support:
        await update.message.reply_text(
            "✅ *No active support sessions.*\n\nBot is auto-replying to all users.",
            parse_mode="Markdown")
        return

    text = f"🆘 *Active Support Sessions: {len(active_support)}*\n\n"
    keyboard = []
    for uid in list(active_support.keys()):
        u = get_user_info(uid)
        name  = u.get("name", str(uid))
        uname = u.get("username", "N/A")
        text += f"👤 {name} | @{uname} | `{uid}`\n"
        keyboard.append([InlineKeyboardButton(f"🔴 End: {name[:20]}", callback_data=f"dis:{uid}:en")])
    keyboard.append([InlineKeyboardButton("🔴 End ALL Sessions", callback_data="end_all_support")])
    await update.message.reply_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))

async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    total    = get_user_count()
    active7  = get_active_users(7)
    active30 = get_active_users(30)
    new_today = get_new_users_today()
    now      = datetime.now()

    await update.message.reply_text(
        f"📊 *Bot Statistics — {BUSINESS_NAME}*\n\n"
        f"👥 Total users: *{total}*\n"
        f"🆕 New today: *{new_today}*\n"
        f"🟢 Active (7 days): *{active7}*\n"
        f"📅 Active (30 days): *{active30}*\n"
        f"🆘 Active support sessions: *{len(active_support)}*\n\n"
        f"📋 *Commands:*\n"
        f"• `/broadcast msg` — send to all\n"
        f"• `/sessions` — manage support\n"
        f"• `/stats` — this screen\n"
        f"• `/getid` — get photo file\\_id\n\n"
        f"🕐 {now.strftime('%d/%m/%Y %H:%M')}",
        parse_mode="Markdown"
    )

# ══════════════════════════════════════════════════════════════
#  CALLBACK HANDLER
# ══════════════════════════════════════════════════════════════

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    user = query.from_user
    cid  = query.message.chat_id

    # ── Language select ───────────────────────────────────────
    if data.startswith("lang_"):
        lang = data[5:]
        context.user_data["lang"] = lang
        await typing_action(cid, context, 1.5)
        await safe_delete(context, cid, query.message.message_id)

        if not await is_member(context, user.id):
            msg = await context.bot.send_message(
                chat_id=cid, text=ui("join_msg", lang),
                parse_mode="Markdown", reply_markup=join_keyboard(lang))
            context.user_data["last_bot_msg_id"] = msg.message_id
            return

        urgency = get_urgency(lang)
        welcome_text = random.choice(WELCOME.get(lang, WELCOME["en"])).format(
            name=user.first_name, business=BUSINESS_NAME)
        msg = await context.bot.send_message(
            chat_id=cid,
            text=f"{urgency}\n\n{welcome_text}",
            parse_mode="Markdown", reply_markup=main_menu(lang),
        )
        context.user_data["last_bot_msg_id"] = msg.message_id
        schedule_cooldown(context, cid, user.first_name, lang)
        return

    lang = get_lang(context)

    # ── Check join ────────────────────────────────────────────
    if data == "check_join":
        await typing_action(cid, context, 1.0)
        if await is_member(context, user.id):
            await safe_delete(context, cid, query.message.message_id)
            urgency = get_urgency(lang)
            welcome_text = random.choice(WELCOME.get(lang, WELCOME["en"])).format(
                name=user.first_name, business=BUSINESS_NAME)
            msg = await context.bot.send_message(
                chat_id=cid,
                text=f"{urgency}\n\n{welcome_text}",
                parse_mode="Markdown", reply_markup=main_menu(lang),
            )
            context.user_data["last_bot_msg_id"] = msg.message_id
            schedule_cooldown(context, cid, user.first_name, lang)
        else:
            await query.answer("❌ Please send a join request first, then tap this button!", show_alert=True)
        return

    # ── Restart ───────────────────────────────────────────────
    if data == "restart":
        await safe_delete(context, cid, query.message.message_id)
        await typing_action(cid, context, 1.2)

        if not await is_member(context, user.id):
            msg = await context.bot.send_message(
                chat_id=cid, text=ui("join_msg", lang),
                parse_mode="Markdown", reply_markup=join_keyboard(lang))
            context.user_data["last_bot_msg_id"] = msg.message_id
            return

        urgency = get_urgency(lang)
        welcome_text = random.choice(WELCOME.get(lang, WELCOME["en"])).format(
            name=user.first_name, business=BUSINESS_NAME)
        msg = await context.bot.send_message(
            chat_id=cid,
            text=f"{urgency}\n\n{welcome_text}",
            parse_mode="Markdown", reply_markup=main_menu(lang),
        )
        context.user_data["last_bot_msg_id"] = msg.message_id
        schedule_cooldown(context, cid, user.first_name, lang)
        return

    # All other callbacks — melt effect
    await safe_delete(context, cid, query.message.message_id)
    await typing_action(cid, context, 1.5)

    if data == "change_lang":
        msg = await context.bot.send_message(
            chat_id=cid,
            text="🌍 Choose your language / Chagua lugha:",
            reply_markup=lang_keyboard())
        context.user_data["last_bot_msg_id"] = msg.message_id

    elif data == "main_menu":
        urgency = get_urgency(lang)
        welcome_text = random.choice(WELCOME.get(lang, WELCOME["en"])).format(
            name=user.first_name, business=BUSINESS_NAME)
        msg = await context.bot.send_message(
            chat_id=cid,
            text=f"{urgency}\n\n{welcome_text}",
            parse_mode="Markdown", reply_markup=main_menu(lang),
        )
        context.user_data["last_bot_msg_id"] = msg.message_id
        schedule_cooldown(context, cid, user.first_name, lang)

    # ── Services ──────────────────────────────────────────────
    elif data == "svc_signals":
        replies = get_replies(SIGNALS_REPLIES, lang)
        img = rand_img(IMGS_SIGNALS, context.user_data, "last_img_signals")
        caption = f"{random.choice(replies)}\n\n{get_testimonial(lang)}"
        try:
            msg = await context.bot.send_photo(
                chat_id=cid, photo=img, caption=caption,
                parse_mode="Markdown", reply_markup=svc_keyboard(lang))
        except Exception:
            msg = await context.bot.send_message(
                chat_id=cid, text=caption,
                parse_mode="Markdown", reply_markup=svc_keyboard(lang))
        context.user_data["last_bot_msg_id"] = msg.message_id

    elif data == "svc_social":
        replies = get_replies(SOCIAL_REPLIES, lang)
        img = rand_img(IMGS_SOCIAL, context.user_data, "last_img_social")
        caption = f"{random.choice(replies)}\n\n{get_testimonial(lang)}"
        try:
            msg = await context.bot.send_photo(
                chat_id=cid, photo=img, caption=caption,
                parse_mode="Markdown", reply_markup=svc_keyboard(lang))
        except Exception:
            msg = await context.bot.send_message(
                chat_id=cid, text=caption,
                parse_mode="Markdown", reply_markup=svc_keyboard(lang))
        context.user_data["last_bot_msg_id"] = msg.message_id

    elif data == "svc_indicator":
        replies = get_replies(INDICATOR_REPLIES, lang)
        img = rand_img(IMGS_INDICATOR, context.user_data, "last_img_indicator")
        try:
            msg = await context.bot.send_photo(
                chat_id=cid, photo=img,
                caption=random.choice(replies),
                parse_mode="Markdown", reply_markup=svc_keyboard(lang, indicator=True))
        except Exception:
            msg = await context.bot.send_message(
                chat_id=cid, text=random.choice(replies),
                parse_mode="Markdown", reply_markup=svc_keyboard(lang, indicator=True))
        context.user_data["last_bot_msg_id"] = msg.message_id

    elif data == "svc_autobot":
        replies = get_replies(AUTOBOT_REPLIES, lang)
        img = rand_img(IMGS_AUTOBOT, context.user_data, "last_img_autobot")
        caption = f"{random.choice(replies)}\n\n{get_testimonial(lang)}"
        try:
            msg = await context.bot.send_photo(
                chat_id=cid, photo=img, caption=caption,
                parse_mode="Markdown", reply_markup=svc_keyboard(lang))
        except Exception:
            msg = await context.bot.send_message(
                chat_id=cid, text=caption,
                parse_mode="Markdown", reply_markup=svc_keyboard(lang))
        context.user_data["last_bot_msg_id"] = msg.message_id

    # ── Support ───────────────────────────────────────────────
    elif data == "do_support":
        await notify_support_request(context, user, lang)
        msg = await context.bot.send_message(
            chat_id=cid,
            text=ui("support_msg", lang),
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(ui("btn_back", lang), callback_data="main_menu")],
            ]),
        )
        context.user_data["last_bot_msg_id"] = msg.message_id

    # ── Referral ──────────────────────────────────────────────
    elif data == "do_referral":
        ref_count = get_referral_count(user.id)
        needed = max(0, REFERRAL_REWARD_COUNT - ref_count)
        ref_text = ui("referral_msg", lang).format(
            bot=BOT_USERNAME, uid=user.id,
            count=ref_count, needed=needed)
        msg = await context.bot.send_message(
            chat_id=cid,
            text=ref_text,
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(ui("btn_support", lang), callback_data="do_support")],
                [InlineKeyboardButton(ui("btn_back", lang), callback_data="main_menu")],
            ])
        )
        context.user_data["last_bot_msg_id"] = msg.message_id

    # ── Testimonials ──────────────────────────────────────────
    elif data == "do_testimonials":
        testimonial = get_testimonial(lang)
        text = ui("testimonials_msg", lang).format(testimonial=testimonial)
        img = rand_img(IMGS_SIGNALS, context.user_data, "last_img_test")
        try:
            msg = await context.bot.send_photo(
                chat_id=cid, photo=img, caption=text,
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton(ui("btn_website", lang), url=WEBSITE_URL)],
                    [InlineKeyboardButton(ui("btn_support", lang), callback_data="do_support")],
                    [InlineKeyboardButton(ui("btn_back", lang), callback_data="main_menu")],
                ]))
        except Exception:
            msg = await context.bot.send_message(
                chat_id=cid, text=text,
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton(ui("btn_back", lang), callback_data="main_menu")],
                ]))
        context.user_data["last_bot_msg_id"] = msg.message_id

    # ── Admin: Connect ────────────────────────────────────────
    elif data.startswith("con:"):
        parts = data.split(":")
        uid   = int(parts[1])
        ulang = parts[2] if len(parts) > 2 else "en"
        active_support[uid] = True
        try:
            await query.message.edit_reply_markup(reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🟢 Connected ✓", callback_data="noop"),
                InlineKeyboardButton("🔴 End Chat", callback_data=f"dis:{uid}:{ulang}"),
            ]]))
        except Exception:
            pass
        await query.message.reply_text(f"✅ Connected to user `{uid}`.", parse_mode="Markdown")
        connected_msgs = {
            "en": "🟢 *You are now connected to our support team!*\n\nPlease describe your issue and we will help you right away. 💬",
            "sw": "🟢 *Sasa umeunganishwa na timu yetu ya msaada!*\n\nTafadhali elezea tatizo lako. 💬",
        }
        try:
            await context.bot.send_chat_action(chat_id=uid, action=ChatAction.TYPING)
            await asyncio.sleep(1.5)
            await context.bot.send_message(
                chat_id=uid,
                text=connected_msgs.get(ulang, connected_msgs["en"]),
                parse_mode="Markdown")
        except Exception as e:
            logger.warning(f"Connect notify user failed: {e}")

    # ── Admin: Disconnect ─────────────────────────────────────
    elif data.startswith("dis:"):
        parts = data.split(":")
        uid   = int(parts[1])
        ulang = parts[2] if len(parts) > 2 else "en"
        active_support.pop(uid, None)
        try:
            await query.message.edit_reply_markup(reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🟢 Connect", callback_data=f"con:{uid}:{ulang}"),
                InlineKeyboardButton("🔴 Ended ✓", callback_data="noop"),
            ]]))
        except Exception:
            pass
        await query.message.reply_text(f"✅ Chat ended for user `{uid}`.", parse_mode="Markdown")
        disconnected_msgs = {
            "en": "👋 *Support chat has ended.*\n\nThank you for contacting us! If you need more help, tap *Contact Support* again. 😊",
            "sw": "👋 *Mazungumzo ya msaada yamekwisha.*\n\nAsante! Bonyeza *Wasiliana na Support* tena ukihitaji msaada. 😊",
        }
        try:
            await context.bot.send_chat_action(chat_id=uid, action=ChatAction.TYPING)
            await asyncio.sleep(1.5)
            await context.bot.send_message(
                chat_id=uid,
                text=disconnected_msgs.get(ulang, disconnected_msgs["en"]),
                parse_mode="Markdown")
        except Exception as e:
            logger.warning(f"Disconnect notify user failed: {e}")

    elif data == "end_all_support":
        count = len(active_support)
        active_support.clear()
        await query.message.reply_text(
            f"✅ Ended all *{count}* support session(s).",
            parse_mode="Markdown")

    elif data == "noop":
        pass

    # ── Admin approve/decline ─────────────────────────────────
    elif data.startswith("approve_"):
        uid = int(data[8:])
        req = pending_requests.get(uid)
        if req:
            try:
                await context.bot.approve_chat_join_request(chat_id=req["chat_id"], user_id=uid)
                pending_requests.pop(uid, None)
                await query.message.edit_text(
                    f"✅ *Approved!*\n👤 {req['user'].full_name} joined *{req['chat_title']}*.",
                    parse_mode="Markdown")
                try:
                    await context.bot.send_message(
                        chat_id=uid,
                        text=f"🎉 Your request to join *{req['chat_title']}* is *approved!* Welcome! 🚀",
                        parse_mode="Markdown")
                except Exception:
                    pass
            except TelegramError as e:
                await query.message.reply_text(f"❌ Error: {e}")
        else:
            await query.answer("⚠️ Request not found.", show_alert=True)

    elif data.startswith("decline_"):
        uid = int(data[8:])
        req = pending_requests.get(uid)
        if req:
            try:
                await context.bot.decline_chat_join_request(chat_id=req["chat_id"], user_id=uid)
                pending_requests.pop(uid, None)
                await query.message.edit_text(
                    f"❌ *Declined.*\n👤 {req['user'].full_name}'s request declined.",
                    parse_mode="Markdown")
                try:
                    await context.bot.send_message(
                        chat_id=uid,
                        text="😔 Your request was not approved. Contact support for help.")
                except Exception:
                    pass
            except TelegramError as e:
                await query.message.reply_text(f"❌ Error: {e}")
        else:
            await query.answer("⚠️ Request not found.", show_alert=True)

# ══════════════════════════════════════════════════════════════
#  TWO-WAY MESSAGING
# ══════════════════════════════════════════════════════════════

async def forward_to_admin(context, user, message):
    now = datetime.now().strftime("%d/%m/%Y %H:%M")
    header = (
        f"💬 *Message from user*\n"
        f"👤 {user.full_name} | @{user.username or 'N/A'}\n"
        f"🆔 `{user.id}` | 🕐 {now}\n"
        f"{'─'*28}\n"
        f"_(Reply to this message to respond)_"
    )
    for aid in ADMIN_IDS:
        try:
            hdr = await context.bot.send_message(
                chat_id=aid, text=header, parse_mode="Markdown")
            fwd = await context.bot.forward_message(
                chat_id=aid, from_chat_id=message.chat_id,
                message_id=message.message_id)
            reply_map[fwd.message_id] = user.id
            reply_map[hdr.message_id] = user.id
        except Exception as e:
            logger.warning(f"Forward failed: {e}")

async def handle_admin_reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message
    replied = message.reply_to_message
    if not replied:
        return

    target_uid = reply_map.get(replied.message_id)
    if not target_uid:
        return

    try:
        await context.bot.send_chat_action(chat_id=target_uid, action=ChatAction.TYPING)
        await asyncio.sleep(1.5)
    except Exception:
        pass

    try:
        if message.photo:
            await context.bot.send_photo(chat_id=target_uid, photo=message.photo[-1].file_id, caption=message.caption or "", parse_mode="Markdown")
        elif message.video:
            await context.bot.send_video(chat_id=target_uid, video=message.video.file_id, caption=message.caption or "", parse_mode="Markdown")
        elif message.voice:
            await context.bot.send_voice(chat_id=target_uid, voice=message.voice.file_id)
        elif message.document:
            await context.bot.send_document(chat_id=target_uid, document=message.document.file_id, caption=message.caption or "", parse_mode="Markdown")
        elif message.sticker:
            await context.bot.send_sticker(chat_id=target_uid, sticker=message.sticker.file_id)
        elif message.text:
            await context.bot.send_message(chat_id=target_uid, text=message.text, parse_mode="Markdown")
        await message.reply_text("✅ Delivered!")
    except Exception as e:
        await message.reply_text(f"❌ Failed: {e}")

# ══════════════════════════════════════════════════════════════
#  MAIN MESSAGE HANDLER
# ══════════════════════════════════════════════════════════════

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message
    if not message:
        return
    user = message.from_user
    lang = get_lang(context)
    cid  = message.chat_id

    # ── ADMIN messages ────────────────────────────────────────
    if is_admin(user.id):
        if message.reply_to_message:
            target = reply_map.get(message.reply_to_message.message_id)
            if target:
                await handle_admin_reply(update, context)
                return
        if message.photo and not message.reply_to_message:
            file_id = message.photo[-1].file_id
            await message.reply_text(
                f"📸 *Photo file\\_id:*\n\n`{file_id}`",
                parse_mode="Markdown")
            return
        return

    register_user(user)

    # Media from user
    if message.photo or message.video or message.voice or message.document or message.sticker:
        await forward_to_admin(context, user, message)
        if not active_support.get(user.id):
            await typing_action(cid, context, 1.0)
            await message.reply_text(ui("msg_received", lang))
        return

    if not message.text:
        return

    text = message.text.strip()
    low  = text.lower()

    # If in active support session — forward silently
    if active_support.get(user.id):
        await forward_to_admin(context, user, message)
        return

    # Forward text to admin
    await forward_to_admin(context, user, message)
    schedule_cooldown(context, cid, user.first_name, lang)
    await typing_action(cid, context, 1.8)

    old_id = context.user_data.get("last_bot_msg_id")
    if old_id:
        await safe_delete(context, cid, old_id)

    # ── Keyword routing ───────────────────────────────────────

    if any(w in low for w in [
        "hi","hello","hey","hujambo","habari","salaam","bonjour","hola",
        "привет","مرحبا","नमस्ते","こんにちは","olá","hallo","salam",
        "niaje","mambo","wassup","sup","ciao","你好","안녕","สวัสดี"
    ]) and not any(w in low for w in [
        "signal","vip","pocket","social","copy","indicator","auto","bot",
        "robot","support","help","price","cost","free","referral"
    ]):
        urgency = get_urgency(lang)
        welcome_text = random.choice(WELCOME.get(lang, WELCOME["en"])).format(
            name=user.first_name, business=BUSINESS_NAME)
        msg = await context.bot.send_message(
            chat_id=cid,
            text=f"{urgency}\n\n{welcome_text}",
            parse_mode="Markdown", reply_markup=main_menu(lang))
        context.user_data["last_bot_msg_id"] = msg.message_id

    elif any(w in low for w in [
        "signal","signals","vip","alert","alerts","ishara","dalili",
        "trade alert","live signal","trading signal","forex signal",
        "binary signal","call","put","entry","expiry","win rate"
    ]):
        img = rand_img(IMGS_SIGNALS, context.user_data, "last_img_signals")
        caption = f"{random.choice(get_replies(SIGNALS_REPLIES, lang))}\n\n{get_testimonial(lang)}"
        try:
            msg = await context.bot.send_photo(
                chat_id=cid, photo=img, caption=caption,
                parse_mode="Markdown", reply_markup=svc_keyboard(lang))
        except Exception:
            msg = await context.bot.send_message(
                chat_id=cid, text=caption,
                parse_mode="Markdown", reply_markup=svc_keyboard(lang))
        context.user_data["last_bot_msg_id"] = msg.message_id

    elif any(w in low for w in [
        "social","copy","pocket","copy trade","copy trading","social trading",
        "master trader","follow trader","auto copy","nakili"
    ]):
        img = rand_img(IMGS_SOCIAL, context.user_data, "last_img_social")
        caption = f"{random.choice(get_replies(SOCIAL_REPLIES, lang))}\n\n{get_testimonial(lang)}"
        try:
            msg = await context.bot.send_photo(
                chat_id=cid, photo=img, caption=caption,
                parse_mode="Markdown", reply_markup=svc_keyboard(lang))
        except Exception:
            msg = await context.bot.send_message(
                chat_id=cid, text=caption,
                parse_mode="Markdown", reply_markup=svc_keyboard(lang))
        context.user_data["last_bot_msg_id"] = msg.message_id

    elif any(w in low for w in [
        "indicator","chart","mt4","mt5","free indicator","kiashiria",
        "arrow","buy sell","technical","analysis","trend","template"
    ]):
        img = rand_img(IMGS_INDICATOR, context.user_data, "last_img_indicator")
        caption = random.choice(get_replies(INDICATOR_REPLIES, lang))
        try:
            msg = await context.bot.send_photo(
                chat_id=cid, photo=img, caption=caption,
                parse_mode="Markdown", reply_markup=svc_keyboard(lang, indicator=True))
        except Exception:
            msg = await context.bot.send_message(
                chat_id=cid, text=caption,
                parse_mode="Markdown", reply_markup=svc_keyboard(lang, indicator=True))
        context.user_data["last_bot_msg_id"] = msg.message_id

    elif any(w in low for w in [
        "auto","bot","robot","automatic","autobot","trading bot","binary bot",
        "automated","passive","earn while","quotex","deriv","olymp","binomo",
        "iq option","expert option","broker","license","leseni"
    ]):
        img = rand_img(IMGS_AUTOBOT, context.user_data, "last_img_autobot")
        caption = f"{random.choice(get_replies(AUTOBOT_REPLIES, lang))}\n\n{get_testimonial(lang)}"
        try:
            msg = await context.bot.send_photo(
                chat_id=cid, photo=img, caption=caption,
                parse_mode="Markdown", reply_markup=svc_keyboard(lang))
        except Exception:
            msg = await context.bot.send_message(
                chat_id=cid, text=caption,
                parse_mode="Markdown", reply_markup=svc_keyboard(lang))
        context.user_data["last_bot_msg_id"] = msg.message_id

    elif any(w in low for w in [
        "referral","refer","invite","earn","reward","link","kiungo","zawadi"
    ]):
        ref_count = get_referral_count(user.id)
        needed = max(0, REFERRAL_REWARD_COUNT - ref_count)
        ref_text = ui("referral_msg", lang).format(
            bot=BOT_USERNAME, uid=user.id,
            count=ref_count, needed=needed)
        msg = await context.bot.send_message(
            chat_id=cid, text=ref_text, parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(ui("btn_back", lang), callback_data="main_menu")],
            ]))
        context.user_data["last_bot_msg_id"] = msg.message_id

    elif any(w in low for w in [
        "price","cost","fee","how much","bei","pesa","pay","payment",
        "subscribe","plan","package","offer","bei gani","ngapi","nunua"
    ]):
        msg = await context.bot.send_message(
            chat_id=cid,
            text=ui("price_msg", lang).format(website=WEBSITE_URL),
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(ui("btn_website", lang), url=WEBSITE_URL)],
                [InlineKeyboardButton(ui("btn_support", lang), callback_data="do_support")],
                [InlineKeyboardButton(ui("btn_back", lang), callback_data="main_menu")],
            ]))
        context.user_data["last_bot_msg_id"] = msg.message_id

    elif any(w in low for w in [
        "support","help","assist","contact","agent","admin","msaada","wasiliana"
    ]):
        await notify_support_request(context, user, lang)
        msg = await context.bot.send_message(
            chat_id=cid,
            text=ui("support_msg", lang),
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(ui("btn_back", lang), callback_data="main_menu")],
            ]))
        context.user_data["last_bot_msg_id"] = msg.message_id

    elif any(w in low for w in [
        "thank","thanks","asante","merci","gracias","спасибо","شكرا","danke"
    ]):
        msg = await context.bot.send_message(
            chat_id=cid,
            text=ui("thanks_msg", lang).format(name=user.first_name),
            parse_mode="Markdown")
        context.user_data["last_bot_msg_id"] = msg.message_id

    else:
        msg = await context.bot.send_message(
            chat_id=cid,
            text=ui("fallback_msg", lang),
            parse_mode="Markdown",
            reply_markup=main_menu(lang))
        context.user_data["last_bot_msg_id"] = msg.message_id

# ══════════════════════════════════════════════════════════════
#  MAIN
# ══════════════════════════════════════════════════════════════

def main():
    init_db()
    app = Application.builder().token(BOT_TOKEN).build()

    # Schedule daily stats at 8:00 AM
    app.job_queue.run_daily(
        daily_stats_job,
        time=datetime.strptime("08:00", "%H:%M").time(),
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("broadcast", broadcast_command))
    app.add_handler(CommandHandler("stats", stats_command))
    app.add_handler(CommandHandler("getid", getid_command))
    app.add_handler(CommandHandler("sessions", support_sessions_command))
    app.add_handler(MessageHandler(
        filters.PHOTO & filters.Caption(["/getid"]) & filters.User(ADMIN_IDS),
        getid_command))
    app.add_handler(ChatJoinRequestHandler(handle_join_request))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, handle_message))

    print(f"✅ {BUSINESS_NAME} Bot v5.0 is LIVE!")
    print("📋 Commands: /broadcast  /stats  /getid  /sessions")
    print("🆕 New features: Referral system | Urgency | Testimonials | Welcome bonus | Daily stats")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
