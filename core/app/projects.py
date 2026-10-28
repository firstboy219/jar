"""The owner's projects (ADR-073): a goal, a schedule, and a team of workers by role.

Each role says what its workers do, how many there are (1–5; at most MAX_WORKERS per run), which AI model they use (any tool-capable
OpenRouter model, or the category's own choice) and whether they operate websites (open, click, fill in — e.g. helping to apply for jobs).
A run spawns every worker as an ordinary owner task: the worker rules (stop before sending anything personal, ask the owner, the owner may
take over the browser), the desk cards and the reports all apply. Workers with the same role split the work by their number.
The schedule is checked every minute (`tick`); times are the owner's (WIB).
"""

import difflib
import logging
import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from . import audit, db, phone_agent, results

log = logging.getLogger("jarvis-core.projects")
TZ = ZoneInfo("Asia/Jakarta")
SCHEDULES = ("manual", "hourly", "daily", "weekdays", "weekly")
MAX_WORKERS = 6          # per run, all roles together (the server's workers and the shared browser are finite)
MAX_ROLES = 6
_TIME = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
_MODEL = re.compile(r"^[a-z0-9][\w.\-]*/[\w.\-:]+$", re.IGNORECASE)
WEEKDAYS = ["Senin", "Selasa", "Rabu", "Kamis", "Jumat", "Sabtu", "Minggu"]

BRIEF = """[PROYEK: {name} · run #{run}] Kamu pekerja proyek ini dengan peran: {role} (pekerja {n} dari {total} dengan peran yang sama).
TUJUAN PROYEK: {goal}
TUGAS PERANMU: {brief}
{split}{web}Akhiri dengan HASIL: apa yang sudah kamu kerjakan dalam run ini (fakta, tautan, angka), apa yang tidak berhasil dan kenapa, dan apa
yang sebaiknya dikerjakan run berikutnya.
{format}"""
SPLIT = ("Ada {total} pekerja dengan peran ini yang bekerja bersamaan: ambil bagian ke-{n} (mis. item, halaman, perusahaan, atau rentang yang berbeda) "
         "supaya tidak mengulang pekerjaan rekanmu; sebut bagian mana yang kamu ambil.\n")
WEB = ("Peran ini MENGOPERASIKAN SITUS: kerjakan di browser (buka halaman, klik, ketik, gulir) — pemilik melihatnya langsung di Meja. "
       "BERHENTI sebelum mengirim lamaran/formulir, membuat akun, membayar, atau mengirim data pribadi: minta persetujuan lewat ask_owner dengan "
       "ringkasan apa yang akan dikirim. Terhalang login/captcha/OTP → ask_owner, pemilik bisa Intervensi.\n")


class ProjectError(ValueError):
    pass


def clean(data: dict) -> dict:
    """A project as the owner sent it, checked (pure; unit-tested)."""
    name = str(data.get("name") or "").strip()[:120]
    if not name:
        raise ProjectError("beri nama proyeknya")
    schedule = data.get("schedule") or "manual"
    if schedule not in SCHEDULES:
        raise ProjectError("jadwal: manual, hourly, daily, weekdays, atau weekly")
    at_time = str(data.get("at_time") or "").strip() or None
    if schedule in ("daily", "weekdays", "weekly") and not (at_time and _TIME.match(at_time)):
        raise ProjectError("isi jam jalannya (JJ:MM)")
    weekday = data.get("weekday")
    if schedule == "weekly" and not (isinstance(weekday, int) and 0 <= weekday <= 6):
        raise ProjectError("pilih harinya")
    roles = []
    for r in (data.get("roles") or [])[:MAX_ROLES]:
        role = str(r.get("role") or "").strip()[:80]
        if not role:
            continue
        try:
            workers = int(r.get("workers") or 1)
        except (TypeError, ValueError):
            workers = 1
        model = str(r.get("model") or "").strip() or None
        if model and not _MODEL.match(model):
            raise ProjectError(f"model untuk peran {role} tidak dikenal: {model}")
        app = str(r.get("app") or "").strip().lower() or None
        if app and app not in phone_agent.APPS:
            raise ProjectError(f"aplikasi HP untuk peran {role} belum didukung: {app}")
        roles.append({"role": role, "brief": str(r.get("brief") or "").strip()[:3000], "workers": 1 if app else max(1, min(5, workers)),
                      "model": model, "web": bool(r.get("web")) and not app, "app": app})   # the phone has one screen: one app worker
    if not roles:
        raise ProjectError("tambahkan minimal satu peran pekerja")
    if sum(r["workers"] for r in roles) > MAX_WORKERS:
        raise ProjectError(f"paling banyak {MAX_WORKERS} pekerja sekali jalan (semua peran)")
    return {"name": name, "goal": str(data.get("goal") or "").strip()[:4000], "schedule": schedule,
            "at_time": at_time if schedule in ("daily", "weekdays", "weekly") else None,
            "weekday": weekday if schedule == "weekly" else None, "roles": roles}


