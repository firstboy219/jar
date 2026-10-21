"""Background workers ("agen worker"): each task the main agent delegates runs as its own Hermes session.

Tasks are unlimited — they queue in Postgres — and up to `worker_concurrency` run at once. Workers keep
running when the phone disconnects; their live progress is broadcast to connected devices and their
result becomes a spoken report (see reports.py).
"""

import asyncio
import logging

from . import approvals, audit, db, hermes, hub, memory, reports
from .config import settings
from .location import Location, context_prefix

log = logging.getLogger("jarvis-core.workers")

_sem: asyncio.Semaphore | None = None
_running: dict[int, asyncio.Task] = {}

# Intent and context only — how to do the work (tools, skills, sub-agents, schedules) is Hermes' call.
WORKER_BRIEF = (
    "Pemilik (lewat agen utama JARVIS yang sedang mengobrol dengannya) memintamu mengerjakan ini; ia tidak "
    "menunggu di chat ini. Kalau butuh jawabannya untuk melanjutkan, tanya lewat ask_owner. Hasil akhirmu "
    "akan diringkas dan diucapkan ke pemilik, jadi akhiri dengan HASIL: fakta/angka penting, sumber, dan "
    "langkah berikutnya bila ada.\n\n"
)
WORKER_CATEGORIES = ("web", "coding", "produktivitas", "analisis", "latar-belakang", "privat")
KIND_CATEGORY = {"situation": "web", "routine": "latar-belakang", "selfcheck": "latar-belakang"}


def _sem_() -> asyncio.Semaphore:
    global _sem
    if _sem is None:
        _sem = asyncio.Semaphore(settings.worker_concurrency)
    return _sem


async def spawn(title: str, instruction: str, session_id: str, actor: str, device_id=None,
                location: Location | None = None, kind: str = "owner", image: str | None = None,
                category: str | None = None, private: bool = False) -> dict:
    """kind: 'owner' (result spoken as a report) or an internal purpose handled by its module:
    'situation' (awareness), 'routine' (habits), 'selfcheck' (self-improvement).
    category: which AI does the work (gateway category); private tasks only ever use the local model."""
    from . import composition
    if category not in WORKER_CATEGORIES:
        category = KIND_CATEGORY.get(kind) or ("analisis" if await composition.strong_mode() else "web")
    if private:
        category = "privat"
    row = await db.pool().fetchrow(
        """INSERT INTO tasks (session_id, device_id, title, instruction, kind, image, category, private)
           VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
           RETURNING id, title, status, kind, category, created_at""",
        session_id, device_id, title.strip()[:120] or "Tugas", instruction.strip()[:12000], kind, image,
        category, private)
    task = dict(row)
    await audit.record(actor, "task.spawned", f"task:{task['id']}", title=task["title"], kind=kind)
    await hub.broadcast({"type": "task", "id": task["id"], "title": task["title"], "status": "queued", "kind": kind})
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
            "RETURNING id, title, instruction, session_id, kind, image, category, private", task_id)
        if row is None:  # cancelled while queued
            return
        kind = row["kind"]
        await hub.broadcast({"type": "task", "id": task_id, "title": row["title"], "status": "running", "kind": kind})
        # internal kinds carry their own instructions; the task number lets tools (ask_owner, documents) refer to it
        brief = f"[tugas #{task_id}] " + (WORKER_BRIEF if kind == "owner" else "")
        if row["image"]:
            brief += ("Gambar terlampir adalah apa yang ditunjukkan pemilik (kamera/layar) saat memberi tugas ini.\n"
                      f"DESKRIPSI GAMBAR (oleh agen utama, karena model worker mungkin tidak bisa melihat): "
                      f"{await describe_image(row['image'])}\n\n")
        async def remember_run(run_id: str) -> None:
            await db.pool().execute("UPDATE tasks SET hermes_run = $2 WHERE id = $1", task_id, run_id)

        try:
            result = None
            async for ev in hermes.stream(context + brief + row["instruction"], f"task-{task_id}", row["image"],
                                          model=f"jarvis-{row['category']}", on_run=remember_run):
                if ev["type"] == "done":
                    result = ev["reply"]
                    continue
                if ev["type"] == "approval":
                    await _bridge_approval(task_id, row["title"], ev)
                    continue
                await hub.broadcast({"type": "task_event", "task_id": task_id, "event": ev})
                if ev["type"] == "tool" and ev["name"] == "memory_search" and ev["status"] == "running":
                    await hub.broadcast({"type": "task_event", "task_id": task_id,
                                         "event": await memory.context_event(ev["label"])})
            from . import billing
            if billing.is_exhausted(result.text):  # Hermes reports a 402 as its "answer": it is a failure
                await billing.notify_exhausted()
                raise RuntimeError("saldo OpenRouter habis")
            await db.pool().execute(
                """UPDATE tasks SET status = 'completed', result = $2, finished_at = now(),
                   prompt_tokens = $3, completion_tokens = $4 WHERE id = $1""",
                task_id, result.text, result.prompt_tokens, result.completion_tokens)
            await hub.broadcast({"type": "task", "id": task_id, "title": row["title"], "status": "completed", "kind": kind})
            await _deliver(task_id, kind, row["title"], result.text, row["session_id"])
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
            await hub.broadcast({"type": "task", "id": task_id, "title": row["title"], "status": "failed", "kind": kind})
            # Background understanding failing is not worth interrupting for; an empty balance is
            # reported once by billing.notify_exhausted instead of once per task.
            if kind in ("owner", "selfcheck") and "saldo OpenRouter habis" not in str(e):
                await reports.from_failure(task_id, row["title"], str(e), row["session_id"])


