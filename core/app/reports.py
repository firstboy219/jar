"""Spoken reports: how worker results reach the owner.

Lifecycle: pending → (phone speaks/shows it, sends `report_spoken`) delivered → acknowledged
(tap "Oke", or the main agent recognises a spoken acknowledgement). A report is spoken ONCE: a pending one is
re-pushed only while the phone has not confirmed speaking it. Delivered reports are never repeated or chased
(the owner turned "make sure I heard" off, 2026-10-26); they stay listed in the app until acknowledged.
"""

import asyncio
import logging
import time

from . import audit, db, hub, llm
from .config import settings

log = logging.getLogger("jarvis-core.reports")
_last_sent: dict[int, float] = {}  # report id -> monotonic time pushed to devices (pending re-push throttle)

WORDING = (
    "Kamu JARVIS. Ubah hasil kerja worker berikut menjadi pesan LISAN untuk pemilik: maksimal 3 kalimat, "
    "bahasa Indonesia natural, tanpa markdown/emoji/daftar, sebut angka atau fakta terpenting, mulai dengan "
    "menyebut tugasnya secara singkat. Jangan menambah fakta yang tidak ada di hasil.")


async def _word(title: str, result: str) -> str:
    try:
        text = await llm.complete([
            {"role": "system", "content": WORDING},
            {"role": "user", "content": f"Tugas: {title}\n\nHasil worker:\n{result[:6000]}"},
        ], max_tokens=220)
    except llm.LLMError as e:
        log.warning("report wording failed: %s", e)
        text = ""
    return text or f"Tugas {title} sudah selesai. {result[:400]}"


async def _create(task_id: int | None, session_id: str, text: str) -> dict:
    row = await db.pool().fetchrow(
        # the task may be gone (closed / its project deleted) by the time its report is written: keep the report, drop the link
        "INSERT INTO reports (task_id, session_id, text) VALUES ((SELECT id FROM tasks WHERE id = $1), $2, $3) RETURNING *",
        task_id, session_id, text)
    await db.pool().execute(
        "INSERT INTO messages (session_id, role, content, route) VALUES ($1, 'assistant', $2, 'report')",
        session_id, text)
    report = dict(row)
    await push(report)
    return report


async def from_task(task_id: int, title: str, result: str, session_id: str) -> dict:
    return await _create(task_id, session_id, await _word(title, result))


async def from_failure(task_id: int, title: str, error: str, session_id: str) -> dict:
    return await _create(task_id, session_id, f"Maaf, tugas {title} gagal dikerjakan: {error[:200]}")


def _event(r: dict, repeat: bool = False) -> dict:
    return {"type": "report", "id": r["id"], "task_id": r["task_id"], "text": r["text"],
            "attempt": r["attempts"] + 1, "repeat": repeat}


async def push(r: dict, repeat: bool = False) -> bool:
    if await hub.broadcast(_event(r, repeat)):
        _last_sent[r["id"]] = time.monotonic()
        return True
    return False


async def spoken(report_id: int) -> None:
    """The phone has said (or shown) it — this is what counts as one delivery attempt."""
    await db.pool().execute(
        """UPDATE reports SET status = 'delivered', attempts = attempts + 1, delivered_at = now()
           WHERE id = $1 AND status IN ('pending', 'delivered')""", report_id)


async def acknowledge(ids: list[int], by: str) -> list[int]:
    rows = await db.pool().fetch(
        """UPDATE reports SET status = 'acknowledged', acked_at = now(), acked_by = $2
           WHERE id = ANY($1::bigint[]) AND status IN ('pending', 'delivered', 'unheard') RETURNING id""",
        ids, by)
    done = [r["id"] for r in rows]
    for i in done:
        _last_sent.pop(i, None)
        await hub.broadcast({"type": "report_ack", "id": i})
    if done:
        await audit.record(by, "report.acknowledged", None, ids=done)
    return done


async def unconfirmed() -> list[dict]:
    rows = await db.pool().fetch(
        """SELECT r.id, r.task_id, r.text, r.status, r.attempts, t.title
           FROM reports r LEFT JOIN tasks t ON t.id = r.task_id
           WHERE r.status IN ('pending', 'delivered') ORDER BY r.id""")
    return [dict(r) for r in rows]


async def recent(limit: int = 50) -> list[dict]:
    rows = await db.pool().fetch("SELECT * FROM reports ORDER BY id DESC LIMIT $1", limit)
    return [dict(r) for r in rows]


async def on_connect(send) -> None:
    """A device (re)connected: give it everything not yet confirmed."""
    for r in await db.pool().fetch(  # only what the phone never spoke; a spoken ('delivered') report is not read out again
            "SELECT * FROM reports WHERE status = 'pending' ORDER BY id"):
        await send(_event(dict(r)))
        _last_sent[r["id"]] = time.monotonic()


async def tick() -> None:
    """One pass of the re-delivery policy (called every few seconds)."""
    if not hub.online():
        return
    now = time.monotonic()
    for r in await db.pool().fetch("SELECT * FROM reports WHERE status = 'pending' ORDER BY id"):
        if now - _last_sent.get(r["id"], 0) > 60:  # pushed but the phone never confirmed speaking it
            await push(dict(r))
    # A delivered report is never repeated or chased ("sudah dengar?"): the owner asked for that to stop (2026-10-26).
    # It stays listed until acknowledged (tap, or the main agent hearing the owner react).


async def run_forever(interval: float = 10) -> None:
    while True:
        try:
            await tick()
        except Exception:
            log.exception("report tick failed")
        await asyncio.sleep(interval)
