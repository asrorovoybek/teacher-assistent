import logging
from datetime import datetime, timezone, timedelta, date
from html import escape

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from database import (
    get_pending_reminders,
    mark_reminder_sent,
    delete_user,
    supabase,
)

logger = logging.getLogger(__name__)

TZ = timezone(timedelta(hours=5))  # Asia/Tashkent

LESSON_TYPES = {
    "lecture": "📖 Ma'ruza",
    "practical": "✏️ Amaliy",
    "lab": "🔬 Laboratoriya",
    "course": "📝 Kurs ishi",
    "seminar": "💬 Seminar",
    "other": "📌 Boshqa",
}

DAYS_UZ = [
    "Dushanba", "Seshanba", "Chorshanba",
    "Payshanba", "Juma", "Shanba", "Yakshanba"
]


def h(text) -> str:
    return escape(str(text if text is not None else ""), quote=False)


def is_odd_week_today() -> bool:
    return date.today().isocalendar()[1] % 2 == 1


def lesson_matches_week(lesson: dict, odd_week: bool) -> bool:
    wt = lesson.get("week_type", "every")
    if wt == "every":
        return True
    if wt == "odd":
        return odd_week
    if wt == "even":
        return not odd_week
    return True


def is_inactive_user_error(err_text: str) -> bool:
    t = err_text.lower()
    return (
        "bot was blocked by the user" in t
        or "user is deactivated" in t
        or "chat not found" in t
        or "user not found" in t
        or "forbidden: bot was blocked by the user" in t
    )


async def safe_send_message(bot, user_id: int, text: str, *, parse_mode: str = "HTML") -> bool:
    try:
        await bot.send_message(user_id, text, parse_mode=parse_mode)
        return True
    except Exception as e:
        err = str(e)
        logger.error(f"send_message xatosi uid={user_id}: {err}")
        if is_inactive_user_error(err):
            deleted = delete_user(user_id)
            if deleted:
                logger.info(f"Inactive/block bo'lgan user bazadan o'chirildi: {user_id}")
        return False


# ──────────────────────────────────────────
# DARS OLDI ESLATMALARI (30 va 10 daqiqa)
# ──────────────────────────────────────────

async def check_upcoming_lessons(bot):
    try:
        now = datetime.now(TZ)
        current_day = now.weekday()
        current_time = now.strftime("%H:%M")
        time_30 = (now + timedelta(minutes=30)).strftime("%H:%M")
        time_10 = (now + timedelta(minutes=10)).strftime("%H:%M")
        odd_week = is_odd_week_today()

        all_settings = supabase.table("user_settings").select("*").execute().data
        settings_map = {s["user_id"]: s for s in all_settings}

        all_lessons = (
            supabase.table("schedule")
            .select("*")
            .eq("day_of_week", current_day)
            .execute()
            .data
        )

        for lesson in all_lessons:
            uid = lesson["user_id"]
            settings = settings_map.get(uid)
            if not settings or settings.get("do_not_disturb"):
                continue

            if not lesson_matches_week(lesson, odd_week):
                continue

            lesson_start = str(lesson.get("start_time", ""))[:5]
            lt = LESSON_TYPES.get(lesson.get("lesson_type", "other"), "📌 Boshqa")
            subject = h(lesson.get("subject", "—"))
            room = h(lesson.get("room", "—"))
            group_name = h(lesson.get("group_name", "—"))
            start_time = h(str(lesson.get("start_time", ""))[:5])
            end_time = h(str(lesson.get("end_time", ""))[:5])
            lt_html = h(lt)

            if settings.get("notify_before_30") and lesson_start == time_30:
                await safe_send_message(
                    bot,
                    uid,
                    (
                        "📅 <b>30 daqiqadan dars boshlanadi!</b>\n\n"
                        f"📚 Fan: <b>{subject}</b>\n"
                        f"📖 Turi: <b>{lt_html}</b>\n"
                        f"🏛 Xona: <b>{room}</b>\n"
                        f"👥 Guruh: <b>{group_name}</b>\n"
                        f"⏰ Vaqt: <b>{start_time} – {end_time}</b>\n\n"
                        "Tayyorlaning! 💪"
                    ),
                )

            if settings.get("notify_before_10") and lesson_start == time_10:
                await safe_send_message(
                    bot,
                    uid,
                    (
                        "⚡️ <b>10 daqiqa qoldi!</b>\n\n"
                        f"📚 Fan: <b>{subject}</b>\n"
                        f"📖 Turi: <b>{lt_html}</b>\n"
                        f"🏛 Xona: <b>{room}</b>\n"
                        f"👥 Guruh: <b>{group_name}</b>\n\n"
                        "Tez yo'lga chiqing! 🏃"
                    ),
                )

            if settings.get("notify_on_time") and lesson_start == current_time:
                await safe_send_message(
                    bot,
                    uid,
                    (
                        "🔴 <b>DARS BOSHLANDI!</b>\n\n"
                        f"📚 <b>{subject}</b>\n"
                        f"📖 Turi: <b>{lt_html}</b>\n"
                        f"🏛 Xona: <b>{room}</b>\n"
                        f"👥 Guruh: <b>{group_name}</b>"
                    ),
                )

    except Exception as e:
        logger.error(f"check_upcoming_lessons xatosi: {e}")


