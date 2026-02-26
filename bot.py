import os
import json
import logging
from datetime import datetime, date, time
import pytz
import httpx
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes, MessageHandler, filters, ConversationHandler

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TOKEN = os.environ.get("BOT_TOKEN")
TIMEZONE = pytz.timezone("Asia/Jakarta")

PRAYERS = ["Subuh", "Dzuhur", "Ashar", "Maghrib", "Isya"]
PRAYER_EMOJI = {"Subuh": "🌅", "Dzuhur": "☀️", "Ashar": "🌤️", "Maghrib": "🌇", "Isya": "🌙"}

DATA_FILE = "prayer_data.json"

WAITING_AYAT = 1
SURAH_PER_PAGE = 10

SURAH_NAMES = {
    1:"Al-Fatihah",2:"Al-Baqarah",3:"Ali 'Imran",4:"An-Nisa",5:"Al-Ma'idah",
    6:"Al-An'am",7:"Al-A'raf",8:"Al-Anfal",9:"At-Tawbah",10:"Yunus",
    11:"Hud",12:"Yusuf",13:"Ar-Ra'd",14:"Ibrahim",15:"Al-Hijr",
    16:"An-Nahl",17:"Al-Isra",18:"Al-Kahf",19:"Maryam",20:"Ta-Ha",
    21:"Al-Anbiya",22:"Al-Hajj",23:"Al-Mu'minun",24:"An-Nur",25:"Al-Furqan",
    26:"Ash-Shu'ara",27:"An-Naml",28:"Al-Qasas",29:"Al-Ankabut",30:"Ar-Rum",
    31:"Luqman",32:"As-Sajdah",33:"Al-Ahzab",34:"Saba",35:"Fatir",
    36:"Ya-Sin",37:"As-Saffat",38:"Sad",39:"Az-Zumar",40:"Ghafir",
    41:"Fussilat",42:"Ash-Shura",43:"Az-Zukhruf",44:"Ad-Dukhan",45:"Al-Jathiyah",
    46:"Al-Ahqaf",47:"Muhammad",48:"Al-Fath",49:"Al-Hujurat",50:"Qaf",
    51:"Adh-Dhariyat",52:"At-Tur",53:"An-Najm",54:"Al-Qamar",55:"Ar-Rahman",
    56:"Al-Waqi'ah",57:"Al-Hadid",58:"Al-Mujadila",59:"Al-Hashr",60:"Al-Mumtahanah",
    61:"As-Saf",62:"Al-Jumu'ah",63:"Al-Munafiqun",64:"At-Taghabun",65:"At-Talaq",
    66:"At-Tahrim",67:"Al-Mulk",68:"Al-Qalam",69:"Al-Haqqah",70:"Al-Ma'arij",
    71:"Nuh",72:"Al-Jinn",73:"Al-Muzzammil",74:"Al-Muddaththir",75:"Al-Qiyamah",
    76:"Al-Insan",77:"Al-Mursalat",78:"An-Naba",79:"An-Nazi'at",80:"Abasa",
    81:"At-Takwir",82:"Al-Infitar",83:"Al-Mutaffifin",84:"Al-Inshiqaq",85:"Al-Buruj",
    86:"At-Tariq",87:"Al-A'la",88:"Al-Ghashiyah",89:"Al-Fajr",90:"Al-Balad",
    91:"Ash-Shams",92:"Al-Layl",93:"Ad-Duha",94:"Ash-Sharh",95:"At-Tin",
    96:"Al-Alaq",97:"Al-Qadr",98:"Al-Bayyinah",99:"Az-Zalzalah",100:"Al-Adiyat",
    101:"Al-Qari'ah",102:"At-Takathur",103:"Al-Asr",104:"Al-Humazah",105:"Al-Fil",
    106:"Quraysh",107:"Al-Ma'un",108:"Al-Kawthar",109:"Al-Kafirun",110:"An-Nasr",
    111:"Al-Masad",112:"Al-Ikhlas",113:"Al-Falaq",114:"An-Nas"
}

# ── Storage ───────────────────────────────────────────────────────────────────

def load_data():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r") as f:
            return json.load(f)
    return {}

def save_data(data):
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=2)

def get_user(data, user_id):
    uid = str(user_id)
    if uid not in data:
        data[uid] = {}
    return data[uid]

def get_prayer_status(data, user_id, today):
    user = get_user(data, user_id)
    if "prayers" not in user:
        user["prayers"] = {}
    if today not in user["prayers"]:
        user["prayers"][today] = {p: False for p in PRAYERS}
    return user["prayers"][today]

