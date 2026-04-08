"""
Pro ob-havo moduli — WeatherAPI asosida, smart cache bilan
Moslik:
- UZ_CITIES
- fetch_weather(lat, lon)
- geocode_city(city_name)
- format_current_weather(data, city_name)
- format_forecast_5day(data, city_name)
- format_hourly_today(data, city_name)

Environment:
- WEATHER_API_KEY=...

Qo'shimcha:
- smart cache
- bir xil so'rovni qayta yubormaslik
- server yukini kamaytirish
"""

import os
import aiohttp
import asyncio
import logging
from datetime import datetime
from time import time

logger = logging.getLogger(__name__)

API_KEY = os.getenv("WEATHER_API_KEY")
BASE_URL = "https://api.weatherapi.com/v1"

# ──────────────────────────────────────────
# CACHE SOZLAMALARI
# ──────────────────────────────────────────

# Hozirgi ob-havo va forecast uchun cache muddati
WEATHER_CACHE_TTL = 600   # 10 daqiqa

# Geocoding uchun cache muddati
GEOCODE_CACHE_TTL = 86400  # 24 soat

# Maksimal cache hajmi
MAX_WEATHER_CACHE = 300
MAX_GEOCODE_CACHE = 300

_weather_cache: dict = {}
_geocode_cache: dict = {}

# Bir xil paytdagi takroriy so'rovlarni bitta requestga birlashtirish
_inflight_weather: dict = {}
_inflight_geocode: dict = {}

_cache_lock = asyncio.Lock()

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

DAYS_UZ = ["Dushanba", "Seshanba", "Chorshanba", "Payshanba", "Juma", "Shanba", "Yakshanba"]

CONDITION_MAP = {
    "sunny": "Quyoshli",
    "clear": "Ochiq osmon",
    "partly cloudy": "Qisman bulutli",
    "cloudy": "Bulutli",
    "overcast": "Qalin bulutli",
    "mist": "Tuman",
    "fog": "Tuman",
    "freezing fog": "Muzlagan tuman",
    "patchy rain possible": "Yomg'ir ehtimoli bor",
    "patchy rain nearby": "Atrofda yomg'ir ehtimoli bor",
    "patchy light drizzle": "Yengil shivit",
    "light drizzle": "Yengil shivit",
    "freezing drizzle": "Muzli shivit",
    "heavy freezing drizzle": "Kuchli muzli shivit",
    "patchy light rain": "Yengil yomg'ir",
    "light rain": "Yengil yomg'ir",
    "moderate rain at times": "Ba'zida o'rtacha yomg'ir",
    "moderate rain": "O'rtacha yomg'ir",
    "heavy rain at times": "Ba'zida kuchli yomg'ir",
    "heavy rain": "Kuchli yomg'ir",
    "light freezing rain": "Yengil muzli yomg'ir",
    "moderate or heavy freezing rain": "Kuchli muzli yomg'ir",
    "light rain shower": "Yengil jala",
    "moderate rain shower": "O'rtacha jala",
    "moderate or heavy rain shower": "Kuchli jala",
    "torrential rain shower": "Juda kuchli jala",
    "thundery outbreaks possible": "Momaqaldiroq ehtimoli bor",
    "patchy light rain with thunder": "Yomg'ir va momaqaldiroq",
    "moderate or heavy rain with thunder": "Kuchli yomg'ir va momaqaldiroq",
    "patchy snow possible": "Qor ehtimoli bor",
    "patchy light snow": "Yengil qor",
    "light snow": "Yengil qor",
    "patchy moderate snow": "O'rtacha qor",
    "moderate snow": "O'rtacha qor",
    "patchy heavy snow": "Kuchli qor",
    "heavy snow": "Kuchli qor",
    "blowing snow": "Qor bo'roni",
    "blizzard": "Kuchli qor bo'roni",
    "patchy sleet possible": "Qor-yomg'ir ehtimoli bor",
    "light sleet": "Yengil qor-yomg'ir",
    "moderate or heavy sleet": "Kuchli qor-yomg'ir",
    "light snow showers": "Yengil qor yog'ishi",
    "moderate or heavy snow showers": "Kuchli qor yog'ishi",
    "ice pellets": "Muz donalari",
    "light showers of ice pellets": "Yengil muz donalari",
    "moderate or heavy showers of ice pellets": "Kuchli muz donalari",
    "patchy light snow with thunder": "Qor va momaqaldiroq",
    "moderate or heavy snow with thunder": "Kuchli qor va momaqaldiroq",
}

