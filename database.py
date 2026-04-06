import os
from supabase import create_client, Client

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# ──────────────────────────────────────────
# FOYDALANUVCHI (users)
# ──────────────────────────────────────────

def get_user(telegram_id: int):
    res = supabase.table("users").select("*").eq("telegram_id", telegram_id).execute()
    return res.data[0] if res.data else None

def create_user(telegram_id: int, full_name: str, username: str = None):
    supabase.table("users").insert({
        "telegram_id": telegram_id,
        "full_name": full_name,
        "username": username,
        "role": "user",
        "is_admin": False
    }).execute()
    supabase.table("user_settings").insert({
        "user_id": telegram_id
    }).execute()

def update_user(telegram_id: int, data: dict):
    supabase.table("users").update(data).eq("telegram_id", telegram_id).execute()

def is_admin(telegram_id: int) -> bool:
    res = supabase.table("users").select("is_admin").eq("telegram_id", telegram_id).execute()
    if res.data:
        return res.data[0].get("is_admin", False)
    return False

def get_all_users():
    res = supabase.table("users").select("*").execute()
    return res.data

def set_admin(telegram_id: int, status: bool):
    supabase.table("users").update({"is_admin": status}).eq("telegram_id", telegram_id).execute()

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
    }).execute()

def get_schedule(user_id: int, day: int = None):
    query = supabase.table("schedule").select("*").eq("user_id", user_id)
    if day is not None:
        query = query.eq("day_of_week", day)
    res = query.order("start_time").execute()
    return res.data

def delete_schedule(schedule_id: int):
    supabase.table("schedule").delete().eq("id", schedule_id).execute()

def get_today_schedule_by_week(user_id: int):
    """Bugungi darslarni hafta turi bilan filtrlash"""
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
    supabase.table("tasks").insert({
        "user_id": user_id,
        "title": title,
        "description": description,
        "due_date": due_date
    }).execute()

def get_tasks(user_id: int, only_undone: bool = True):
    query = supabase.table("tasks").select("*").eq("user_id", user_id)
    if only_undone:
        query = query.eq("is_done", False)
    res = query.order("due_date").execute()
    return res.data

def complete_task(task_id: int):
    supabase.table("tasks").update({"is_done": True}).eq("id", task_id).execute()

def delete_task(task_id: int):
    supabase.table("tasks").delete().eq("id", task_id).execute()

# ──────────────────────────────────────────
# ESLATMALAR (reminders)
# ──────────────────────────────────────────

def add_reminder(user_id: int, title: str, remind_at: str, repeat_type: str = "none"):
    supabase.table("reminders").insert({
        "user_id": user_id,
        "title": title,
        "remind_at": remind_at,
        "repeat_type": repeat_type
    }).execute()

def get_pending_reminders():
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()
    res = supabase.table("reminders").select("*").eq("is_sent", False).lte("remind_at", now).execute()
    return res.data

def mark_reminder_sent(reminder_id: int):
    supabase.table("reminders").update({"is_sent": True}).eq("id", reminder_id).execute()

def get_user_reminders(user_id: int):
    res = supabase.table("reminders").select("*").eq("user_id", user_id).eq("is_sent", False).order("remind_at").execute()
    return res.data

# ──────────────────────────────────────────
# SOZLAMALAR (user_settings)
# ──────────────────────────────────────────

def get_settings(user_id: int):
    res = supabase.table("user_settings").select("*").eq("user_id", user_id).execute()
    return res.data[0] if res.data else None

def update_settings(user_id: int, data: dict):
    supabase.table("user_settings").update(data).eq("user_id", user_id).execute()

# ──────────────────────────────────────────
# STATISTIKA (admin uchun)
# ──────────────────────────────────────────

def get_stats():
    users = supabase.table("users").select("telegram_id", count="exact").execute()
    tasks = supabase.table("tasks").select("id", count="exact").execute()
    schedules = supabase.table("schedule").select("id", count="exact").execute()
    reminders = supabase.table("reminders").select("id", count="exact").execute()
    return {
        "users": users.count or 0,
        "tasks": tasks.count or 0,
        "schedules": schedules.count or 0,
        "reminders": reminders.count or 0
    }
