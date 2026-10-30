"""Weather where the owner is (ADR-087), from Open-Meteo (no key): the context line of the front page, the alarm's greeting, the brief,
and the trip plans (rain → a coat, the backup option). Cached 15 minutes per place."""

import time
from datetime import datetime

import httpx

from . import home
from .location import WIB

URL = "https://api.open-meteo.com/v1/forecast"
TTL_S = 900
WMO = {0: "cerah", 1: "cerah berawan", 2: "berawan", 3: "mendung", 45: "berkabut", 48: "berkabut", 51: "gerimis", 53: "gerimis", 55: "gerimis",
       61: "hujan ringan", 63: "hujan", 65: "hujan lebat", 80: "hujan lokal", 81: "hujan", 82: "hujan lebat", 95: "badai petir", 96: "badai petir", 99: "badai petir"}
_cache: dict[str, tuple[float, dict]] = {}


def describe(code: int | None) -> str:
    return WMO.get(int(code or 0), "berawan")


def rain_window(hours: list[str], probs: list[int], now: datetime, threshold: int = 40) -> tuple[str, int] | None:
    """The first hour from now with rain likely (≥ threshold %): ("07", 45). Pure."""
    for h, p in zip(hours, probs):
        t = datetime.fromisoformat(h)
        if t.date() == now.date() and t.hour >= now.hour and (p or 0) >= threshold:
            return f"{t.hour:02d}", int(p)
    return None


def _client() -> httpx.AsyncClient:  # seam for tests
    return httpx.AsyncClient(timeout=10)


async def _coords() -> tuple[float, float] | None:
    from . import location, places
    last = await location.last() or {}
    if last.get("lat") is not None:
        return float(last["lat"]), float(last["lon"])
    for p in await places.listing():
        if p["name"] == "rumah":
            return p["lat"], p["lon"]
    return None


async def at(lat: float, lon: float) -> dict:
    key = f"{lat:.2f},{lon:.2f}"
    hit = _cache.get(key)
    if hit and time.monotonic() - hit[0] < TTL_S:
        return hit[1]
    async with _client() as c:
        r = await c.get(URL, params={"latitude": lat, "longitude": lon, "timezone": "Asia/Jakarta", "forecast_days": 2,
                                     "current": "temperature_2m,weather_code,precipitation",
                                     "hourly": "precipitation_probability,weather_code,temperature_2m",
                                     "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max"})
        r.raise_for_status()
        js = r.json()
    cur = js.get("current") or {}
    hourly = js.get("hourly") or {}
    now = datetime.now(WIB).replace(tzinfo=None)
    rain = rain_window(hourly.get("time") or [], hourly.get("precipitation_probability") or [], now)
    out = {"temp": round(cur.get("temperature_2m", 0)), "code": cur.get("weather_code"), "text": describe(cur.get("weather_code")),
           "rain": {"hour": rain[0], "pct": rain[1]} if rain else None,
           "max": round((js.get("daily") or {}).get("temperature_2m_max", [0])[0]), "min": round((js.get("daily") or {}).get("temperature_2m_min", [0])[0]),
           "hourly": [{"time": t[11:16], "pct": p, "temp": round(tt)} for t, p, tt in zip(hourly.get("time", [])[:48], hourly.get("precipitation_probability", [])[:48],
                                                                                        hourly.get("temperature_2m", [])[:48])]}
    _cache[key] = (time.monotonic(), out)
    return out


async def here() -> dict | None:
    c = await _coords()
    if not c:
        return None
    try:
        return await at(*c)
    except Exception:
        return None


async def today_text() -> str:
    w = await here()
    if not w:
        return ""
    t = f"Cuaca {w['text']}, {w['temp']}°C."
    if w.get("rain"):
        t += f" Kemungkinan hujan {w['rain']['pct']}% sekitar jam {int(w['rain']['hour'])}."
    return t


@home.context_part("weather")
async def _ctx(m: home.Moment) -> str | None:
    w = await here()
    if not w:
        return None
    return f"{w['temp']}°C {w['text']}" + (f" · hujan {w['rain']['pct']}% jam {int(w['rain']['hour'])}" if w.get("rain") else "")
