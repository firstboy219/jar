"""Al-Qur'an (ADR-087): the text, transliteration and the Kemenag translation from equran.id (cached here, never written by AI), where
the owner read up to, his khatam progress and streak, murottal audio per verse, and reminders for his routine surahs (Al-Mulk at night,
Al-Kahf on Friday) — the reminders go through the master flow as a fixed procedure.

The context of a verse (owner 2026-10-30): where and in which order its surah came down, the period of the Prophet's mission it belongs to
and what he was going through then (fixed text, the standard sirah), the Kemenag introduction of the surah and the Kemenag tafsir of the
verse word for word — and a short summary of its occasion (asbabun nuzul) drawn by the light brain from that tafsir ONLY: when the tafsir
names no particular occasion the summary says so, it never fills the gap. The translation read aloud is the phone's own voice (app)."""

import asyncio
import hashlib
import html as htmllib
import logging
import re
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


AYAT = [7, 286, 200, 176, 120, 165, 206, 75, 129, 109, 123, 111, 43, 52, 99, 128, 111, 110, 98, 135, 112, 78, 118, 64, 77, 227, 93, 88, 69, 60, 34, 30, 73, 54,
        45, 83, 182, 88, 75, 85, 54, 53, 89, 59, 37, 35, 38, 29, 18, 45, 60, 49, 62, 55, 78, 96, 29, 22, 24, 13, 14, 11, 11, 18, 12, 12, 30, 52, 52, 44, 28, 28,
        20, 56, 40, 31, 50, 40, 46, 42, 29, 19, 36, 25, 22, 17, 19, 26, 30, 20, 15, 21, 11, 8, 8, 19, 5, 8, 8, 11, 11, 8, 3, 9, 5, 4, 7, 3, 6, 3, 5, 4, 5, 6]
LATIN = ("Al-Fatihah,Al-Baqarah,Ali 'Imran,An-Nisa',Al-Ma'idah,Al-An'am,Al-A'raf,Al-Anfal,At-Taubah,Yunus,Hud,Yusuf,Ar-Ra'd,Ibrahim,Al-Hijr,An-Nahl,Al-Isra',"
         "Al-Kahf,Maryam,Taha,Al-Anbiya',Al-Hajj,Al-Mu'minun,An-Nur,Al-Furqan,Asy-Syu'ara',An-Naml,Al-Qasas,Al-'Ankabut,Ar-Rum,Luqman,As-Sajdah,Al-Ahzab,"
         "Saba',Fatir,Yasin,As-Saffat,Sad,Az-Zumar,Gafir,Fussilat,Asy-Syura,Az-Zukhruf,Ad-Dukhan,Al-Jasiyah,Al-Ahqaf,Muhammad,Al-Fath,Al-Hujurat,Qaf,"
         "Az-Zariyat,At-Tur,An-Najm,Al-Qamar,Ar-Rahman,Al-Waqi'ah,Al-Hadid,Al-Mujadalah,Al-Hasyr,Al-Mumtahanah,As-Saff,Al-Jumu'ah,Al-Munafiqun,At-Tagabun,"
         "At-Talaq,At-Tahrim,Al-Mulk,Al-Qalam,Al-Haqqah,Al-Ma'arij,Nuh,Al-Jinn,Al-Muzzammil,Al-Muddassir,Al-Qiyamah,Al-Insan,Al-Mursalat,An-Naba',"
         "An-Nazi'at,'Abasa,At-Takwir,Al-Infitar,Al-Mutaffifin,Al-Insyiqaq,Al-Buruj,At-Tariq,Al-A'la,Al-Gasyiyah,Al-Fajr,Al-Balad,Asy-Syams,Al-Lail,"
         "Ad-Duha,Asy-Syarh,At-Tin,Al-'Alaq,Al-Qadr,Al-Bayyinah,Az-Zalzalah,Al-'Adiyat,Al-Qari'ah,At-Takasur,Al-'Asr,Al-Humazah,Al-Fil,Quraisy,Al-Ma'un,"
         "Al-Kausar,Al-Kafirun,An-Nasr,Al-Lahab,Al-Ikhlas,Al-Falaq,An-Nas").split(",")


