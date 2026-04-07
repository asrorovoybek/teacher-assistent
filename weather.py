"""
Ob-havo moduli — Open-Meteo API (bepul, API key kerak emas)
"""

import aiohttp
import logging
from datetime import datetime, date

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────
# O'ZBEKISTON SHAHARLARI
# ──────────────────────────────────────────

UZ_CITIES = {
    "Toshkent":      (41.2995, 69.2401),
    "Samarqand":     (39.6542, 66.9597),
    "Buxoro":        (39.7680, 64.4219),
    "Namangan":      (41.0011, 71.6725),
    "Andijon":       (40.7821, 72.3442),
    "Farg'ona":      (40.3864, 71.7864),
    "Qarshi":        (38.8600, 65.7900),
    "Nukus":         (42.4600, 59.6100),
    "Termiz":        (37.2242, 67.2783),
    "Urganch":       (41.5500, 60.6333),
    "Navoiy":        (40.0900, 65.3800),
    "Jizzax":        (40.1158, 67.8422),
    "Guliston":      (40.4897, 68.7786),
    "Muborak":       (39.2700, 65.1500),
    "Denov":         (38.2700, 67.8900),
}

# ──────────────────────────────────────────
# OB-HAVO KODLARI
# ──────────────────────────────────────────

WMO_CODES = {
    0:  ("☀️", "Ochiq osmon"),
    1:  ("🌤", "Ko'pincha ochiq"),
    2:  ("⛅️", "Qisman bulutli"),
    3:  ("☁️", "Bulutli"),
    45: ("🌫", "Tuman"),
    48: ("🌫", "Muzlagan tuman"),
    51: ("🌦", "Yengil shivit"),
    53: ("🌦", "O'rtacha shivit"),
    55: ("🌧", "Kuchli shivit"),
    61: ("🌧", "Yengil yomg'ir"),
    63: ("🌧", "O'rtacha yomg'ir"),
    65: ("🌧", "Kuchli yomg'ir"),
    71: ("🌨", "Yengil qor"),
    73: ("❄️", "O'rtacha qor"),
    75: ("❄️", "Kuchli qor"),
    77: ("🌨", "Qor donalari"),
    80: ("🌦", "Yengil jala"),
    81: ("🌧", "O'rtacha jala"),
    82: ("⛈", "Kuchli jala"),
    85: ("🌨", "Qorli jala"),
    86: ("❄️", "Kuchli qorli jala"),
    95: ("⛈", "Momaqaldiroq"),
    96: ("⛈", "Do'l bilan momaqaldiroq"),
    99: ("⛈", "Kuchli do'l bilan momaqaldiroq"),
}

def get_wmo(code: int):
    return WMO_CODES.get(code, ("🌡", "Noma'lum"))

def wind_direction(deg: float) -> str:
    dirs = [
        "⬆️ Sh", "↗️ Sh-Sh.S", "➡️ Sh.S", "↘️ J-Sh.S",
        "⬇️ J", "↙️ J-G'", "⬅️ G'", "↖️ Sh-G'"
    ]
    return dirs[round(deg / 45) % 8]

def uv_level(uv: float) -> str:
    if uv < 3:
        return "Past 🟢"
    if uv < 6:
        return "O'rtacha 🟡"
    if uv < 8:
        return "Yuqori 🟠"
    if uv < 11:
        return "Juda yuqori 🔴"
    return "Ekstremal 🟣"

# ──────────────────────────────────────────
# API
# ──────────────────────────────────────────

BASE_URL = "https://api.open-meteo.com/v1/forecast"
GEO_URL = "https://geocoding-api.open-meteo.com/v1/search"

async def fetch_weather(lat: float, lon: float) -> dict | None:
    params = {
        "latitude": lat,
        "longitude": lon,
        "current": [
            # DIQQAT: bu yerga "time" qo'shilmaydi
            "temperature_2m",
            "apparent_temperature",
            "relative_humidity_2m",
            "precipitation",
            "weather_code",
            "wind_speed_10m",
            "wind_direction_10m",
            "surface_pressure",
            "uv_index",
            "visibility",
            "is_day"
        ],
        "daily": [
            "weather_code",
            "temperature_2m_max",
            "temperature_2m_min",
            "precipitation_sum",
            "precipitation_probability_max",
            "wind_speed_10m_max",
            "uv_index_max",
            "sunrise",
            "sunset",
        ],
        "hourly": [
            "temperature_2m",
            "precipitation_probability",
            "weather_code",
        ],
        "timezone": "Asia/Tashkent",
        "forecast_days": 5,
    }

    try:
        timeout = aiohttp.ClientTimeout(total=15)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(BASE_URL, params=params) as resp:
                if resp.status == 200:
                    return await resp.json()

                body = await resp.text()
                logger.error(f"fetch_weather HTTP {resp.status}: {body}")
                return None

    except Exception as e:
        logger.exception(f"fetch_weather xatosi: {e}")
        return None

