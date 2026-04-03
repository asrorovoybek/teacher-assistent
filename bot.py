import asyncio
import logging
import os
from datetime import datetime, timedelta

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    Message, CallbackQuery,
    InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
)

from database import (
    get_user, create_user, update_user,
    add_schedule, get_schedule, delete_schedule, get_today_schedule, DAYS,
    add_task, get_tasks, complete_task, delete_task,
    add_reminder, get_user_reminders,
    get_settings, update_settings
)
from scheduler import setup_scheduler

# ──────────────────────────────────────────
# SOZLAMALAR
# ──────────────────────────────────────────

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv("BOT_TOKEN")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# ──────────────────────────────────────────
# STATE GURUHLARI
# ──────────────────────────────────────────

class RegisterState(StatesGroup):
    full_name = State()
    faculty = State()
    department = State()
    position = State()

class ScheduleState(StatesGroup):
    day = State()
    subject = State()
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

# ──────────────────────────────────────────
# KLAVIATURALAR
# ──────────────────────────────────────────

def main_menu():
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="📅 Dars jadvali"), KeyboardButton(text="✅ Vazifalar")],
        [KeyboardButton(text="🔔 Eslatmalar"), KeyboardButton(text="👤 Profilim")],
        [KeyboardButton(text="⚙️ Sozlamalar")]
    ], resize_keyboard=True)

def days_keyboard():
    days = ["Dushanba", "Seshanba", "Chorshanba", "Payshanba", "Juma", "Shanba", "Yakshanba"]
    buttons = [[InlineKeyboardButton(text=d, callback_data=f"day_{i}")] for i, d in enumerate(days)]
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def schedule_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Dars qo'shish", callback_data="add_lesson")],
        [InlineKeyboardButton(text="📋 Bugungi darslar", callback_data="today_lessons")],
        [InlineKeyboardButton(text="📆 Barcha jadval", callback_data="all_schedule")],
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

# ──────────────────────────────────────────
# START VA RO'YXATDAN O'TISH
# ──────────────────────────────────────────

@dp.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext):
    user = get_user(message.from_user.id)
    if user:
        await message.answer(
            f"👋 Xush kelibsiz, *{user['full_name']}*!\n\nNimadan boshlaymiz?",
            reply_markup=main_menu(),
            parse_mode="Markdown"
        )
    else:
        await message.answer(
            "👋 *O'qituvchi Yordamchi Botga xush kelibsiz!*\n\n"
            "Bu bot sizga:\n"
            "📅 Dars jadvalingizni boshqarishga\n"
            "✅ Kunlik vazifalarni rejalashtirishga\n"
            "🔔 Muhim eslatmalar olishga yordam beradi!\n\n"
            "Boshlash uchun to'liq ismingizni kiriting:",
            parse_mode="Markdown"
        )
        await state.set_state(RegisterState.full_name)

@dp.message(RegisterState.full_name)
async def reg_name(message: Message, state: FSMContext):
    await state.update_data(full_name=message.text)
    await message.answer("🏛 Fakultetingizni kiriting:")
    await state.set_state(RegisterState.faculty)

@dp.message(RegisterState.faculty)
async def reg_faculty(message: Message, state: FSMContext):
    await state.update_data(faculty=message.text)
    await message.answer("📚 Kafedratingizni kiriting:")
    await state.set_state(RegisterState.department)

@dp.message(RegisterState.department)
async def reg_department(message: Message, state: FSMContext):
    await state.update_data(department=message.text)
    await message.answer("💼 Lavozimingizni kiriting (masalan: Dotsent, O'qituvchi):")
    await state.set_state(RegisterState.position)

@dp.message(RegisterState.position)
async def reg_position(message: Message, state: FSMContext):
    data = await state.get_data()
    create_user(message.from_user.id, data["full_name"])
    update_user(message.from_user.id, {
        "faculty": data["faculty"],
        "department": data["department"],
        "position": message.text
    })
    await state.clear()
    await message.answer(
        f"✅ *Ro'yxatdan o'tdingiz!*\n\n"
        f"👤 Ism: {data['full_name']}\n"
        f"🏛 Fakultet: {data['faculty']}\n"
        f"📚 Kafedra: {data['department']}\n"
        f"💼 Lavozim: {message.text}\n\n"
        f"Endi nimadan boshlaymiz?",
        reply_markup=main_menu(),
        parse_mode="Markdown"
    )

# ──────────────────────────────────────────
# PROFIL
# ──────────────────────────────────────────

@dp.message(F.text == "👤 Profilim")
async def show_profile(message: Message):
    user = get_user(message.from_user.id)
    if not user:
        await message.answer("Avval ro'yxatdan o'ting: /start")
        return
    await message.answer(
        f"👤 *Profilingiz*\n\n"
        f"Ism: *{user['full_name']}*\n"
        f"🏛 Fakultet: {user.get('faculty', '—')}\n"
        f"📚 Kafedra: {user.get('department', '—')}\n"
        f"💼 Lavozim: {user.get('position', '—')}\n"
        f"📅 Ro'yxatdan o'tgan: {str(user['created_at'])[:10]}",
        parse_mode="Markdown"
    )