# ── Prayer Times API ──────────────────────────────────────────────────────────

async def get_prayer_times(lat=None, lon=None, city="Bekasi", country="ID"):
    today = date.today()
    if lat and lon:
        url = f"https://api.aladhan.com/v1/timings/{today.day}-{today.month}-{today.year}?latitude={lat}&longitude={lon}&method=11"
    else:
        url = f"https://api.aladhan.com/v1/timingsByCity/{today.day}-{today.month}-{today.year}?city={city}&country={country}&method=11"
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

async def get_city_name(lat, lon):
    try:
        url = f"https://nominatim.openstreetmap.org/reverse?lat={lat}&lon={lon}&format=json"
        async with httpx.AsyncClient(headers={"User-Agent": "SolatBot/1.0"}) as client:
            r = await client.get(url, timeout=10)
            addr = r.json().get("address", {})
            return addr.get("city") or addr.get("town") or addr.get("county") or "Lokasi kamu"
    except Exception:
        return "Lokasi kamu"

# ── Prayer Tracker ────────────────────────────────────────────────────────────

def build_tracker_keyboard(prayer_status):
    keyboard = []
    for prayer, done in prayer_status.items():
        emoji = PRAYER_EMOJI[prayer]
        status = "✅" if done else "⬜"
        keyboard.append([InlineKeyboardButton(f"{status} {emoji} {prayer}", callback_data=f"toggle_{prayer}")])
    keyboard.append([InlineKeyboardButton("🔄 Refresh", callback_data="refresh")])
    return InlineKeyboardMarkup(keyboard)

def build_tracker_text(prayer_status, prayer_times, city_name=""):
    today = datetime.now(TIMEZONE).strftime("%A, %d %B %Y")
    done_count = sum(prayer_status.values())
    loc = f"📍 {city_name} | " if city_name else ""
    text = f"🕌 *Tracker Solat — {today}*\n{loc}✅ {done_count}/5 solat\n\n"
    text += "*Jadwal & Status Hari Ini:*\n"
    for prayer in PRAYERS:
        emoji = PRAYER_EMOJI[prayer]
        status = "✅" if prayer_status[prayer] else "⬜"
        t = prayer_times.get(prayer, "-")
        text += f"{status} {emoji} *{prayer}* — {t}\n"
    text += "\nTap tombol di bawah untuk tandai sudah solat 👇"
    return text

async def show_tracker(update: Update, context: ContextTypes.DEFAULT_TYPE):
    today = date.today().isoformat()
    data = load_data()
    user_id = update.effective_user.id
    user = get_user(data, user_id)
    prayer_status = get_prayer_status(data, user_id, today)

    lat = user.get("lat")
    lon = user.get("lon")
    city_name = user.get("city_name", "Bekasi")

    try:
        prayer_times = await get_prayer_times(lat, lon, city=city_name if not lat else "Bekasi")
    except Exception:
        prayer_times = {}

    text = build_tracker_text(prayer_status, prayer_times, city_name)
    keyboard = build_tracker_keyboard(prayer_status)

    if update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=keyboard, parse_mode="Markdown")
    else:
        await update.message.reply_text(text, reply_markup=keyboard, parse_mode="Markdown")

# ── Location ──────────────────────────────────────────────────────────────────