# ──────────────────────────────────────────
# CACHE YORDAMCHI FUNKSIYALAR
# ──────────────────────────────────────────

def _make_weather_key(lat: float, lon: float) -> str:
    # Koordinatalarni biroz yumaloqlab, juda yaqin joylarni bitta keyga tushiramiz
    return f"{round(float(lat), 4)},{round(float(lon), 4)}"

def _make_geocode_key(city_name: str) -> str:
    return " ".join((city_name or "").strip().lower().split())

def _cache_get(cache: dict, key: str, ttl: int):
    item = cache.get(key)
    if not item:
        return None
    if time() - item["ts"] > ttl:
        cache.pop(key, None)
        return None
    return item["data"]

def _cache_set(cache: dict, key: str, data, max_size: int):
    if len(cache) >= max_size:
        oldest_key = min(cache.keys(), key=lambda k: cache[k]["ts"])
        cache.pop(oldest_key, None)
    cache[key] = {"data": data, "ts": time()}

# ──────────────────────────────────────────
# YORDAMCHI FUNKSIYALAR
# ──────────────────────────────────────────

def safe_num(value, default=0):
    try:
        return float(value)
    except Exception:
        return default

def format_local_datetime(localtime_str: str) -> str:
    try:
        dt = datetime.strptime(localtime_str, "%Y-%m-%d %H:%M")
        return dt.strftime("%d.%m.%Y %H:%M")
    except Exception:
        return localtime_str or "—"

def detect_season(month: int) -> str:
    if month in (12, 1, 2):
        return "qish"
    if month in (3, 4, 5):
        return "bahor"
    if month in (6, 7, 8):
        return "yoz"
    return "kuz"

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

def aqi_level(pm25):
    if pm25 is None:
        return "—"
    if pm25 <= 12:
        return "Yaxshi 🟢"
    if pm25 <= 35.4:
        return "O'rtacha 🟡"
    if pm25 <= 55.4:
        return "Sezgirlar uchun zararli 🟠"
    if pm25 <= 150.4:
        return "Zararli 🔴"
    return "Juda zararli 🟣"

def wind_direction(deg: float) -> str:
    dirs = ["⬆️ Sh", "↗️ Sh-Sh.S", "➡️ Sh.S", "↘️ J-Sh.S",
            "⬇️ J", "↙️ J-G'", "⬅️ G'", "↖️ Sh-G'"]
    return dirs[round(deg / 45) % 8]

def condition_emoji(condition_text: str) -> str:
    c = (condition_text or "").lower()
    if "thunder" in c:
        return "⛈"
    if "snow" in c or "blizzard" in c or "ice" in c:
        return "❄️"
    if "sleet" in c:
        return "🌨"
    if "rain" in c or "drizzle" in c or "shower" in c:
        return "🌧"
    if "fog" in c or "mist" in c:
        return "🌫"
    if "overcast" in c:
        return "☁️"
    if "cloud" in c:
        return "☁️"
    if "sunny" in c or "clear" in c:
        return "☀️"
    return "🌤"