async def _bridge_approval(task_id: int, title: str, ev: dict) -> None:
    """Hermes paused before a dangerous command: ask the owner (Approval Center on the phone/admin,
    spoken by the main agent) and pass the decision back. No answer within the expiry = denied."""
    a = await approvals.create(
        "hermes_command", f"{title}: {ev['description'] or 'perintah berisiko'}",
        {"run_id": ev["run_id"], "request_id": ev.get("request_id"), "command": ev["command"],
         "description": ev["description"], "task_id": task_id},
        "hermes", "high", idempotency_key=f"hermes:{ev['run_id']}:{ev.get('request_id') or ev['command'][:80]}")
    await hub.broadcast({"type": "approval", "id": a["id"], "title": a["title"], "risk": "high",
                         "detail": {"command": ev["command"], "description": ev["description"]}})
    await reports._create(task_id, "system", f"Aku butuh izinmu untuk tugas {title}: {ev['description'] or ev['command'][:120]}. "
                                             f"Setujui atau tolak di Persetujuan nomor {a['id']}.")

    async def wait_and_answer() -> None:
        for _ in range(60 * 60 // 3):  # Hermes itself gives up after approvals.timeout
            cur = await approvals.get(a["id"])
            if cur and cur["status"] != "awaiting_approval":
                ok = cur["status"] in ("approved", "executing", "completed")
                await hermes.answer_approval(ev["run_id"], ok, ev.get("request_id"))
                return
            await asyncio.sleep(3)
    asyncio.create_task(wait_and_answer())


async def describe_image(image: str) -> str:
    """The worker model is text-only: let the vision-capable main model write down what is in the picture."""
    from . import llm
    try:
        return await llm.complete([
            {"role": "system", "content": "Deskripsikan gambar ini selengkap mungkin untuk orang yang tidak bisa "
                                          "melihatnya: objek, merek/model, teks yang terbaca, angka, warna, kondisi. Padat, tanpa basa-basi."},
            {"role": "user", "content": [{"type": "text", "text": "Gambar:"},
                                         {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image}"}}]},
        ], category="penglihatan", max_tokens=350, caller="worker") or "(tidak ada deskripsi)"
    except Exception as e:
        return f"(gambar tidak bisa dideskripsikan: {type(e).__name__})"


async def _deliver(task_id: int, kind: str, title: str, result: str, session_id: str) -> None:
    """Where a finished worker's result goes, by purpose."""
    if kind == "situation":
        from . import awareness
        await awareness.on_situation(task_id, result)
    elif kind == "routine":
        pass  # the worker stored the habits it found as memories itself
    elif kind == "selfcheck":
        from . import selfimprove
        await reports._create(task_id, session_id, await selfimprove.on_selfcheck(task_id, result))
    else:
        await reports.from_task(task_id, title, result, session_id)


async def cancel(task_id: int, actor: str) -> bool:
    t = _running.get(task_id)
    run = await db.pool().fetchval("SELECT hermes_run FROM tasks WHERE id = $1 AND status = 'running'", task_id)
    if run:
        await hermes.stop(run)
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
        "SELECT id, title, status, kind, category, created_at, started_at FROM tasks WHERE status IN ('queued', 'running') ORDER BY id")
    return [dict(r) for r in rows]


async def recent(limit: int = 50) -> list[dict]:
    rows = await db.pool().fetch(
        """SELECT id, title, status, kind, category, private, instruction, result, error, created_at, started_at,
                  finished_at, prompt_tokens, completion_tokens FROM tasks ORDER BY id DESC LIMIT $1""", limit)
    return [dict(r) for r in rows]


async def resume_after_restart() -> int:
    """Tasks interrupted by a restart are re-run (workers are research/drafting; risky actions go
    through idempotent approvals, so re-running is safe)."""
    rows = await db.pool().fetch(
        "UPDATE tasks SET status = 'queued', started_at = NULL WHERE status IN ('queued', 'running') RETURNING id")
    for r in rows:
        _start(r["id"])
    return len(rows)
