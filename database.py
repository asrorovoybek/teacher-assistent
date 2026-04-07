import os
import logging
from supabase import create_client, Client

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────
# YORDAMCHI FUNKSIYA
# ──────────────────────────────────────────

def safe_execute(query, default=None):
    try:
        res = query.execute()
        return res
    except Exception as e:
        logger.error(f"Supabase xatosi: {e}")
        return default


# ──────────────────────────────────────────
# FOYDALANUVCHI (users)
# ──────────────────────────────────────────

def get_user(telegram_id: int):
    res = safe_execute(
        supabase.table("users").select("*").eq("telegram_id", telegram_id),
        default=None
    )
    if res and getattr(res, "data", None):
        return res.data[0]
    return None


def create_user(telegram_id: int, full_name: str, username: str = None):
    """
    Yangi foydalanuvchi yaratadi.
    Agar user oldin mavjud bo'lsa, qayta insert qilmaydi.
    """
    existing = get_user(telegram_id)
    if existing:
        return existing

    safe_execute(
        supabase.table("users").insert({
            "telegram_id": telegram_id,
            "full_name": full_name,
            "username": username,
            "role": "user",
            "is_admin": False
        })
    )

    safe_execute(
        supabase.table("user_settings").insert({
            "user_id": telegram_id
        })
    )

    return get_user(telegram_id)


def update_user(telegram_id: int, data: dict):
    safe_execute(
        supabase.table("users").update(data).eq("telegram_id", telegram_id)
    )


def is_admin(telegram_id: int) -> bool:
    res = safe_execute(
        supabase.table("users").select("is_admin").eq("telegram_id", telegram_id),
        default=None
    )
    if res and getattr(res, "data", None):
        return res.data[0].get("is_admin", False)
    return False


def get_all_users():
    res = safe_execute(
        supabase.table("users").select("*"),
        default=None
    )
    return res.data if res and getattr(res, "data", None) else []


def set_admin(telegram_id: int, status: bool):
    safe_execute(
        supabase.table("users").update({"is_admin": status}).eq("telegram_id", telegram_id)
    )


def delete_user(telegram_id: int):
    """
    Foydalanuvchini va unga tegishli asosiy ma'lumotlarni o'chiradi.
    Block qilgan userlarni avtomatik tozalash uchun ishlatiladi.
    """
    try:
        safe_execute(supabase.table("schedule").delete().eq("user_id", telegram_id))
        safe_execute(supabase.table("tasks").delete().eq("user_id", telegram_id))
        safe_execute(supabase.table("reminders").delete().eq("user_id", telegram_id))
        safe_execute(supabase.table("user_settings").delete().eq("user_id", telegram_id))
        safe_execute(supabase.table("users").delete().eq("telegram_id", telegram_id))
        logger.info(f"Foydalanuvchi o'chirildi: {telegram_id}")
        return True
    except Exception as e:
        logger.error(f"delete_user xatosi ({telegram_id}): {e}")
        return False


# ──────────────────────────────────────────
# DARS JADVALI (schedule)
# ──────────────────────────────────────────

DAYS = {
    0: "Dushanba",
    1: "Seshanba",
    2: "Chorshanba",
    3: "Payshanba",
    4: "Juma",
    5: "Shanba",
    6: "Yakshanba"
}

LESSON_TYPES = {
    "lecture": "📖 Ma'ruza",
    "practical": "✏️ Amaliy",
    "lab": "🔬 Laboratoriya",
    "course": "📝 Kurs ishi",
    "seminar": "💬 Seminar",
    "other": "📌 Boshqa"
}

WEEK_TYPES = {
    "every": "🔄 Har hafta",
    "odd": "1️⃣ Toq haftalar",
    "even": "2️⃣ Juft haftalar"
}


def add_schedule(user_id: int, day: int, subject: str, room: str, group_name: str,
                 start_time: str, end_time: str,
                 lesson_type: str = "other", week_type: str = "every"):
    safe_execute(
        supabase.table("schedule").insert({
            "user_id": user_id,
            "day_of_week": day,
            "subject": subject,
            "room": room,
            "group_name": group_name,
            "start_time": start_time,
            "end_time": end_time,
            "lesson_type": lesson_type,
            "week_type": week_type
        })
    )


