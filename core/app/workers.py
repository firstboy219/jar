"""Background workers ("agen worker"): each task the main agent delegates runs as its own Hermes session.

Tasks are unlimited — they queue in Postgres — and up to `worker_concurrency` run at once. Workers keep
running when the phone disconnects; their live progress is broadcast to connected devices and their
result becomes a spoken report (see reports.py).
"""

import asyncio
import logging

from . import audit, db, hermes, hub, memory, reports
from .config import settings
from .location import Location, context_prefix

log = logging.getLogger("jarvis-core.workers")

_sem: asyncio.Semaphore | None = None
_running: dict[int, asyncio.Task] = {}

WORKER_BRIEF = (
    "Kamu adalah WORKER JARVIS. Agen utama menugaskanmu satu pekerjaan dari pemilik; pemilik tidak sedang "
    "menunggu di chat ini. Kerjakan sampai tuntas dengan alat yang ada (web, memori, n8n, dll). "
    "Tindakan berisiko tetap lewat request_approval. Akhiri dengan HASIL: fakta/angka penting, sumber, dan "
    "langkah berikutnya bila ada — padat, tanpa basa-basi; hasil ini akan diringkas dan diucapkan ke pemilik.\n\n"
)


def _sem_() -> asyncio.Semaphore:
    global _sem
    if _sem is None:
        _sem = asyncio.Semaphore(settings.worker_concurrency)
    return _sem


async def spawn(title: str, instruction: str, session_id: str, actor: str, device_id=None,
                location: Location | None = None) -> dict:
    row = await db.pool().fetchrow(
        """INSERT INTO tasks (session_id, device_id, title, instruction) VALUES ($1, $2, $3, $4)
           RETURNING id, title, status, created_at""",
        session_id, device_id, title.strip()[:120] or "Tugas", instruction.strip()[:8000])
    task = dict(row)
    await audit.record(actor, "task.spawned", f"task:{task['id']}", title=task["title"])
    await hub.broadcast({"type": "task", "id": task["id"], "title": task["title"], "status": "queued"})
    _start(task["id"], context_prefix(location))
    return task


def _start(task_id: int, context: str = "") -> None:
    t = asyncio.create_task(_run(task_id, context))
    _running[task_id] = t
    t.add_done_callback(lambda _: _running.pop(task_id, None))


async def _run(task_id: int, context: str) -> None:
    async with _sem_():
        row = await db.pool().fetchrow(
            "UPDATE tasks SET status = 'running', started_at = now() WHERE id = $1 AND status = 'queued' "
            "RETURNING id, title, instruction, session_id", task_id)
        if row is None:  # cancelled while queued
            return
        await hub.broadcast({"type": "task", "id": task_id, "title": row["title"], "status": "running"})
        try:
            result = None
            async for ev in hermes.stream(context + WORKER_BRIEF + row["instruction"], f"task-{task_id}"):
                if ev["type"] == "done":
                    result = ev["reply"]
                    continue
                await hub.broadcast({"type": "task_event", "task_id": task_id, "event": ev})
                if ev["type"] == "tool" and ev["name"] == "memory_search" and ev["status"] == "running":
                    await hub.broadcast({"type": "task_event", "task_id": task_id,
                                         "event": await memory.context_event(ev["label"])})
            await db.pool().execute(
                """UPDATE tasks SET status = 'completed', result = $2, finished_at = now(),
                   prompt_tokens = $3, completion_tokens = $4 WHERE id = $1""",
                task_id, result.text, result.prompt_tokens, result.completion_tokens)
            await hub.broadcast({"type": "task", "id": task_id, "title": row["title"], "status": "completed"})
            await reports.from_task(task_id, row["title"], result.text, row["session_id"])
        except asyncio.CancelledError:
            await db.pool().execute(
                "UPDATE tasks SET status = 'cancelled', finished_at = now() WHERE id = $1", task_id)
            await hub.broadcast({"type": "task", "id": task_id, "title": row["title"], "status": "cancelled"})
            raise
        except Exception as e:
            log.exception("worker %s failed", task_id)
            await db.pool().execute(
                "UPDATE tasks SET status = 'failed', error = $2, finished_at = now() WHERE id = $1",
                task_id, str(e)[:1000])
            await hub.broadcast({"type": "task", "id": task_id, "title": row["title"], "status": "failed"})
            await reports.from_failure(task_id, row["title"], str(e), row["session_id"])


async def cancel(task_id: int, actor: str) -> bool:
    t = _running.get(task_id)
    changed = await db.pool().execute(
        "UPDATE tasks SET status = 'cancelled', finished_at = now() WHERE id = $1 AND status IN ('queued', 'running')",
        task_id)
    if t:
        t.cancel()
    ok = changed.endswith("1")
    if ok:
        await audit.record(actor, "task.cancelled", f"task:{task_id}")
    return ok


async def active() -> list[dict]:
    rows = await db.pool().fetch(
        "SELECT id, title, status, created_at, started_at FROM tasks WHERE status IN ('queued', 'running') ORDER BY id")
    return [dict(r) for r in rows]


async def recent(limit: int = 50) -> list[dict]:
    rows = await db.pool().fetch(
        """SELECT id, title, status, instruction, result, error, created_at, started_at, finished_at
           FROM tasks ORDER BY id DESC LIMIT $1""", limit)
    return [dict(r) for r in rows]


async def resume_after_restart() -> int:
    """Tasks interrupted by a restart are re-run (workers are research/drafting; risky actions go
    through idempotent approvals, so re-running is safe)."""
    rows = await db.pool().fetch(
        "UPDATE tasks SET status = 'queued', started_at = NULL WHERE status IN ('queued', 'running') RETURNING id")
    for r in rows:
        _start(r["id"])
    return len(rows)
