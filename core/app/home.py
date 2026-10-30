"""The front page (ADR-087): what the owner most likely needs right now, so he never has to look for a screen.

Every feature of the app is in one catalog (FEATURES). The front page is made of:
  - one hero card and two supporting cards, picked by score from the PROVIDERS (each feature module registers one): what waits for the
    owner, what is running, the next prayer, the trip home, a coffee offer, the business, the brief …, scored for the moment (time of
    day, weekday, the place the owner is at);
  - seven shortcuts, ordered by when the owner usually opens each feature (app_usage, learned) and what fits the time of day;
  - a context line (day, time, place, weather) and a greeting.
"""

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Awaitable, Callable

from . import db
from .location import WIB

log = logging.getLogger("jarvis-core")

# ---------- the catalog: every screen of the app ----------
# id → label, icon (web/app/icons.js), group, route ('#/…' a screen of the app, 'native:…' something only the phone does), and the
# moments it fits. `setup` names what must be connected first (shown on the feature, never hidden).

GROUPS = ["Sehari-hari", "Perjalanan", "Kerja", "Info hari ini", "Bisnis", "Keuangan", "Ibadah & keluarga", "Otak JARVIS"]

FEATURES: list[dict] = [
    {"id": "obrolan", "label": "Obrolan", "icon": "chat", "group": "Sehari-hari", "route": "#/obrolan", "slots": []},
    {"id": "bicara", "label": "Mode bicara", "icon": "mic", "group": "Sehari-hari", "route": "native:talk", "slots": []},
    {"id": "musik", "label": "Musik", "icon": "music", "group": "Sehari-hari", "route": "#/musik", "slots": ["pagi", "sore", "malam"]},
    {"id": "video", "label": "Video", "icon": "video", "group": "Sehari-hari", "route": "#/video", "slots": ["malam"]},
    {"id": "kamera", "label": "Kamera ukur", "icon": "camera", "group": "Sehari-hari", "route": "#/ukur", "slots": []},
    {"id": "berkas", "label": "Berkas & PDF", "icon": "file", "group": "Sehari-hari", "route": "#/berkas", "slots": ["kerja", "siang"]},
    {"id": "bimbing", "label": "Bimbing layar", "icon": "screen", "group": "Sehari-hari", "route": "#/bimbing", "slots": []},
    {"id": "halaman", "label": "Halaman aktif", "icon": "pages", "group": "Sehari-hari", "route": "#/halaman", "slots": []},
    {"id": "berangkat", "label": "Berangkat", "icon": "train", "group": "Perjalanan", "route": "#/berangkat", "slots": ["pagi"]},
    {"id": "pulang", "label": "Pulang", "icon": "car", "group": "Perjalanan", "route": "#/pulang", "slots": ["sore"]},
    {"id": "perjalanan", "label": "Di jalan", "icon": "lock", "group": "Perjalanan", "route": "#/perjalanan", "slots": []},
    {"id": "inbox", "label": "Perlu perhatian", "icon": "inbox", "group": "Kerja", "route": "#/inbox", "slots": ["kerja", "siang", "sore"]},
    {"id": "rapat", "label": "Rekam rapat", "icon": "meet", "group": "Kerja", "route": "#/rapat", "slots": ["kerja"]},
    {"id": "catatan", "label": "Catatan & tugas", "icon": "notes", "group": "Kerja", "route": "#/catatan", "slots": ["kerja", "malam"]},
    {"id": "rekap", "label": "Rekap harian", "icon": "recap", "group": "Kerja", "route": "#/rekap", "slots": ["malam"]},
    {"id": "misi", "label": "Misi", "icon": "layers", "group": "Kerja", "route": "#/misi", "slots": []},
    {"id": "karier", "label": "Karier JobStreet", "icon": "job", "group": "Kerja", "route": "#/karier", "slots": ["pagi", "malam"]},
    {"id": "brief", "label": "Brief pagi", "icon": "news", "group": "Info hari ini", "route": "#/brief", "slots": ["subuh", "pagi"]},
    {"id": "bioskop", "label": "Film bioskop", "icon": "film", "group": "Info hari ini", "route": "#/bioskop", "slots": ["sore", "malam", "akhir-pekan"]},
    {"id": "bisnis", "label": "Bisnis hari ini", "icon": "chart", "group": "Bisnis", "route": "#/bisnis", "slots": ["kerja", "siang", "sore"]},
    {"id": "tren", "label": "Tren & strategi", "icon": "invest", "group": "Bisnis", "route": "#/tren", "slots": []},
    {"id": "peluang", "label": "Peluang baru", "icon": "bulb", "group": "Bisnis", "route": "#/peluang", "slots": []},
    {"id": "sumber", "label": "Sumber API", "icon": "code", "group": "Bisnis", "route": "#/sumber", "slots": []},
    {"id": "gaji", "label": "Alokasi gaji", "icon": "wallet", "group": "Keuangan", "route": "#/gaji", "slots": ["gajian"]},
    {"id": "invest", "label": "Investasi", "icon": "invest", "group": "Keuangan", "route": "#/invest", "slots": ["gajian"]},
    {"id": "kopi", "label": "Kopi", "icon": "coffee", "group": "Keuangan", "route": "#/kopi", "slots": ["siang"]},
    {"id": "butuh", "label": "Izin & persetujuan", "icon": "shield", "group": "Keuangan", "route": "#/butuh", "slots": []},
    {"id": "sholat", "label": "Jadwal sholat", "icon": "moon", "group": "Ibadah & keluarga", "route": "#/sholat", "slots": ["subuh", "siang", "sore"]},
    {"id": "bangun", "label": "Alarm", "icon": "alarm", "group": "Ibadah & keluarga", "route": "#/bangun", "slots": ["malam"]},
    {"id": "dongeng", "label": "Dongeng anak", "icon": "book", "group": "Ibadah & keluarga", "route": "#/dongeng", "slots": ["malam"]},
    {"id": "hijriah", "label": "Kalender Islam", "icon": "cal", "group": "Ibadah & keluarga", "route": "#/hijriah", "slots": []},
    {"id": "quran", "label": "Al-Qur'an", "icon": "quran", "group": "Ibadah & keluarga", "route": "#/quran", "slots": ["subuh", "malam"]},
    {"id": "alur", "label": "Alur langsung", "icon": "flow", "group": "Otak JARVIS", "route": "#/alur", "slots": []},
    {"id": "bengkel", "label": "Bengkel otak", "icon": "code", "group": "Otak JARVIS", "route": "#/bengkel", "slots": []},
    {"id": "ingatan", "label": "Ingatan & skill", "icon": "db", "group": "Otak JARVIS", "route": "#/ingatan", "slots": []},
    {"id": "kebiasaan", "label": "Kebiasaan", "icon": "repeat", "group": "Otak JARVIS", "route": "#/kebiasaan", "slots": []},
    {"id": "kontrol", "label": "Kontrol", "icon": "gear", "group": "Otak JARVIS", "route": "#/kontrol", "slots": []},
]
FEATURE_IDS = {f["id"] for f in FEATURES}

