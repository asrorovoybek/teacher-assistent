import asyncio
import logging
from datetime import datetime, timezone, timedelta, date
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from database import (
    get_pending_reminders, mark_reminder_sent,
    supabase
)

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────
# DARS OLDI ESLATMALARI (30 va 10 daqiqa)
# ──────────────────────────────────────────

async def check_upcoming_lessons(bot):
    try:
        # UTC+5 Toshkent vaqti
        now = datetime.now(timezone(timedelta(hours=5)))
        current_day = now.weekday()
        current_time = now.strftime("%H:%M")
        time_30 = (now + timedelta(minutes=30)).strftime("%H:%M")
        time_10 = (now + timedelta(minutes=10)).strftime("%H:%M")

        # Hozirgi hafta toqmi yoki juftmi
        from datetime import date
        week_number = date.today().isocalendar()[1]
        is_odd_week = (week_number % 2 == 1)

        all_settings = supabase.table("user_settings").select("*").execute().data
        settings_map = {s["user_id"]: s for s in all_settings}

        all_lessons = supabase.table("schedule").select("*").eq("day_of_week", current_day).execute().data

        # Dars turi matnlari
        LESSON_TYPES = {
            "lecture": "📖 Ma'ruza",
            "practical": "✏️ Amaliy",
            "lab": "🔬 Laboratoriya",
            "course": "📝 Kurs ishi",
            "seminar": "💬 Seminar",
            "other": "📌 Boshqa"
        }

        for lesson in all_lessons:
            uid = lesson["user_id"]
            settings = settings_map.get(uid)
            if not settings or settings.get("do_not_disturb"):
                continue

            # Toq/juft hafta filtri
            wt = lesson.get("week_type", "every")
            if wt == "odd" and not is_odd_week:
                continue
            if wt == "even" and is_odd_week:
                continue

            lesson_start = lesson["start_time"][:5]
            lt = LESSON_TYPES.get(lesson.get("lesson_type", "other"), "📌 Boshqa")

            if settings.get("notify_before_30") and lesson_start == time_30:
                await bot.send_message(uid,
                    f"📅 *30 daqiqadan dars boshlanadi!*\n\n"
                    f"📚 Fan: *{lesson['subject']}*\n"
                    f"📖 Turi: *{lt}*\n"
                    f"🏛 Xona: *{lesson['room']}*\n"
                    f"👥 Guruh: *{lesson['group_name']}*\n"
                    f"⏰ Vaqt: *{lesson['start_time'][:5]} – {lesson['end_time'][:5]}*\n\n"
                    f"Tayyorlaning! 💪",
                    parse_mode="Markdown")

            if settings.get("notify_before_10") and lesson_start == time_10:
                await bot.send_message(uid,
                    f"⚡️ *10 daqiqa qoldi!*\n\n"
                    f"📚 Fan: *{lesson['subject']}*\n"
                    f"📖 Turi: *{lt}*\n"
                    f"🏛 Xona: *{lesson['room']}*\n"
                    f"👥 Guruh: *{lesson['group_name']}*\n\n"
                    f"Tez yo'lga chiqing! 🏃",
                    parse_mode="Markdown")

            if settings.get("notify_on_time") and lesson_start == current_time:
                await bot.send_message(uid,
                    f"🔴 *DARS BOSHLANDI!*\n\n"
                    f"📚 *{lesson['subject']}*\n"
                    f"📖 Turi: *{lt}*\n"
                    f"🏛 Xona: *{lesson['room']}*\n"
                    f"👥 Guruh: *{lesson['group_name']}*",
                    parse_mode="Markdown")

    except Exception as e:
        logger.error(f"check_upcoming_lessons xatosi: {e}")

# ──────────────────────────────────────────
# ERTALABKI XABAR
# ──────────────────────────────────────────

async def send_morning_message(bot):
    """Har kuni ertalab — BITTA so'rov bilan"""
    try:
        now = datetime.now()
        current_time = now.strftime("%H:%M")
        current_day = now.weekday()
        days_uz = ["Dushanba", "Seshanba", "Chorshanba", "Payshanba", "Juma", "Shanba", "Yakshanba"]
        today_name = days_uz[current_day]

        # Barcha sozlamalar va foydalanuvchilarni BITTA so'rovda
        all_settings = supabase.table("user_settings").select("*").execute().data
        all_users = supabase.table("users").select("telegram_id, full_name").execute().data
        users_map = {u["telegram_id"]: u for u in all_users}

        # Bugungi barcha darslar BITTA so'rovda
        all_lessons = supabase.table("schedule").select("*").eq("day_of_week", current_day).order("start_time").execute().data
        lessons_map = {}
        for l in all_lessons:
            lessons_map.setdefault(l["user_id"], []).append(l)

        # Barcha bajarilmagan vazifalar BITTA so'rovda
        all_tasks = supabase.table("tasks").select("*").eq("is_done", False).execute().data
        tasks_map = {}
        for t in all_tasks:
            tasks_map.setdefault(t["user_id"], []).append(t)

        for settings in all_settings:
            uid = settings["user_id"]
            if settings.get("do_not_disturb"):
                continue

            morning_time = str(settings.get("morning_time", "07:00"))[:5]
            if current_time != morning_time:
                continue

            user = users_map.get(uid)
            if not user:
                continue

            lessons = lessons_map.get(uid, [])
            tasks = tasks_map.get(uid, [])

            msg = f"🌅 *Xayrli tong, {user['full_name']}!*\n"
            msg += f"📆 Bugun: *{today_name}, {now.strftime('%d.%m.%Y')}*\n\n"

            if lessons:
                msg += f"📚 *Bugungi darslar ({len(lessons)} ta):*\n"
                for l in lessons:
                    msg += f"  ⏰ {l['start_time'][:5]} — {l['subject']} ({l['room']})\n"
            else:
                msg += "📚 Bugun dars yo'q!\n"

            if tasks:
                msg += f"\n✅ *Bajarilmagan vazifalar: {len(tasks)} ta*\n"
                for t in tasks[:3]:
                    msg += f"  • {t['title']}\n"
                if len(tasks) > 3:
                    msg += f"  _...va yana {len(tasks)-3} ta_\n"

            msg += "\n💪 *Samarali kun tilaymiz!*"

            await bot.send_message(uid, msg, parse_mode="Markdown")

    except Exception as e:
        logger.error(f"send_morning_message xatosi: {e}")