def translate_condition(condition_text: str) -> str:
    if not condition_text:
        return "Noma'lum"

    lower = condition_text.strip().lower()
    if lower in CONDITION_MAP:
        return CONDITION_MAP[lower]

    if "freezing fog" in lower:
        return "Muzlagan tuman"
    if "fog" in lower or "mist" in lower:
        return "Tuman"
    if "thunder" in lower:
        return "Momaqaldiroq"
    if "snow" in lower:
        return "Qor"
    if "sleet" in lower:
        return "Qor-yomg'ir"
    if "ice" in lower:
        return "Muzli yog'in"
    if "drizzle" in lower:
        return "Shivit"
    if "shower" in lower:
        return "Jala"
    if "rain" in lower:
        return "Yomg'ir"
    if "overcast" in lower:
        return "Qalin bulutli"
    if "cloud" in lower:
        return "Bulutli"
    if "sun" in lower or "clear" in lower:
        return "Quyoshli"

    return condition_text

def translate_severity(text: str) -> str:
    t = (text or "").lower()
    if "minor" in t:
        return "Past"
    if "moderate" in t:
        return "O'rtacha"
    if "severe" in t:
        return "Kuchli"
    if "extreme" in t:
        return "Juda kuchli"
    return text or "—"

def translate_alert(text: str) -> str:
    t = (text or "").lower()
    if "лавин" in t or "avalanche" in t:
        return "Qor ko‘chishi xavfi"
    if "storm" in t or "буря" in t:
        return "Bo‘ron xavfi"
    if "heavy rain" in t or "сильный дожд" in t:
        return "Kuchli yomg‘ir ogohlantirishi"
    if "rain" in t or "дожд" in t:
        return "Yomg‘ir ogohlantirishi"
    if "snow" in t or "снег" in t:
        return "Qor ogohlantirishi"
    if "wind" in t or "ветер" in t:
        return "Kuchli shamol ogohlantirishi"
    if "fog" in t or "туман" in t:
        return "Tuman ogohlantirishi"
    if "heat" in t or "жара" in t:
        return "Issiq havo ogohlantirishi"
    if "cold" in t or "мороз" in t:
        return "Sovuq havo ogohlantirishi"
    if "thunder" in t or "гроза" in t:
        return "Momaqaldiroq ogohlantirishi"
    if "flood" in t or "наводнен" in t:
        return "Suv toshqini ogohlantirishi"
    if "dust" in t or "пыль" in t:
        return "Chang-to‘zon ogohlantirishi"
    if "ice" in t or "гололед" in t:
        return "Muzlama ogohlantirishi"
    return text or "Ob-havo ogohlantirishi"

# ──────────────────────────────────────────
# AQILLI TAVSIYA
# ──────────────────────────────────────────

