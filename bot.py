import asyncio
import html
import logging
import os
import re
from datetime import datetime, timedelta

from aiogram import Bot, Dispatcher, F
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    Message, CallbackQuery,
    InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton,
    BotCommand
)
from aiohttp import web

from database import (
    get_user, create_user, update_user, delete_user,
    add_schedule, get_schedule, delete_schedule, get_today_schedule_by_week, DAYS,
    LESSON_TYPES, WEEK_TYPES,
    add_task, get_tasks, complete_task, delete_task,
    add_reminder, get_user_reminders,
    get_settings, update_settings,
    is_admin, get_all_users, set_admin, get_stats
)
from scheduler import setup_scheduler
from weather import (
    UZ_CITIES, fetch_weather, geocode_city,
    format_current_weather, format_forecast_5day, format_hourly_today
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_IDS = list(map(int, os.getenv("ADMIN_IDS", "").split(","))) if os.getenv("ADMIN_IDS") else []

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN topilmadi")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())


class RegisterState(StatesGroup):
    full_name = State()
    role_type = State()
    organization = State()


class ScheduleState(StatesGroup):
    day = State()
    subject = State()
    lesson_type = State()
    week_type = State()
    room = State()
    group_name = State()
    start_time = State()
    end_time = State()


class TaskState(StatesGroup):
    title = State()
    description = State()
    due_date = State()


class ReminderState(StatesGroup):
    title = State()
    date = State()
    time = State()
    repeat = State()


class SettingsState(StatesGroup):
    morning_time = State()
    evening_time = State()


class WeatherState(StatesGroup):
    city_input = State()


class AdminState(StatesGroup):
    broadcast_text = State()
    set_admin_id = State()


# ──────────────────────────────────────────
# YORDAMCHI FUNKSIYALAR
# ──────────────────────────────────────────

def normalize_full_name(text: str) -> str:
    return " ".join((text or "").strip().split())


def is_valid_full_name(text: str) -> bool:
    if not text:
        return False

    text = normalize_full_name(text)
    if len(text) < 5 or len(text) > 60:
        return False

    parts = text.split()
    if len(parts) < 2:
        return False

    for part in parts:
        if len(part) < 2:
            return False

    if not re.fullmatch(r"[A-Za-zÀ-ÿА-Яа-яҒғҚқҲҳЎўЁёʼ'`\-\s]+", text):
        return False

    lowered = text.lower()
    banned_words = {
        "test", "asd", "qwerty", "admin", "user",
        "nickname", "nik", "name", "familiya", "ism"
    }
    if lowered in banned_words:
        return False

    if any(ch.isdigit() for ch in text):
        return False

    return True


def get_display_username(username: str | None) -> str:
    return f"@{username}" if username else "—"


def escape_html(text: str | None) -> str:
    return html.escape(str(text or "—"))


def safe_text(text: str | None, limit: int | None = None) -> str:
    value = str(text or "—")
    if limit and len(value) > limit:
        value = value[:limit - 1] + "…"
    return escape_html(value)


def split_long_message(text: str, chunk_size: int = 3500) -> list[str]:
    if len(text) <= chunk_size:
        return [text]

    chunks = []
    current = ""
    for line in text.splitlines(True):
        if len(current) + len(line) > chunk_size:
            if current:
                chunks.append(current)
                current = ""
        if len(line) > chunk_size:
            for i in range(0, len(line), chunk_size):
                part = line[i:i + chunk_size]
                if current:
                    chunks.append(current)
                    current = ""
                chunks.append(part)
        else:
            current += line
    if current:
        chunks.append(current)
    return chunks


def format_broadcast_error(exc: Exception) -> str:
    err = str(exc).strip()
    low = err.lower()
    if "bot was blocked by the user" in low:
        return "bot foydalanuvchi tomonidan bloklangan"
    if "user is deactivated" in low:
        return "foydalanuvchi akkaunti o‘chirilgan"
    if "chat not found" in low:
        return "chat topilmadi"
    if "forbidden" in low:
        return "ruxsat yo‘q / foydalanuvchi botni to‘xtatgan"
    if "too many requests" in low:
        return "Telegram limitiga urildi"
    return err[:300] if err else "noma’lum xatolik"


def is_removable_user_error(exc: Exception) -> bool:
    low = str(exc).lower()
    removable_patterns = [
        "bot was blocked by the user",
        "user is deactivated",
        "chat not found",
        "user not found",
        "forbidden: bot was blocked",
    ]
    return any(p in low for p in removable_patterns)


# ──────────────────────────────────────────
# KLAVIATURALAR
# ──────────────────────────────────────────

def main_menu(user_id: int = None):
    buttons = [
        [KeyboardButton(text="📅 Dars jadvali"), KeyboardButton(text="✅ Vazifalar")],
        [KeyboardButton(text="🔔 Eslatmalar"), KeyboardButton(text="🌤 Ob-havo")],
        [KeyboardButton(text="👤 Profilim"), KeyboardButton(text="⚙️ Sozlamalar")],
        [KeyboardButton(text="❓ Yordam")]
    ]
    if user_id and is_admin(user_id):
        buttons.append([KeyboardButton(text="🔐 Admin panel")])
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)


def days_keyboard():
    days = ["Dushanba", "Seshanba", "Chorshanba", "Payshanba", "Juma", "Shanba", "Yakshanba"]
    buttons = [[InlineKeyboardButton(text=d, callback_data=f"day_{i}")] for i, d in enumerate(days)]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def lesson_type_keyboard():
    buttons = [[InlineKeyboardButton(text=val, callback_data=f"ltype_{key}")] for key, val in LESSON_TYPES.items()]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def week_type_keyboard():
    buttons = [[InlineKeyboardButton(text=val, callback_data=f"wtype_{key}")] for key, val in WEEK_TYPES.items()]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def schedule_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Dars qo'shish", callback_data="add_lesson")],
        [InlineKeyboardButton(text="📋 Bugungi darslar", callback_data="today_lessons")],
        [InlineKeyboardButton(text="📆 Barcha jadval", callback_data="all_schedule")],
        [InlineKeyboardButton(text="🗑 Dars o'chirish", callback_data="delete_lesson")],
    ])