def next_run(p: dict, after: datetime) -> datetime | None:
    """When a scheduled project runs next, strictly after `after` (pure; unit-tested). Manual → None."""
    s = p.get("schedule")
    if s == "manual" or not s:
        return None
    local = after.astimezone(TZ)
    if s == "hourly":
        return (local.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)).astimezone(after.tzinfo)
    hh, mm = (int(x) for x in p["at_time"].split(":"))
    day = local.replace(hour=hh, minute=mm, second=0, microsecond=0)
    for _ in range(8):
        if day > local and (s == "daily" or (s == "weekdays" and day.weekday() < 5) or (s == "weekly" and day.weekday() == p.get("weekday"))):
            return day.astimezone(after.tzinfo)
        day += timedelta(days=1)
    return None


def schedule_text(p: dict) -> str:
    s = p.get("schedule")
    return {"manual": "Manual (tekan Jalankan)", "hourly": "Tiap jam", "daily": f"Tiap hari {p.get('at_time')}",
            "weekdays": f"Senin–Jumat {p.get('at_time')}",
            "weekly": f"Tiap {WEEKDAYS[p['weekday']] if isinstance(p.get('weekday'), int) else '?'} {p.get('at_time')}"}.get(s, s or "")


async def check_models(roles: list[dict]) -> None:
    """Every chosen model must exist and be able to use tools (workers browse, write files, ask the owner)."""
    from . import openrouter
    wanted = [r["model"] for r in roles if r["model"]]
    if not wanted:
        return
    catalog = await openrouter.catalog()
    if catalog is None:
        return   # catalog unreachable: the gateway falls back to the category's models if the pick does not answer
    for m in wanted:
        info = openrouter.get(catalog, m)
        if not info:
            raise ProjectError(f"model {m} tidak ada di OpenRouter")
        if not info["tools"]:
            raise ProjectError(f"{info['name']} tidak bisa memakai alat — pekerja butuh itu")


async def save(data: dict, actor: str, project_id: int | None = None) -> dict:
    p = clean(data)
    await check_models(p["roles"])
    async with db.pool().acquire() as conn, conn.transaction():
        nxt = next_run(p, datetime.now(TZ))
        if project_id:
            row = await conn.fetchrow(
                """UPDATE projects SET name = $2, goal = $3, schedule = $4, at_time = $5, weekday = $6, next_run = $7, updated_at = now()
                   WHERE id = $1 RETURNING id""", project_id, p["name"], p["goal"], p["schedule"], p["at_time"], p["weekday"], nxt)
            if not row:
                raise ProjectError("proyek tidak ditemukan")
            await conn.execute("DELETE FROM project_roles WHERE project_id = $1", project_id)
        else:
            row = await conn.fetchrow(
                """INSERT INTO projects (name, goal, schedule, at_time, weekday, next_run) VALUES ($1, $2, $3, $4, $5, $6) RETURNING id""",
                p["name"], p["goal"], p["schedule"], p["at_time"], p["weekday"], nxt)
        for i, r in enumerate(p["roles"]):
            await conn.execute("""INSERT INTO project_roles (project_id, role, brief, workers, model, web, sort, app)
                                  VALUES ($1, $2, $3, $4, $5, $6, $7, $8)""",
                               row["id"], r["role"], r["brief"], r["workers"], r["model"], r["web"], i, r["app"])
    await audit.record(actor, "project.saved", f"project:{row['id']}", name=p["name"])
    return await get(row["id"])


async def set_status(project_id: int, status: str, actor: str) -> dict:
    if status not in ("active", "paused"):
        raise ProjectError("status: active atau paused")
    p = await get(project_id)
    if not p:
        raise ProjectError("proyek tidak ditemukan")
    nxt = next_run(p, datetime.now(TZ)) if status == "active" else None
    await db.pool().execute("UPDATE projects SET status = $2, next_run = $3, updated_at = now() WHERE id = $1", project_id, status, nxt)
    await audit.record(actor, f"project.{status}", f"project:{project_id}")
    return await get(project_id)


async def delete(project_id: int, actor: str) -> bool:
    from . import workers
    for t in await db.pool().fetch("SELECT id FROM tasks WHERE project_id = $1 AND status IN ('queued', 'running')", project_id):
        await workers.stop(t["id"], actor)
    done = (await db.pool().execute("DELETE FROM projects WHERE id = $1", project_id)).endswith("1")
    if done:
        await audit.record(actor, "project.deleted", f"project:{project_id}")
    return done