def build_lifestyle_advice(current: dict, forecast_day: dict, location: dict):
    advice = []

    feels = safe_num(current.get("feelslike_c"))
    wind = safe_num(current.get("wind_kph"))
    gust = safe_num(current.get("gust_kph"))
    uv = safe_num(current.get("uv"))
    humidity = safe_num(current.get("humidity"))
    rain_chance = safe_num(forecast_day.get("daily_chance_of_rain"))
    snow_chance = safe_num(forecast_day.get("daily_chance_of_snow"))
    max_temp = safe_num(forecast_day.get("maxtemp_c"))
    min_temp = safe_num(forecast_day.get("mintemp_c"))
    vis_km = safe_num(current.get("vis_km"))
    condition_text = (current.get("condition", {}) or {}).get("text", "").lower()

    pm25 = None
    air_quality = current.get("air_quality") or {}
    for k in ("pm2_5", "pm2_5_us", "pm2.5"):
        if air_quality.get(k) is not None:
            pm25 = safe_num(air_quality.get(k), None)
            break

    if rain_chance >= 60:
        advice.append("🌧 Soyabon oling — yog‘ingarchilik ehtimoli yuqori.")
    elif rain_chance >= 30:
        advice.append("🌦 Yengil yog‘ingarchilik bo‘lishi mumkin — ehtiyot bo‘ling.")

    if snow_chance >= 40 or "snow" in condition_text or "sleet" in condition_text:
        advice.append("❄️ Qor yoki muzlash ehtimoli bor — yo‘lda ehtiyot bo‘ling.")

    if "thunder" in condition_text:
        advice.append("⛈ Momaqaldiroq bor — ochiq joyda uzoq turmang.")

    if feels <= -5:
        advice.append("🥶 Juda sovuq — qalin kiyim, bosh kiyim va qo‘lqop tavsiya etiladi.")
    elif feels <= 5:
        advice.append("🧥 Sovuqroq — issiqroq kiyining.")
    elif feels >= 35:
        advice.append("🔥 Juda issiq — ko‘proq suv iching va quyoshdan saqlaning.")
    elif feels >= 28:
        advice.append("😎 Issiq — yengil kiyim va suv olib yuring.")

    if gust >= 50 or wind >= 40:
        advice.append("🌬 Shamol kuchli — tashqarida ehtiyot bo‘ling.")
    elif wind >= 25:
        advice.append("💨 Shamol sezilarli — yengil buyumlarni ehtiyot qiling.")

    if uv >= 8:
        advice.append("☀️ UV juda yuqori — bosh kiyim va quyoshdan himoya vositasi tavsiya etiladi.")
    elif uv >= 6:
        advice.append("🧴 UV yuqori — uzoq vaqt tik quyoshda qolmang.")

    if humidity >= 90 and vis_km <= 5:
        advice.append("🌫 Namlik va tuman yuqori — yo‘lda ko‘rish pasayishi mumkin.")
    elif vis_km <= 2:
        advice.append("🚗 Ko‘rish masofasi past — transportda ehtiyot bo‘ling.")

    if pm25 is not None:
        level = aqi_level(pm25)
        if "zararli" in level.lower():
            advice.append("😷 Havo sifati yomon — uzoq vaqt tashqarida qolishni kamaytiring.")
        elif "o'rtacha" in level.lower():
            advice.append("🌤 Havo sifati o‘rtacha — sezgirlar ehtiyot bo‘lsin.")

    localtime = location.get("localtime", "")
    try:
        month = datetime.strptime(localtime, "%Y-%m-%d %H:%M").month
    except Exception:
        month = datetime.now().month

    season = detect_season(month)
    if season == "yoz" and max_temp >= 36:
        advice.append("🧊 Yozgi issiq kuchli — kunduzda soyada ko‘proq yuring.")
    elif season == "qish" and min_temp <= 0:
        advice.append("🧣 Qishki sovuq — ertalab va kechqurun ayniqsa issiq kiying.")
    elif season == "bahor" and rain_chance >= 40:
        advice.append("🌱 Bahorgi o‘zgaruvchan ob-havo — soyabon foydali bo‘ladi.")
    elif season == "kuz" and humidity >= 80:
        advice.append("🍂 Kuzgi nam havo — shamollab qolmaslik uchun ehtiyot bo‘ling.")

    return advice[:5]

def build_tomorrow_brief(data: dict):
    forecast_days = data.get("forecast", {}).get("forecastday", [])
    if len(forecast_days) < 2:
        return None

    tomorrow = forecast_days[1]
    day = tomorrow.get("day", {})
    date_str = tomorrow.get("date")
    try:
        d = datetime.strptime(date_str, "%Y-%m-%d")
        day_name = DAYS_UZ[d.weekday()]
        date_fmt = d.strftime("%d.%m")
    except Exception:
        day_name = "Ertaga"
        date_fmt = date_str or ""

    cond_en = (day.get("condition", {}) or {}).get("text", "")
    cond_uz = translate_condition(cond_en)
    emoji = condition_emoji(cond_en)
    max_temp = safe_num(day.get("maxtemp_c"))
    min_temp = safe_num(day.get("mintemp_c"))
    rain_chance = int(safe_num(day.get("daily_chance_of_rain")))
    snow_chance = int(safe_num(day.get("daily_chance_of_snow")))

    extra = []
    if rain_chance >= 60:
        extra.append("yomg‘ir ehtimoli yuqori")
    elif snow_chance >= 40:
        extra.append("qor ehtimoli bor")
    elif max_temp >= 35:
        extra.append("issiq kuchli bo‘ladi")
    elif min_temp <= 0:
        extra.append("sovuq bo‘ladi")

    extra_text = f" — {', '.join(extra)}" if extra else ""

    return (
        f"📌 <b>Ertangi qisqa xulosa</b>\n"
        f"{emoji} {day_name}, {date_fmt}: {min_temp:+.0f}°C / {max_temp:+.0f}°C, {cond_uz}{extra_text}"
    )