# the order in which each surah came down (Tanzil's metadata, the standard Egyptian chronology), by surah number
ORDER = [5, 87, 89, 92, 112, 55, 39, 88, 113, 51, 52, 53, 96, 72, 54, 70, 50, 69, 44, 45, 73, 103, 74, 102, 42, 47, 48, 49, 85, 84, 57, 75, 90, 58,
         43, 41, 56, 38, 59, 60, 61, 62, 63, 64, 65, 66, 95, 111, 106, 34, 67, 76, 23, 37, 97, 46, 94, 105, 101, 91, 109, 110, 104, 108, 99, 107, 77, 2,
         78, 79, 71, 40, 3, 4, 31, 98, 33, 80, 81, 24, 7, 82, 86, 83, 27, 36, 8, 68, 10, 35, 26, 9, 11, 12, 28, 1, 25, 100, 93, 14, 30, 16, 13, 32,
         19, 29, 17, 15, 18, 114, 6, 22, 20, 21]
# the periods of the mission by that order, and what the Prophet ﷺ was going through in each (the standard sirah; approximate years)
PERIODS = [
    (21, "Makkah awal", "±tahun 1–4 kenabian",
     "Rasulullah saw baru menerima wahyu. Dakwah dimulai diam-diam kepada keluarga dan sahabat terdekat (Khadijah, Ali, Abu Bakar, Zaid), "
     "lalu terang-terangan kepada kerabat dan penduduk Makkah. Pengikutnya masih sedikit; pokok ajarannya tauhid, hari akhir, dan akhlak."),
    (60, "Makkah pertengahan", "±tahun 5–9 kenabian",
     "Dakwah sudah terbuka dan penolakan Quraisy makin keras: ejekan, tuduhan, penyiksaan terhadap sahabat yang lemah, sebagian sahabat "
     "hijrah ke Habasyah, dan Bani Hasyim diboikot di lembah Abu Thalib. Rasulullah saw bersabar dan terus menyeru."),
    (86, "Makkah akhir", "±tahun 10–13 kenabian",
     "Tahun kesedihan: Abu Thalib dan Khadijah wafat, Rasulullah saw ditolak di Thaif, lalu dimuliakan dengan Isra' Mi'raj. Orang-orang "
     "Yatsrib berbaiat di Aqabah, dan kaum Muslimin bersiap hijrah ke Madinah."),
    (98, "Madinah awal", "±tahun 1–5 Hijriah",
     "Rasulullah saw membangun masyarakat Muslim di Madinah: masjid, persaudaraan Muhajirin–Anshar, Piagam Madinah, perubahan kiblat. "
     "Terjadi Perang Badar dan Uhud; muncul golongan munafik dan ketegangan dengan sebagian Yahudi Madinah."),
    (110, "Madinah pertengahan", "±tahun 5–8 Hijriah",
     "Masa Perang Khandaq, Perjanjian Hudaibiyah, dan surat-surat dakwah kepada para raja. Hukum keluarga dan masyarakat dimantapkan, "
     "dan Islam meluas ke kabilah-kabilah Arab."),
    (114, "Madinah akhir", "±tahun 8–10 Hijriah",
     "Fathu Makkah, Perang Hunain dan Tabuk, utusan kabilah datang masuk Islam, lalu Haji Wada'. Ajaran Islam disempurnakan menjelang "
     "wafatnya Rasulullah saw."),
]


def period(order: int) -> dict:
    """The period of the mission a surah of this revelation order belongs to. Pure."""
    for last, name, years, nabi in PERIODS:
        if order <= last:
            return {"nama": name, "tahun": years, "nabi": nabi}
    return {"nama": "", "tahun": "", "nabi": ""}


def surah_period(tempat: str, order: int) -> dict:
    """The period, unless Kemenag places the surah differently from the chronology (Al-Falaq, An-Nas): then the scholars' difference. Pure."""
    if tempat and (tempat == "Mekah") != (order <= 86):
        return {"nama": "Diperselisihkan", "tahun": "",
                "nabi": f"Ulama berbeda pendapat apakah surah ini turun di Makkah atau Madinah; Kemenag menggolongkannya sebagai surah {tempat}."}
    return period(order)


def plain(text: str) -> str:
    """equran.id's HTML (<i>, <br>, entities) as plain text. Pure."""
    t = re.sub(r"<br\s*/?>|</p>", "\n", str(text or ""), flags=re.I)
    return re.sub(r"[ \t]+", " ", htmllib.unescape(re.sub(r"<[^>]+>", "", t))).strip()