# ──────────────────────────────────────────
# DARS JADVALI
# ──────────────────────────────────────────

@dp.message(F.text == "📅 Dars jadvali")
async def schedule_main(message: Message):
    user = get_user(message.from_user.id)
    if not user:
        await message.answer("Avval ro'yxatdan o'ting: /start")
        return
    await message.answer("📅 *Dars jadvali*", reply_markup=schedule_menu(), parse_mode="Markdown")

@dp.callback_query(F.data == "add_lesson")
async def add_lesson_start(call: CallbackQuery, state: FSMContext):
    await call.message.answer("📆 Qaysi kuni dars?", reply_markup=days_keyboard())
    await state.set_state(ScheduleState.day)
    await call.answer()

@dp.callback_query(F.data.startswith("day_"), ScheduleState.day)
async def lesson_day(call: CallbackQuery, state: FSMContext):
    day = int(call.data.split("_")[1])
    await state.update_data(day=day)
    await call.message.answer(f"✅ {DAYS[day]} tanlandi.\n\n📚 Fan nomini kiriting:")
    await state.set_state(ScheduleState.subject)
    await call.answer()

@dp.message(ScheduleState.subject)
async def lesson_subject(message: Message, state: FSMContext):
    await state.update_data(subject=message.text)
    await message.answer("🏛 Xona raqamini kiriting (masalan: 301-xona):")
    await state.set_state(ScheduleState.room)

@dp.message(ScheduleState.room)
async def lesson_room(message: Message, state: FSMContext):
    await state.update_data(room=message.text)
    await message.answer("👥 Guruh nomini kiriting (masalan: 21-guruh):")
    await state.set_state(ScheduleState.group_name)

@dp.message(ScheduleState.group_name)
async def lesson_group(message: Message, state: FSMContext):
    await state.update_data(group_name=message.text)
    await message.answer("⏰ Dars boshlanish vaqtini kiriting (masalan: 09:00):")
    await state.set_state(ScheduleState.start_time)

@dp.message(ScheduleState.start_time)
async def lesson_start_time(message: Message, state: FSMContext):
    await state.update_data(start_time=message.text)
    await message.answer("⏰ Dars tugash vaqtini kiriting (masalan: 10:30):")
    await state.set_state(ScheduleState.end_time)

@dp.message(ScheduleState.end_time)
async def lesson_end_time(message: Message, state: FSMContext):
    data = await state.get_data()
    add_schedule(
        message.from_user.id,
        data["day"], data["subject"], data["room"],
        data["group_name"], data["start_time"], message.text
    )
    await state.clear()
    await message.answer(
        f"✅ *Dars qo'shildi!*\n\n"
        f"📚 Fan: {data['subject']}\n"
        f"📆 Kun: {DAYS[data['day']]}\n"
        f"🏛 Xona: {data['room']}\n"
        f"👥 Guruh: {data['group_name']}\n"
        f"⏰ Vaqt: {data['start_time']} - {message.text}",
        reply_markup=main_menu(),
        parse_mode="Markdown"
    )

@dp.callback_query(F.data == "today_lessons")
async def today_lessons(call: CallbackQuery):
    lessons = get_today_schedule(call.from_user.id)
    if not lessons:
        await call.message.answer("📭 Bugun dars yo'q!")
    else:
        days_uz = ["Dushanba", "Seshanba", "Chorshanba", "Payshanba", "Juma", "Shanba", "Yakshanba"]
        today = datetime.now().weekday()
        msg = f"📅 *Bugungi darslar — {days_uz[today]}*\n\n"
        for l in lessons:
            msg += f"⏰ *{l['start_time'][:5]}-{l['end_time'][:5]}*\n"
            msg += f"📚 {l['subject']}\n"
            msg += f"🏛 {l['room']} | 👥 {l['group_name']}\n\n"
        await call.message.answer(msg, parse_mode="Markdown")
    await call.answer()

@dp.callback_query(F.data == "all_schedule")
async def all_schedule(call: CallbackQuery):
    msg = "📆 *Haftalik dars jadvalingiz*\n\n"
    has_any = False
    for day_num, day_name in DAYS.items():
        lessons = get_schedule(call.from_user.id, day_num)
        if lessons:
            has_any = True
            msg += f"*{day_name}:*\n"
            for l in lessons:
                msg += f"  ⏰ {l['start_time'][:5]}-{l['end_time'][:5]} — {l['subject']} ({l['room']})\n"
            msg += "\n"
    if not has_any:
        await call.message.answer("📭 Jadval bo'sh! Dars qo'shing.")
    else:
        await call.message.answer(msg, parse_mode="Markdown")
    await call.answer()

# ──────────────────────────────────────────
# VAZIFALAR
# ──────────────────────────────────────────

@dp.message(F.text == "✅ Vazifalar")
async def tasks_main(message: Message):
    user = get_user(message.from_user.id)
    if not user:
        await message.answer("Avval ro'yxatdan o'ting: /start")
        return
    await message.answer("✅ *Vazifalar*", reply_markup=tasks_menu(), parse_mode="Markdown")

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
        f"✅ *Vazifa qo'shildi!*\n📝 {data['title']}",
        reply_markup=main_menu(),
        parse_mode="Markdown"
    )