def build_alerts_text(data: dict):
    alerts = data.get("alerts", {}).get("alert", []) or []
    if not alerts:
        return None

    lines = ["⚠️ <b>Ogohlantirishlar</b>"]
    for alert in alerts[:2]:
        headline_raw = alert.get("headline") or alert.get("event") or "Ob-havo ogohlantirishi"
        severity_raw = alert.get("severity", "")
        headline = translate_alert(headline_raw)
        severity = translate_severity(severity_raw)
        if severity and severity != "—":
            lines.append(f"• {headline} ({severity})")
        else:
            lines.append(f"• {headline}")
    return "\n".join(lines)

# ──────────────────────────────────────────
# API SO'ROVLARI — SMART CACHE BILAN
# ──────────────────────────────────────────

async def geocode_city(city_name: str):
    if not API_KEY:
        logger.error("WEATHER_API_KEY topilmadi")
        return None

    cache_key = _make_geocode_key(city_name)
    cached = _cache_get(_geocode_cache, cache_key, GEOCODE_CACHE_TTL)
    if cached is not None:
        logger.info(f"geocode_city cache hit: {cache_key}")
        return cached

    async with _cache_lock:
        if cache_key in _inflight_geocode:
            future = _inflight_geocode[cache_key]
            created_here = False
        else:
            future = asyncio.get_running_loop().create_future()
            _inflight_geocode[cache_key] = future
            created_here = True

    if not created_here:
        logger.info(f"geocode_city in-flight wait: {cache_key}")
        return await future

    url = f"{BASE_URL}/search.json"
    params = {"key": API_KEY, "q": city_name, "lang": "en"}

    try:
        timeout = aiohttp.ClientTimeout(total=12)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url, params=params) as resp:
                text = await resp.text()
                if resp.status != 200:
                    logger.error(f"geocode_city HTTP {resp.status}: {text}")
                    result = None
                else:
                    data = await resp.json()
                    if not data:
                        result = None
                    else:
                        item = data[0]
                        result = (item["lat"], item["lon"], item["name"])

        if result is not None:
            _cache_set(_geocode_cache, cache_key, result, MAX_GEOCODE_CACHE)

        future.set_result(result)
        return result

    except Exception as e:
        logger.exception(f"geocode_city xatosi: {e}")
        future.set_result(None)
        return None
    finally:
        async with _cache_lock:
            _inflight_geocode.pop(cache_key, None)

async def fetch_weather(lat: float, lon: float):
    if not API_KEY:
        logger.error("WEATHER_API_KEY topilmadi")
        return None

    cache_key = _make_weather_key(lat, lon)
    cached = _cache_get(_weather_cache, cache_key, WEATHER_CACHE_TTL)
    if cached is not None:
        logger.info(f"fetch_weather cache hit: {cache_key}")
        return cached

    async with _cache_lock:
        if cache_key in _inflight_weather:
            future = _inflight_weather[cache_key]
            created_here = False
        else:
            future = asyncio.get_running_loop().create_future()
            _inflight_weather[cache_key] = future
            created_here = True

    if not created_here:
        logger.info(f"fetch_weather in-flight wait: {cache_key}")
        return await future

    url = f"{BASE_URL}/forecast.json"
    params = {
        "key": API_KEY,
        "q": f"{lat},{lon}",
        "days": 5,
        "aqi": "yes",
        "alerts": "yes",
        "lang": "en",
    }

    try:
        timeout = aiohttp.ClientTimeout(total=15)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url, params=params) as resp:
                text = await resp.text()
                if resp.status != 200:
                    logger.error(f"fetch_weather HTTP {resp.status}: {text}")
                    result = None
                else:
                    result = await resp.json()

        if result is not None:
            _cache_set(_weather_cache, cache_key, result, MAX_WEATHER_CACHE)

        future.set_result(result)
        return result

    except Exception as e:
        logger.exception(f"fetch_weather xatosi: {e}")
        future.set_result(None)
        return None
    finally:
        async with _cache_lock:
            _inflight_weather.pop(cache_key, None)