async def surah_list() -> list[dict]:
    """The 114 surahs (equran.id, cached); when it cannot be reached yet, the built-in names and verse counts keep progress working."""
    try:
        return [{"nomor": s["nomor"], "nama": s["nama"], "latin": s["namaLatin"], "ayat": s["jumlahAyat"], "arti": s["arti"], "tempat": s["tempatTurun"]}
                for s in (await _cached(0))["list"]]
    except Exception as e:
        log.warning("surah list unavailable (%s): built-in list", e)
        return [{"nomor": i + 1, "nama": "", "latin": LATIN[i], "ayat": AYAT[i], "arti": "", "tempat": ""} for i in range(114)]


async def surah(nomor: int, qari: str = "05") -> dict:
    if not 1 <= nomor <= 114:
        raise ValueError("nomor surah 1–114")
    d = await _cached(nomor)
    return {"nomor": d["nomor"], "nama": d["nama"], "latin": d["namaLatin"], "arti": d["arti"], "jumlah": d["jumlahAyat"], "tempat": d["tempatTurun"],
            "audio_full": (d.get("audioFull") or {}).get(qari), "qari": QARI.get(qari, qari),
            "ayat": [{"n": int(a["nomorAyat"]), "arab": a["teksArab"], "latin": a["teksLatin"], "arti": a["teksIndonesia"],
                      "audio": (a.get("audio") or {}).get(qari), "juz": juz_of(d["nomor"], int(a["nomorAyat"]))} for a in d["ayat"]]}


async def tafsir(nomor: int) -> dict:
    """The Kemenag tafsir of a surah (equran.id), cached as fetched: {ayah: text}."""
    row = await db.pool().fetchval("SELECT data FROM quran_tafsir WHERE nomor = $1", nomor)
    if row:
        return row
    async with _client() as c:
        r = await c.get(f"{EQURAN}/tafsir/{nomor}")
        r.raise_for_status()
        try:
            d = r.json()["data"]
            d["tafsir"][0]["teks"]
        except (KeyError, IndexError, TypeError, ValueError):
            raise httpx.HTTPError("equran.id tidak mengirim tafsir") from None
    data = {"deskripsi": plain(d.get("deskripsi")), "ayat": {str(int(t["ayat"])): plain(t["teks"]) for t in d.get("tafsir") or []}}
    await db.pool().execute("INSERT INTO quran_tafsir (nomor, data) VALUES ($1, $2) ON CONFLICT (nomor) DO UPDATE SET data = EXCLUDED.data", nomor, data)
    return data


async def context(nomor: int, ayah: int) -> dict:
    """Everything known about when and why a verse came down — no AI here (the summary is only read from the cache)."""
    lst = await surah_list()
    if not 1 <= nomor <= 114 or not 1 <= ayah <= lst[nomor - 1]["ayat"]:
        raise ValueError("ayat tidak ada")
    meta, order = lst[nomor - 1], ORDER[nomor - 1]
    t = await tafsir(nomor)
    summary = await db.pool().fetchval("SELECT data FROM quran_context WHERE surah = $1 AND ayah = $2", nomor, ayah)
    return {"surah": {"nomor": nomor, "latin": meta["latin"], "tempat": meta["tempat"] or ("Madinah" if order > 86 else "Mekah"), "urutan": order,
                      "periode": surah_period(meta["tempat"], order), "pengantar": t["deskripsi"]},
            "ayah": ayah, "tafsir": t["ayat"].get(str(ayah), ""), "ringkasan": summary, "sumber": "Tafsir Kemenag RI (equran.id)"}


CONTEXT_KEYS = ("sebab", "peristiwa", "waktu", "riwayat")


def clean_context(d: dict) -> dict:
    """The brain's reading of the tafsir, kept to its fields; 'ada' false when it found no particular occasion. Pure."""
    out = {k: " ".join(str(d.get(k) or "").split())[:700] or None for k in CONTEXT_KEYS}
    out["ada"] = bool(d.get("ada")) and bool(out["sebab"])
    if not out["ada"]:
        out["sebab"] = None
    return out


