"""Situational awareness: what makes the main agent "alive" instead of waiting to be asked.

The phone sends a context heartbeat (place, movement, battery/charging, headset, screen, upcoming
calendar events). On meaningful change — moved somewhere new, started driving, an event soon, or simply
a while since the last look — a *situation worker* is asked to work out where the owner is, what they are
probably doing and what they will likely want, and to prepare it. Understanding the situation is
delegated; the main agent keeps the result (SITUASI SAAT INI in its prompt) and decides whether to speak
first — at most once per PROACTIVE_GAP, never in quiet hours, never while the owner is mid-conversation.
A daily *routine worker* turns the coarse context history into remembered habits.
"""

import asyncio
import json
import logging
import math
import re
from datetime import datetime, timedelta, timezone

from pydantic import BaseModel, Field

from . import db, hub, memory, notifications
from .config import settings
from .location import WIB, Location, remember_last

log = logging.getLogger("jarvis-core.awareness")

PROACTIVE_GAP = timedelta(minutes=45)
PERIODIC_CHECK = timedelta(minutes=90)
MOVED_M = 400
CONTEXT_RETENTION_DAYS = 30

_state = {"context": None, "checked_at": None, "checked_at_place": None, "checked_activity": None,
          "announced_events": set(), "last_proactive": None, "situation": None}


class CalendarEvent(BaseModel):
    title: str = Field(max_length=200)
    start_ms: int
    end_ms: int | None = None
    location: str | None = Field(default=None, max_length=200)


class DeviceContext(BaseModel):
    location: Location | None = None
    activity: str = Field(default="unknown", pattern="^(still|walking|driving|unknown)$")
    speed_kmh: float | None = Field(default=None, ge=0, le=400)
    battery: int | None = Field(default=None, ge=0, le=100)
    charging: bool | None = None
    headset: bool | None = None
    screen_on: bool | None = None
    network: str | None = Field(default=None, max_length=20)
    unmuted: bool | None = None
    calendar: list[CalendarEvent] = Field(default_factory=list, max_length=8)
    app_version: str | None = Field(default=None, max_length=20)

    def describe(self) -> str:
        parts = []
        if self.location:
            parts.append(f"di {self.location.address or f'{self.location.lat:.4f},{self.location.lon:.4f}'}")
        parts.append({"still": "diam", "walking": "berjalan", "driving": "berkendara", "unknown": "gerak tidak diketahui"}[self.activity]
                     + (f" ({self.speed_kmh:.0f} km/j)" if self.speed_kmh else ""))
        if self.battery is not None:
            parts.append(f"baterai {self.battery}%{' (mengisi)' if self.charging else ''}")
        if self.headset:
            parts.append("pakai headset")
        if self.screen_on is not None:
            parts.append("layar menyala" if self.screen_on else "layar mati")
        if self.unmuted is not None:
            parts.append("mic JARVIS aktif" if self.unmuted else "mic JARVIS mati")
        for e in self.calendar[:3]:
            start = datetime.fromtimestamp(e.start_ms / 1000, timezone.utc).astimezone(WIB)
            parts.append(f"agenda '{e.title}' {start:%a %H:%M}" + (f" di {e.location}" if e.location else ""))
        return "; ".join(parts)


def distance_m(a: Location, b: Location) -> float:
    r = 6_371_000
    p1, p2 = math.radians(a.lat), math.radians(b.lat)
    dp, dl = p2 - p1, math.radians(b.lon - a.lon)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(h))


def current() -> DeviceContext | None:
    return _state["context"]


def situation() -> dict | None:
    return _state["situation"]


async def receive(ctx: DeviceContext) -> None:
    _state["context"] = ctx
    if ctx.location:
        await remember_last(ctx.location)
    await db.pool().execute(
        "INSERT INTO context_log (lat, lon, address, activity, charging, headset) VALUES ($1, $2, $3, $4, $5, $6)",
        round(ctx.location.lat, 3) if ctx.location else None, round(ctx.location.lon, 3) if ctx.location else None,
        ctx.location.address if ctx.location else None, ctx.activity, ctx.charging, ctx.headset)