# ──────────────────────────────────────────
# ERTALABKI XABAR
# ──────────────────────────────────────────

async def send_morning_message(bot):
    try:
        now = datetime.now(TZ)
        current_time = now.strftime("%H:%M")
        current_day = now.weekday()
        today_name = DAYS_UZ[current_day]
        odd_week = is_odd_week_today()
        week_text = "Toq hafta" if odd_week else "Juft hafta"

        all_settings = supabase.table("user_settings").select("*").execute().data
        all_users = supabase.table("users").select("telegram_id, full_name").execute().data
        users_map = {u["telegram_id"]: u for u in all_users}

        all_lessons = (
            supabase.table("schedule")
            .select("*")
            .eq("day_of_week", current_day)
            .order("start_time")
            .execute()
            .data
        )
        lessons_map = {}
        for lesson in all_lessons:
            if lesson_matches_week(lesson, odd_week):
                lessons_map.setdefault(lesson["user_id"], []).append(lesson)

        all_tasks = supabase.table("tasks").select("*").eq("is_done", False).execute().data
        tasks_map = {}
        for task in all_tasks:
            tasks_map.setdefault(task["user_id"], []).append(task)

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
            full_name = h(user.get("full_name", "Foydalanuvchi"))

            msg = (
                f"🌅 <b>Xayrli tong, {full_name}!</b>\n"
                f"📆 Bugun: <b>{today_name}, {now.strftime('%d.%m.%Y')}</b>\n"
                f"🗓 Hafta turi: <b>{week_text}</b>\n\n"
            )

            if lessons:
                msg += f"📚 <b>Bugungi darslar ({len(lessons)} ta):</b>\n"
                for lesson in lessons:
                    msg += (
                        f"• <b>{h(str(lesson['start_time'])[:5])}</b> — "
                        f"{h(lesson['subject'])} ({h(lesson['room'])})\n"
                    )
            else:
                msg += "📚 Bugun dars yo'q!\n"

            if tasks:
                msg += f"\n✅ <b>Bajarilmagan vazifalar: {len(tasks)} ta</b>\n"
                for task in tasks[:3]:
                    msg += f"• {h(task['title'])}\n"
                if len(tasks) > 3:
                    msg += f"… va yana {len(tasks) - 3} ta\n"

            msg += "\n💪 <b>Samarali kun tilaymiz!</b>"
            await safe_send_message(bot, uid, msg)

    except Exception as e:
        logger.error(f"send_morning_message xatosi: {e}")


# ──────────────────────────────────────────
# KECHKI XULOSA
# ──────────────────────────────────────────