def context_messages(c: dict) -> list[dict]:
    """The light brain's brief for a verse's occasion: the Kemenag introduction and tafsir, and nothing may be added to them. Pure."""
    nomor, ayah = c["surah"]["nomor"], c["ayah"]
    return [{"role": "system", "content": (
        "Kamu membantu memahami konteks turunnya ayat Al-Qur'an HANYA dari teks Tafsir Kemenag yang diberikan. Jangan menambah riwayat, nama, "
        "tempat, atau tahun yang tidak tertulis di teks itu. Bila teks tidak menyebut sebab turun (asbabun nuzul) khusus, isi ada=false dan "
        "sebab=null. Bahasa Indonesia yang santun; tulis 'Rasulullah saw'. "
        'JSON: {"ada": true/false, "sebab": "sebab turunnya ayat menurut teks, 1-3 kalimat, atau null", '
        '"peristiwa": "apa yang sedang dialami/dilakukan Rasulullah saw saat itu menurut teks, atau null", '
        '"waktu": "kapan/di mana menurut teks (mis. di Makkah sebelum hijrah), atau null", "riwayat": "perawi/sumber yang disebut teks, atau null"}')},
        {"role": "user", "content": f"Surah {c['surah']['latin']} ({nomor}) ayat {ayah}. Tempat turun surah: {c['surah']['tempat']}.\n\n"
                                    f"PENGANTAR SURAH (Kemenag):\n{c['surah']['pengantar'][:3000]}\n\nTAFSIR AYAT INI (Kemenag):\n{c['tafsir'][:9000]}"}]


async def summarize(nomor: int, ayah: int) -> dict:
    """The occasion of a verse, read from its Kemenag tafsir by the light brain (master flow), once — then kept."""
    if cached := await db.pool().fetchval("SELECT data FROM quran_context WHERE surah = $1 AND ayah = $2", nomor, ayah):
        return cached
    c = await context(nomor, ayah)
    if not c["tafsir"]:
        raise ValueError("tafsir ayat ini belum tersedia")
    msgs = context_messages(c)
    r = await master.run(master.Job("quran", "konteks", f"konteks turun {c['surah']['latin']}:{ayah}", messages=msgs, json_out=True, max_tokens=900,
                                    temperature=0.1))
    if r["status"] != "done" or not isinstance(r["result"], dict):
        raise ValueError(r.get("error") or "ringkasan gagal dibuat")
    data = clean_context(r["result"])
    await db.pool().execute("INSERT INTO quran_context (surah, ayah, data, run_id) VALUES ($1, $2, $3, $4) ON CONFLICT (surah, ayah) DO NOTHING",
                            nomor, ayah, data, r.get("run_id"))
    return data


# ---------- the translation read aloud by ElevenLabs, kept per verse (owner 2026-10-31) ----------

VOICE_MODEL = "elevenlabs/eleven-multilingual-v2"   # Indonesian read well; the owner's own ElevenLabs choice wins
_voice_locks: dict[str, asyncio.Lock] = {}


def voice_chunks(text: str, limit: int = 1000) -> list[str]:
    """A long translation split at sentence ends (then commas, then words) into pieces one voice call takes. Pure."""
    text = " ".join(str(text or "").split())
    out, cur = [], ""
    for part in re.split(r"(?<=[.!?;:])\s+", text):
        while len(part) > limit:   # one very long sentence: at a comma, else at a space
            cut = part.rfind(", ", 0, limit)
            cut = cut + 1 if cut > limit // 2 else (part.rfind(" ", 0, limit) if part.rfind(" ", 0, limit) > 0 else limit)
            if cur:
                out.append(cur)
                cur = ""
            out.append(part[:cut].strip())
            part = part[cut:].strip()
        if cur and len(cur) + 1 + len(part) > limit:
            out.append(cur)
            cur = part
        else:
            cur = f"{cur} {part}".strip()
    if cur:
        out.append(cur)
    return [c for c in out if c]


def voice_path(nomor: int, ayah: int, model: str, voice_name: str, text: str):
    """Where a verse's translation audio is kept for good (a new voice or text → a new file). Pure."""
    from . import voice
    key = hashlib.sha1(f"{model}|{voice_name}|{text}".encode()).hexdigest()[:12]
    return voice.VOICE_DIR / "quran" / f"{nomor:03d}-{ayah:03d}-{key}.mp3"