async def get(project_id: int) -> dict | None:
    row = await db.pool().fetchrow("SELECT * FROM projects WHERE id = $1", project_id)
    if not row:
        return None
    p = dict(row)
    p["roles"] = [dict(r) for r in await db.pool().fetch("SELECT * FROM project_roles WHERE project_id = $1 ORDER BY sort, id", project_id)]
    p["schedule_text"] = schedule_text(p)
    p["workers"] = [dict(r) for r in await db.pool().fetch(
        """SELECT t.id, t.title, t.status, t.model_used, t.model_override, t.project_run, r.role, left(coalesce(t.error, ''), 160) AS error,
                  left(coalesce(t.result, ''), 8000) AS result, t.created_at, t.finished_at
           FROM tasks t LEFT JOIN project_roles r ON r.id = t.project_role
           WHERE t.project_id = $1 AND t.project_run >= $2 - 1 ORDER BY t.project_run DESC, t.id""", project_id, p["runs"])]
    for w in p["workers"]:   # the card shows a short plain preview; the full structured result is opened from it (ADR-075)
        w["result"] = results.spoken(w["result"])[:400]
    return p


async def list_() -> dict:
    from . import hermes_studio
    ids = [r["id"] for r in await db.pool().fetch("SELECT id FROM projects ORDER BY status, updated_at DESC")]
    try:
        cron = hermes_studio.cron_jobs()
    except Exception:
        cron = []
    return {"projects": [await get(i) for i in ids], "cron": cron, "max_workers": MAX_WORKERS}


async def run(project_id: int, actor: str, trigger: str = "manual") -> dict:
    """Spawn this run's workers (as owner tasks, each with its role's brief and model)."""
    from . import workers
    p = await get(project_id)
    if not p:
        raise ProjectError("proyek tidak ditemukan")
    busy = await db.pool().fetchval("SELECT count(*) FROM tasks WHERE project_id = $1 AND status IN ('queued', 'running')", project_id)
    if busy:
        raise ProjectError(f"run sebelumnya masih berjalan ({busy} pekerja) — tunggu atau hentikan dulu")
    n_run = await db.pool().fetchval(
        "UPDATE projects SET runs = runs + 1, last_run = now(), next_run = $2, updated_at = now() WHERE id = $1 RETURNING runs",
        project_id, next_run(p, datetime.now(TZ)) if p["status"] == "active" else None)
    spawned, asked = [], []
    for r in p["roles"]:
        if r.get("app"):   # an app on the owner's phone (ADR-077): only the owner's schedule starts it unasked; ▶ Jalankan asks for approval too
            goal = f"[PROYEK: {p['name']} · run #{n_run} · peran {r['role']}] {r['brief'] or r['role']}" + (f" — tujuan proyek: {p['goal']}" if p["goal"] else "")
            pr = await phone_agent.request(goal, r["app"], actor, f"project-{project_id}", scheduled=trigger == "schedule",
                                           project={"project_id": project_id, "role_id": r["id"], "run": n_run, "model": r["model"]})
            (spawned.append(pr["task_id"]) if pr.get("task_id") else asked.append(pr["id"]))
            continue
        for n in range(1, r["workers"] + 1):
            brief = BRIEF.format(name=p["name"], run=n_run, role=r["role"], n=n, total=r["workers"], goal=p["goal"] or "(lihat tugas peran)",
                                 brief=r["brief"] or r["role"], split=SPLIT.format(n=n, total=r["workers"]) if r["workers"] > 1 else "",
                                 web=WEB if r["web"] else "", format=results.FORMAT_HELP)
            t = await workers.spawn(f"{p['name']} · {r['role']}" + (f" {n}/{r['workers']}" if r["workers"] > 1 else ""),
                                    brief, f"project-{project_id}", actor, category="web" if r["web"] else "analisis")
            await db.pool().execute("UPDATE tasks SET project_id = $2, project_role = $3, project_run = $4, model_override = $5 WHERE id = $1",
                                    t["id"], project_id, r["id"], n_run, r["model"])
            spawned.append(t["id"])
    await audit.record(actor, "project.run", f"project:{project_id}", run=n_run, trigger=trigger, workers=len(spawned), approvals=len(asked))
    return {"run": n_run, "tasks": spawned, "approvals": asked}


async def tick() -> int:
    """Run the projects whose time has come (called every minute)."""
    due = await db.pool().fetch("SELECT id FROM projects WHERE status = 'active' AND next_run IS NOT NULL AND next_run <= now()")
    for r in due:
        try:
            await run(r["id"], "jadwal", "schedule")
        except ProjectError as e:   # the previous run is still busy: try at the next slot
            p = await get(r["id"])
            await db.pool().execute("UPDATE projects SET next_run = $2 WHERE id = $1", r["id"], next_run(p, datetime.now(TZ)))
            log.info("project %s skipped: %s", r["id"], e)
    return len(due)