def due_reason(ctx: DeviceContext, now: datetime) -> str | None:
    """Why a fresh look at the situation is needed now (None = not needed). Pure, unit-tested."""
    if _state["checked_at"] is None:
        return "pertama kali hari ini"
    if ctx.location and _state["checked_at_place"] and distance_m(ctx.location, _state["checked_at_place"]) > MOVED_M:
        return "pemilik berpindah tempat"
    if ctx.activity in ("driving", "walking") and ctx.activity != _state["checked_activity"]:
        return f"pemilik mulai {'berkendara' if ctx.activity == 'driving' else 'berjalan'}"
    for e in ctx.calendar:
        start = datetime.fromtimestamp(e.start_ms / 1000, timezone.utc)
        key = f"{e.title}@{e.start_ms}"
        if timedelta(0) < start - now <= timedelta(minutes=30) and key not in _state["announced_events"]:
            _state["announced_events"].add(key)
            return f"agenda '{e.title}' sebentar lagi"
    if now - _state["checked_at"] > PERIODIC_CHECK:
        return "pemeriksaan berkala"
    return None


SITUATION_TASK = """Kamu bertugas MEMAHAMI SITUASI pemilik sekarang untuk JARVIS (agen utama), supaya JARVIS bisa \
proaktif seperti asisten manusia. Alasan pemeriksaan: {reason}.

Konteks HP sekarang: {context}
Waktu: {time}
Notifikasi terbaru: {notifs}
Situasi terakhir yang dipahami: {last}

Langkah: cari di memori kebiasaan/rutinitas pemilik yang relevan dengan waktu & tempat ini (memory_search), \
pahami di mana ia berada (jenis tempat) dan kemungkinan sedang apa, lalu SIAPKAN info yang kemungkinan ia \
butuhkan sekarang (mis. cuaca/macet bila akan berangkat, persiapan agenda berikutnya, pengingat yang relevan). \
Jangan menebak berlebihan: tandai keyakinanmu. Jangan menghubungi siapa pun.

Akhiri HANYA dengan JSON:
{{"where": "…", "doing": "…", "likely_need": "…", "prepared": "info yang sudah kamu siapkan (singkat)",
  "confidence": 0.0-1.0, "speak": true/false, "line": "satu-dua kalimat lisan untuk menyapa pemilik bila speak=true"}}
speak=true hanya jika ada hal yang benar-benar berguna untuk disampaikan sekarang."""


async def tick(now: datetime | None = None) -> str | None:
    """One pass of the awareness loop; returns why a situation worker was started (or None)."""
    from . import workers
    now = now or datetime.now(timezone.utc)
    ctx = _state["context"]
    if ctx is None or not hub.online() or notifications.quiet_now(now):
        return None
    if any(t["kind"] == "situation" for t in await workers.active()):
        return None
    reason = due_reason(ctx, now)
    if not reason:
        return None
    _state.update(checked_at=now, checked_at_place=ctx.location, checked_activity=ctx.activity)
    recent = await notifications.recent(5)
    last = _state["situation"]
    instruction = SITUATION_TASK.format(
        reason=reason, context=ctx.describe(), time=now.astimezone(WIB).strftime("%A %d %B %Y %H:%M WIB"),
        notifs="; ".join(f"{n['app']}: {n['title']}" for n in recent) or "-",
        last=json.dumps({k: last[k] for k in ("where", "doing", "likely_need")}, ensure_ascii=False) if last else "-")
    await workers.spawn("Memahami situasi", instruction, "awareness", "jarvis-core", kind="situation",
                        location=ctx.location)
    return reason


def parse_json(text: str) -> dict:
    m = re.search(r"\{.*\}", text or "", re.DOTALL)
    try:
        return json.loads(m.group(0)) if m else {}
    except ValueError:
        return {}


async def owner_busy_talking(now: datetime) -> bool:
    last_user = await db.pool().fetchval(
        "SELECT max(created_at) FROM messages WHERE role = 'user' AND session_id NOT IN ('awareness', 'notifications')")
    return last_user is not None and now - last_user < timedelta(seconds=60)