async def ask_location(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = ReplyKeyboardMarkup(
        [[KeyboardButton("📍 Kirim Lokasi Saya", request_location=True)]],
        resize_keyboard=True, one_time_keyboard=True
    )
    await update.message.reply_text(
        "Kirim lokasi kamu biar jadwal solatnya akurat ya! 📍\n\nTap tombol di bawah 👇",
        reply_markup=keyboard
    )

async def handle_location(update: Update, context: ContextTypes.DEFAULT_TYPE):
    location = update.message.location
    lat, lon = location.latitude, location.longitude
    data = load_data()
    user = get_user(data, update.effective_user.id)
    city_name = await get_city_name(lat, lon)
    user["lat"] = lat
    user["lon"] = lon
    user["city_name"] = city_name
    save_data(data)
    await update.message.reply_text(
        f"✅ Lokasi tersimpan! Terdeteksi: *{city_name}*\n\nJadwal solat kamu sekarang otomatis menyesuaikan lokasimu 🎉",
        reply_markup=ReplyKeyboardRemove(),
        parse_mode="Markdown"
    )

# ── Jadwal & Rekap ────────────────────────────────────────────────────────────

async def jadwal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = load_data()
    user = get_user(data, update.effective_user.id)
    lat = user.get("lat")
    lon = user.get("lon")
    city_name = user.get("city_name", "Bekasi")
    try:
        times = await get_prayer_times(lat, lon, city=city_name if not lat else "Bekasi")
        today = datetime.now(TIMEZONE).strftime("%d %B %Y")
        text = f"🕌 *Jadwal Solat {city_name}*\n📅 {today}\n\n"
        for prayer in PRAYERS:
            text += f"{PRAYER_EMOJI[prayer]} *{prayer}*: {times.get(prayer, '-')}\n"
        await update.message.reply_text(text, parse_mode="Markdown")
    except Exception:
        await update.message.reply_text("Gagal ambil jadwal. Coba lagi nanti.")

async def rekap(update: Update, context: ContextTypes.DEFAULT_TYPE):
    today = date.today().isoformat()
    data = load_data()
    prayer_status = get_prayer_status(data, update.effective_user.id, today)
    done = [p for p, v in prayer_status.items() if v]
    missed = [p for p, v in prayer_status.items() if not v]
    text = "📊 *Rekap Solat Hari Ini*\n\n"
    text += f"✅ Sudah ({len(done)}): {', '.join(done) if done else '-'}\n"
    text += f"⬜ Belum ({len(missed)}): {', '.join(missed) if missed else '-'}\n\n"
    if len(done) == 5:
        text += "MasyaAllah, solat hari ini lengkap! 🎉🤲"
    elif len(done) >= 3:
        text += "Semangat, masih ada waktu untuk yang tertinggal! 💪"
    else:
        text += "Yuk kejar solat yang belum! Semoga Allah mudahkan 🤲"
    await update.message.reply_text(text, parse_mode="Markdown")

# ── Pengingat Solat ───────────────────────────────────────────────────────────

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
    data = load_data()
    user = get_user(data, update.effective_user.id)
    lat = user.get("lat")
    lon = user.get("lon")
    city_name = user.get("city_name", "Bekasi")
    try:
        times = await get_prayer_times(lat, lon, city=city_name if not lat else "Bekasi")
        chat_id = update.effective_chat.id
        now = datetime.now(TIMEZONE)
        for job in context.job_queue.get_jobs_by_name(str(chat_id)):
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
        text = "✅ Pengingat solat aktif!\n\n" + "\n".join(scheduled) if scheduled else "Semua waktu solat hari ini sudah lewat."
        await update.message.reply_text(text)
    except Exception:
        await update.message.reply_text("Gagal setup pengingat. Coba lagi nanti.")

# ── Al-Quran Tracker ──────────────────────────────────────────────────────────

def build_surah_keyboard(page=0):
    start = page * SURAH_PER_PAGE + 1
    end = min(start + SURAH_PER_PAGE, 115)
    keyboard = []
    row = []
    for i in range(start, end):
        name = SURAH_NAMES[i]
        short = name[:13] + "…" if len(name) > 13 else name
        row.append(InlineKeyboardButton(f"{i}. {short}", callback_data=f"surah_{i}"))
        if len(row) == 2:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)

    nav = []
    total_pages = (114 + SURAH_PER_PAGE - 1) // SURAH_PER_PAGE
    if page > 0:
        nav.append(InlineKeyboardButton("⬅️ Prev", callback_data=f"qpage_{page-1}"))
    nav.append(InlineKeyboardButton(f"{page+1}/{total_pages}", callback_data="noop"))
    if end < 115:
        nav.append(InlineKeyboardButton("Next ➡️", callback_data=f"qpage_{page+1}"))
    keyboard.append(nav)
    keyboard.append([InlineKeyboardButton("❌ Batal", callback_data="qcancel")])
    return InlineKeyboardMarkup(keyboard)

async def quran(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = load_data()
    user = get_user(data, update.effective_user.id)
    quran_data = user.get("quran", {})
    last = quran_data.get("last_read")
    target = quran_data.get("daily_target", 0)
    reminder = quran_data.get("reminder", None)

    text = "📖 *Al-Quran Tracker*\n\n"
    if last:
        surah_num = last["surah"]
        surah_name = SURAH_NAMES.get(surah_num, f"Surah {surah_num}")
        text += f"📌 *Terakhir baca:*\nSurah {surah_num}. {surah_name}, Ayat {last['ayat']}\n"
        text += f"🕐 {last.get('updated_at', '')}\n\n"
    else:
        text += "Belum ada data bacaan.\n\n"
    if target:
        text += f"🎯 *Target harian:* {target} halaman\n"
    if reminder:
        text += f"⏰ *Pengingat baca:* {reminder}\n"

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📝 Update Posisi Baca", callback_data="qpage_0")],
    ])
    await update.message.reply_text(text, reply_markup=keyboard, parse_mode="Markdown")