def tasks_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Vazifa qo'shish", callback_data="add_task")],
        [InlineKeyboardButton(text="📋 Vazifalar ro'yxati", callback_data="list_tasks")],
    ])


def reminders_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Eslatma qo'shish", callback_data="add_reminder")],
        [InlineKeyboardButton(text="📋 Eslatmalarim", callback_data="list_reminders")],
    ])


def repeat_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔂 Bir marta", callback_data="repeat_none")],
        [InlineKeyboardButton(text="📅 Har kuni", callback_data="repeat_daily")],
        [InlineKeyboardButton(text="📆 Har hafta", callback_data="repeat_weekly")],
    ])


def role_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👨‍🏫 O'qituvchi", callback_data="role_teacher")],
        [InlineKeyboardButton(text="🎓 Talaba", callback_data="role_student")],
        [InlineKeyboardButton(text="💼 Xodim / Boshqa", callback_data="role_other")],
    ])


def admin_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📊 Statistika", callback_data="admin_stats")],
        [InlineKeyboardButton(text="👥 Foydalanuvchilar", callback_data="admin_users")],
        [InlineKeyboardButton(text="📢 Xabar yuborish (broadcast)", callback_data="admin_broadcast")],
        [InlineKeyboardButton(text="🔑 Admin qo'shish", callback_data="admin_set_admin")],
    ])


def weather_cities_keyboard():
    buttons = []
    cities = list(UZ_CITIES.keys())
    for i in range(0, len(cities), 2):
        row = [InlineKeyboardButton(text=cities[i], callback_data=f"wcity_{cities[i]}")]
        if i + 1 < len(cities):
            row.append(InlineKeyboardButton(text=cities[i + 1], callback_data=f"wcity_{cities[i + 1]}"))
        buttons.append(row)
    buttons.append([InlineKeyboardButton(text="🔍 Boshqa shahar kiriting", callback_data="wcity_custom")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def weather_actions_keyboard(city_name: str):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🌡 Hozirgi ob-havo", callback_data=f"wact_now_{city_name}")],
        [InlineKeyboardButton(text="📅 5 kunlik prognoz", callback_data=f"wact_5day_{city_name}")],
        [InlineKeyboardButton(text="⏱ Bugungi soatlik", callback_data=f"wact_hourly_{city_name}")],
        [InlineKeyboardButton(text="🏙 Shaharni o'zgartirish", callback_data="weather_change_city")],
    ])


# ──────────────────────────────────────────
# START / REGISTRATSIYA
# ──────────────────────────────────────────

@dp.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext):
    user = get_user(message.from_user.id)
    if user:
        update_user(message.from_user.id, {"username": message.from_user.username})
        await message.answer(
            f"👋 Xush kelibsiz, <b>{safe_text(user['full_name'])}</b>!\n\nNimadan boshlaymiz?",
            reply_markup=main_menu(message.from_user.id),
            parse_mode=ParseMode.HTML,
        )
    else:
        await message.answer(
            "👋 <b>HelpTeach botiga xush kelibsiz!</b>\n\n"
            "Bu bot sizga:\n"
            "📅 Dars/ish jadvalingizni boshqarishga\n"
            "✅ Kunlik vazifalarni rejalashtirishga\n"
            "🔔 Muhim eslatmalar olishga yordam beradi!\n\n"
            "Boshlash uchun <b>ism va familiyangizni to'liq kiriting</b>.\n"
            "Namuna: <b>Oybek Asrorov</b>\n\n"
            "❗ Iltimos, tasodifiy matn, qisqartma, raqam yoki noto'g'ri ism kiritmang.",
            parse_mode=ParseMode.HTML,
        )
        await state.set_state(RegisterState.full_name)


@dp.message(RegisterState.full_name)
async def reg_name(message: Message, state: FSMContext):
    full_name = normalize_full_name(message.text)
    if not is_valid_full_name(full_name):
        await message.answer(
            "❌ Ism-familiya noto'g'ri formatda kiritildi.\n\n"
            "Iltimos, <b>ism va familiyangizni to'liq va to'g'ri kiriting</b>.\n"
            "Namuna: <b>Oybek Asrorov</b>\n\n"
            "Tasodifiy matn, bitta so'z, raqam yoki qisqa yozuv qabul qilinmaydi.",
            parse_mode=ParseMode.HTML,
        )
        return

    await state.update_data(full_name=full_name)
    await message.answer("👤 Siz kim? Rolingizni tanlang:", reply_markup=role_keyboard())
    await state.set_state(RegisterState.role_type)


@dp.callback_query(F.data.startswith("role_"), RegisterState.role_type)
async def reg_role(call: CallbackQuery, state: FSMContext):
    role_map = {
        "role_teacher": ("teacher", "👨‍🏫 O'qituvchi"),
        "role_student": ("student", "🎓 Talaba"),
        "role_other": ("other", "💼 Xodim/Boshqa")
    }
    role_key, _ = role_map[call.data]
    await state.update_data(role=role_key)

    if role_key == "teacher":
        await call.message.answer("🏛 Muassasa/Universitetingiz nomini kiriting:")
    elif role_key == "student":
        await call.message.answer("🏛 O'quv yurtingiz va guruhingizni kiriting (masalan: TATU, AT-23):")
    else:
        await call.message.answer("🏢 Tashkilot yoki ish joyingizni kiriting:")

    await state.set_state(RegisterState.organization)
    await call.answer()


@dp.message(RegisterState.organization)
async def reg_organization(message: Message, state: FSMContext):
    data = await state.get_data()
    organization = normalize_full_name(message.text) if message.text else message.text

    create_user(message.from_user.id, data["full_name"], username=message.from_user.username)
    update_user(message.from_user.id, {
        "role": data["role"],
        "organization": organization,
        "username": message.from_user.username,
    })
    await state.clear()

    role_emoji = {"teacher": "👨‍🏫", "student": "🎓", "other": "💼"}.get(data["role"], "👤")
    await message.answer(
        f"✅ <b>Ro'yxatdan o'tdingiz!</b>\n\n"
        f"👤 Ism: <b>{safe_text(data['full_name'])}</b>\n"
        f"{role_emoji} Rol: <b>{safe_text(data['role'])}</b>\n"
        f"🏛 Tashkilot: <b>{safe_text(organization)}</b>\n"
        f"🔗 Username: <b>{safe_text(get_display_username(message.from_user.username))}</b>\n\n"
        f"Endi /help buyrug'i orqali bot imkoniyatlarini ko'ring yoki pastdagi menyu orqali boshlang!",
        reply_markup=main_menu(message.from_user.id),
        parse_mode=ParseMode.HTML,
    )