async def send_evening_summary(bot):
    try:
        now = datetime.now(TZ)
        current_time = now.strftime("%H:%M")

        all_settings = supabase.table("user_settings").select("*").execute().data
        all_users = supabase.table("users").select("telegram_id, full_name").execute().data
        users_map = {u["telegram_id"]: u for u in all_users}

        all_done = supabase.table("tasks").select("user_id").eq("is_done", True).execute().data
        all_pending = supabase.table("tasks").select("*").eq("is_done", False).execute().data

        done_map = {}
        for task in all_done:
            done_map[task["user_id"]] = done_map.get(task["user_id"], 0) + 1

        pending_map = {}
        for task in all_pending:
            pending_map.setdefault(task["user_id"], []).append(task)

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
            full_name = h(user.get("full_name", "Foydalanuvchi"))

            msg = (
                f"🌙 <b>Kechqurun xulosa, {full_name}!</b>\n\n"
                f"✅ Bajarilgan vazifalar: <b>{done_count} ta</b>\n"
                f"⏳ Kutayotgan vazifalar: <b>{len(pending_tasks)} ta</b>\n\n"
            )

            if pending_tasks:
                msg += "📋 <b>Ertaga bajarilishi kerak:</b>\n"
                for task in pending_tasks[:3]:
                    msg += f"• {h(task['title'])}\n"

            msg += "\n😴 <b>Yaxshi dam oling!</b>"
            await safe_send_message(bot, uid, msg)

    except Exception as e:
        logger.error(f"send_evening_summary xatosi: {e}")


# ──────────────────────────────────────────
# MAXSUS ESLATMALAR
# ──────────────────────────────────────────

async def check_custom_reminders(bot):
    try:
        reminders = get_pending_reminders()
        if not reminders:
            return

        all_settings = supabase.table("user_settings").select("*").execute().data
        settings_map = {s["user_id"]: s for s in all_settings}

        for reminder in reminders:
            uid = reminder["user_id"]
            settings = settings_map.get(uid)

            if settings and settings.get("do_not_disturb"):
                continue

            sent = await safe_send_message(
                bot,
                uid,
                (
                    "🔔 <b>ESLATMA!</b>\n\n"
                    f"📌 {h(reminder['title'])}\n\n"
                    "Bu eslatma siz tomondan o'rnatilgan edi."
                ),
            )
            if not sent:
                continue

            mark_reminder_sent(reminder["id"])

            if reminder["repeat_type"] == "daily":
                new_time = (datetime.fromisoformat(reminder["remind_at"]) + timedelta(days=1)).isoformat()
                supabase.table("reminders").insert({
                    "user_id": uid,
                    "title": reminder["title"],
                    "remind_at": new_time,
                    "repeat_type": "daily",
                }).execute()
            elif reminder["repeat_type"] == "weekly":
                new_time = (datetime.fromisoformat(reminder["remind_at"]) + timedelta(weeks=1)).isoformat()
                supabase.table("reminders").insert({
                    "user_id": uid,
                    "title": reminder["title"],
                    "remind_at": new_time,
                    "repeat_type": "weekly",
                }).execute()

    except Exception as e:
        logger.error(f"check_custom_reminders xatosi: {e}")


# ──────────────────────────────────────────
# SCHEDULER ISHGA TUSHIRISH
# ──────────────────────────────────────────


def setup_scheduler(bot):
    scheduler = AsyncIOScheduler(timezone="Asia/Tashkent")

    scheduler.add_job(check_upcoming_lessons, "interval", minutes=1, args=[bot], max_instances=1)
    scheduler.add_job(check_custom_reminders, "interval", minutes=1, args=[bot], max_instances=1)
    scheduler.add_job(send_morning_message, "interval", minutes=1, args=[bot], max_instances=1)
    scheduler.add_job(send_evening_summary, "interval", minutes=1, args=[bot], max_instances=1)

    scheduler.start()
    logger.info("✅ Scheduler ishga tushdi!")
    return scheduler