async def geocode_city(city_name: str) -> tuple | None:
    params = {
        "name": city_name,
        "count": 1,
        "language": "uz",
        "format": "json"
    }

    try:
        timeout = aiohttp.ClientTimeout(total=10)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(GEO_URL, params=params) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    results = data.get("results", [])
                    if results:
                        r = results[0]
                        return r["latitude"], r["longitude"], r["name"]

                body = await resp.text()
                logger.error(f"geocode_city HTTP {resp.status}: {body}")
                return None

    except Exception as e:
        logger.exception(f"geocode_city xatosi: {e}")
        return None

# ──────────────────────────────────────────
# FORMATLASH
# ──────────────────────────────────────────

def format_current_weather(data: dict, city_name: str) -> str:
    c = data["current"]
    d = data["daily"]

    code = c["weather_code"]
    emoji, desc = get_wmo(code)

    temp = c["temperature_2m"]
    feels = c["apparent_temperature"]
    humidity = c["relative_humidity_2m"]
    wind_spd = c["wind_speed_10m"]
    wind_dir = wind_direction(c["wind_direction_10m"])
    pressure = c["surface_pressure"]
    uv = c.get("uv_index", 0)
    vis = c.get("visibility", 0)

    t_max = d["temperature_2m_max"][0]
    t_min = d["temperature_2m_min"][0]
    precip_prob = d["precipitation_probability_max"][0]
    sunrise = str(d["sunrise"][0])[11:16]
    sunset = str(d["sunset"][0])[11:16]

    current_api_time = c.get("time")
    if current_api_time:
        try:
            dt = datetime.fromisoformat(current_api_time)
            time_str = dt.strftime("%d.%m.%Y %H:%M")
        except Exception:
            time_str = str(current_api_time).replace("T", " ")
    else:
        time_str = datetime.now().strftime("%d.%m.%Y %H:%M")

    msg = (
        f"{emoji} <b>{city_name} — Hozirgi ob-havo</b>\n"
        f"🕐 {time_str} (UTC+5)\n\n"
        f"🌡 Harorat: <b>{temp:+.0f}°C</b> (his qilinadi: <b>{feels:+.0f}°C</b>)\n"
        f"📊 Bugun: {t_min:+.0f}°C / {t_max:+.0f}°C\n"
        f"☁️ Holat: <b>{desc}</b>\n\n"
        f"💧 Namlik: <b>{humidity}%</b>\n"
        f"🌬 Shamol: <b>{wind_spd:.0f} km/soat</b> {wind_dir}\n"
        f"🔻 Bosim: <b>{pressure:.0f} hPa</b>\n"
        f"🌂 Yog'in ehtimoli: <b>{precip_prob}%</b>\n"
        f"☀️ UV indeks: <b>{uv_level(uv)}</b>\n"
        f"👁 Ko'rinish: <b>{vis/1000:.0f} km</b>\n\n"
        f"🌅 Tong: <b>{sunrise}</b> | 🌇 Shom: <b>{sunset}</b>\n"
    )
    return msg

def format_forecast_5day(data: dict, city_name: str) -> str:
    d = data["daily"]
    days_uz = ["Dushanba", "Seshanba", "Chorshanba", "Payshanba", "Juma", "Shanba", "Yakshanba"]

    msg = f"📅 <b>{city_name} — 5 kunlik prognoz</b>\n\n"
    dates = d.get("time", [])

    for i in range(min(5, len(dates))):
        date_str = dates[i][:10]
        day_date = date.fromisoformat(date_str)
        weekday = days_uz[day_date.weekday()]
        date_fmt = day_date.strftime("%d.%m")

        code = d["weather_code"][i]
        emoji, desc = get_wmo(code)
        t_max = d["temperature_2m_max"][i]
        t_min = d["temperature_2m_min"][i]
        precip = d["precipitation_sum"][i]
        precip_prob = d["precipitation_probability_max"][i]
        wind = d["wind_speed_10m_max"][i]

        msg += (
            f"{emoji} <b>{weekday}, {date_fmt}</b>\n"
            f"   🌡 {t_min:+.0f}°C / {t_max:+.0f}°C  |  {desc}\n"
            f"   🌂 {precip_prob}%  💧 {precip:.1f} mm  🌬 {wind:.0f} km/soat\n\n"
        )

    return msg

def format_hourly_today(data: dict, city_name: str) -> str:
    h = data["hourly"]

    current_api_time = data.get("current", {}).get("time")
    if current_api_time:
        now_dt = datetime.fromisoformat(current_api_time)
        today_str = now_dt.date().isoformat()
        now_hour = now_dt.hour
    else:
        now_dt = datetime.now()
        today_str = date.today().isoformat()
        now_hour = now_dt.hour

    msg = f"⏱ <b>{city_name} — Bugungi soatlik prognoz</b>\n\n"
    count = 0

    for i, time_str in enumerate(h["time"]):
        if not time_str.startswith(today_str):
            continue

        hour = int(time_str[11:13])
        if hour < now_hour:
            continue

        if count >= 8:
            break

        code = h["weather_code"][i]
        emoji, _ = get_wmo(code)
        temp = h["temperature_2m"][i]
        rain = h["precipitation_probability"][i]

        msg += f"{hour:02d}:00  {emoji} <b>{temp:+.0f}°C</b>  🌂{rain}%\n"
        count += 1

    if count == 0:
        msg += "Bugun uchun soatlik ma'lumot tugadi.\n"

    return msg