# ── Conversation: pilih surah → ketik ayat ───────────────────────────────────

async def show_surah_page(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Entry point & navigasi halaman surah."""
    query = update.callback_query
    await query.answer()

    if query.data == "qcancel":
        await query.edit_message_text("❌ Dibatalkan.")
        return ConversationHandler.END

    if query.data == "noop":
        return WAITING_AYAT if context.user_data.get("selected_surah") else 0

    # qpage_N
    page = int(query.data.replace("qpage_", ""))
    total_pages = (114 + SURAH_PER_PAGE - 1) // SURAH_PER_PAGE
    text = f"📖 *Pilih Surah* (hal. {page+1}/{total_pages})\n\nKamu berhenti baca di surah mana?"
    await query.edit_message_text(text, reply_markup=build_surah_keyboard(page), parse_mode="Markdown")
    return 0  # state: pilih surah

async def surah_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Callback saat surah dipilih."""
    query = update.callback_query
    await query.answer()

    if query.data == "qcancel":
        await query.edit_message_text("❌ Dibatalkan.")
        return ConversationHandler.END

    surah_num = int(query.data.replace("surah_", ""))
    context.user_data["selected_surah"] = surah_num
    surah_name = SURAH_NAMES.get(surah_num, f"Surah {surah_num}")

    await query.edit_message_text(
        f"📖 Surah dipilih: *{surah_num}. {surah_name}*\n\n"
        f"Sekarang ketik nomor *ayat* terakhir yang kamu baca 👇\n\n"
        f"_(Ketik /batal untuk membatalkan)_",
        parse_mode="Markdown"
    )
    return WAITING_AYAT

async def receive_ayat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Terima input ayat dari user."""
    try:
        ayat = int(update.message.text.strip())
        if ayat < 1:
            raise ValueError
    except ValueError:
        await update.message.reply_text("Nomor ayat harus angka ya. Contoh ketik: `5`", parse_mode="Markdown")
        return WAITING_AYAT

    surah_num = context.user_data.get("selected_surah")
    if not surah_num:
        await update.message.reply_text("Terjadi kesalahan. Coba ketik /quran lagi.")
        return ConversationHandler.END

    data = load_data()
    user = get_user(data, update.effective_user.id)
    if "quran" not in user:
        user["quran"] = {}
    user["quran"]["last_read"] = {
        "surah": surah_num,
        "ayat": ayat,
        "updated_at": datetime.now(TIMEZONE).strftime("%d/%m/%Y %H:%M")
    }
    save_data(data)

    surah_name = SURAH_NAMES.get(surah_num, f"Surah {surah_num}")
    await update.message.reply_text(
        f"✅ Tersimpan!\n\n📌 *Posisi terakhir:*\nSurah {surah_num}. {surah_name}, Ayat {ayat}\n\nSemoga istiqomah! 🤲",
        parse_mode="Markdown"
    )
    return ConversationHandler.END

async def batal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ Dibatalkan.")
    return ConversationHandler.END

# ── Target & Pengingat Quran ──────────────────────────────────────────────────

async def target_quran(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if not args:
        await update.message.reply_text("Format: `/target_quran [halaman]`\nContoh: `/target_quran 5`", parse_mode="Markdown")
        return
    try:
        target = int(args[0])
    except ValueError:
        await update.message.reply_text("Target harus berupa angka.", parse_mode="Markdown")
        return
    data = load_data()
    user = get_user(data, update.effective_user.id)
    if "quran" not in user:
        user["quran"] = {}
    user["quran"]["daily_target"] = target
    save_data(data)
    await update.message.reply_text(
        f"✅ Target harian tersimpan: *{target} halaman/hari*\n\nSemangat khatam! 📖🤲",
        parse_mode="Markdown"
    )

async def send_quran_reminder(context: ContextTypes.DEFAULT_TYPE):
    chat_id = context.job.data["chat_id"]
    data = load_data()
    user = get_user(data, chat_id)
    quran_data = user.get("quran", {})
    last = quran_data.get("last_read")
    target = quran_data.get("daily_target", 0)
    text = "📖 Waktunya baca Al-Quran! 🤲\n\n"
    if last:
        surah_num = last["surah"]
        surah_name = SURAH_NAMES.get(surah_num, f"Surah {surah_num}")
        text += f"Lanjut dari: *Surah {surah_num}. {surah_name}, Ayat {last['ayat']}*\n"
    if target:
        text += f"Target hari ini: *{target} halaman*\n"
    text += "\nSetelah baca, ketik /quran untuk update posisi 📌"
    await context.bot.send_message(chat_id=chat_id, text=text, parse_mode="Markdown")

async def ingatkan_quran(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if not args:
        await update.message.reply_text("Format: `/ingatkan_quran 20:00`", parse_mode="Markdown")
        return
    try:
        hour, minute = map(int, args[0].split(":"))
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            raise ValueError
    except ValueError:
        await update.message.reply_text("Format jam salah. Contoh: `/ingatkan_quran 20:00`", parse_mode="Markdown")
        return
    data = load_data()
    user = get_user(data, update.effective_user.id)
    if "quran" not in user:
        user["quran"] = {}
    user["quran"]["reminder"] = f"{hour:02d}:{minute:02d}"
    save_data(data)
    chat_id = update.effective_chat.id
    for job in context.job_queue.get_jobs_by_name(f"quran_{chat_id}"):
        job.schedule_removal()
    context.job_queue.run_daily(
        send_quran_reminder,
        time=time(hour=hour, minute=minute, tzinfo=TIMEZONE),
        data={"chat_id": chat_id},
        name=f"quran_{chat_id}"
    )
    await update.message.reply_text(
        f"✅ Pengingat baca Quran diset jam *{hour:02d}:{minute:02d}* setiap hari! 📖\n\nSemoga istiqomah! 🤲",
        parse_mode="Markdown"
    )

# ── Start ─────────────────────────────────────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Assalamu'alaikum! 🕌\n\n"
        "Aku asisten ibadah harianmu.\n\n"
        "*📍 Setup Lokasi:*\n"
        "/lokasi — kirim lokasi biar jadwal solat akurat\n\n"
        "*🕌 Solat:*\n"
        "/solat — tracker & tandai solat\n"
        "/jadwal — jadwal solat hari ini\n"
        "/rekap — rekap solat hari ini\n"
        "/ingatkan — notif otomatis tiap waktu solat\n\n"
        "*📖 Al-Quran:*\n"
        "/quran — lihat & update posisi baca\n"
        "/target\_quran [halaman] — set target harian\n"
        "/ingatkan\_quran [jam:menit] — pengingat baca Quran\n\n"
        "Semoga istiqomah! 🤲",
        parse_mode="Markdown"
    )

# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    app = Application.builder().token(TOKEN).build()

    # Conversation handler untuk alur: pilih surah → ketik ayat
    quran_conv = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(show_surah_page, pattern="^qpage_"),
        ],
        states={
            0: [
                CallbackQueryHandler(show_surah_page, pattern="^qpage_"),
                CallbackQueryHandler(surah_selected, pattern="^surah_"),
                CallbackQueryHandler(batal, pattern="^qcancel$"),
            ],
            WAITING_AYAT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_ayat),
            ],
        },
        fallbacks=[
            CommandHandler("batal", batal),
            CallbackQueryHandler(batal, pattern="^qcancel$"),
        ],
        per_message=False,
        allow_reentry=True,
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("lokasi", ask_location))
    app.add_handler(CommandHandler("solat", show_tracker))
    app.add_handler(CommandHandler("jadwal", jadwal))
    app.add_handler(CommandHandler("rekap", rekap))
    app.add_handler(CommandHandler("ingatkan", setup_reminders))
    app.add_handler(CommandHandler("quran", quran))
    app.add_handler(CommandHandler("target_quran", target_quran))
    app.add_handler(CommandHandler("ingatkan_quran", ingatkan_quran))
    app.add_handler(CommandHandler("batal", batal))
    app.add_handler(quran_conv)

    # Handler untuk solat tracker (toggle & refresh)
    app.add_handler(CallbackQueryHandler(
        lambda u, c: show_tracker(u, c),
        pattern="^(toggle_|refresh)"
    ))

    app.add_handler(MessageHandler(filters.LOCATION, handle_location))

    logger.info("Bot started!")
    app.run_polling()

if __name__ == "__main__":
    main()