# ──────────────────────────────────────────
# YORDAM / PROFIL
# ──────────────────────────────────────────

@dp.message(Command("help"))
@dp.message(F.text == "❓ Yordam")
async def cmd_help(message: Message):
    admin = is_admin(message.from_user.id)
    text = (
        "<b>📖 BOT HAQIDA TO'LIQ QO'LLANMA</b>\n\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "<b>📅 DARS JADVALI</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "Bot sizga haftalik dars/ish jadvalingizni saqlash va boshqarish imkonini beradi.\n\n"
        "<b>Dars qo'shishda kiritiladi:</b>\n"
        "• Kun (Dushanba–Yakshanba)\n"
        "• Fan/Mashg'ulot nomi\n"
        "• Dars turi: 📖 Ma'ruza, ✏️ Amaliy, 🔬 Laboratoriya, 📝 Kurs ishi, 💬 Seminar\n"
        "• Hafta turi: 🔄 Har hafta, 1️⃣ Toq haftalar, 2️⃣ Juft haftalar\n"
        "• Xona/auditoriya raqami\n"
        "• Guruh nomi\n"
        "• Boshlanish va tugash vaqti\n\n"
        "📌 <b>Toq/Juft hafta</b> — bir haftada amaliy, keyingisida laboratoriya bo'ladigan darslar uchun!\n\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "<b>✅ VAZIFALAR</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "Kunlik va muddatli vazifalaringizni saqlang.\n\n"
        "• Vazifa nomi va izoh qo'shing\n"
        "• Muddat belgilang\n"
        "• Bajarildi deb belgilang ✅\n"
        "• Kerak bo'lmasa o'chiring 🗑\n\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "<b>🔔 ESLATMALAR</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "• Aniq sana va vaqtga eslatma qo'ying\n"
        "• Bir martalik, har kunlik yoki har haftalik takrorlash\n"
        "• Bot belgilangan vaqtda avtomatik xabar yuboradi\n\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "<b>🤖 AVTOMATIK BILDIRISHNOMALAR</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "• 🌅 Ertalabki xabar — bugungi darslar va vazifalar\n"
        "• ⏰ Darsdan 30 daqiqa oldin eslatma\n"
        "• ⚡️ Darsdan 10 daqiqa oldin eslatma\n"
        "• 🔴 Dars boshlanganida xabar\n"
        "• 🌙 Kechki xulosa — bajarilgan/qolgan vazifalar\n\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "🌤 *OB-HAVO*\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "Bot sizga shaharlar bo'yicha ob-havo ma'lumotlarini ko'rsatadi.\n\n"
        "• 🌡 Hozirgi ob-havo\n"
        "• 📅 5 kunlik prognoz\n"
        "• ⏱ Bugungi soatlik prognoz\n"
        "• 💡 Aqlli tavsiyalar (soyabon, shamol, sovuq, issiq va boshqalar)\n"
        "• 😷 Havo sifati ma'lumoti\n"
        "• ⚠️ Ob-havo ogohlantirishlari (mavjud bo'lsa)\n\n"
        "📌 Shaharni tugmalardan tanlashingiz yoki o'zingiz yozib kiritishingiz mumkin.\n\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "<b>⚙️ SOZLAMALAR</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "• Ertalabki xabar vaqtini o'zgartirish\n"
        "• Kechki xulosa vaqtini o'zgartirish\n"
        "• 🔕 Bezovta qilma rejimi\n\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "<b>📌 BUYRUQLAR</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "/start — Botni qayta ishga tushirish\n"
        "/help — Shu yordam sahifasi\n"
        "/profile — Profilingizni ko'rish\n"
        "/today — Bugungi darslar\n"
        "/tasks — Vazifalar ro'yxati\n"
        "/weather — Ob-havo bo'limini ochish\n"
    )
    if admin:
        text += (
            "\n━━━━━━━━━━━━━━━━━━━━━\n"
            "<b>🔐 ADMIN BUYRUQLARI</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━\n"
            "/admin — Admin panelni ochish\n"
            "/stats — Statistika\n"
            "/broadcast — Barcha foydalanuvchilarga xabar\n"
            "/users — Foydalanuvchilar ro'yxati\n"
            "/setadmin [ID] — Foydalanuvchiga admin berish\n"
        )
    await message.answer(text, parse_mode=ParseMode.HTML)


@dp.message(Command("profile"))
@dp.message(F.text == "👤 Profilim")
async def show_profile(message: Message):
    user = get_user(message.from_user.id)
    if not user:
        await message.answer("Avval ro'yxatdan o'ting: /start")
        return

    update_user(message.from_user.id, {"username": message.from_user.username})
    role_emoji = {
        "teacher": "👨‍🏫 O'qituvchi",
        "student": "🎓 Talaba",
        "other": "💼 Xodim/Boshqa"
    }.get(user.get("role", ""), "👤")
    admin_badge = " 🔐 Admin" if is_admin(message.from_user.id) else ""
    await message.answer(
        f"👤 <b>Profilingiz</b>{admin_badge}\n\n"
        f"Ism: <b>{safe_text(user['full_name'])}</b>\n"
        f"Username: <b>{safe_text(get_display_username(message.from_user.username))}</b>\n"
        f"Rol: {safe_text(role_emoji)}\n"
        f"🏛 Tashkilot: {safe_text(user.get('organization', user.get('faculty', '—')))}\n"
        f"📅 Ro'yxatdan o'tgan: {safe_text(str(user['created_at'])[:10])}",
        parse_mode=ParseMode.HTML,
    )


# ──────────────────────────────────────────
# BUGUNGI DARSLAR
# ──────────────────────────────────────────