# ──────────────────────────────────────────
# FORMATLASH
# ──────────────────────────────────────────

def format_current_weather(data: dict, city_name: str) -> str:
    location = data.get("location", {})
    current = data.get("current", {})
    forecast_day = data.get("forecast", {}).get("forecastday", [{}])[0].get("day", {})
    astro = data.get("forecast", {}).get("forecastday", [{}])[0].get("astro", {})

    real_city_name = location.get("name") or city_name
    localtime = format_local_datetime(location.get("localtime", ""))
    cond_en = (current.get("condition", {}) or {}).get("text", "")
    cond_uz = translate_condition(cond_en)
    emoji = condition_emoji(cond_en)

    temp = safe_num(current.get("temp_c"))
    feels = safe_num(current.get("feelslike_c"))
    humidity = int(safe_num(current.get("humidity")))
    wind = safe_num(current.get("wind_kph"))
    wind_deg = safe_num(current.get("wind_degree"))
    pressure = safe_num(current.get("pressure_mb"))
    uv = safe_num(current.get("uv"))
    vis = safe_num(current.get("vis_km"))
    max_temp = safe_num(forecast_day.get("maxtemp_c"))
    min_temp = safe_num(forecast_day.get("mintemp_c"))
    rain_chance = int(safe_num(forecast_day.get("daily_chance_of_rain")))

    air_quality = current.get("air_quality") or {}
    pm25 = None
    for k in ("pm2_5", "pm2_5_us", "pm2.5"):
        if air_quality.get(k) is not None:
            pm25 = safe_num(air_quality.get(k), None)
            break

    msg = (
        f"{emoji} <b>{real_city_name} — Hozirgi ob-havo</b>\n"
        f"🕐 {localtime} (mahalliy vaqt)\n\n"
        f"🌡 Harorat: <b>{temp:+.0f}°C</b> (his qilinadi: <b>{feels:+.0f}°C</b>)\n"
        f"📊 Bugun: {min_temp:+.0f}°C / {max_temp:+.0f}°C\n"
        f"☁️ Holat: <b>{cond_uz}</b>\n\n"
        f"💧 Namlik: <b>{humidity}%</b>\n"
        f"🌬 Shamol: <b>{wind:.0f} km/soat</b> {wind_direction(wind_deg)}\n"
        f"🔻 Bosim: <b>{pressure:.0f} hPa</b>\n"
        f"🌂 Yog'in ehtimoli: <b>{rain_chance}%</b>\n"
        f"☀️ UV indeks: <b>{uv_level(uv)}</b>\n"
        f"👁 Ko'rinish: <b>{vis:.0f} km</b>\n"
    )

    if pm25 is not None:
        msg += f"😷 Havo sifati (PM2.5): <b>{pm25:.1f}</b> — {aqi_level(pm25)}\n"

    msg += f"\n🌅 Tong: <b>{astro.get('sunrise', '—')}</b> | 🌇 Shom: <b>{astro.get('sunset', '—')}</b>\n"

    advice = build_lifestyle_advice(current, forecast_day, location)
    if advice:
        msg += "\n💡 <b>Tavsiya</b>\n"
        for item in advice:
            msg += f"• {item}\n"

    tomorrow = build_tomorrow_brief(data)
    if tomorrow:
        msg += "\n" + tomorrow + "\n"

    alerts_text = build_alerts_text(data)
    if alerts_text:
        msg += "\n" + alerts_text + "\n"

    return msg.strip()