async def translation_voice(nomor: int, ayah: int):
    """The Kemenag translation of a verse read by ElevenLabs: made once (through the master flow), then the kept recording."""
    from . import voice
    s = await surah(nomor)
    a = next((x for x in s["ayat"] if x["n"] == ayah), None)
    if not a:
        raise ValueError("ayat tidak ada")
    text = plain(a["arti"])
    cfg = await voice.tts_settings()
    model = cfg["model"] if str(cfg.get("model", "")).startswith("elevenlabs/") else VOICE_MODEL
    path = voice_path(nomor, ayah, model, cfg["voice"], text)
    if path.exists():
        return path
    lock = _voice_locks.setdefault(path.name, asyncio.Lock())
    async with lock:
        if path.exists():
            return path

        async def make():
            audio = b"".join([await voice.synthesize(chunk, model, cfg["voice"], preview=True) for chunk in voice_chunks(text)])
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".part")
            tmp.write_bytes(audio)
            tmp.replace(path)
            return {"bytes": len(audio), "chars": len(text)}
        r = await master.run(master.Job("quran", "suara-terjemahan", f"suara terjemahan {s['latin']}:{ayah}", skill=make))
        if r["status"] != "done":
            raise voice.VoiceError(r.get("error") or "suara terjemahan gagal dibuat", 503)
    _voice_locks.pop(path.name, None)
    return path


def voice_kept() -> int:
    from . import voice
    d = voice.VOICE_DIR / "quran"
    return len(list(d.glob("*.mp3"))) if d.exists() else 0


async def progress() -> dict:
    s = await appsettings.get("quran")
    lst = await surah_list()
    counts = [x["ayat"] for x in lst]
    last = await db.pool().fetchrow("SELECT surah, ayah, at FROM quran_reads ORDER BY id DESC LIMIT 1")
    days = [r["d"] for r in await db.pool().fetch(
        "SELECT DISTINCT (at AT TIME ZONE 'Asia/Jakarta')::date AS d FROM quran_reads WHERE at > now() - interval '120 days'")]
    today = datetime.now(WIB).date()
    khatam = await db.pool().fetchval("SELECT value FROM settings_kv WHERE key = 'quran:khatam'") or {"count": 0}
    out = {"khatam": khatam.get("count", 0), "streak": streak(days, today), "qari": s["qari"], "qari_name": QARI.get(s["qari"]), "routines": s["routines"],
           "voice_kept": voice_kept()}
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


@router.get(API + "/context/{nomor}/{ayah}")
async def api_context(nomor: int, ayah: int, device: dict = Depends(owner)):
    try:
        return await context(nomor, ayah)
    except ValueError as e:
        raise HTTPException(404, str(e))
    except httpx.HTTPError:
        raise HTTPException(503, "tafsir belum bisa diambil — coba lagi")


@router.post(API + "/context/{nomor}/{ayah}/summary")
async def api_context_summary(nomor: int, ayah: int, device: dict = Depends(owner)):
    try:
        return await summarize(nomor, ayah)
    except ValueError as e:
        raise HTTPException(409, str(e))
    except httpx.HTTPError:
        raise HTTPException(503, "tafsir belum bisa diambil — coba lagi")


@router.get(API + "/voice/{nomor}/{ayah}")
async def api_translation_voice(nomor: int, ayah: int, device: dict = Depends(owner)):
    """The verse's translation in the ElevenLabs voice (audio/mpeg), kept after its first reading. An error: the app reads it with the
    device's own voice."""
    from fastapi.responses import FileResponse
    from . import voice
    try:
        path = await translation_voice(nomor, ayah)
    except ValueError as e:
        raise HTTPException(404, str(e))
    except voice.VoiceError as e:
        raise HTTPException(e.status, str(e))
    except httpx.HTTPError:
        raise HTTPException(503, "teks ayat belum bisa diambil")
    return FileResponse(path, media_type="audio/mpeg", headers={"Cache-Control": "private, max-age=31536000"})


@router.post(API + "/read")
async def api_read(body: MarkIn, device: dict = Depends(owner)):
    try:
        return await mark(body.surah, body.ayah)
    except ValueError as e:
        raise HTTPException(422, str(e))