@dp.message(Command("today"))
async def cmd_today(message: Message):
    lessons = get_today_schedule_by_week(message.from_user.id)
    await send_today_lessons(message, lessons)


async def send_today_lessons(message, lessons):
    from datetime import date
    week_number = date.today().isocalendar()[1]
    week_type_str = "Toq hafta 1️⃣" if week_number % 2 == 1 else "Juft hafta 2️⃣"

    if not lessons:
        await message.answer(f"📭 Bugun dars yo'q!\n<i>{week_type_str}</i>", parse_mode=ParseMode.HTML)
        return

    msg = f"📅 <b>Bugungi darslar</b>\n<i>{week_type_str}</i>\n\n"
    for l in lessons:
        lt = LESSON_TYPES.get(l.get("lesson_type", "other"), "📌 Boshqa")
        msg += (
            f"⏰ <b>{safe_text(l['start_time'][:5])} – {safe_text(l['end_time'][:5])}</b>\n"
            f"📚 {safe_text(l['subject'])} | {safe_text(lt)}\n"
            f"🏛 Xona: {safe_text(l['room'])} | 👥 {safe_text(l['group_name'])}\n\n"
        )
    await message.answer(msg, parse_mode=ParseMode.HTML)


# ──────────────────────────────────────────
# DARS JADVALI
# ──────────────────────────────────────────

@dp.message(F.text == "📅 Dars jadvali")
async def schedule_main(message: Message):
    user = get_user(message.from_user.id)
    if not user:
        await message.answer("Avval ro'yxatdan o'ting: /start")
        return
    await message.answer("📅 <b>Dars jadvali</b>", reply_markup=schedule_menu(), parse_mode=ParseMode.HTML)


@dp.callback_query(F.data == "add_lesson")
async def add_lesson_start(call: CallbackQuery, state: FSMContext):
    await call.message.answer("📆 Qaysi kuni dars?", reply_markup=days_keyboard())
    await state.set_state(ScheduleState.day)
    await call.answer()


@dp.callback_query(F.data.startswith("day_"), ScheduleState.day)
async def lesson_day(call: CallbackQuery, state: FSMContext):
    day = int(call.data.split("_")[1])
    await state.update_data(day=day)
    await call.message.answer("📚 Fan yoki mashg'ulot nomini kiriting:")
    await state.set_state(ScheduleState.subject)
    await call.answer()


@dp.message(ScheduleState.subject)
async def lesson_subject(message: Message, state: FSMContext):
    await state.update_data(subject=message.text)
    await message.answer("📖 Dars turini tanlang:", reply_markup=lesson_type_keyboard())
    await state.set_state(ScheduleState.lesson_type)


@dp.callback_query(F.data.startswith("ltype_"), ScheduleState.lesson_type)
async def lesson_type_chosen(call: CallbackQuery, state: FSMContext):
    ltype = call.data.replace("ltype_", "")
    await state.update_data(lesson_type=ltype)
    await call.message.answer("📅 Hafta turini tanlang:", reply_markup=week_type_keyboard())
    await state.set_state(ScheduleState.week_type)
    await call.answer()


@dp.callback_query(F.data.startswith("wtype_"), ScheduleState.week_type)
async def week_type_chosen(call: CallbackQuery, state: FSMContext):
    wtype = call.data.replace("wtype_", "")
    await state.update_data(week_type=wtype)
    await call.message.answer("🏛 Xona/auditoriya raqamini kiriting:")
    await state.set_state(ScheduleState.room)
    await call.answer()


@dp.message(ScheduleState.room)
async def lesson_room(message: Message, state: FSMContext):
    await state.update_data(room=message.text)
    await message.answer("👥 Guruh nomini kiriting (yo'q bo'lsa '-' yozing):")
    await state.set_state(ScheduleState.group_name)


@dp.message(ScheduleState.group_name)
async def lesson_group(message: Message, state: FSMContext):
    await state.update_data(group_name=message.text)
    await message.answer("⏰ Boshlanish vaqtini kiriting (masalan: 08:00):")
    await state.set_state(ScheduleState.start_time)


@dp.message(ScheduleState.start_time)
async def lesson_start(message: Message, state: FSMContext):
    await state.update_data(start_time=message.text)
    await message.answer("⏰ Tugash vaqtini kiriting (masalan: 09:30):")
    await state.set_state(ScheduleState.end_time)


@dp.message(ScheduleState.end_time)
async def lesson_end(message: Message, state: FSMContext):
    data = await state.get_data()
    add_schedule(
        message.from_user.id,
        data["day"], data["subject"], data["room"], data["group_name"],
        data["start_time"], message.text,
        data.get("lesson_type", "other"),
        data.get("week_type", "every"),
    )
    await state.clear()

    lt = LESSON_TYPES.get(data.get("lesson_type", "other"), "📌 Boshqa")
    wt = WEEK_TYPES.get(data.get("week_type", "every"), "🔄 Har hafta")
    await message.answer(
        f"✅ <b>Dars qo'shildi!</b>\n\n"
        f"📚 {safe_text(data['subject'])} | {safe_text(lt)}\n"
        f"📅 {safe_text(DAYS[data['day']])} | {safe_text(wt)}\n"
        f"⏰ {safe_text(data['start_time'])} – {safe_text(message.text)}\n"
        f"🏛 Xona: {safe_text(data['room'])} | 👥 {safe_text(data['group_name'])}",
        reply_markup=main_menu(message.from_user.id),
        parse_mode=ParseMode.HTML,
    )


@dp.callback_query(F.data == "today_lessons")
async def today_lessons(call: CallbackQuery):
    lessons = get_today_schedule_by_week(call.from_user.id)
    await send_today_lessons(call.message, lessons)
    await call.answer()


