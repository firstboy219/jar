"""Background workers ("agen worker"): each task the main agent delegates runs as its own Hermes session.

Tasks are unlimited — they queue in Postgres — and up to `worker_concurrency` run at once. Workers keep
running when the phone disconnects; their live progress is broadcast to connected devices and their
result becomes a spoken report (see reports.py).
"""

import asyncio
import logging

from . import approvals, audit, db, gateway, hermes, hub, memory, quick, reports, writer
from .config import settings
from .location import Location, context_prefix

log = logging.getLogger("jarvis-core.workers")

_sem: asyncio.Semaphore | None = None
_running: dict[int, asyncio.Task] = {}
_stopping: set[int] = set()  # stopped by "Netralkan": kept as 'stopped' (retry/close), not 'cancelled'
_progress: dict[int, list[str]] = {}  # what a running worker has done so far (for a retry after a stop)
_background_turn: asyncio.Lock | None = None  # one background Hermes task at a time on the local CPU
waiting: set[int] = set()  # background tasks waiting for their turn on the CPU

# Intent and context only — how to do the work (tools, skills, sub-agents, schedules) is Hermes' call.
WORKER_BRIEF = (
    "Pemilik (lewat agen utama JARVIS yang sedang mengobrol dengannya) memintamu mengerjakan ini; ia tidak "
    "menunggu di chat ini. Kalau butuh jawabannya untuk melanjutkan, tanya lewat ask_owner. Hasil akhirmu "
    "akan diringkas dan diucapkan ke pemilik, jadi akhiri dengan HASIL: fakta/angka penting, sumber, dan "
    "langkah berikutnya bila ada.\n\n"
)
WORKER_CATEGORIES = ("web", "coding", "produktivitas", "analisis", "latar-belakang", "privat")
KIND_CATEGORY = {"situation": "web", "routine": "latar-belakang", "selfcheck": "latar-belakang", "selfimprove": "coding",
                 "flowcheck": "latar-belakang"}


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
    if category not in WORKER_CATEGORIES and not (category and (await gateway.categories()).get(category, {}).get("worker")):
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
    if kind not in ("owner", "meeting"):  # everything JARVIS starts by itself is listed for the owner
        from . import ops
        ops.note(f"Mulai {ops.KIND_TEXT.get(kind, kind)} #{task['id']}: {task['title']}.")
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

        turn = None
        try:
            result = None
            turn = await _yield_to_owner(task_id, kind, row)
            if row["instruction"].startswith(writer.MARK):  # a draft (email, reply, letter): written by core, minutes not hours
                await hub.broadcast({"type": "task_event", "task_id": task_id,
                                     "event": {"type": "thought", "text": "menulis draf"}})
                result = hermes.HermesReply(await writer.produce(task_id, row["instruction"], row["private"]), None, None, 0)
            elif await _quick_first(kind, row):  # simple look-up while workers run locally: seconds, not a Hermes session
                await hub.broadcast({"type": "task_event", "task_id": task_id,
                                     "event": {"type": "thought", "text": "mencari cepat di web"}})
                if text := await quick.answer(row["instruction"]):
                    result = hermes.HermesReply(text, None, None, 0)
            for attempt in range(HERMES_RETRIES + 1):
                events = _nothing() if result else hermes.stream(
                    context + brief + row["instruction"], f"task-{task_id}", row["image"],
                    model=f"jarvis-{row['category']}", on_run=remember_run)
                started = False
                try:
                    async for ev in events:
                        started = True
                        if ev["type"] == "done":
                            result = ev["reply"]
                            continue
                        if ev["type"] == "approval":
                            await _bridge_approval(task_id, row["title"], ev)
                            continue
                        await hub.broadcast({"type": "task_event", "task_id": task_id, "event": ev})
                        _note(task_id, ev)
                        if ev["type"] == "tool" and ev["name"] == "memory_search" and ev["status"] == "running":
                            await hub.broadcast({"type": "task_event", "task_id": task_id,
                                                 "event": await memory.context_event(ev["label"])})
                    break
                except hermes.HermesError as e:
                    # Hermes restarting (deploy, crash): wait for it instead of failing the owner's task
                    if started or "tidak dapat dihubungi" not in str(e) or attempt == HERMES_RETRIES:
                        raise
                    log.warning("worker %s: Hermes unreachable, retry %s", task_id, attempt + 1)
                    await asyncio.sleep(HERMES_RETRY_S)
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
            stopped = task_id in _stopping
            await db.pool().execute(
                "UPDATE tasks SET status = $2, finished_at = now(), progress = coalesce($3, progress) WHERE id = $1",
                task_id, "stopped" if stopped else "cancelled", progress_text(task_id) if stopped else None)
            await hub.broadcast({"type": "task", "id": task_id, "title": row["title"], "status": "stopped" if stopped else "cancelled"})
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
            if kind == "owner" and "saldo OpenRouter habis" not in str(e):  # JARVIS looks for its own way next time
                from . import perf
                await perf.capability_gap("tugas", row["title"] + ": " + row["instruction"][:300], str(e))
        finally:
            if turn is not None:
                turn.release()
            _stopping.discard(task_id)
            _progress.pop(task_id, None)
            waiting.discard(task_id)