def format_forecast_5day(data: dict, city_name: str) -> str:
    location = data.get("location", {})
    forecast_days = data.get("forecast", {}).get("forecastday", [])
    real_city_name = location.get("name") or city_name

    msg = f"📅 <b>{real_city_name} — 5 kunlik prognoz</b>\n\n"

    for item in forecast_days[:5]:
        try:
            day_date = datetime.strptime(item["date"], "%Y-%m-%d")
            weekday = DAYS_UZ[day_date.weekday()]
            date_fmt = day_date.strftime("%d.%m")
        except Exception:
            weekday = "Kun"
            date_fmt = item.get("date", "")

        day = item.get("day", {})
        cond_en = (day.get("condition", {}) or {}).get("text", "")
        cond_uz = translate_condition(cond_en)
        emoji = condition_emoji(cond_en)

        t_max = safe_num(day.get("maxtemp_c"))
        t_min = safe_num(day.get("mintemp_c"))
        rain = safe_num(day.get("totalprecip_mm"))
        rain_chance = int(safe_num(day.get("daily_chance_of_rain")))
        snow_chance = int(safe_num(day.get("daily_chance_of_snow")))
        wind = safe_num(day.get("maxwind_kph"))

        extra = []
        if rain_chance > 0:
            extra.append(f"🌂 {rain_chance}%")
        if snow_chance > 0:
            extra.append(f"❄️ {snow_chance}%")
        extra_line = "  ".join(extra)

        msg += (
            f"{emoji} <b>{weekday}, {date_fmt}</b>\n"
            f"   🌡 {t_min:+.0f}°C / {t_max:+.0f}°C  |  {cond_uz}\n"
            f"   💧 {rain:.1f} mm  🌬 {wind:.0f} km/soat"
        )
        if extra_line:
            msg += f"  {extra_line}"
        msg += "\n\n"

    tomorrow = build_tomorrow_brief(data)
    if tomorrow:
        msg += tomorrow + "\n"

    alerts_text = build_alerts_text(data)
    if alerts_text:
        msg += "\n" + alerts_text + "\n"

    return msg.strip()

def format_hourly_today(data: dict, city_name: str) -> str:
    location = data.get("location", {})
    forecast_days = data.get("forecast", {}).get("forecastday", [])
    real_city_name = location.get("name") or city_name
    localtime = location.get("localtime", "")

    try:
        now_dt = datetime.strptime(localtime, "%Y-%m-%d %H:%M")
        now_hour = now_dt.hour
        today_str = now_dt.strftime("%Y-%m-%d")
    except Exception:
        now_dt = datetime.now()
        now_hour = now_dt.hour
        today_str = now_dt.strftime("%Y-%m-%d")

    today_obj = None
    for item in forecast_days:
        if item.get("date") == today_str:
            today_obj = item
            break
    if today_obj is None and forecast_days:
        today_obj = forecast_days[0]

    hours = today_obj.get("hour", []) if today_obj else []

    msg = f"⏱ <b>{real_city_name} — Bugungi soatlik prognoz</b>\n\n"
    count = 0

    for hour_data in hours:
        time_str = hour_data.get("time", "")
        try:
            hour = int(time_str[11:13])
        except Exception:
            continue

        if hour < now_hour:
            continue
        if count >= 8:
            break

        cond_en = (hour_data.get("condition", {}) or {}).get("text", "")
        emoji = condition_emoji(cond_en)
        temp = safe_num(hour_data.get("temp_c"))
        rain = int(safe_num(hour_data.get("chance_of_rain")))
        wind = safe_num(hour_data.get("wind_kph"))

        msg += f"{hour:02d}:00  {emoji} <b>{temp:+.0f}°C</b>  🌂{rain}%  🌬{wind:.0f} km/soat\n"
        count += 1

    if count == 0:
        msg += "Bugun uchun soatlik ma'lumot tugadi.\n"

    tomorrow = build_tomorrow_brief(data)
    if tomorrow:
        msg += "\n" + tomorrow + "\n"

    return msg.strip()