@dp.callback_query(F.data == "all_schedule")
async def all_schedule(call: CallbackQuery):
    msg = "📆 <b>Haftalik jadval:</b>\n\n"
    has_any = False
    for day_num, day_name in DAYS.items():
        lessons = get_schedule(call.from_user.id, day_num)
        if lessons:
            has_any = True
            msg += f"<b>{safe_text(day_name)}:</b>\n"
            for l in lessons:
                lt = LESSON_TYPES.get(l.get("lesson_type", "other"), "📌")
                wt = WEEK_TYPES.get(l.get("week_type", "every"), "")
                msg += f"  ⏰ {safe_text(l['start_time'][:5])}–{safe_text(l['end_time'][:5])} | {safe_text(l['subject'])} {safe_text(lt)}\n"
                msg += f"     🏛 {safe_text(l['room'])} | 👥 {safe_text(l['group_name'])} | {safe_text(wt)}\n"
            msg += "\n"

    if not has_any:
        msg = "📭 Jadval bo'sh! Dars qo'shing."

    for chunk in split_long_message(msg):
        await call.message.answer(chunk, parse_mode=ParseMode.HTML)
    await call.answer()


@dp.callback_query(F.data == "delete_lesson")
async def delete_lesson_start(call: CallbackQuery):
    all_lessons = []
    for day_num in range(7):
        lessons = get_schedule(call.from_user.id, day_num)
        all_lessons.extend(lessons)

    if not all_lessons:
        await call.message.answer("📭 Jadval bo'sh!")
        await call.answer()
        return

    buttons = []
    for l in all_lessons:
        lt = LESSON_TYPES.get(l.get("lesson_type", "other"), "📌")
        wt_short = {"every": "har", "odd": "toq", "even": "juft"}.get(l.get("week_type", "every"), "")
        label = f"{DAYS[l['day_of_week']]} | {l['start_time'][:5]} | {l['subject']} {lt} ({wt_short})"
        buttons.append([InlineKeyboardButton(text=label[:64], callback_data=f"del_lesson_{l['id']}")])

    await call.message.answer(
        "🗑 Qaysi darsni o'chirmoqchisiz?",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
    )
    await call.answer()


@dp.callback_query(F.data.startswith("del_lesson_"))
async def confirm_delete_lesson(call: CallbackQuery):
    lesson_id = int(call.data.split("_")[-1])
    delete_schedule(lesson_id)
    await call.message.edit_text("✅ Dars o'chirildi!")
    await call.answer()


# ──────────────────────────────────────────
# VAZIFALAR
# ──────────────────────────────────────────

@dp.message(Command("tasks"))
@dp.message(F.text == "✅ Vazifalar")
async def tasks_main(message: Message):
    user = get_user(message.from_user.id)
    if not user:
        await message.answer("Avval ro'yxatdan o'ting: /start")
        return
    await message.answer("✅ <b>Vazifalar</b>", reply_markup=tasks_menu(), parse_mode=ParseMode.HTML)


@dp.callback_query(F.data == "add_task")
async def add_task_start(call: CallbackQuery, state: FSMContext):
    await call.message.answer("📝 Vazifa nomini kiriting:")
    await state.set_state(TaskState.title)
    await call.answer()


@dp.message(TaskState.title)
async def task_title(message: Message, state: FSMContext):
    await state.update_data(title=message.text)
    await message.answer("📄 Izoh kiriting (ixtiyoriy, o'tkazish uchun '-' yozing):")
    await state.set_state(TaskState.description)


@dp.message(TaskState.description)
async def task_description(message: Message, state: FSMContext):
    desc = None if message.text == "-" else message.text
    await state.update_data(description=desc)
    await message.answer("📅 Muddat kiriting (masalan: 2025-12-31, o'tkazish uchun '-'):")
    await state.set_state(TaskState.due_date)


@dp.message(TaskState.due_date)
async def task_due_date(message: Message, state: FSMContext):
    data = await state.get_data()
    due = None if message.text == "-" else message.text
    add_task(message.from_user.id, data["title"], data.get("description"), due)
    await state.clear()
    await message.answer(
        f"✅ <b>Vazifa qo'shildi!</b>\n📝 {safe_text(data['title'])}",
        reply_markup=main_menu(message.from_user.id),
        parse_mode=ParseMode.HTML,
    )


@dp.callback_query(F.data == "list_tasks")
async def list_tasks(call: CallbackQuery):
    tasks = get_tasks(call.from_user.id)
    if not tasks:
        await call.message.answer("🎉 Barcha vazifalar bajarilgan!")
        await call.answer()
        return

    for task in tasks:
        due = f"\n📅 Muddat: {safe_text(task['due_date'])}" if task.get('due_date') else ""
        desc = f"\n📄 {safe_text(task['description'])}" if task.get('description') else ""
        kb = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="✅ Bajarildi", callback_data=f"done_task_{task['id']}"),
            InlineKeyboardButton(text="🗑 O'chirish", callback_data=f"del_task_{task['id']}")
        ]])
        await call.message.answer(f"📝 <b>{safe_text(task['title'])}</b>{desc}{due}", reply_markup=kb, parse_mode=ParseMode.HTML)
    await call.answer()


@dp.callback_query(F.data.startswith("done_task_"))
async def done_task(call: CallbackQuery):
    task_id = int(call.data.split("_")[-1])
    complete_task(task_id)
    await call.message.edit_text("✅ <b>Vazifa bajarildi!</b> Tabriklaymiz! 🎉", parse_mode=ParseMode.HTML)
    await call.answer()


@dp.callback_query(F.data.startswith("del_task_"))
async def del_task(call: CallbackQuery):
    task_id = int(call.data.split("_")[-1])
    delete_task(task_id)
    await call.message.edit_text("🗑 Vazifa o'chirildi.")
    await call.answer()


# ──────────────────────────────────────────
# ESLATMALAR
# ──────────────────────────────────────────

@dp.message(F.text == "🔔 Eslatmalar")
async def reminders_main(message: Message):
    user = get_user(message.from_user.id)
    if not user:
        await message.answer("Avval ro'yxatdan o'ting: /start")
        return
    await message.answer("🔔 <b>Eslatmalar</b>", reply_markup=reminders_menu(), parse_mode=ParseMode.HTML)


@dp.callback_query(F.data == "add_reminder")
async def add_reminder_start(call: CallbackQuery, state: FSMContext):
    await call.message.answer("📌 Eslatma nomini kiriting:")
    await state.set_state(ReminderState.title)
    await call.answer()