# ---------- the moment ----------

SLOTS = ("subuh", "pagi", "kerja", "siang", "sore", "malam", "larut")


def slot_of(t: datetime) -> str:
    """The part of the day the front page is made for."""
    m = t.hour * 60 + t.minute
    if 210 <= m < 330:
        return "subuh"            # 03.30–05.30
    if m < 210 or m >= 1350:
        return "larut"            # 22.30–03.30
    if m < 510:
        return "pagi"             # –08.30
    if m < 720:
        return "kerja"            # –12.00
    if m < 930:
        return "siang"            # –15.30
    if m < 1110:
        return "sore"             # –18.30
    return "malam"


def tags_of(t: datetime, slot: str, payday: int = 25) -> set[str]:
    """The moment as tags features can be fit to: the slot, a weekend, payday (and the last days of the month)."""
    tags = {slot}
    if t.weekday() >= 5:
        tags.add("akhir-pekan")
    last_day = ((t.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)).day
    if t.day == min(payday, last_day) or t.day >= last_day - 2:
        tags.add("gajian")
    return tags


GREETING = {"subuh": "Waktunya bangun.", "pagi": "Selamat pagi.", "kerja": "Semangat kerjanya.", "siang": "Selamat siang.",
            "sore": "Selamat sore.", "malam": "Selamat malam.", "larut": "Sudah larut."}
DAYS = ["SENIN", "SELASA", "RABU", "KAMIS", "JUMAT", "SABTU", "MINGGU"]
MONTHS = ["JAN", "FEB", "MAR", "APR", "MEI", "JUN", "JUL", "AGU", "SEP", "OKT", "NOV", "DES"]


@dataclass
class Moment:
    now: datetime
    slot: str
    tags: set[str]
    place: str | None = None
    extras: dict = field(default_factory=dict)   # what context providers add (weather …)


# ---------- providers ----------

