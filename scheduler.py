import asyncio
import logging
from datetime import datetime, timezone, timedelta
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from database import (
    get_pending_reminders, mark_reminder_sent,
    supabase, get_settings
)

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────
# DARS OLDI ESLATMALARI (30 va 10 daqiqa)
# ──────────────────────────────────────────

async def check_upcoming_lessons(bot):
    """Har daqiqa ishga tushadi — dars oldi eslatmalari"""
    try:
        now = datetime.now()
        current_day = now.weekday()  # 0=Dushanba
        current_time = now.strftime("%H:%M")

        # 30 daqiqadan keyin bo'ladigan vaqt
        time_30 = (now + timedelta(minutes=30)).strftime("%H:%M")
        # 10 daqiqadan keyin bo'ladigan vaqt
        time_10 = (now + timedelta(minutes=10)).strftime("%H:%M")

        # Barcha foydalanuvchilarni olish
        users = supabase.table("users").select("telegram_id").execute().data

        for user in users:
            uid = user["telegram_id"]
            settings = get_settings(uid)
            if not settings:
                continue
            if settings.get("do_not_disturb"):
                continue

            # Darslarni tekshirish
            lessons = supabase.table("schedule").select("*").eq("user_id", uid).eq("day_of_week", current_day).execute().data

            for lesson in lessons:
                lesson_start = lesson["start_time"][:5]  # "HH:MM"

                # 30 daqiqa oldin eslatma
                if settings.get("notify_before_30") and lesson_start == time_30:
                    await bot.send_message(
                        uid,
                        f"📅 *30 daqiqadan dars boshlanadi!*\n\n"
                        f"📚 Fan: *{lesson['subject']}*\n"
                        f"🏛 Xona: *{lesson['room']}*\n"
                        f"👥 Guruh: *{lesson['group_name']}*\n"
                        f"⏰ Vaqt: *{lesson['start_time'][:5]} - {lesson['end_time'][:5]}*\n\n"
                        f"Tayyorlaning! 💪",
                        parse_mode="Markdown"
                    )

                # 10 daqiqa oldin eslatma
                if settings.get("notify_before_10") and lesson_start == time_10:
                    await bot.send_message(
                        uid,
                        f"⚡️ *10 daqiqa qoldi!*\n\n"
                        f"📚 Fan: *{lesson['subject']}*\n"
                        f"🏛 Xona: *{lesson['room']}*\n"
                        f"👥 Guruh: *{lesson['group_name']}*\n\n"
                        f"Tez yo'lga chiqing! 🏃",
                        parse_mode="Markdown"
                    )

                # Aynan dars vaqtida
                if settings.get("notify_on_time") and lesson_start == current_time:
                    await bot.send_message(
                        uid,
                        f"🔴 *DARS BOSHLANDI!*\n\n"
                        f"📚 *{lesson['subject']}*\n"
                        f"🏛 Xona: *{lesson['room']}*\n"
                        f"👥 Guruh: *{lesson['group_name']}*",
                        parse_mode="Markdown"
                    )

    except Exception as e:
        logger.error(f"check_upcoming_lessons xatosi: {e}")


# ──────────────────────────────────────────
# ERTALABKI XABAR
# ──────────────────────────────────────────

async def send_morning_message(bot):
    """Har kuni ertalab foydalanuvchi belgilagan vaqtda"""
    try:
        now = datetime.now()
        current_time = now.strftime("%H:%M")
        current_day = now.weekday()

        users = supabase.table("users").select("telegram_id, full_name").execute().data

        for user in users:
            uid = user["telegram_id"]
            settings = get_settings(uid)
            if not settings:
                continue
            if settings.get("do_not_disturb"):
                continue

            morning_time = str(settings.get("morning_time", "07:00"))[:5]

            if current_time == morning_time:
                # Bugungi darslarni olish
                lessons = supabase.table("schedule").select("*").eq("user_id", uid).eq("day_of_week", current_day).order("start_time").execute().data

                # Bajarilmagan vazifalarni olish
                tasks = supabase.table("tasks").select("*").eq("user_id", uid).eq("is_done", False).execute().data

                days_uz = ["Dushanba", "Seshanba", "Chorshanba", "Payshanba", "Juma", "Shanba", "Yakshanba"]
                today_name = days_uz[current_day]

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
                    for t in tasks[:3]:  # faqat 3 tasini ko'rsatamiz
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
    """Har kuni kechqurun xulosa yuborish"""
    try:
        now = datetime.now()
        current_time = now.strftime("%H:%M")

        users = supabase.table("users").select("telegram_id, full_name").execute().data

        for user in users:
            uid = user["telegram_id"]
            settings = get_settings(uid)
            if not settings:
                continue
            if settings.get("do_not_disturb"):
                continue

            evening_time = str(settings.get("evening_time", "21:00"))[:5]

            if current_time == evening_time:
                # Bugungi bajarilgan vazifalar
                done_tasks = supabase.table("tasks").select("*").eq("user_id", uid).eq("is_done", True).execute().data
                pending_tasks = supabase.table("tasks").select("*").eq("user_id", uid).eq("is_done", False).execute().data

                msg = f"🌙 *Kechqurun xulosa, {user['full_name']}!*\n\n"
                msg += f"✅ Bajarilgan vazifalar: *{len(done_tasks)} ta*\n"
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
# MAXSUS ESLATMALAR (foydalanuvchi qo'shgan)
# ──────────────────────────────────────────

async def check_custom_reminders(bot):
    """Foydalanuvchi qo'shgan eslatmalarni tekshirish"""
    try:
        reminders = get_pending_reminders()

        for reminder in reminders:
            uid = reminder["user_id"]
            settings = get_settings(uid)

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

            # Agar takroriy bo'lsa — yangi vaqt qo'shish
            if reminder["repeat_type"] == "daily":
                new_time = (datetime.fromisoformat(reminder["remind_at"]) + timedelta(days=1)).isoformat()
                supabase.table("reminders").insert({
                    "user_id": uid,
                    "title": reminder["title"],
                    "remind_at": new_time,
                    "repeat_type": "daily"
                }).execute()
            elif reminder["repeat_type"] == "weekly":
                new_time = (datetime.fromisoformat(reminder["remind_at"]) + timedelta(weeks=1)).isoformat()
                supabase.table("reminders").insert({
                    "user_id": uid,
                    "title": reminder["title"],
                    "remind_at": new_time,
                    "repeat_type": "weekly"
                }).execute()

    except Exception as e:
        logger.error(f"check_custom_reminders xatosi: {e}")


# ──────────────────────────────────────────
# SCHEDULER ISHGA TUSHIRISH
# ──────────────────────────────────────────

def setup_scheduler(bot):
    """Barcha vazifalarni schedulerga qo'shish"""
    scheduler = AsyncIOScheduler(timezone="Asia/Tashkent")

    # Har daqiqa — dars oldi eslatmalari va maxsus eslatmalar
    scheduler.add_job(check_upcoming_lessons, "interval", minutes=1, args=[bot])
    scheduler.add_job(check_custom_reminders, "interval", minutes=1, args=[bot])

    # Har daqiqa — ertalab va kechki xabarlar (vaqtni tekshirib yuboradi)
    scheduler.add_job(send_morning_message, "interval", minutes=1, args=[bot])
    scheduler.add_job(send_evening_summary, "interval", minutes=1, args=[bot])

    scheduler.start()
    logger.info("✅ Scheduler ishga tushdi!")
    return scheduler
