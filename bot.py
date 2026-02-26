import os
import json
import asyncio
import logging
from datetime import datetime, date
import pytz
import httpx
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TOKEN = os.environ.get("BOT_TOKEN")
TIMEZONE = pytz.timezone("Asia/Jakarta")
CITY = "Bekasi"
COUNTRY = "ID"

PRAYERS = ["Subuh", "Dzuhur", "Ashar", "Maghrib", "Isya"]
PRAYER_EMOJI = {"Subuh": "🌅", "Dzuhur": "☀️", "Ashar": "🌤️", "Maghrib": "🌇", "Isya": "🌙"}

# Simple file-based storage
DATA_FILE = "prayer_data.json"

def load_data():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r") as f:
            return json.load(f)
    return {}

def save_data(data):
    with open(DATA_FILE, "w") as f:
        json.dump(data, f)

def get_user_data(data, user_id, today):
    uid = str(user_id)
    if uid not in data:
        data[uid] = {}
    if today not in data[uid]:
        data[uid][today] = {p: False for p in PRAYERS}
    return data[uid][today]

async def get_prayer_times():
    today = date.today()
    url = f"https://api.aladhan.com/v1/timingsByCity/{today.day}-{today.month}-{today.year}?city={CITY}&country={COUNTRY}&method=11"
    async with httpx.AsyncClient() as client:
        r = await client.get(url, timeout=10)
        timings = r.json()["data"]["timings"]
    return {
        "Subuh": timings["Fajr"],
        "Dzuhur": timings["Dhuhr"],
        "Ashar": timings["Asr"],
        "Maghrib": timings["Maghrib"],
        "Isya": timings["Isha"],
    }

def build_tracker_keyboard(prayer_status):
    keyboard = []
    for prayer, done in prayer_status.items():
        emoji = PRAYER_EMOJI[prayer]
        status = "✅" if done else "⬜"
        keyboard.append([InlineKeyboardButton(
            f"{status} {emoji} {prayer}",
            callback_data=f"toggle_{prayer}"
        )])
    keyboard.append([InlineKeyboardButton("🔄 Refresh", callback_data="refresh")])
    return InlineKeyboardMarkup(keyboard)

def build_tracker_text(prayer_status, prayer_times):
    today = datetime.now(TIMEZONE).strftime("%A, %d %B %Y")
    done_count = sum(prayer_status.values())
    text = f"🕌 *Tracker Solat — {today}*\n"
    text += f"📍 {CITY} | ✅ {done_count}/5 solat\n\n"
    text += "*Jadwal & Status Hari Ini:*\n"
    for prayer in PRAYERS:
        emoji = PRAYER_EMOJI[prayer]
        status = "✅" if prayer_status[prayer] else "⬜"
        time = prayer_times.get(prayer, "-")
        text += f"{status} {emoji} *{prayer}* — {time}\n"
    text += "\nTap tombol di bawah untuk tandai sudah solat 👇"
    return text

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Assalamu'alaikum! 🕌\n\n"
        "Aku bot tracker solat kamu.\n\n"
        "Perintah yang tersedia:\n"
        "/solat — lihat tracker & tandai solat\n"
        "/jadwal — lihat jadwal solat hari ini\n"
        "/rekap — rekap solat hari ini\n\n"
        "Semoga istiqomah! 🤲"
    )

async def show_tracker(update: Update, context: ContextTypes.DEFAULT_TYPE):
    today = date.today().isoformat()
    data = load_data()
    user_id = update.effective_user.id
    prayer_status = get_user_data(data, user_id, today)
    
    try:
        prayer_times = await get_prayer_times()
    except Exception:
        prayer_times = {}

    text = build_tracker_text(prayer_status, prayer_times)
    keyboard = build_tracker_keyboard(prayer_status)
    
    if update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=keyboard, parse_mode="Markdown")
    else:
        await update.message.reply_text(text, reply_markup=keyboard, parse_mode="Markdown")

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    today = date.today().isoformat()
    data = load_data()
    user_id = update.effective_user.id
    prayer_status = get_user_data(data, user_id, today)
    
    if query.data.startswith("toggle_"):
        prayer = query.data.replace("toggle_", "")
        if prayer in PRAYERS:
            prayer_status[prayer] = not prayer_status[prayer]
            save_data(data)
    
    await show_tracker(update, context)