@dp.message(ReminderState.title)
async def reminder_title(message: Message, state: FSMContext):
    await state.update_data(title=message.text)
    await message.answer("📅 Sanani kiriting (masalan: 2025-12-31):")
    await state.set_state(ReminderState.date)


@dp.message(ReminderState.date)
async def reminder_date(message: Message, state: FSMContext):
    await state.update_data(date=message.text)
    await message.answer("⏰ Vaqtni kiriting (masalan: 14:30):")
    await state.set_state(ReminderState.time)


@dp.message(ReminderState.time)
async def reminder_time(message: Message, state: FSMContext):
    time_input = message.text.strip()
    if "T" in time_input or "-" in time_input:
        await message.answer("❌ Faqat vaqtni kiriting! Masalan: 14:30")
        return
    await state.update_data(time=time_input)
    await message.answer("🔂 Takrorlanishini tanlang:", reply_markup=repeat_keyboard())
    await state.set_state(ReminderState.repeat)


@dp.callback_query(F.data.startswith("repeat_"), ReminderState.repeat)
async def reminder_repeat(call: CallbackQuery, state: FSMContext):
    repeat = call.data.replace("repeat_", "")
    data = await state.get_data()
    try:
        date_str = data['date'].strip()
        time_str = data['time'].strip()
        remind_at = f"{date_str}T{time_str}:00+05:00"
    except Exception:
        await call.message.answer("❌ Sana yoki vaqt formati noto'g'ri!\nQaytadan /start dan boshlang.")
        await state.clear()
        await call.answer()
        return

    add_reminder(call.from_user.id, data["title"], remind_at, repeat)
    await state.clear()
    repeat_text = {"none": "Bir marta", "daily": "Har kuni", "weekly": "Har hafta"}
    await call.message.answer(
        f"✅ <b>Eslatma qo'shildi!</b>\n\n"
        f"📌 {safe_text(data['title'])}\n"
        f"📅 {safe_text(date_str)} ⏰ {safe_text(time_str)}\n"
        f"🔂 {safe_text(repeat_text.get(repeat, repeat))}",
        reply_markup=main_menu(call.from_user.id),
        parse_mode=ParseMode.HTML,
    )
    await call.answer()


@dp.callback_query(F.data == "list_reminders")
async def list_reminders(call: CallbackQuery):
    reminders = get_user_reminders(call.from_user.id)
    if not reminders:
        await call.message.answer("📭 Faol eslatmalar yo'q!")
        await call.answer()
        return
    msg = "🔔 <b>Faol eslatmalar:</b>\n\n"
    repeat_text = {"none": "Bir marta", "daily": "Har kuni", "weekly": "Har hafta"}
    for r in reminders:
        time_str = str(r["remind_at"])[:16].replace("T", " ")
        msg += f"📌 <b>{safe_text(r['title'])}</b>\n"
        msg += f"⏰ {safe_text(time_str)} | 🔂 {safe_text(repeat_text.get(r['repeat_type'], r['repeat_type']))}\n\n"
    for chunk in split_long_message(msg):
        await call.message.answer(chunk, parse_mode=ParseMode.HTML)
    await call.answer()


# ──────────────────────────────────────────
# OB-HAVO
# ──────────────────────────────────────────

@dp.message(Command("weather"))
@dp.message(F.text == "🌤 Ob-havo")
async def weather_main(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "🌤 <b>Ob-havo</b>\n\nQaysi shahar uchun ob-havo ko'rmoqchisiz?",
        reply_markup=weather_cities_keyboard(),
        parse_mode="HTML"
    )


@dp.callback_query(F.data == "weather_change_city")
async def weather_change_city(call: CallbackQuery):
    await call.message.answer("🏙 Shaharni tanlang:", reply_markup=weather_cities_keyboard())
    await call.answer()


@dp.callback_query(F.data.startswith("wcity_"))
async def weather_city_selected(call: CallbackQuery, state: FSMContext):
    city = call.data[6:]
    if city == "custom":
        await call.message.answer(
            "🔍 Shahar nomini kiriting (o'zbek, rus yoki ingliz tilida):\n"
            "Masalan: Sirdaryo, Shahrisabz, Chirchiq..."
        )
        await state.set_state(WeatherState.city_input)
        await call.answer()
        return

    await call.answer("⏳ Ma'lumot olinmoqda...")
    await call.message.answer(
        f"📍 <b>{safe_text(city)}</b> uchun qanday ma'lumot kerak?",
        reply_markup=weather_actions_keyboard(city),
        parse_mode=ParseMode.HTML,
    )


@dp.message(WeatherState.city_input)
async def weather_custom_city(message: Message, state: FSMContext):
    await state.clear()
    city_input = message.text.strip()
    msg = await message.answer("⏳ Shahar qidirilmoqda...")

    result = await geocode_city(city_input)
    if not result:
        await msg.edit_text(
            f"❌ <b>{safe_text(city_input)}</b> shahri topilmadi.\n\n"
            "Iltimos, boshqa nom kiriting yoki ro'yxatdan tanlang.",
            reply_markup=weather_cities_keyboard(),
            parse_mode=ParseMode.HTML,
        )
        return

    lat, lon, found_name = result
    UZ_CITIES[found_name] = (lat, lon)
    await msg.delete()
    await message.answer(
        f"📍 <b>{safe_text(found_name)}</b> uchun qanday ma'lumot kerak?",
        reply_markup=weather_actions_keyboard(found_name),
        parse_mode=ParseMode.HTML,
    )


@dp.callback_query(F.data.startswith("wact_"))
async def weather_action(call: CallbackQuery):
    parts = call.data.split("_", 2)
    if len(parts) < 3:
        await call.answer("Xatolik!")
        return

    action = parts[1]
    city_name = parts[2]
    coords = UZ_CITIES.get(city_name)
    if not coords:
        await call.answer("❌ Shahar topilmadi!")
        return

    await call.answer("⏳ Yuklanmoqda...")
    data = await fetch_weather(coords[0], coords[1])
    if not data:
        await call.message.answer("❌ Ob-havo ma'lumotini olishda xatolik. Keyinroq qayta urinib ko'ring.")
        return

    nav_kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🌡 Hozir", callback_data=f"wact_now_{city_name}"),
            InlineKeyboardButton(text="📅 5 kun", callback_data=f"wact_5day_{city_name}"),
            InlineKeyboardButton(text="⏱ Soatlik", callback_data=f"wact_hourly_{city_name}"),
        ],
        [InlineKeyboardButton(text="🏙 Shahar o'zgartirish", callback_data="weather_change_city")],
    ])

    if action == "now":
        text = format_current_weather(data, city_name)
    elif action == "5day":
        text = format_forecast_5day(data, city_name)
    elif action == "hourly":
        text = format_hourly_today(data, city_name)
    else:
        await call.message.answer("Noma'lum amal!")
        return

    await call.message.answer(text, parse_mode=ParseMode.HTML, reply_markup=nav_kb)