Card = dict   # {id, title, sub, route, icon, tone, cta?, score, kind}
Provider = Callable[[Moment], Awaitable[list[Card]]]
PROVIDERS: dict[str, Provider] = {}
CONTEXT: dict[str, Callable[[Moment], Awaitable[str | None]]] = {}   # a word for the context line ("27°C cerah")


def provider(name: str):
    def wrap(fn: Provider) -> Provider:
        PROVIDERS[name] = fn
        return fn
    return wrap


def context_part(name: str):
    def wrap(fn):
        CONTEXT[name] = fn
        return fn
    return wrap


async def _safe(name: str, coro, timeout: float = 4.0):
    try:
        return await asyncio.wait_for(coro, timeout)
    except Exception as e:  # one feature failing never empties the front page
        log.warning("home provider %s failed: %s", name, e)
        return None


def pick(cards: list[Card], n_side: int = 2) -> tuple[Card | None, list[Card]]:
    """The hero (the best card that asks for something) and the next best cards, one per kind."""
    ranked = sorted((c for c in cards if c), key=lambda c: -float(c.get("score") or 0))
    hero = next((c for c in ranked if c.get("cta")), None)
    side, kinds = [], {hero["kind"]} if hero else set()
    for c in ranked:
        if c is hero or c.get("kind") in kinds:
            continue
        side.append(c)
        kinds.add(c.get("kind"))
        if len(side) == n_side:
            break
    return hero, side


# ---------- shortcuts, learned from what the owner opens ----------

def hour_weight(a: int, b: int) -> float:
    d = min(abs(a - b), 24 - abs(a - b))
    return {0: 1.0, 1: 0.6, 2: 0.25}.get(d, 0.0)


def rank_shortcuts(opens: list[tuple[str, datetime]], m: Moment, n: int = 7) -> list[str]:
    """Features in the order the owner is likely to want them now: how often he opened each near this hour (same kind of day counts
    more) over 30 days, plus what fits the moment. Pure."""
    score: dict[str, float] = {f["id"]: 0.0 for f in FEATURES}
    weekend = m.now.weekday() >= 5
    for feature, at in opens:
        if feature not in score:
            continue
        t = at.astimezone(WIB)
        w = hour_weight(t.hour, m.now.hour)
        if w:
            score[feature] += w * (1.0 if (t.weekday() >= 5) == weekend else 0.5)
    for f in FEATURES:
        if m.tags & set(f["slots"]):
            score[f["id"]] += 2.0
    order = sorted((f for f in FEATURES if f["route"].startswith("#/")), key=lambda f: (-score[f["id"]], FEATURES.index(f)))
    return [f["id"] for f in order[:n]]


async def opened(feature: str) -> bool:
    if feature not in FEATURE_IDS:
        return False
    await db.pool().execute("INSERT INTO app_usage (feature) VALUES ($1)", feature)
    return True


async def shortcuts(m: Moment, n: int = 7) -> list[dict]:
    rows = await db.pool().fetch("SELECT feature, opened_at FROM app_usage WHERE opened_at > now() - interval '30 days'")
    ids = rank_shortcuts([(r["feature"], r["opened_at"]) for r in rows], m, n)
    by_id = {f["id"]: f for f in FEATURES}
    return [{k: by_id[i][k] for k in ("id", "label", "icon", "route")} for i in ids]


# ---------- the page ----------

async def moment(now: datetime | None = None, slot: str | None = None) -> Moment:
    from . import places
    now = (now or datetime.now(WIB)).astimezone(WIB)
    s = slot if slot in SLOTS else slot_of(now)
    place = (await _safe("place", places.current())) or {}
    from . import appsettings
    payday = int((await appsettings.get("money")).get("payday") or 25)
    return Moment(now=now, slot=s, tags=tags_of(now, s, payday), place=place.get("place"))


def context_line(m: Moment, parts: list[str]) -> str:
    bits = [f"{DAYS[m.now.weekday()]} {m.now.day} {MONTHS[m.now.month - 1]}", m.now.strftime("%H.%M")]
    if m.place:
        bits.append(m.place.upper())
    return " · ".join(bits + [p for p in parts if p])


def subtitle(needs: int, running: int) -> str:
    if needs:
        return f"{'Satu hal' if needs == 1 else f'{needs} hal'} butuh keputusanmu. Sisanya aku urus."
    if running:
        return f"{running} misi sedang aku kerjakan."
    return "Semua aman. Mau aku bantu apa?"


