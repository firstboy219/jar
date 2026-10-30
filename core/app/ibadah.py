"""Ibadah (ADR-087): the prayer times where the owner is (Kemenag schedule via api.myquran.com, cached; computed here when it is down),
the Hijri date, sunnah fasting and bekam days, the qibla — and the reminders, which go through the master flow as a fixed procedure.

The city follows the owner: the Kemenag city of the place he is at (kantor → Jakarta, rumah → Bogor), found from the phone's address;
or the city he picked. A reminder is quiet (vibration only) while a meeting is being recorded."""

import logging
import math
import re
import time
from datetime import date, datetime, timedelta

import httpx
from fastapi import APIRouter, Depends, HTTPException

from . import appclock, appsettings, db, home, hub, master, setup_status
from .appauth import owner
from .location import WIB

log = logging.getLogger("jarvis-core")
router = APIRouter()
API = "/api/v1/app/ibadah"
MYQURAN = "https://api.myquran.com/v2"
PRAYERS = ["subuh", "dzuhur", "ashar", "maghrib", "isya"]
LABEL = {"imsak": "Imsak", "subuh": "Subuh", "terbit": "Terbit", "dhuha": "Dhuha", "dzuhur": "Dzuhur", "ashar": "Ashar", "maghrib": "Maghrib", "isya": "Isya"}
DEFAULT_CITY = ("1301", "KOTA JAKARTA")
KAABA = (21.4225, 39.8262)
HIJRI_MONTHS = ["Muharram", "Safar", "Rabiul Awal", "Rabiul Akhir", "Jumadil Awal", "Jumadil Akhir", "Rajab", "Syaban", "Ramadan", "Syawal",
                "Dzulqa'dah", "Dzulhijjah"]


# ---------- pure: the sun, the qibla, the Hijri calendar ----------

def _fix(a: float, b: float) -> float:
    a = a - b * math.floor(a / b)
    return a + b if a < 0 else a


def julian(y: int, m: int, d: int) -> float:
    if m <= 2:
        y, m = y - 1, m + 12
    a = y // 100
    return math.floor(365.25 * (y + 4716)) + math.floor(30.6001 * (m + 1)) + d + 2 - a + a // 4 - 1524.5


def _sun(jd: float) -> tuple[float, float]:
    d = jd - 2451545.0
    g = math.radians(_fix(357.529 + 0.98560028 * d, 360))
    q = _fix(280.459 + 0.98564736 * d, 360)
    lam = math.radians(_fix(q + 1.915 * math.sin(g) + 0.020 * math.sin(2 * g), 360))
    e = math.radians(23.439 - 0.00000036 * d)
    ra = math.degrees(math.atan2(math.cos(e) * math.sin(lam), math.cos(lam))) / 15
    decl = math.asin(math.sin(e) * math.sin(lam))
    return decl, q / 15 - _fix(ra, 24)


def compute_times(day: date, lat: float, lon: float, tz: float = 7.0) -> dict[str, str]:
    """Prayer times by the Kemenag rule (subuh −20°, isya −18°, ashar shadow 1×, 2 minutes of ihtiyat). Pure; the fallback when the
    Kemenag schedule cannot be fetched. Within a few minutes of it."""
    jd = julian(day.year, day.month, day.day) - lon / 360.0
    phi = math.radians(lat)

    def noon(t: float) -> float:
        return _fix(12 - _sun(jd + t)[1], 24)

    def at_angle(angle: float, t: float, before: bool) -> float:
        decl = _sun(jd + t)[0]
        c = (-math.sin(math.radians(angle)) - math.sin(decl) * math.sin(phi)) / (math.cos(decl) * math.cos(phi))
        h = math.degrees(math.acos(max(-1.0, min(1.0, c)))) / 15
        return noon(t) + (-h if before else h)

    def asr(t: float) -> float:
        decl = _sun(jd + t)[0]
        angle = -math.degrees(math.atan(1 / (1 + math.tan(abs(phi - decl)))))
        return at_angle(angle, t, False)

    raw = {"subuh": at_angle(20, 5 / 24, True), "terbit": at_angle(0.833, 6 / 24, True), "dzuhur": noon(12 / 24),
           "ashar": asr(13 / 24), "maghrib": at_angle(0.833, 18 / 24, False), "isya": at_angle(18, 18 / 24, False)}
    out = {}
    for k, v in raw.items():
        t = v + tz - lon / 15 + (-2 if k == "terbit" else 2) / 60
        mins = int(round(_fix(t, 24) * 60)) % 1440
        out[k] = f"{mins // 60:02d}:{mins % 60:02d}"
    sub = int(out["subuh"][:2]) * 60 + int(out["subuh"][3:])
    out["imsak"] = f"{(sub - 10) // 60:02d}:{(sub - 10) % 60:02d}"
    return out