DRAFT_TITLE = "Menulis draf"
BACKGROUND_KINDS = ("selfimprove", "selfcheck", "routine", "situation")
RESUME_MARK = "\n\n---LANJUTAN---\n"
HERMES_RETRIES, HERMES_RETRY_S = 6, 20  # up to 2 minutes for Hermes to come back


async def _yield_to_owner(task_id: int, kind: str, row) -> asyncio.Lock | None:
    """On the local CPU one Hermes session at a time is already slow: JARVIS' own background work
    (self-improvement, self-check, habits) waits while the owner has work running or is talking."""
    global _background_turn
    if kind not in BACKGROUND_KINDS:
        return None
    from . import ops
    if _background_turn is None:
        _background_turn = asyncio.Lock()
    while not (await gateway.plan(row["category"], caller="worker", worker=True))[0].cloud:
        talking = await db.pool().fetchval(
            "SELECT EXISTS (SELECT 1 FROM messages WHERE role = 'user' AND created_at > now() - interval '5 minutes')")
        ok, why = await ops.background_ok()
        if ok and not talking and not _background_turn.locked():
            await _background_turn.acquire()  # several background sessions on one CPU slot only evict each other's cache
            if task_id in waiting:
                ops.note(f"Giliran {ops.KIND_TEXT.get(kind, kind)} #{task_id} dimulai: {row['title']}.")
            waiting.discard(task_id)
            return _background_turn
        why = why or ("kamu sedang mengobrol denganku" if talking else "kerja latar lain sedang berjalan (satu per satu)")
        if task_id not in waiting:
            ops.note(f"{ops.KIND_TEXT.get(kind, kind).capitalize()} #{task_id} menunggu giliran — {why}.")
        waiting.add(task_id)
        await hub.broadcast({"type": "task_event", "task_id": task_id, "event": {"type": "thought", "text": f"menunggu: {why}"}})
        await asyncio.sleep(60)
    return None


async def _nothing():
    return
    yield


async def _quick_first(kind: str, row) -> bool:
    if kind != "owner" or row["image"] or row["category"] != "web" or not quick.suitable(row["instruction"]):
        return False
    return not (await gateway.plan("web", caller="worker", private=row["private"], worker=True))[0].cloud


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
    elif title.startswith(DRAFT_TITLE):
        await reports._create(task_id, session_id, result)  # already worded for the owner
    else:
        if kind == "selfimprove":  # a flow watcher fix finished: its issues are handled
            from . import auditor
            await auditor.on_fix_done(task_id)
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


def _note(task_id: int, ev: dict) -> None:
    """Remember the worker's steps briefly: tools used and its latest thinking."""
    steps = _progress.setdefault(task_id, [])
    if ev.get("type") == "tool" and ev.get("status") != "running":
        steps.append(f"- alat {ev.get('name')}: {str(ev.get('label') or '')[:120]}")
    elif ev.get("type") == "thought" and ev.get("text"):
        if steps and steps[-1].startswith("- pikir: "):
            steps[-1] = (steps[-1] + str(ev["text"]))[-600:]
        else:
            steps.append("- pikir: " + str(ev["text"])[-400:])
    del steps[:-25]