def find(projects: list[dict], name: str) -> dict | None:
    """The project the owner means by `name` ("lamar kerja" → "Bantu lamar kerja"): exact, contained, then the closest (pure; unit-tested)."""
    q = " ".join(str(name or "").lower().split())
    if not q:
        return projects[0] if len(projects) == 1 else None
    by = {p["name"].lower(): p for p in projects}
    if q in by:
        return by[q]
    hits = [p for n, p in by.items() if q in n or n in q]
    if len(hits) == 1:
        return hits[0]
    close = difflib.get_close_matches(q, list(by), n=1, cutoff=0.5)
    return by[close[0]] if close else (hits[0] if hits else None)


STATUS_WORD = {"queued": "antre", "running": "bekerja", "completed": "selesai", "failed": "gagal", "stopped": "dihentikan", "cancelled": "batal"}


def status_text(p: dict) -> str:
    """One project as the main agent tells it (pure; unit-tested): status, schedule, the latest run's workers."""
    head = f"Proyek \"{p['name']}\" ({'aktif' if p['status'] == 'active' else 'dijeda'}, {p.get('schedule_text') or p['schedule']})"
    if p.get("next_run") and p["status"] == "active":
        nr = p["next_run"].astimezone(TZ)
        head += f", berikutnya {WEEKDAYS[nr.weekday()]} {nr:%d/%m %H:%M} WIB"
    last = [w for w in p.get("workers") or [] if w.get("project_run") == p.get("runs")]
    if not last:
        return head + " — belum pernah dijalankan." if not p.get("runs") else head + "."
    count: dict[str, int] = {}
    for w in last:
        count[STATUS_WORD.get(w["status"], w["status"])] = count.get(STATUS_WORD.get(w["status"], w["status"]), 0) + 1
    lines = [head + f" — run #{p['runs']}: " + ", ".join(f"{v} {k}" for k, v in count.items()) + "."]
    for w in last[:6]:
        tail = w.get("error") if w["status"] == "failed" else (w.get("result") or "")[:160] if w["status"] == "completed" else ""
        lines.append(f"  · #{w['id']} {w.get('role') or w['title']}: {STATUS_WORD.get(w['status'], w['status'])}" + (f" — {tail}" if tail else ""))
    return "\n".join(lines)


async def situation_block() -> str:
    """What the main agent knows about the owner's projects every turn (ADR-074): the active ones and any with workers busy."""
    ids = [r["id"] for r in await db.pool().fetch(
        """SELECT p.id FROM projects p WHERE p.status = 'active'
              OR EXISTS (SELECT 1 FROM tasks t WHERE t.project_id = p.id AND t.status IN ('queued', 'running'))
           ORDER BY p.updated_at DESC LIMIT 6""")]
    if not ids:
        return ""
    rows = [await get(i) for i in ids]
    return ("PROYEK PEMILIK (kamu yang mengawasinya; alat proyek untuk lihat/jalankan/jeda/lanjutkan/buat):\n"
            + "\n".join(f"- {status_text(p)}" for p in rows if p))


async def run_results(project_id: int, run: int | None = None) -> dict | None:
    """What the workers of one run handed back, in full and structured for the desk (ADR-075): the latest run unless one is named."""
    p = await db.pool().fetchrow("SELECT id, name, goal, runs FROM projects WHERE id = $1", project_id)
    if not p:
        return None
    runs = [r["project_run"] for r in await db.pool().fetch(
        "SELECT DISTINCT project_run FROM tasks WHERE project_id = $1 AND project_run IS NOT NULL ORDER BY project_run DESC LIMIT 30", project_id)]
    run = run if run in runs else (runs[0] if runs else None)
    workers = []
    for t in await db.pool().fetch(
            """SELECT t.id, t.title, t.status, t.model_used, t.model_override, t.error, left(coalesce(t.result, ''), 60000) AS result,
                      t.started_at, t.finished_at, r.role
               FROM tasks t LEFT JOIN project_roles r ON r.id = t.project_role WHERE t.project_id = $1 AND t.project_run = $2 ORDER BY t.id""",
            project_id, run):
        doc, text = results.split(t["result"])
        docs = [dict(d) for d in await db.pool().fetch(
            "SELECT id::text AS id, title, format FROM documents WHERE task_id = $1 ORDER BY created_at", t["id"])]
        workers.append({"id": t["id"], "role": t["role"] or t["title"], "title": t["title"], "status": t["status"],
                        "model": t["model_used"] or t["model_override"] or "", "error": t["error"] or "", "doc": doc, "text": text,
                        "documents": docs, "started_at": t["started_at"], "finished_at": t["finished_at"]})
    return {"project": {"id": p["id"], "name": p["name"], "goal": p["goal"]}, "run": run, "runs": runs, "workers": workers}