@dp.callback_query(F.data == "list_tasks")
async def list_tasks(call: CallbackQuery):
    tasks = get_tasks(call.from_user.id)
    if not tasks:
        await call.message.answer("🎉 Barcha vazifalar bajarilgan!")
        await call.answer()
        return

    for task in tasks:
        due = f"\n📅 Muddat: {task['due_date']}" if task.get('due_date') else ""
        desc = f"\n📄 {task['description']}" if task.get('description') else ""
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Bajarildi", callback_data=f"done_task_{task['id']}"),
                InlineKeyboardButton(text="🗑 O'chirish", callback_data=f"del_task_{task['id']}")
            ]
        ])
        await call.message.answer(
            f"📝 *{task['title']}*{desc}{due}",
            reply_markup=kb,
            parse_mode="Markdown"
        )
    await call.answer()

@dp.callback_query(F.data.startswith("done_task_"))
async def done_task(call: CallbackQuery):
    task_id = int(call.data.split("_")[-1])
    complete_task(task_id)
    await call.message.edit_text("✅ *Vazifa bajarildi!* Tabriklaymiz! 🎉", parse_mode="Markdown")
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
    await message.answer("🔔 *Eslatmalar*", reply_markup=reminders_menu(), parse_mode="Markdown")

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
    await state.update_data(time=message.text)
    await message.answer("🔂 Takrorlanishini tanlang:", reply_markup=repeat_keyboard())
    await state.set_state(ReminderState.repeat)

@dp.callback_query(F.data.startswith("repeat_"), ReminderState.repeat)
async def reminder_repeat(call: CallbackQuery, state: FSMContext):
    repeat = call.data.replace("repeat_", "")
    data = await state.get_data()
    remind_at = f"{data['date']}T{data['time']}:00+05:00"
    add_reminder(call.from_user.id, data["title"], remind_at, repeat)
    await state.clear()

    repeat_text = {"none": "Bir marta", "daily": "Har kuni", "weekly": "Har hafta"}
    await call.message.answer(
        f"✅ *Eslatma qo'shildi!*\n\n"
        f"📌 {data['title']}\n"
        f"📅 {data['date']} ⏰ {data['time']}\n"
        f"🔂 {repeat_text.get(repeat, repeat)}",
        reply_markup=main_menu(),
        parse_mode="Markdown"
    )
    await call.answer()

@dp.callback_query(F.data == "list_reminders")
async def list_reminders(call: CallbackQuery):
    reminders = get_user_reminders(call.from_user.id)
    if not reminders:
        await call.message.answer("📭 Faol eslatmalar yo'q!")
        await call.answer()
        return

    msg = "🔔 *Faol eslatmalar:*\n\n"
    for r in reminders:
        time_str = str(r["remind_at"])[:16].replace("T", " ")
        repeat_text = {"none": "Bir marta", "daily": "Har kuni", "weekly": "Har hafta"}
        msg += f"📌 *{r['title']}*\n"
        msg += f"⏰ {time_str} | 🔂 {repeat_text.get(r['repeat_type'], r['repeat_type'])}\n\n"
    await call.message.answer(msg, parse_mode="Markdown")
    await call.answer()

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
        [InlineKeyboardButton(text=f"🔕 Bezovta qilma rejimi: {dnd}", callback_data="toggle_dnd")],
    ])

    await message.answer(
        f"⚙️ *Sozlamalar*\n\n"
        f"🌅 Ertalabki xabar: *{str(settings.get('morning_time', '07:00'))[:5]}*\n"
        f"🌙 Kechki xulosa: *{str(settings.get('evening_time', '21:00'))[:5]}*\n"
        f"🔕 Bezovta qilma: *{dnd}*\n\n"
        f"30 daqiqa oldin eslatma: {'✅' if settings.get('notify_before_30') else '❌'}\n"
        f"10 daqiqa oldin eslatma: {'✅' if settings.get('notify_before_10') else '❌'}\n"
        f"Dars boshida eslatma: {'✅' if settings.get('notify_on_time') else '❌'}",
        reply_markup=kb,
        parse_mode="Markdown"
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
    await message.answer(f"✅ Ertalabki vaqt *{message.text}* ga o'zgartirildi!", parse_mode="Markdown")

@dp.callback_query(F.data == "set_evening")
async def set_evening(call: CallbackQuery, state: FSMContext):
    await call.message.answer("🌙 Yangi kechki vaqtni kiriting (masalan: 21:00):")
    await state.set_state(SettingsState.evening_time)
    await call.answer()

@dp.message(SettingsState.evening_time)
async def save_evening(message: Message, state: FSMContext):
    update_settings(message.from_user.id, {"evening_time": message.text})
    await state.clear()
    await message.answer(f"✅ Kechki vaqt *{message.text}* ga o'zgartirildi!", parse_mode="Markdown")

# ──────────────────────────────────────────
# ISHGA TUSHIRISH
# ──────────────────────────────────────────

async def main():
    setup_scheduler(bot)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