def progress_text(task_id: int) -> str | None:
    steps = _progress.get(task_id)
    return "\n".join(steps)[-4000:] if steps else None


async def stop(task_id: int, actor: str) -> bool:
    """Stop a task but keep it (status 'stopped') so the owner can retry it with what it had done, or close it."""
    row = await db.pool().fetchrow("SELECT status, hermes_run, kind FROM tasks WHERE id = $1", task_id)
    if not row or row["status"] not in ("queued", "running"):
        return False
    _stopping.add(task_id)
    if row["hermes_run"] and row["status"] == "running":
        try:
            await hermes.stop(row["hermes_run"])
        except Exception:
            log.warning("could not stop Hermes run of task %s", task_id)
    t = _running.get(task_id)
    if row["status"] == "queued":  # still waiting for a free worker slot: nothing to keep yet
        await db.pool().execute("UPDATE tasks SET status = 'stopped', finished_at = now() WHERE id = $1 AND status = 'queued'", task_id)
    if t and not t.done():
        t.cancel()  # a running one records 'stopped' + its progress in the CancelledError handler
    else:
        await db.pool().execute(
            "UPDATE tasks SET status = 'stopped', finished_at = now() WHERE id = $1 AND status IN ('queued', 'running')", task_id)
        _stopping.discard(task_id)
    await audit.record(actor, "task.stopped", f"task:{task_id}")
    return True


async def stop_all(actor: str) -> list[dict]:
    rows = await db.pool().fetch("SELECT id, title, kind FROM tasks WHERE status IN ('queued', 'running') ORDER BY id")
    for r in rows:
        await stop(r["id"], actor)
    return [dict(r) for r in rows]


async def retry(task_id: int, actor: str) -> dict | None:
    """Run a stopped (or failed) task again; it continues from what it had done."""
    row = await db.pool().fetchrow("SELECT id, title, status, kind, instruction, progress FROM tasks WHERE id = $1", task_id)
    if not row or row["status"] not in ("stopped", "failed") or row["kind"] == "flowcheck":
        return None
    instruction = row["instruction"].split(RESUME_MARK)[0]
    if row["progress"]:
        instruction += (RESUME_MARK + "Tugas ini sempat dihentikan pemilik untuk meringankan server. Yang sudah "
                        "dikerjakan sebelumnya:\n" + row["progress"] + "\nLanjutkan dari situ; jangan ulangi langkah yang sudah selesai.")
    await db.pool().execute(
        """UPDATE tasks SET status = 'queued', instruction = $2, started_at = NULL, finished_at = NULL, error = NULL
           WHERE id = $1""", task_id, instruction[:16000])
    await audit.record(actor, "task.retried", f"task:{task_id}")
    await hub.broadcast({"type": "task", "id": task_id, "title": row["title"], "status": "queued", "kind": row["kind"]})
    _start(task_id)
    return {"id": task_id, "status": "queued"}


async def close(task_id: int, actor: str) -> bool:
    """The owner does not want a stopped/failed task any more."""
    r = await db.pool().execute(
        "UPDATE tasks SET status = 'cancelled' WHERE id = $1 AND status IN ('stopped', 'failed')", task_id)
    if r.endswith("1"):
        await audit.record(actor, "task.closed", f"task:{task_id}")
        await hub.broadcast({"type": "task", "id": task_id, "title": "", "status": "cancelled"})
        return True
    return False


async def stopped() -> list[dict]:
    rows = await db.pool().fetch(
        "SELECT id, title, kind, finished_at FROM tasks WHERE status = 'stopped' ORDER BY id DESC LIMIT 10")
    return [dict(r) for r in rows]


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
    await db.pool().execute(  # the flow watcher runs inside core, not as a Hermes session: just close it
        "UPDATE tasks SET status = 'failed', error = 'dihentikan oleh restart', finished_at = now() "
        "WHERE kind = 'flowcheck' AND status IN ('queued', 'running')")
    rows = await db.pool().fetch(
        "UPDATE tasks SET status = 'queued', started_at = NULL WHERE status IN ('queued', 'running') RETURNING id")
    for r in rows:
        _start(r["id"])
    return len(rows)