# ──────────────────────────────────────────
# SOZLAMALAR
# ──────────────────────────────────────────

@dp.message(F.text == "⚙️ Sozlamalar")
async def settings_main(message: Message):
    settings = get_settings(message.from_user.id)
    if not settings:
        await message.answer("Avval ro'yxatdan o'ting: /start")
        return
    dnd = "✅ Yoqiq" if settings.get("do_not_disturb") else "❌ O'chiq"
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🌅 Ertalab vaqtini o'zgartirish", callback_data="set_morning")],
        [InlineKeyboardButton(text="🌙 Kechki vaqtini o'zgartirish", callback_data="set_evening")],
        [InlineKeyboardButton(text=f"🔕 Bezovta qilma: {dnd}", callback_data="toggle_dnd")],
    ])
    await message.answer(
        f"⚙️ <b>Sozlamalar</b>\n\n"
        f"🌅 Ertalabki xabar: <b>{safe_text(str(settings.get('morning_time', '07:00'))[:5])}</b>\n"
        f"🌙 Kechki xulosa: <b>{safe_text(str(settings.get('evening_time', '21:00'))[:5])}</b>\n"
        f"🔕 Bezovta qilma: <b>{safe_text(dnd)}</b>\n\n"
        f"30 daqiqa oldin: {'✅' if settings.get('notify_before_30') else '❌'}\n"
        f"10 daqiqa oldin: {'✅' if settings.get('notify_before_10') else '❌'}\n"
        f"Dars boshida: {'✅' if settings.get('notify_on_time') else '❌'}",
        reply_markup=kb,
        parse_mode=ParseMode.HTML,
    )


@dp.callback_query(F.data == "toggle_dnd")
async def toggle_dnd(call: CallbackQuery):
    settings = get_settings(call.from_user.id)
    new_val = not settings.get("do_not_disturb", False)
    update_settings(call.from_user.id, {"do_not_disturb": new_val})
    status = "yoqildi 🔕" if new_val else "o'chirildi 🔔"
    await call.message.answer(f"Bezovta qilma rejimi {status}")
    await call.answer()


@dp.callback_query(F.data == "set_morning")
async def set_morning(call: CallbackQuery, state: FSMContext):
    await call.message.answer("🌅 Yangi ertalabki vaqtni kiriting (masalan: 07:00):")
    await state.set_state(SettingsState.morning_time)
    await call.answer()


@dp.message(SettingsState.morning_time)
async def save_morning(message: Message, state: FSMContext):
    update_settings(message.from_user.id, {"morning_time": message.text})
    await state.clear()
    await message.answer(f"✅ Ertalabki vaqt <b>{safe_text(message.text)}</b> ga o'zgartirildi!", parse_mode=ParseMode.HTML)


@dp.callback_query(F.data == "set_evening")
async def set_evening(call: CallbackQuery, state: FSMContext):
    await call.message.answer("🌙 Yangi kechki vaqtni kiriting (masalan: 21:00):")
    await state.set_state(SettingsState.evening_time)
    await call.answer()


@dp.message(SettingsState.evening_time)
async def save_evening(message: Message, state: FSMContext):
    update_settings(message.from_user.id, {"evening_time": message.text})
    await state.clear()
    await message.answer(f"✅ Kechki vaqt <b>{safe_text(message.text)}</b> ga o'zgartirildi!", parse_mode=ParseMode.HTML)


# ──────────────────────────────────────────
# ADMIN PANEL
# ──────────────────────────────────────────