# ──────────────────────────────────────────
# KECHKI XULOSA
# ──────────────────────────────────────────

async def send_evening_summary(bot):
    """Har kuni kechqurun — BITTA so'rov bilan"""
    try:
        now = datetime.now()
        current_time = now.strftime("%H:%M")

        all_settings = supabase.table("user_settings").select("*").execute().data
        all_users = supabase.table("users").select("telegram_id, full_name").execute().data
        users_map = {u["telegram_id"]: u for u in all_users}

        # Barcha vazifalarni BITTA so'rovda
        all_done = supabase.table("tasks").select("user_id").eq("is_done", True).execute().data
        all_pending = supabase.table("tasks").select("*").eq("is_done", False).execute().data

        done_map = {}
        for t in all_done:
            done_map[t["user_id"]] = done_map.get(t["user_id"], 0) + 1

        pending_map = {}
        for t in all_pending:
            pending_map.setdefault(t["user_id"], []).append(t)

        for settings in all_settings:
            uid = settings["user_id"]
            if settings.get("do_not_disturb"):
                continue

            evening_time = str(settings.get("evening_time", "21:00"))[:5]
            if current_time != evening_time:
                continue

            user = users_map.get(uid)
            if not user:
                continue

            done_count = done_map.get(uid, 0)
            pending_tasks = pending_map.get(uid, [])

            msg = f"🌙 *Kechqurun xulosa, {user['full_name']}!*\n\n"
            msg += f"✅ Bajarilgan vazifalar: *{done_count} ta*\n"
            msg += f"⏳ Kutayotgan vazifalar: *{len(pending_tasks)} ta*\n\n"

            if pending_tasks:
                msg += "📋 *Ertaga bajarilishi kerak:*\n"
                for t in pending_tasks[:3]:
                    msg += f"  • {t['title']}\n"

            msg += "\n😴 *Yaxshi dam oling!*"

            await bot.send_message(uid, msg, parse_mode="Markdown")

    except Exception as e:
        logger.error(f"send_evening_summary xatosi: {e}")


# ──────────────────────────────────────────
# MAXSUS ESLATMALAR
# ──────────────────────────────────────────

async def check_custom_reminders(bot):
    """Foydalanuvchi qo'shgan eslatmalarni tekshirish"""
    try:
        reminders = get_pending_reminders()
        if not reminders:
            return

        # Barcha sozlamalarni BITTA so'rovda
        all_settings = supabase.table("user_settings").select("*").execute().data
        settings_map = {s["user_id"]: s for s in all_settings}

        for reminder in reminders:
            uid = reminder["user_id"]
            settings = settings_map.get(uid)

            if settings and settings.get("do_not_disturb"):
                continue

            await bot.send_message(
                uid,
                f"🔔 *ESLATMA!*\n\n"
                f"📌 {reminder['title']}\n\n"
                f"_Bu eslatma siz tomondan o'rnatilgan edi._",
                parse_mode="Markdown"
            )
            mark_reminder_sent(reminder["id"])

            if reminder["repeat_type"] == "daily":
                new_time = (datetime.fromisoformat(reminder["remind_at"]) + timedelta(days=1)).isoformat()
                supabase.table("reminders").insert({
                    "user_id": uid, "title": reminder["title"],
                    "remind_at": new_time, "repeat_type": "daily"
                }).execute()
            elif reminder["repeat_type"] == "weekly":
                new_time = (datetime.fromisoformat(reminder["remind_at"]) + timedelta(weeks=1)).isoformat()
                supabase.table("reminders").insert({
                    "user_id": uid, "title": reminder["title"],
                    "remind_at": new_time, "repeat_type": "weekly"
                }).execute()

    except Exception as e:
        logger.error(f"check_custom_reminders xatosi: {e}")


# ──────────────────────────────────────────
# SCHEDULER ISHGA TUSHIRISH
# ──────────────────────────────────────────

def setup_scheduler(bot):
    scheduler = AsyncIOScheduler(timezone="Asia/Tashkent")

    # max_instances=1 — eski job tugamay yangi boshlanmaydi
    scheduler.add_job(check_upcoming_lessons, "interval", minutes=1, args=[bot], max_instances=1)
    scheduler.add_job(check_custom_reminders, "interval", minutes=1, args=[bot], max_instances=1)
    scheduler.add_job(send_morning_message,   "interval", minutes=1, args=[bot], max_instances=1)
    scheduler.add_job(send_evening_summary,   "interval", minutes=1, args=[bot], max_instances=1)

    scheduler.start()
    logger.info("✅ Scheduler ishga tushdi!")
    return scheduler
