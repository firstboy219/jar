"""Al-Qur'an (ADR-087): the text, transliteration and the Kemenag translation from equran.id (cached here, never written by AI), where
the owner read up to, his khatam progress and streak, murottal audio per verse, and reminders for his routine surahs (Al-Mulk at night,
Al-Kahf on Friday) — the reminders go through the master flow as a fixed procedure."""

import logging
from datetime import date, datetime, timedelta

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from . import appclock, appsettings, db, home, hub, master, setup_status
from .appauth import owner
from .location import WIB

log = logging.getLogger("jarvis-core")
router = APIRouter()
API = "/api/v1/app/quran"
EQURAN = "https://equran.id/api/v2"
TOTAL_AYAT = 6236
AYAT_PER_PAGE = TOTAL_AYAT / 604
QARI = {"01": "Abdullah Al-Juhany", "02": "Abdul Muhsin Al-Qasim", "03": "Abdurrahman as-Sudais", "04": "Ibrahim Al-Dossari", "05": "Misyari Rasyid Al-Afasi"}
# where each juz begins (surah, ayah) — the Madinah mushaf
JUZ = [(1, 1), (2, 142), (2, 253), (3, 93), (4, 24), (4, 148), (5, 83), (6, 111), (7, 88), (8, 41), (9, 93), (11, 6), (12, 53), (15, 1), (17, 1),
       (18, 75), (21, 1), (23, 1), (25, 21), (27, 56), (29, 46), (33, 31), (36, 28), (39, 32), (41, 47), (46, 1), (51, 31), (58, 1), (67, 1), (78, 1)]


def juz_of(surah: int, ayah: int) -> int:
    """Which juz a verse is in. Pure."""
    n = 1
    for i, (s, a) in enumerate(JUZ):
        if (surah, ayah) >= (s, a):
            n = i + 1
    return n


def position(surah: int, ayah: int, counts: list[int]) -> int:
    """The verse's number counted through the whole mushaf (1…6236). `counts` = verses per surah. Pure."""
    return sum(counts[: surah - 1]) + ayah


def streak(days: list[date], today: date) -> int:
    """Days in a row, ending today or yesterday, with some reading. Pure."""
    have = set(days)
    d = today if today in have else today - timedelta(days=1)
    n = 0
    while d in have:
        n += 1
        d -= timedelta(days=1)
    return n


def per_day_pages(pos: int, target: date | None, today: date) -> float | None:
    """Pages a day to finish by the target. Pure."""
    if not target or target <= today:
        return None
    left = TOTAL_AYAT - pos
    return round(left / AYAT_PER_PAGE / (target - today).days, 1)


def _client() -> httpx.AsyncClient:  # seam for tests
    return httpx.AsyncClient(timeout=20, headers={"User-Agent": "JARVIS/1.0"})


async def _cached(nomor: int) -> dict:
    row = await db.pool().fetchval("SELECT data FROM quran_surah WHERE nomor = $1", nomor)
    if row:
        return row
    async with _client() as c:
        r = await c.get(f"{EQURAN}/surat" + (f"/{nomor}" if nomor else ""))
        r.raise_for_status()
        data = r.json()["data"]
    await db.pool().execute("INSERT INTO quran_surah (nomor, data) VALUES ($1, $2) ON CONFLICT (nomor) DO UPDATE SET data = EXCLUDED.data", nomor,
                            {"list": data} if nomor == 0 else data)
    return {"list": data} if nomor == 0 else data


async def surah_list() -> list[dict]:
    return [{"nomor": s["nomor"], "nama": s["nama"], "latin": s["namaLatin"], "ayat": s["jumlahAyat"], "arti": s["arti"], "tempat": s["tempatTurun"]}
            for s in (await _cached(0))["list"]]


async def surah(nomor: int, qari: str = "05") -> dict:
    if not 1 <= nomor <= 114:
        raise ValueError("nomor surah 1–114")
    d = await _cached(nomor)
    return {"nomor": d["nomor"], "nama": d["nama"], "latin": d["namaLatin"], "arti": d["arti"], "jumlah": d["jumlahAyat"], "tempat": d["tempatTurun"],
            "audio_full": (d.get("audioFull") or {}).get(qari), "qari": QARI.get(qari, qari),
            "ayat": [{"n": int(a["nomorAyat"]), "arab": a["teksArab"], "latin": a["teksLatin"], "arti": a["teksIndonesia"],
                      "audio": (a.get("audio") or {}).get(qari), "juz": juz_of(d["nomor"], int(a["nomorAyat"]))} for a in d["ayat"]]}