async def on_situation(task_id: int, result: str, now: datetime | None = None) -> dict:
    """Situation worker finished: remember the understanding; maybe speak first."""
    now = now or datetime.now(timezone.utc)
    s = parse_json(result)
    if not s:
        log.warning("situation worker %s returned no JSON", task_id)
        return {"spoke": False}
    s["at"] = now.isoformat()
    _state["situation"] = s
    line = str(s.get("line") or "").strip()
    can_speak = (
        s.get("speak") is True and line and float(s.get("confidence") or 0) >= 0.5
        and not notifications.quiet_now(now)
        and (_state["last_proactive"] is None or now - _state["last_proactive"] >= PROACTIVE_GAP)
        and not await owner_busy_talking(now))
    if can_speak:
        _state["last_proactive"] = now
        await db.pool().execute(
            "INSERT INTO messages (session_id, role, content, route) VALUES ('awareness', 'assistant', $1, 'proactive')", line)
        await hub.broadcast({"type": "proactive", "text": line, "situation": {k: s.get(k) for k in ("where", "doing", "likely_need")}})
    return {"spoke": bool(can_speak), "situation": s}


def situation_block() -> str | None:
    s = _state["situation"]
    ctx = _state["context"]
    if not s and not ctx:
        return None
    lines = ["SITUASI SAAT INI (hasil pengamatan; bisa salah, konfirmasi bila ragu):"]
    if ctx:
        lines.append(f"- Sinyal HP: {ctx.describe()}")
    if s:
        lines.append(f"- Pemahaman: di {s.get('where', '?')}; kemungkinan sedang {s.get('doing', '?')}; "
                     f"kemungkinan butuh {s.get('likely_need', '?')} (keyakinan {s.get('confidence', '?')})")
        if s.get("prepared"):
            lines.append(f"- Sudah disiapkan: {s['prepared']}")
    return "\n".join(lines)


# ---------- routines ----------

ROUTINE_TASK = """Kamu bertugas mempelajari KEBIASAAN pemilik untuk JARVIS. Data 14 hari terakhir (lokasi kasar \
per jam, WIB):
{places}

Topik yang sering ia minta: {topics}

Simpulkan pola yang cukup kuat (muncul ≥3 hari), mis. "Hari kerja sekitar 07.30 berangkat dari Pondok Aren ke \
kantor" atau "Malam hari biasanya di rumah dan bertanya soal tagihan". Simpan SETIAP pola sebagai memori \
terpisah dengan memory_save(category="experience", kind="assumption"). Jangan simpan pola yang lemah atau \
data sensitif. Akhiri dengan ringkasan pola yang kamu simpan."""


async def routine_digest() -> tuple[str, str]:
    rows = await db.pool().fetch(
        """SELECT extract(isodow FROM at AT TIME ZONE 'Asia/Jakarta')::int AS dow,
                  extract(hour FROM at AT TIME ZONE 'Asia/Jakarta')::int AS hour,
                  coalesce(address, lat::text || ',' || lon::text, '?') AS place, activity, count(*) AS n
           FROM context_log WHERE at > now() - interval '14 days'
           GROUP BY 1, 2, 3, 4 ORDER BY 1, 2, n DESC""")
    days = ["", "Sen", "Sel", "Rab", "Kam", "Jum", "Sab", "Min"]
    places = "\n".join(f"{days[r['dow']]} {r['hour']:02d}:00 {r['place']} ({r['activity']}, {r['n']}x)" for r in rows[:300]) or "-"
    topics = await db.pool().fetch(
        """SELECT left(content, 80) AS c FROM messages WHERE role = 'user' AND route IN ('assistant', 'core')
           AND created_at > now() - interval '14 days' ORDER BY id DESC LIMIT 60""")
    return places, "; ".join(r["c"] for r in topics) or "-"


async def start_routine_learning() -> int | None:
    from . import workers
    places, topics = await routine_digest()
    if places == "-":
        return None
    t = await workers.spawn("Mempelajari kebiasaan", ROUTINE_TASK.format(places=places, topics=topics),
                            "awareness", "jarvis-core", kind="routine")
    return t["id"]


async def purge_old() -> None:
    await db.pool().execute(
        "DELETE FROM context_log WHERE at < now() - make_interval(days => $1)", CONTEXT_RETENTION_DAYS)


async def run_forever(interval: float = 60) -> None:
    last_routine_day = None
    while True:
        try:
            await tick()
            now = datetime.now(timezone.utc).astimezone(WIB)
            if now.hour == 4 and last_routine_day != now.date():  # once a day, early morning
                last_routine_day = now.date()
                await purge_old()
                await start_routine_learning()
        except Exception:
            log.exception("awareness tick failed")
        await asyncio.sleep(interval)