@dp.message(F.text == "🔐 Admin panel")
@dp.message(Command("admin"))
async def admin_panel(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("⛔️ Sizda admin huquqi yo'q!")
        return
    await message.answer("🔐 <b>Admin panel</b>", reply_markup=admin_menu(), parse_mode=ParseMode.HTML)


@dp.callback_query(F.data == "admin_stats")
async def admin_stats(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        await call.answer("⛔️ Ruxsat yo'q!")
        return
    stats = get_stats()
    await call.message.answer(
        f"📊 <b>Bot statistikasi</b>\n\n"
        f"👥 Foydalanuvchilar: <b>{stats['users']}</b>\n"
        f"📅 Jadvaldagi darslar: <b>{stats['schedules']}</b>\n"
        f"✅ Vazifalar: <b>{stats['tasks']}</b>\n"
        f"🔔 Eslatmalar: <b>{stats['reminders']}</b>",
        parse_mode=ParseMode.HTML,
    )
    await call.answer()


@dp.callback_query(F.data == "admin_users")
async def admin_users(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        await call.answer("⛔️ Ruxsat yo'q!")
        return

    users = get_all_users()
    if not users:
        await call.message.answer("Foydalanuvchilar yo'q!")
        await call.answer()
        return

    header = f"👥 <b>Foydalanuvchilar ({len(users)} ta):</b>\n\n"
    parts = [header]
    current = ""
    for idx, u in enumerate(users, start=1):
        role_e = {"teacher": "👨‍🏫", "student": "🎓", "other": "💼"}.get(u.get("role", ""), "👤")
        admin_b = " 🔐" if u.get("is_admin") else ""
        username = get_display_username(u.get("username"))
        block = (
            f"{idx}. {role_e} <b>{safe_text(u['full_name'])}</b>{admin_b}\n"
            f"   ID: <code>{safe_text(u['telegram_id'])}</code>\n"
            f"   Username: {safe_text(username)}\n"
            f"   {safe_text(u.get('organization', u.get('faculty', '—')))}\n\n"
        )
        if len(current) + len(block) > 3200:
            parts.append(current)
            current = block
        else:
            current += block
    if current:
        parts.append(current)

    for chunk in parts:
        await call.message.answer(chunk, parse_mode=ParseMode.HTML)
    await call.answer()


@dp.callback_query(F.data == "admin_broadcast")
async def admin_broadcast_start(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        await call.answer("⛔️ Ruxsat yo'q!")
        return
    await call.message.answer(
        "📢 Barcha foydalanuvchilarga yuboriladigan xabarni kiriting:\n"
        "<i>(Bekor qilish uchun /cancel yozing)</i>",
        parse_mode=ParseMode.HTML,
    )
    await state.set_state(AdminState.broadcast_text)
    await call.answer()


@dp.message(Command("cancel"), AdminState.broadcast_text)
async def cancel_broadcast(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("❌ Bekor qilindi.", reply_markup=main_menu(message.from_user.id))


@dp.message(AdminState.broadcast_text)
async def admin_broadcast_send(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return

    await state.clear()
    users = get_all_users()
    success = 0
    fail = 0
    removed = 0
    failed_users = []

    for u in users:
        try:
            await bot.send_message(
                u["telegram_id"],
                f"📢 <b>Admin xabari:</b>\n\n{safe_text(message.text, limit=3500)}",
                parse_mode=ParseMode.HTML,
            )
            success += 1
            await asyncio.sleep(0.03)
        except Exception as e:
            fail += 1
            readable = format_broadcast_error(e)
            user_label = f"{u.get('full_name', 'Noma’lum')} ({u['telegram_id']})"
            if is_removable_user_error(e):
                if delete_user(u["telegram_id"]):
                    removed += 1
                    failed_users.append(f"🗑 {safe_text(user_label)} — {safe_text(readable)} — bazadan o‘chirildi")
                else:
                    failed_users.append(f"❌ {safe_text(user_label)} — {safe_text(readable)} — o‘chirish muvaffaqiyatsiz")
            else:
                failed_users.append(f"⚠️ {safe_text(user_label)} — {safe_text(readable)}")
            logger.warning("Broadcast xatosi user_id=%s: %s", u["telegram_id"], e)
            await asyncio.sleep(0.05)

    summary = (
        f"📢 <b>Xabar yuborildi!</b>\n\n"
        f"✅ Muvaffaqiyatli: <b>{success}</b> ta\n"
        f"❌ Xato: <b>{fail}</b> ta\n"
        f"🗑 Bazadan o‘chirilganlar: <b>{removed}</b> ta"
    )
    await message.answer(summary, parse_mode=ParseMode.HTML)

    if failed_users:
        detail_header = "<b>Broadcast xatolari tafsiloti:</b>\n\n"
        detail_text = detail_header + "\n".join(failed_users)
        for chunk in split_long_message(detail_text, chunk_size=3500):
            await message.answer(chunk, parse_mode=ParseMode.HTML)


@dp.callback_query(F.data == "admin_set_admin")
async def admin_set_admin_start(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        await call.answer("⛔️ Ruxsat yo'q!")
        return
    await call.message.answer("🔑 Admin qilmoqchi bo'lgan foydalanuvchining Telegram ID sini kiriting:")
    await state.set_state(AdminState.set_admin_id)
    await call.answer()


@dp.message(AdminState.set_admin_id)
async def admin_set_admin_confirm(message: Message, state: FSMContext):
    try:
        target_id = int(message.text.strip())
        set_admin(target_id, True)
        await state.clear()
        await message.answer(f"✅ ID <code>{target_id}</code> ga admin huquqi berildi!", parse_mode=ParseMode.HTML)
    except ValueError:
        await message.answer("❌ Noto'g'ri ID! Faqat raqam kiriting.")


@dp.message(Command("setadmin"))
async def cmd_setadmin(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("⛔️ Ruxsat yo'q!")
        return
    parts = message.text.split()
    if len(parts) < 2:
        await message.answer("Ishlatish: /setadmin [telegram_id]")
        return
    try:
        target_id = int(parts[1])
        set_admin(target_id, True)
        await message.answer(f"✅ ID <code>{target_id}</code> ga admin huquqi berildi!", parse_mode=ParseMode.HTML)
    except ValueError:
        await message.answer("❌ Noto'g'ri ID!")


@dp.message(Command("stats"))
async def cmd_stats(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("⛔️ Ruxsat yo'q!")
        return
    stats = get_stats()
    await message.answer(
        f"📊 <b>Bot statistikasi</b>\n\n"
        f"👥 Foydalanuvchilar: <b>{stats['users']}</b>\n"
        f"📅 Jadvaldagi darslar: <b>{stats['schedules']}</b>\n"
        f"✅ Vazifalar: <b>{stats['tasks']}</b>\n"
        f"🔔 Eslatmalar: <b>{stats['reminders']}</b>",
        parse_mode=ParseMode.HTML,
    )


# ──────────────────────────────────────────
# BOT KOMANDALARI / STARTUP
# ──────────────────────────────────────────

async def set_bot_commands():
    user_commands = [
        BotCommand(command="start", description="Botni boshlash"),
        BotCommand(command="help", description="Yordam va qo'llanma"),
        BotCommand(command="today", description="Bugungi darslar"),
        BotCommand(command="tasks", description="Vazifalar ro'yxati"),
        BotCommand(command="profile", description="Profilim"),
        BotCommand(command="weather", description="Ob-havo ma'lumoti"),
    ]
    await bot.set_my_commands(user_commands)


async def health(request):
    return web.Response(text="Bot ishlayapti! ✅")


async def main():
    await bot.delete_webhook(drop_pending_updates=True)
    logger.info("Webhook tozalandi. Polling ishga tushmoqda...")
    logger.info("Agar TelegramConflictError chiqsa, bot 2 joyda ishlayotgan bo'ladi. Faqat 1 ta instance qoldiring.")

    await set_bot_commands()
    setup_scheduler(bot)

    app = web.Application()
    app.router.add_get("/", health)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.getenv("PORT", 8080))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()

    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()
        await runner.cleanup()


if __name__ == "__main__":
    asyncio.run(main())