async def jadwal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        times = await get_prayer_times()
        today = datetime.now(TIMEZONE).strftime("%d %B %Y")
        text = f"🕌 *Jadwal Solat {CITY}*\n📅 {today}\n\n"
        for prayer in PRAYERS:
            emoji = PRAYER_EMOJI[prayer]
            text += f"{emoji} *{prayer}*: {times.get(prayer, '-')}\n"
        await update.message.reply_text(text, parse_mode="Markdown")
    except Exception:
        await update.message.reply_text("Gagal ambil jadwal solat. Coba lagi nanti.")

async def rekap(update: Update, context: ContextTypes.DEFAULT_TYPE):
    today = date.today().isoformat()
    data = load_data()
    user_id = update.effective_user.id
    prayer_status = get_user_data(data, user_id, today)
    
    done = [p for p, v in prayer_status.items() if v]
    missed = [p for p, v in prayer_status.items() if not v]
    
    text = f"📊 *Rekap Solat Hari Ini*\n\n"
    text += f"✅ Sudah solat ({len(done)}): {', '.join(done) if done else '-'}\n"
    text += f"⬜ Belum solat ({len(missed)}): {', '.join(missed) if missed else '-'}\n\n"
    
    if len(done) == 5:
        text += "MasyaAllah, solat hari ini lengkap! 🎉🤲"
    elif len(done) >= 3:
        text += "Semangat, masih ada waktu untuk solat yang tertinggal! 💪"
    else:
        text += "Yuk kejar solat yang belum! Semoga Allah mudahkan 🤲"
    
    await update.message.reply_text(text, parse_mode="Markdown")

async def send_prayer_reminder(context: ContextTypes.DEFAULT_TYPE):
    prayer_name = context.job.data["prayer"]
    chat_id = context.job.data["chat_id"]
    emoji = PRAYER_EMOJI[prayer_name]
    await context.bot.send_message(
        chat_id=chat_id,
        text=f"{emoji} Waktunya *{prayer_name}*! 🕌\n\nJangan lupa solat ya. Ketik /solat untuk tandai. 🤲",
        parse_mode="Markdown"
    )

async def setup_reminders(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        times = await get_prayer_times()
        chat_id = update.effective_chat.id
        now = datetime.now(TIMEZONE)
        
        # Remove existing jobs for this chat
        current_jobs = context.job_queue.get_jobs_by_name(str(chat_id))
        for job in current_jobs:
            job.schedule_removal()
        
        scheduled = []
        for prayer, time_str in times.items():
            hour, minute = map(int, time_str.split(":"))
            prayer_time = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            
            if prayer_time > now:
                context.job_queue.run_once(
                    send_prayer_reminder,
                    when=prayer_time,
                    data={"prayer": prayer, "chat_id": chat_id},
                    name=str(chat_id)
                )
                scheduled.append(f"{PRAYER_EMOJI[prayer]} {prayer} ({time_str})")
        
        if scheduled:
            text = "✅ Pengingat solat aktif untuk hari ini!\n\n" + "\n".join(scheduled)
        else:
            text = "Semua waktu solat hari ini sudah lewat. Coba lagi besok!"
        
        await update.message.reply_text(text)
    except Exception as e:
        await update.message.reply_text("Gagal setup pengingat. Coba lagi nanti.")

def main():
    app = Application.builder().token(TOKEN).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("solat", show_tracker))
    app.add_handler(CommandHandler("jadwal", jadwal))
    app.add_handler(CommandHandler("rekap", rekap))
    app.add_handler(CommandHandler("ingatkan", setup_reminders))
    app.add_handler(CallbackQueryHandler(handle_callback))
    
    logger.info("Bot started!")
    app.run_polling()

if __name__ == "__main__":
    main()