def shifted(known: dict[str, str], calc_then: dict[str, str], calc_now: dict[str, str]) -> dict[str, str]:
    """A day's times from a nearby Kemenag day of the same city plus how much the computed times moved in between — keeps that city's
    own corrections (elevation, rounding) the plain calculation does not know. Pure."""
    out = {}
    for k, v in known.items():
        if k in calc_then and k in calc_now:
            m = (int(v[:2]) * 60 + int(v[3:5]) + (int(calc_now[k][:2]) * 60 + int(calc_now[k][3:5])) - (int(calc_then[k][:2]) * 60 + int(calc_then[k][3:5]))) % 1440
            out[k] = f"{m // 60:02d}:{m % 60:02d}"
        else:
            out[k] = v
    return out


def qibla(lat: float, lon: float) -> float:
    """Bearing to the Kaaba in degrees from north. Pure."""
    p1, p2 = math.radians(lat), math.radians(KAABA[0])
    dl = math.radians(KAABA[1] - lon)
    b = math.degrees(math.atan2(math.sin(dl), math.cos(p1) * math.tan(p2) - math.sin(p1) * math.cos(dl)))
    return round(_fix(b, 360), 1)


def tabular_hijri(d: date) -> tuple[int, int, int]:
    """The arithmetic (tabular) Hijri date of a Gregorian day: (year, month, day). Pure; corrected by the Kemenag offset elsewhere."""
    jd = int(julian(d.year, d.month, d.day) + 0.5)
    l = jd - 1948440 + 10632
    n = (l - 1) // 10631
    l = l - 10631 * n + 354
    j = ((10985 - l) // 5316) * ((50 * l) // 17719) + (l // 5670) * ((43 * l) // 15238)
    l = l - ((30 - j) // 15) * ((17719 * j) // 50) - (j // 16) * ((15238 * j) // 43) + 29
    m = (24 * l) // 709
    dd = l - (709 * m) // 24
    y = 30 * n + j - 30
    return y, m, dd


def hijri_of(d: date, offset: int = 0) -> tuple[int, int, int]:
    return tabular_hijri(d + timedelta(days=offset))


def events_for(d: date, h: tuple[int, int, int]) -> list[dict]:
    """What a day is in the Islamic calendar (sunnah fasting, bekam, feast days). Pure."""
    y, m, dd = h
    out = []
    if m == 9:
        out.append({"kind": "ramadan", "title": "Puasa Ramadan" if dd > 1 else "Awal Ramadan", "fast": True, "isbat": dd == 1})
    if m == 10 and dd == 1:
        out.append({"kind": "feast", "title": "Idulfitri", "fast": False, "isbat": True})
    if m == 12 and dd == 9:
        out.append({"kind": "fast", "title": "Puasa Arafah", "fast": True, "isbat": True})
    if m == 12 and dd == 10:
        out.append({"kind": "feast", "title": "Iduladha", "fast": False, "isbat": True})
    if m == 1 and dd == 1:
        out.append({"kind": "day", "title": f"Tahun baru Islam {y} H", "fast": False})
    if m == 1 and dd in (9, 10):
        out.append({"kind": "fast", "title": "Puasa Tasua" if dd == 9 else "Puasa Asyura", "fast": True})
    if m == 3 and dd == 12:
        out.append({"kind": "day", "title": "Maulid Nabi", "fast": False})
    if m == 7 and dd == 27:
        out.append({"kind": "day", "title": "Isra Mi'raj", "fast": False})
    if m == 8 and dd == 15:
        out.append({"kind": "day", "title": "Nisfu Syaban", "fast": False})
    if dd in (13, 14, 15) and m not in (9,) and not (m == 12 and dd == 13):
        out.append({"kind": "fast", "title": "Puasa Ayyamul Bidh", "fast": True})
    if dd in (17, 19, 21):
        out.append({"kind": "bekam", "title": "Hari bekam sunnah", "fast": False, "best": d.weekday() in (0, 1, 3)})
    if d.weekday() in (0, 3) and m != 9 and not (m == 10 and dd == 1) and not (m == 12 and dd in (10, 11, 12, 13)):
        out.append({"kind": "fast", "title": "Puasa Senin" if d.weekday() == 0 else "Puasa Kamis", "fast": True, "weekly": True})
    return out


def hijri_text(h: tuple[int, int, int]) -> str:
    return f"{h[2]} {HIJRI_MONTHS[h[1] - 1]} {h[0]} H"


def next_prayer(times: dict[str, str], now: datetime) -> dict | None:
    cur = now.hour * 60 + now.minute
    for k in PRAYERS:
        t = int(times[k][:2]) * 60 + int(times[k][3:5])
        if t >= cur:
            return {"name": k, "label": LABEL[k], "time": times[k][:5], "in_min": t - cur}
    return None


def city_words(address: str) -> list[str]:
    """Words of a reverse-geocoded address worth searching the Kemenag city list for, best first. Pure."""
    a = address or ""
    out = [m.group(2).strip() for m in re.finditer(r"(Kota|Kabupaten|Kab\.)\s+([A-Za-z][A-Za-z ]{2,30}?)(?=,|$|\s+\d)", a)]
    for part in [p.strip() for p in a.split(",")][1:]:
        w = re.sub(r"\b(Kota|Kabupaten|Kab\.|Kecamatan|Kec\.|Kelurahan|Jawa Barat|Jawa Tengah|Jawa Timur|DKI|Daerah Khusus Ibukota|Indonesia|\d+)\b", "", part).strip()
        if len(w) >= 4 and w not in out:
            out.append(w)
    if re.search(r"jakarta", a, re.I):   # Kemenag has one city for all of Jakarta
        out = ["Jakarta"] + [w for w in out if w != "Jakarta"]
    return out[:5]


# ---------- the world ----------

def _client() -> httpx.AsyncClient:  # seam for tests
    return httpx.AsyncClient(timeout=12, headers={"User-Agent": "JARVIS/1.0"})


async def _search_city(word: str) -> tuple[str, str] | None:
    async with _client() as c:
        r = await c.get(f"{MYQURAN}/sholat/kota/cari/{word}")
        data = r.json().get("data") or []
    if not data:
        return None
    best = next((x for x in data if x["lokasi"].startswith("KOTA")), data[0])
    return str(best["id"]), best["lokasi"]


async def city() -> tuple[str, str, dict | None]:
    """(Kemenag city id, its name, coordinates) for the prayer times now: the owner's pick, else where the phone is."""
    from . import location, places
    s = await appsettings.get("ibadah")
    if s.get("city_id"):
        return s["city_id"], s.get("city") or s["city_id"], None
    last = await location.last() or {}
    lat, lon = last.get("lat"), last.get("lon")
    here = (await places.current()).get("place")
    key = f"{round(lat, 1)},{round(lon, 1)}" if lat is not None else ""
    cache = await db.pool().fetchval("SELECT value FROM settings_kv WHERE key = 'ibadah:citycache'") or {}
    if key and key in cache:
        cid, name = cache[key]
        return cid, name, {"lat": lat, "lon": lon, "place": here}
    found = None
    for w in city_words(last.get("address") or ""):
        try:
            found = await _search_city(w)
        except Exception:
            found = None
        if found:
            break
    if found and key:
        cache[key] = list(found)
        await db.pool().execute("""INSERT INTO settings_kv (key, value) VALUES ('ibadah:citycache', $1)
                                   ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value""", dict(list(cache.items())[-50:]))
    cid, name = found or DEFAULT_CITY
    return cid, name, ({"lat": lat, "lon": lon, "place": here} if lat is not None else None)


async def times_for(city_id: str, day: date, coords: dict | None = None) -> tuple[dict[str, str], str]:
    """The day's schedule for a city: from the cache, else the Kemenag month (one call fills the month), else computed here."""
    row = await db.pool().fetchval("SELECT times FROM prayer_days WHERE city_id = $1 AND day = $2", city_id, day)
    if row:
        return row, "kemenag"
    try:
        async with _client() as c:
            r = await c.get(f"{MYQURAN}/sholat/jadwal/{city_id}/{day.year}/{day.month:02d}")
            js = r.json()
        for j in (js.get("data") or {}).get("jadwal") or []:
            t = {k: j[k] for k in ("imsak", "subuh", "terbit", "dhuha", "dzuhur", "ashar", "maghrib", "isya") if k in j}
            await db.pool().execute("""INSERT INTO prayer_days (city_id, day, times) VALUES ($1, $2, $3)
                                       ON CONFLICT (city_id, day) DO UPDATE SET times = EXCLUDED.times""", city_id, date.fromisoformat(j["date"]), t)
        row = await db.pool().fetchval("SELECT times FROM prayer_days WHERE city_id = $1 AND day = $2", city_id, day)
        if row:
            return row, "kemenag"
    except Exception as e:
        log.warning("Kemenag schedule for %s unavailable: %s", city_id, e)
    lat, lon = (coords or {}).get("lat") or -6.2, (coords or {}).get("lon") or 106.82
    near = await db.pool().fetchrow(
        "SELECT day, times FROM prayer_days WHERE city_id = $1 AND abs(day - $2::date) <= 60 ORDER BY abs(day - $2::date) LIMIT 1", city_id, day)
    if near:   # the city's own Kemenag day nearby (its elevation, its rounding) moved by how much the sun moved since
        return shifted(near["times"], compute_times(near["day"], lat, lon), compute_times(day, lat, lon)), "hitungan"
    return compute_times(day, lat, lon), "hitungan"


async def hijri_offset(day: date | None = None) -> int:
    """Days to shift the tabular calendar to match the Kemenag date for `day` (today by default; refreshed once a day from api.myquran.com)."""
    today = day or datetime.now(WIB).date()
    saved = await db.pool().fetchval("SELECT value FROM settings_kv WHERE key = 'ibadah:hijri'") or {}
    if saved.get("day") == today.isoformat():
        return int(saved.get("offset", 0))
    offset = int(saved.get("offset", -1))
    try:
        async with _client() as c:
            num = (await c.get(f"{MYQURAN}/cal/hijr/{today.isoformat()}")).json()["data"]["num"]
        want = (num[6], num[5], num[4])   # year, month, day
        for off in (-2, -1, 0, 1, 2):
            if tabular_hijri(today + timedelta(days=off)) == want:
                offset = off
                break
    except Exception as e:
        log.warning("Hijri date unavailable: %s", e)
    await db.pool().execute("""INSERT INTO settings_kv (key, value) VALUES ('ibadah:hijri', $1)
                               ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value""", {"day": today.isoformat(), "offset": offset})
    return offset


async def today_view(now: datetime | None = None) -> dict:
    now = (now or datetime.now(WIB)).astimezone(WIB)
    cid, name, coords = await city()
    times, source = await times_for(cid, now.date(), coords)
    off = await hijri_offset(now.date())
    h = hijri_of(now.date(), off)
    s = await appsettings.get("ibadah")
    nxt = next_prayer(times, now)
    if not nxt:   # after isya: tomorrow's subuh
        t2, _ = await times_for(cid, now.date() + timedelta(days=1), coords)
        cur = now.hour * 60 + now.minute
        sub = int(t2["subuh"][:2]) * 60 + int(t2["subuh"][3:5])
        nxt = {"name": "subuh", "label": "Subuh", "time": t2["subuh"][:5], "in_min": 1440 - cur + sub, "tomorrow": True}
    return {"city": name, "city_id": cid, "place": (coords or {}).get("place"), "source": source, "date": now.date().isoformat(),
            "hijri": hijri_text(h), "hijri_num": list(h), "today_events": events_for(now.date(), h),
            "times": {k: times[k][:5] for k in ("imsak", "subuh", "terbit", "dzuhur", "ashar", "maghrib", "isya") if k in times},
            "next": nxt, "reminders": s["reminders"], "qibla": qibla(coords["lat"], coords["lon"]) if coords else qibla(-6.2, 106.82),
            "quiet": await _quiet_reason(), "trip": await _safe_trip_note(times), "before_min": s.get("before_min", 0)}


async def _safe_trip_note(times: dict) -> dict | None:
    try:
        return await trip_note(times)
    except Exception as e:
        log.info("trip prayer note: %s", e)
        return None


async def calendar(days: int = 210) -> list[dict]:
    off = await hijri_offset()
    start = datetime.now(WIB).date()
    out = []
    for i in range(days):
        d = start + timedelta(days=i)
        h = hijri_of(d, off)
        for e in events_for(d, h):
            if e.get("weekly") and i > 7:
                continue
            out.append({"date": d.isoformat(), "hijri": hijri_text(h), "weekday": d.weekday(), **e})
    return out


# ---------- reminders (through the master flow: a fixed procedure, no AI) ----------

async def _quiet_reason() -> str:
    from . import meetings
    s = await appsettings.get("ibadah")
    if not s.get("quiet_in_meeting"):
        return ""
    card = await meetings.desk_card()
    if card and card.get("state") == "recording":
        return "sedang rapat"
    trip = await db.pool().fetchval("SELECT value FROM settings_kv WHERE key = 'commute:active'")
    if trip and (trip or {}).get("mode") == "krl":
        return "di KRL"
    return ""


async def _sent(key: str) -> bool:
    day = datetime.now(WIB).date().isoformat()
    sent = await db.pool().fetchval("SELECT value FROM settings_kv WHERE key = 'ibadah:sent'") or {}
    if sent.get("day") != day:
        sent = {"day": day, "keys": []}
    if key in sent["keys"]:
        return True
    sent["keys"].append(key)
    await db.pool().execute("""INSERT INTO settings_kv (key, value) VALUES ('ibadah:sent', $1)
                               ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value""", sent)
    return False


async def remind(name: str, at: str, mode: str, quiet: str) -> dict:
    title = f"Waktunya {LABEL[name]} {at.replace(':', '.')}"
    text = f"{'Pengingat getar — ' + quiet + '. ' if quiet else ''}Jadwal Kemenag untuk lokasimu."
    await hub.broadcast({"type": "notify", "title": title, "text": text, "kind": "prayer", "mode": "getar" if quiet else mode, "route": "#/sholat"})
    return {"sent": title, "mode": "getar" if quiet else mode}


@appclock.every(30, "ibadah.reminders")
async def tick(now: datetime | None = None) -> list[str]:
    now = (now or datetime.now(WIB)).astimezone(WIB)
    s = await appsettings.get("ibadah")
    cid, _, coords = await city()
    times, _ = await times_for(cid, now.date(), coords)
    cur = now.hour * 60 + now.minute
    done = []
    for name in PRAYERS:
        mode = (s.get("reminders") or {}).get(name, "notif")
        if mode == "off" or name not in times:
            continue
        t = int(times[name][:2]) * 60 + int(times[name][3:5]) - int(s.get("before_min") or 0)
        if 0 <= cur - t <= 10 and not await _sent(f"prayer:{name}"):
            quiet = await _quiet_reason()
            await master.run(master.Job("sholat", "pengingat", f"ingatkan waktu {name}", trigger="schedule",
                                        skill=lambda name=name, at=times[name][:5], mode=mode, quiet=quiet: remind(name, at, mode, quiet)))
            done.append(name)
    # sahur before a sunnah fast, and the day before a bekam day
    off = await hijri_offset(now.date())
    tomorrow = now.date() + timedelta(days=1)
    ev_today = events_for(now.date(), hijri_of(now.date(), off))
    ev_tomorrow = events_for(tomorrow, hijri_of(tomorrow, off))
    if s.get("sahur_reminder") and any(e.get("fast") for e in ev_today) and appclock.hhmm_due(s.get("sahur_time") or "03:30", now) \
            and now.hour < 6 and not await _sent("sahur"):
        what = next(e["title"] for e in ev_today if e.get("fast"))
        await master.run(master.Job("hijriah", "sahur", "ingatkan sahur", trigger="schedule",
                                    skill=lambda what=what: _notify("Waktunya sahur", f"Hari ini {what}. Imsak {times.get('imsak', '')[:5]}.", "#/hijriah")))
        done.append("sahur")
    if s.get("bekam_reminder") and any(e["kind"] == "bekam" for e in ev_tomorrow) and now.hour >= 19 and not await _sent("bekam"):
        await master.run(master.Job("hijriah", "bekam", "ingatkan hari bekam besok", trigger="schedule",
                                    skill=lambda: _notify("Besok hari bekam sunnah", "Mau aku carikan klinik bekam & buatkan janji?", "#/hijriah")))
        done.append("bekam")
    return done


async def _notify(title: str, text: str, route: str) -> dict:
    await hub.broadcast({"type": "notify", "title": title, "text": text, "kind": "info", "route": route})
    return {"sent": title}


# ---------- the front page and the catalog ----------

@home.provider("sholat")
async def _home(m: home.Moment) -> list[dict]:
    v = await today_view(m.now)
    n = v["next"]
    soon = n["in_min"] <= 30
    score = 85 if (m.slot == "subuh" and n["name"] == "subuh") else (70 if soon else 25)
    card = {"id": "sholat", "title": f"{n['label']} {n['time'].replace(':', '.')}" + (" (besok)" if n.get("tomorrow") else ""),
            "sub": (f"{n['in_min']} menit lagi" if n["in_min"] < 120 else f"{n['in_min'] // 60} jam {n['in_min'] % 60} mnt lagi") + f" · {v['city'].title()}",
            "route": "#/sholat", "icon": "moon", "tone": "green", "score": score}
    if soon:
        card["cta"] = "Lihat jadwal"
    out = [card]
    fasts = [e for e in v["today_events"] if e.get("fast") or e["kind"] in ("bekam", "feast")]
    if fasts:
        out.append({"id": "hijri-today", "title": fasts[0]["title"], "sub": v["hijri"], "route": "#/hijriah", "icon": "cal", "tone": "green", "score": 30})
    return out


@home.context_part("hijri")
async def _ctx(m: home.Moment) -> str | None:
    return None


@setup_status.check("sholat")
async def _ready() -> dict:
    return setup_status.ready()


# ---------- API ----------

# ---------- mosques nearby; a prayer that falls during the trip ----------

MOSQUE_WORDS = re.compile(r"\b(masjid|mesjid|musholl?a|mushol+a|musala|surau|langgar|al[- ])", re.I)
_mosque_cache: dict[str, tuple[float, list]] = {}


def mosques_from(hits: list[dict], lat: float, lon: float) -> list[dict]:
    """Nominatim's places of worship → the mosques/mushollas, nearest first. Pure."""
    from .places import distance_m
    out = []
    for h in hits:
        name = (h.get("name") or h.get("display_name", "").split(",")[0]).strip()
        if not name or not MOSQUE_WORDS.search(name + " " + h.get("display_name", "")):
            continue
        d = distance_m(lat, lon, float(h["lat"]), float(h["lon"]))
        out.append({"name": name, "lat": float(h["lat"]), "lon": float(h["lon"]), "m": int(d),
                    "maps": f"https://www.google.com/maps/dir/?api=1&destination={h['lat']},{h['lon']}&travelmode=walking"})
    return sorted(out, key=lambda x: x["m"])[:8]


async def mosques(lat: float, lon: float) -> list[dict]:
    key = f"{round(lat, 3)},{round(lon, 3)}"
    hit = _mosque_cache.get(key)
    if hit and time.monotonic() - hit[0] < 86400:
        return hit[1]
    from .maps import UA
    d = 0.012
    async with _client() as c:
        r = await c.get("https://nominatim.openstreetmap.org/search", headers=UA,
                        params={"amenity": "place_of_worship", "format": "jsonv2", "limit": 40, "bounded": 1,
                                "viewbox": f"{lon - d},{lat + d},{lon + d},{lat - d}", "accept-language": "id"})
    found = mosques_from(r.json() if r.status_code == 200 else [], lat, lon)
    _mosque_cache[key] = (time.monotonic(), found)
    return found


def during(times: dict, start_hm: str, end_hm: str) -> list[str]:
    """The prayers whose time falls between leaving and arriving (a trip on the train). Pure."""
    a, b = int(start_hm[:2]) * 60 + int(start_hm[3:5]), int(end_hm[:2]) * 60 + int(end_hm[3:5])
    if b < a:
        b += 1440
    return [n for n in PRAYERS if n in times and a <= int(times[n][:2]) * 60 + int(times[n][3:5]) <= b]


async def trip_note(times: dict) -> dict | None:
    """A prayer during the trip home/to work: say so, and the nearest mosque after getting off."""
    from . import commute
    t = await commute.active()
    if not t or not t["chosen"] or t["chosen"].get("kind") == "car":
        return None
    o = t["chosen"]
    hit = during(times, o.get("dep") or o.get("leave"), o.get("arrive"))
    if not hit:
        return None
    st = t["plan"]["to"]["name"]
    pos = await commute._station_pos(st)
    near = []
    if pos:
        try:
            near = (await mosques(pos["lat"], pos["lon"]))[:2]
        except Exception:
            near = []
    n = hit[0]
    return {"prayer": n, "time": times[n][:5], "station": st, "arr": o.get("arr"),
            "text": f"{n.capitalize()} {times[n][:5]} saat kamu di KRL — turun di {st} {str(o.get('arr', '')).replace(':', '.')}" + (f"; terdekat: {near[0]['name']} ({near[0]['m']} m)" if near else ""),
            "mosques": near}


@router.get(API + "/mosques")
async def api_mosques(device: dict = Depends(owner)):
    from . import location
    last = await location.last() or {}
    if last.get("lat") is None:
        raise HTTPException(409, "lokasi HP belum diketahui")
    try:
        return {"mosques": await mosques(last["lat"], last["lon"]), "from": {"lat": last["lat"], "lon": last["lon"]}}
    except httpx.HTTPError as e:
        raise HTTPException(503, f"peta belum terjangkau ({type(e).__name__})")


@router.get(API + "/today")
async def api_today(device: dict = Depends(owner)):
    return await today_view()


@router.get(API + "/calendar")
async def api_calendar(days: int = 210, device: dict = Depends(owner)):
    v = await today_view()
    return {"hijri": v["hijri"], "today_events": v["today_events"], "events": await calendar(max(7, min(days, 400)))}


@router.get(API + "/month")
async def api_month(offset: int = 0, device: dict = Depends(owner)):
    """A whole Hijri month as a grid (the current one, or `offset` months away): each day with its Gregorian date and its events."""
    off = await hijri_offset()
    today = datetime.now(WIB).date()
    y, m, _ = hijri_of(today, off)
    m += offset
    while m > 12:
        y, m = y + 1, m - 12
    while m < 1:
        y, m = y - 1, m + 12
    start = today + timedelta(days=int(offset * 29.53) - 31)
    days = []
    for i in range(0, 95):
        d = start + timedelta(days=i)
        h = hijri_of(d, off)
        if (h[0], h[1]) == (y, m):
            days.append({"date": d.isoformat(), "day": h[2], "weekday": d.weekday(), "today": d == today, "events": [e["title"] for e in events_for(d, h)]})
    return {"title": hijri_text((y, m, 1)).split(" ", 1)[1], "days": days}


@router.get(API + "/cities")
async def api_cities(q: str, device: dict = Depends(owner)):
    async with _client() as c:
        r = await c.get(f"{MYQURAN}/sholat/kota/cari/{q[:40]}")
        return {"cities": [{"id": str(x["id"]), "name": x["lokasi"]} for x in (r.json().get("data") or [])]}


@router.get(API + "/wake")
async def api_wake(device: dict = Depends(owner)):
    """What the alarm says when it wakes the owner: subuh, the weather, the first thing of the day (a fixed procedure, no AI)."""
    async def compose() -> dict:
        from . import weather
        v = await today_view()
        w = await weather.today_text()
        firsts = [c for c in (await home.feed()).get("all", []) if c.get("kind") in ("meeting", "commute", "tasks", "calendar")][:1]
        parts = ["Selamat pagi."]
        if v["next"]["name"] == "subuh":
            parts.append(f"Subuh {v['next']['time'].replace(':', '.')}, {v['next']['in_min']} menit lagi.")
        if w:
            parts.append(w)
        if firsts:
            parts.append(f"{firsts[0]['title']}.")
        return {"text": " ".join(parts), "subuh": v["times"].get("subuh"), "next": v["next"], "hijri": v["hijri"]}
    r = await master.run(master.Job("bangun", "sapaan", "susun sapaan bangun pagi", trigger="schedule", skill=compose))
    return r.get("result") or {"text": "Selamat pagi."}
