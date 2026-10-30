"""Proactive notifications: the phone forwards notifications, JARVIS decides what is worth saying.

Notifications arriving close together are batched (DEBOUNCE_S) and triaged by the main-agent model:
  skip     — promos, routine, duplicates: logged only
  announce — worth a short spoken mention, once
  urgent   — important/time-critical: becomes a report, repeated until the owner confirms hearing it
Quiet hours (default 22:00–06:00 WIB) only let urgent ones through. Content flagged sensitive (OTP,
passwords, card numbers) never goes to the cloud model; only "a sensitive notification from <app>".
"""

import asyncio
import logging
import re
from datetime import datetime, timedelta, timezone

from pydantic import BaseModel, Field

from . import audit, db, hub, reports, sensitive
from .config import settings
from .location import WIB

log = logging.getLogger("jarvis-core.notifications")
DEBOUNCE_S = 5.0
RETENTION_DAYS = 7
OTP = re.compile(r"\b(otp|kode (verifikasi|otp|keamanan)|verification code|one[- ]time|kode rahasia|pin)\b", re.IGNORECASE)

_pending: list[dict] = []
_flush_task: asyncio.Task | None = None


class Notification(BaseModel):
    app: str = Field(min_length=1, max_length=80)
    package: str = Field(min_length=1, max_length=200)
    title: str = Field(default="", max_length=300)
    text: str = Field(default="", max_length=2000)
    posted_at: int = Field(ge=0)  # epoch ms on the phone


TRIAGE = """Kamu JARVIS. Pemilik minta kamu memberi tahu notifikasi HP-nya tanpa menunggu ditanya, \
tapi jangan mengganggu untuk hal remeh. Untuk setiap notifikasi berikut, putuskan:
- "skip": promo, iklan, notifikasi rutin aplikasi, update, sistem, grup ramai yang tidak menyebut pemilik.
- "announce": pesan pribadi dari orang, info yang mungkin ingin ia tahu sekarang.
- "urgent": penting/mendesak — transaksi/keuangan tak terduga, keamanan akun, panggilan tak terjawab \
berulang, kabar keluarga, tenggat hari ini.
Lalu tulis SATU kalimat lisan singkat (bahasa Indonesia natural, tanpa markdown) yang merangkum semua \
yang tidak di-skip, mis. "Ada WhatsApp dari Budi: rapat jadi jam 3." Jika semuanya skip, kalimat kosong.
Jawab HANYA JSON: {"decisions": [{"id": <id>, "decision": "skip|announce|urgent"}], "say": "<kalimat>"}"""


def quiet_now(now: datetime | None = None) -> bool:
    start, _, end = settings.quiet_hours.partition("-")
    if not start or not end:
        return False
    t = (now or datetime.now(timezone.utc)).astimezone(WIB).strftime("%H:%M")
    return (start <= t < end) if start < end else (t >= start or t < end)


def redact(n: Notification) -> tuple[str, str, bool]:
    """Title/text safe for the cloud model; flag when content was withheld."""
    blob = f"{n.title} {n.text}"
    if sensitive.scan(blob) or OTP.search(blob):
        return f"{n.app}: notifikasi sensitif", "(isi disembunyikan — mungkin OTP/kode/kata sandi)", True
    return n.title, n.text, False


async def receive(n: Notification, device_id) -> int:
    title, text, is_sensitive = redact(n)
    posted = datetime.fromtimestamp(n.posted_at / 1000, timezone.utc)
    nid = await db.pool().fetchval(
        """INSERT INTO notifications (device_id, app, package, title, text, sensitive, posted_at)
           VALUES ($1, $2, $3, $4, $5, $6, $7) RETURNING id""",
        device_id, n.app, n.package, title, text, is_sensitive, posted)
    _pending.append({"id": nid, "app": n.app, "title": title, "text": text})
    _schedule_flush()
    return nid


def _schedule_flush() -> None:
    global _flush_task
    if _flush_task is None or _flush_task.done():
        _flush_task = asyncio.create_task(_flush_later())


async def _flush_later() -> None:
    await asyncio.sleep(DEBOUNCE_S)
    batch = _pending[:]
    _pending.clear()
    if batch:
        try:
            await triage(batch)
        except Exception:
            log.exception("notification triage failed")


async def triage(batch: list[dict]) -> dict:
    listing = "\n".join(f'- id {b["id"]} | {b["app"]} | {b["title"]} | {b["text"][:400]}' for b in batch)
    from . import master   # through the master flow (ADR-087); a notification is personal: never a free endpoint
    try:
        result = await master.ask(master.Job("perhatian", "notif-triase", "pilah notifikasi HP: abaikan, sebutkan, atau mendesak", trigger="event",
                                             messages=[{"role": "system", "content": TRIAGE}, {"role": "user", "content": f"Notifikasi:\n{listing}"}],
                                             json_out=True, no_free=True, max_tokens=300))
        if not isinstance(result, dict):
            raise ValueError("bukan objek JSON")
    except (master.FlowError, ValueError) as e:
        log.warning("triage unavailable (%s); announcing plainly", e)
        result = {"decisions": [{"id": b["id"], "decision": "announce"} for b in batch],
                  "say": "Ada notifikasi baru: " + "; ".join(f'{b["app"]} — {b["title"]}' for b in batch[:3])}
    decisions = {int(d["id"]): d.get("decision", "skip") for d in result.get("decisions", []) if str(d.get("id", "")).isdigit()}
    say = str(result.get("say") or "").strip()
    level = "urgent" if "urgent" in decisions.values() else ("announce" if "announce" in decisions.values() else "skip")
    if level == "announce" and quiet_now():
        level = "skip"  # quiet hours: only urgent gets through
    for b in batch:
        await db.pool().execute("UPDATE notifications SET decision = $2, spoken = $3 WHERE id = $1",
                                b["id"], decisions.get(b["id"], "skip"), say if level != "skip" else None)
    if level == "urgent" and say:
        await reports._create(None, "notifications", say)  # repeated until acknowledged
    elif level == "announce" and say:
        await hub.broadcast({"type": "announce", "text": say})
    await audit.record("jarvis-core", f"notifications.{level}", None, count=len(batch))
    return {"level": level, "say": say, "decisions": decisions}


async def recent(limit: int = 10) -> list[dict]:
    rows = await db.pool().fetch(
        "SELECT id, app, title, text, posted_at, decision FROM notifications ORDER BY id DESC LIMIT $1", limit)
    return [dict(r) for r in rows]


async def purge_old() -> int:
    result = await db.pool().execute(
        "DELETE FROM notifications WHERE received_at < now() - make_interval(days => $1)", RETENTION_DAYS)
    return int(result.split()[-1])