def get_schedule(user_id: int, day: int = None):
    query = supabase.table("schedule").select("*").eq("user_id", user_id)
    if day is not None:
        query = query.eq("day_of_week", day)
    res = safe_execute(query.order("start_time"), default=None)
    return res.data if res and getattr(res, "data", None) else []


def delete_schedule(schedule_id: int):
    safe_execute(
        supabase.table("schedule").delete().eq("id", schedule_id)
    )


def get_today_schedule_by_week(user_id: int):
    from datetime import datetime, date
    today = datetime.now().weekday()
    all_lessons = get_schedule(user_id, today)
    week_number = date.today().isocalendar()[1]
    is_odd_week = (week_number % 2 == 1)

    result = []
    for lesson in all_lessons:
        wt = lesson.get("week_type", "every")
        if wt == "every":
            result.append(lesson)
        elif wt == "odd" and is_odd_week:
            result.append(lesson)
        elif wt == "even" and not is_odd_week:
            result.append(lesson)

    return result


# ──────────────────────────────────────────
# VAZIFALAR (tasks)
# ──────────────────────────────────────────

def add_task(user_id: int, title: str, description: str = None, due_date: str = None):
    safe_execute(
        supabase.table("tasks").insert({
            "user_id": user_id,
            "title": title,
            "description": description,
            "due_date": due_date
        })
    )


def get_tasks(user_id: int, only_undone: bool = True):
    query = supabase.table("tasks").select("*").eq("user_id", user_id)
    if only_undone:
        query = query.eq("is_done", False)
    res = safe_execute(query.order("due_date"), default=None)
    return res.data if res and getattr(res, "data", None) else []


def complete_task(task_id: int):
    safe_execute(
        supabase.table("tasks").update({"is_done": True}).eq("id", task_id)
    )


def delete_task(task_id: int):
    safe_execute(
        supabase.table("tasks").delete().eq("id", task_id)
    )


# ──────────────────────────────────────────
# ESLATMALAR (reminders)
# ──────────────────────────────────────────

def add_reminder(user_id: int, title: str, remind_at: str, repeat_type: str = "none"):
    safe_execute(
        supabase.table("reminders").insert({
            "user_id": user_id,
            "title": title,
            "remind_at": remind_at,
            "repeat_type": repeat_type
        })
    )


def get_pending_reminders():
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()
    res = safe_execute(
        supabase.table("reminders")
        .select("*")
        .eq("is_sent", False)
        .lte("remind_at", now),
        default=None
    )
    return res.data if res and getattr(res, "data", None) else []


def mark_reminder_sent(reminder_id: int):
    safe_execute(
        supabase.table("reminders").update({"is_sent": True}).eq("id", reminder_id)
    )


def get_user_reminders(user_id: int):
    res = safe_execute(
        supabase.table("reminders")
        .select("*")
        .eq("user_id", user_id)
        .eq("is_sent", False)
        .order("remind_at"),
        default=None
    )
    return res.data if res and getattr(res, "data", None) else []


# ──────────────────────────────────────────
# SOZLAMALAR (user_settings)
# ──────────────────────────────────────────

def get_settings(user_id: int):
    res = safe_execute(
        supabase.table("user_settings").select("*").eq("user_id", user_id),
        default=None
    )
    if res and getattr(res, "data", None):
        return res.data[0]
    return None


def update_settings(user_id: int, data: dict):
    safe_execute(
        supabase.table("user_settings").update(data).eq("user_id", user_id)
    )


# ──────────────────────────────────────────
# STATISTIKA (admin uchun)
# ──────────────────────────────────────────

def get_stats():
    users = safe_execute(
        supabase.table("users").select("telegram_id", count="exact"),
        default=None
    )
    tasks = safe_execute(
        supabase.table("tasks").select("id", count="exact"),
        default=None
    )
    schedules = safe_execute(
        supabase.table("schedule").select("id", count="exact"),
        default=None
    )
    reminders = safe_execute(
        supabase.table("reminders").select("id", count="exact"),
        default=None
    )

    return {
        "users": getattr(users, "count", 0) or 0,
        "tasks": getattr(tasks, "count", 0) or 0,
        "schedules": getattr(schedules, "count", 0) or 0,
        "reminders": getattr(reminders, "count", 0) or 0
    }
