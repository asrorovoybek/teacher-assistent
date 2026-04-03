import os
from supabase import create_client, Client

# Supabase ulanish
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# ──────────────────────────────────────────
# FOYDALANUVCHI (users)
# ──────────────────────────────────────────

def get_user(telegram_id: int):
    """Foydalanuvchini ID bo'yicha olish"""
    res = supabase.table("users").select("*").eq("telegram_id", telegram_id).execute()
    return res.data[0] if res.data else None

def create_user(telegram_id: int, full_name: str):
    """Yangi foydalanuvchi yaratish"""
    supabase.table("users").insert({
        "telegram_id": telegram_id,
        "full_name": full_name
    }).execute()
    # Sozlamalarni ham yaratamiz
    supabase.table("user_settings").insert({
        "user_id": telegram_id
    }).execute()

def update_user(telegram_id: int, data: dict):
    """Foydalanuvchi ma'lumotlarini yangilash"""
    supabase.table("users").update(data).eq("telegram_id", telegram_id).execute()

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

def add_schedule(user_id: int, day: int, subject: str, room: str, group_name: str, start_time: str, end_time: str):
    """Yangi dars qo'shish"""
    supabase.table("schedule").insert({
        "user_id": user_id,
        "day_of_week": day,
        "subject": subject,
        "room": room,
        "group_name": group_name,
        "start_time": start_time,
        "end_time": end_time
    }).execute()

def get_schedule(user_id: int, day: int = None):
    """Jadval olish (kun bo'yicha yoki hammasi)"""
    query = supabase.table("schedule").select("*").eq("user_id", user_id)
    if day is not None:
        query = query.eq("day_of_week", day)
    res = query.order("start_time").execute()
    return res.data

def delete_schedule(schedule_id: int):
    """Jadvalni o'chirish"""
    supabase.table("schedule").delete().eq("id", schedule_id).execute()

def get_today_schedule(user_id: int):
    """Bugungi darslarni olish"""
    from datetime import datetime
    today = datetime.now().weekday()  # 0=Dushanba
    return get_schedule(user_id, today)

# ──────────────────────────────────────────
# VAZIFALAR (tasks)
# ──────────────────────────────────────────

def add_task(user_id: int, title: str, description: str = None, due_date: str = None):
    """Yangi vazifa qo'shish"""
    supabase.table("tasks").insert({
        "user_id": user_id,
        "title": title,
        "description": description,
        "due_date": due_date
    }).execute()

def get_tasks(user_id: int, only_undone: bool = True):
    """Vazifalarni olish"""
    query = supabase.table("tasks").select("*").eq("user_id", user_id)
    if only_undone:
        query = query.eq("is_done", False)
    res = query.order("due_date").execute()
    return res.data

def complete_task(task_id: int):
    """Vazifani bajarildi deb belgilash"""
    supabase.table("tasks").update({"is_done": True}).eq("id", task_id).execute()

def delete_task(task_id: int):
    """Vazifani o'chirish"""
    supabase.table("tasks").delete().eq("id", task_id).execute()

# ──────────────────────────────────────────
# ESLATMALAR (reminders)
# ──────────────────────────────────────────

def add_reminder(user_id: int, title: str, remind_at: str, repeat_type: str = "none"):
    """Yangi eslatma qo'shish"""
    supabase.table("reminders").insert({
        "user_id": user_id,
        "title": title,
        "remind_at": remind_at,
        "repeat_type": repeat_type
    }).execute()

def get_pending_reminders():
    """Yuborilmagan eslatmalarni olish"""
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()
    res = supabase.table("reminders").select("*").eq("is_sent", False).lte("remind_at", now).execute()
    return res.data

def mark_reminder_sent(reminder_id: int):
    """Eslatmani yuborildi deb belgilash"""
    supabase.table("reminders").update({"is_sent": True}).eq("id", reminder_id).execute()

def get_user_reminders(user_id: int):
    """Foydalanuvchi eslatmalarini olish"""
    res = supabase.table("reminders").select("*").eq("user_id", user_id).eq("is_sent", False).order("remind_at").execute()
    return res.data

# ──────────────────────────────────────────
# SOZLAMALAR (user_settings)
# ──────────────────────────────────────────

def get_settings(user_id: int):
    """Foydalanuvchi sozlamalarini olish"""
    res = supabase.table("user_settings").select("*").eq("user_id", user_id).execute()
    return res.data[0] if res.data else None

def update_settings(user_id: int, data: dict):
    """Sozlamalarni yangilash"""
    supabase.table("user_settings").update(data).eq("user_id", user_id).execute()