async def feed(slot: str | None = None, now: datetime | None = None) -> dict:
    m = await moment(now, slot)
    results = await asyncio.gather(*(_safe(n, fn(m)) for n, fn in PROVIDERS.items()))
    cards: list[Card] = []
    for name, got in zip(PROVIDERS, results):
        for c in got or []:
            cards.append({"kind": name, **c})
    parts = await asyncio.gather(*(_safe(n, fn(m), 3.0) for n, fn in CONTEXT.items()))
    hero, side = pick(cards)
    needs = sum(1 for c in cards if c["kind"] == "needs")
    running = sum(int(c.get("count") or 0) for c in cards if c["kind"] == "missions")
    return {"slot": m.slot, "tags": sorted(m.tags), "place": m.place, "context": context_line(m, [p for p in parts if p]),
            "greeting": GREETING[m.slot], "subtitle": subtitle(needs, running), "hero": hero, "cards": side,
            "shortcuts": await shortcuts(m), "needs": needs, "all": sorted(cards, key=lambda c: -float(c.get("score") or 0))}


# ---------- the providers every app has ----------

@provider("needs")
async def _needs(m: Moment) -> list[Card]:
    from . import needs as needs_mod
    out = []
    for i, n in enumerate(await needs_mod.listing()):
        out.append({"id": f"need:{n['kind']}:{n['id']}", "title": n["title"], "sub": n.get("sub", ""), "route": "#/butuh",
                    "icon": n.get("icon", "shield"), "tone": "amber", "cta": n.get("cta", "Tinjau"), "score": 100 - i, "need": n})   # answered right on the card
    return out


@provider("missions")
async def _missions(m: Moment) -> list[Card]:
    from . import workers
    running = [w for w in await workers.overview() if w.get("status") in ("queued", "running")]
    if not running:
        return []
    top = running[0]
    sub = f"{len(running)} misi berjalan" if len(running) > 1 else ("antre" if top["status"] == "queued" else "sedang dikerjakan")
    return [{"id": "missions", "title": top.get("title") or "Misi", "sub": sub, "route": f"#/misi/{top['task_id']}", "icon": "layers",
             "tone": "violet", "score": 45, "count": len(running),
             "list": [{"id": w["task_id"], "title": (w.get("title") or "Misi")[:80], "status": w["status"], "progress": w.get("progress"),
                       "phase": w.get("phase") or w.get("runtime_note") or "", "route": f"#/misi/{w['task_id']}"} for w in running[:4]]}]


@provider("scheduled")
async def _scheduled(m: Moment) -> list[Card]:
    """Recurring missions: his projects with a schedule, the next run within a day."""
    from . import projects
    rows = await db.pool().fetch("SELECT id, name, schedule, at_time, weekday, next_run FROM projects WHERE schedule <> 'manual' AND next_run IS NOT NULL "
                                 "AND next_run < now() + interval '24 hours' ORDER BY next_run LIMIT 3")
    if not rows:
        return []
    items = [{"id": r["id"], "title": r["name"], "when": r["next_run"].astimezone(m.now.tzinfo).strftime("%H.%M"), "repeat": projects.schedule_text(dict(r))} for r in rows]
    return [{"id": "scheduled", "title": f"Terjadwal: {items[0]['title']}", "sub": f"{items[0]['repeat']} · berikutnya {items[0]['when']}" + (f" · +{len(items) - 1}" if len(items) > 1 else ""),
             "route": "#/misi?tab=jadwal", "icon": "clock", "tone": "cyan", "score": 22, "list": items}]


@provider("tasks")
async def _tasks(m: Moment) -> list[Card]:
    from . import notes
    today = [t for t in await notes.tasks("today") if not t.get("checked")]
    if not today:
        return []
    first = today[0].get("text") or ""
    return [{"id": "tasks", "title": f"{len(today)} tugas hari ini", "sub": first[:80], "route": "#/catatan", "icon": "notes", "tone": "cyan",
             "score": 35 + (15 if m.slot in ("pagi", "kerja") else 0)}]


@provider("meeting")
async def _meeting(m: Moment) -> list[Card]:
    from . import meetings
    card = await meetings.desk_card()
    if not card:
        return []
    return [{"id": "meeting", "title": card.get("title") or "Rapat sedang direkam", "sub": "Merekam · ketuk untuk lihat transkrip",
             "route": "#/rapat", "icon": "meet", "tone": "red", "cta": "Buka rapat", "score": 95}]


@provider("player")
async def _player(m: Moment) -> list[Card]:
    from . import stage
    p = stage.desk_player()
    if not p:
        return []
    title = p.get("title") or p.get("name") or "Musik"
    return [{"id": "player", "title": title[:80], "sub": "Sedang diputar", "route": "#/musik", "icon": "music", "tone": "amber", "score": 20}]