async def progress() -> dict:
    s = await appsettings.get("quran")
    lst = await surah_list()
    counts = [x["ayat"] for x in lst]
    last = await db.pool().fetchrow("SELECT surah, ayah, at FROM quran_reads ORDER BY id DESC LIMIT 1")
    days = [r["d"] for r in await db.pool().fetch(
        "SELECT DISTINCT (at AT TIME ZONE 'Asia/Jakarta')::date AS d FROM quran_reads WHERE at > now() - interval '120 days'")]
    today = datetime.now(WIB).date()
    khatam = await db.pool().fetchval("SELECT value FROM settings_kv WHERE key = 'quran:khatam'") or {"count": 0}
    out = {"khatam": khatam.get("count", 0), "streak": streak(days, today), "qari": s["qari"], "qari_name": QARI.get(s["qari"]), "routines": s["routines"]}
    if last:
        pos = position(last["surah"], last["ayah"], counts)
        meta = lst[last["surah"] - 1]
        target = date.fromisoformat(s["target_date"]) if s.get("target_date") else None
        total = sum(counts) or TOTAL_AYAT
        out.update(last={"surah": last["surah"], "latin": meta["latin"], "nama": meta["nama"], "ayah": last["ayah"], "juz": juz_of(last["surah"], last["ayah"]),
                         "page": int(pos / AYAT_PER_PAGE) + 1, "at": last["at"].isoformat()},
                   pct=round(100 * pos / total), per_day_pages=per_day_pages(pos, target, today), target_date=s.get("target_date"))
    return out


async def mark(surah_n: int, ayah: int) -> dict:
    lst = await surah_list()
    if not 1 <= surah_n <= 114 or not 1 <= ayah <= lst[surah_n - 1]["ayat"]:
        raise ValueError("ayat tidak ada")
    prev = await db.pool().fetchrow("SELECT surah, ayah FROM quran_reads ORDER BY id DESC LIMIT 1")
    await db.pool().execute("INSERT INTO quran_reads (surah, ayah) VALUES ($1, $2)", surah_n, ayah)
    if surah_n == 114 and ayah == lst[113]["ayat"] and (not prev or (prev["surah"], prev["ayah"]) != (114, ayah)):
        k = await db.pool().fetchval("SELECT value FROM settings_kv WHERE key = 'quran:khatam'") or {"count": 0}
        k["count"] = int(k.get("count", 0)) + 1
        k["last"] = datetime.now(WIB).date().isoformat()
        await db.pool().execute("""INSERT INTO settings_kv (key, value) VALUES ('quran:khatam', $1)
                                   ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value""", k)
    return await progress()


@appclock.every(60, "quran.routines")
async def tick(now: datetime | None = None) -> list[str]:
    now = (now or datetime.now(WIB)).astimezone(WIB)
    s = await appsettings.get("quran")
    done = []
    for r in s.get("routines") or []:
        try:
            n, at, days = int(r.get("surah")), str(r.get("time") or ""), [int(d) for d in r.get("days") or []]
        except (TypeError, ValueError):
            continue
        if now.weekday() not in days or not appclock.hhmm_due(at, now) or now.hour * 60 + now.minute - (int(at[:2]) * 60 + int(at[3:5])) > 10:
            continue
        key = f"quran:sent:{n}:{now.date().isoformat()}"
        if await db.pool().fetchval("SELECT 1 FROM settings_kv WHERE key = $1", key):
            continue
        await db.pool().execute("INSERT INTO settings_kv (key, value) VALUES ($1, 'true'::jsonb) ON CONFLICT DO NOTHING", key)
        name = (await surah_list())[n - 1]["latin"]

        async def send(name=name, n=n):
            await hub.broadcast({"type": "notify", "title": f"Waktunya membaca {name}", "text": "Ketuk untuk membuka dan mendengarkan.",
                                 "kind": "info", "route": f"#/quran/{n}"})
            return {"sent": name}
        await master.run(master.Job("quran", "rutin", f"ingatkan membaca surah {name}", trigger="schedule", skill=send))
        done.append(name)
    return done


@home.provider("quran")
async def _home(m: home.Moment) -> list[dict]:
    if m.slot not in ("subuh", "malam", "larut") and not (m.now.weekday() == 4 and m.slot == "pagi"):
        return []
    p = await progress()
    if not p.get("last"):
        return [{"id": "quran", "title": "Mulai membaca Al-Qur'an", "sub": "JARVIS menandai sampai mana kamu membaca", "route": "#/quran", "icon": "quran",
                 "tone": "green", "score": 20}]
    l = p["last"]
    return [{"id": "quran", "title": f"Lanjut baca {l['latin']}", "sub": f"ayat {l['ayah']} · juz {l['juz']} · khatam {p.get('pct', 0)}%",
             "route": f"#/quran/{l['surah']}?ayah={l['ayah']}", "icon": "quran", "tone": "green", "score": 40 if m.slot == "subuh" else 30}]


@setup_status.check("quran")
async def _ready() -> dict:
    return setup_status.ready()


# ---------- API ----------

class MarkIn(BaseModel):
    surah: int = Field(ge=1, le=114)
    ayah: int = Field(ge=1, le=286)


@router.get(API)
async def api_progress(device: dict = Depends(owner)):
    return {"progress": await progress(), "surahs": await surah_list(), "qari": QARI}


@router.get(API + "/surah/{nomor}")
async def api_surah(nomor: int, device: dict = Depends(owner)):
    try:
        return await surah(nomor, (await appsettings.get("quran"))["qari"])
    except ValueError as e:
        raise HTTPException(404, str(e))


@router.post(API + "/read")
async def api_read(body: MarkIn, device: dict = Depends(owner)):
    try:
        return await mark(body.surah, body.ayah)
    except ValueError as e:
        raise HTTPException(422, str(e))
