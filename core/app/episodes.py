"""Episodic memory (Blueprint v2 §8): what each finished task was about, how it was done and how it ended.

A task that comes back ("cek lagi harga emas", "laporan tren minggu ini") starts from the previous result and approach
instead of researching from zero — and a failed attempt leaves its lesson. Stored in Postgres (with the goal's embedding;
a few hundred episodes need no vector index). Always best-effort: a failure here never touches the task.
"""

import json
import logging
import re
from datetime import datetime

from . import db, memory

log = logging.getLogger("jarvis-core.episodes")
MIN_SIMILARITY = 0.62
FRESH_DAYS = 30        # an older result is shown as "may be outdated"


def format_brief(eps: list[dict], now: datetime | None = None) -> str:
    """The worker's "tugas serupa pernah dikerjakan" paragraph. Pure; unit-tested."""
    if not eps:
        return ""
    now = now or datetime.now(eps[0]["created_at"].tzinfo)
    lines = []
    for e in eps:
        age = (now - e["created_at"]).days
        when = "hari ini" if age <= 0 else f"{age} hari lalu"
        state = (f"berhasil ({e['lesson']})" if e.get("lesson") else "berhasil") if e["success"] else f"GAGAL ({e['lesson'] or 'penyebab tidak tercatat'})"
        stale = "; mungkin sudah usang, periksa ulang bagian yang bisa berubah" if age > FRESH_DAYS else ""
        body = f" Hasil: {e['result'][:500]}" if e["result"] else ""
        how = f" Cara: {e['approach'][:200]}." if e["approach"] else ""
        lines.append(f"- {when}, {state}{stale}.{how}{body}")
    return "TUGAS SERUPA PERNAH DIKERJAKAN (mulai dari sini, jangan riset ulang yang masih berlaku):\n" + "\n".join(lines) + "\n\n"


def pattern(minutes: float | None, steps: list[str], model: str | None, helped: int, ok: bool, lane: str | None = None,
            lane_note: str | None = None) -> str:
    """How a task went, in one line the next similar task can learn from (pure; unit-tested):
    'berhasil dalam 7 menit, 12 langkah (browser_navigate×5, terminal×3), model deepseek-v4.1-flash; pemilik membantu 1x'."""
    tools: dict[str, int] = {}
    for st in steps or []:
        if st.startswith("- alat "):
            name = st[7:].split(":", 1)[0].strip()
            tools[name] = tools.get(name, 0) + 1
    top = ", ".join(f"{k}×{v}" for k, v in sorted(tools.items(), key=lambda kv: -kv[1])[:4])
    parts = [("berhasil" if ok else "gagal") + (f" dalam {round(minutes)} menit" if minutes is not None else "")]
    if tools:
        parts.append(f"{sum(tools.values())} langkah ({top})")
    if model:
        parts.append(f"model {model.split('/')[-1]}")
    if lane:   # which of the two brains (or Hermes' own tools) did it — Hermes learns where such work belongs (ADR-081)
        parts.append(f"jalur {lane}" + (" — jalur ringan tidak menemukan jawaban" if lane_note and "ringan tidak menemukan" in lane_note else ""))
    line = ", ".join(parts)
    if helped:
        line += f"; pemilik membantu {helped}x (pertanyaan/intervensi) — siapkan itu dari awal"
    return line[:400]


async def record(task_id: int, steps: list[str] | None = None) -> dict | None:
    """Write the finished task into episodic memory — the owner's tasks, project workers and the dev team (ADR-074) — with the pattern
    of how it went (time, steps, model, whether the owner had to help), so the next similar task starts from it."""
    row = await db.pool().fetchrow(
        """SELECT goal, title, kind, plan, result, error, status, cost_usd::float AS cost, model_used, artifacts, company_id,
                  runtime, runtime_note, EXTRACT(EPOCH FROM (finished_at - started_at)) / 60.0 AS minutes FROM tasks
           WHERE id = $1 AND kind IN ('owner', 'devteam') AND status IN ('completed', 'failed')""", task_id)
    if not row or not (row["goal"] or row["title"]):
        return None
    plan = row["plan"] if isinstance(row["plan"], list) else json.loads(row["plan"] or "[]") if isinstance(row["plan"], str) else []
    arts = row["artifacts"] if isinstance(row["artifacts"], list) else []
    checks = [a for a in arts if isinstance(a, dict) and a.get("type") == "verification"]
    ok = row["status"] == "completed" and (not checks or bool(checks[-1].get("ok")))
    lesson = None
    if not ok:
        from . import modelinsight
        lesson = (modelinsight.classify_error(row["error"] or "") + (f": {row['error'][:160]}" if row["error"] else "")
                  if row["status"] == "failed" else str(checks[-1].get("evidence"))[:200])
    helped = await db.pool().fetchval(
        """SELECT (SELECT count(*) FROM owner_questions WHERE task_id = $1)
                + (SELECT count(*) FROM audit_events WHERE action = 'live.takeover' AND target = $2)""", task_id, f"task:{task_id}")
    how = pattern(float(row["minutes"]) if row["minutes"] is not None else None, steps or [], row["model_used"], int(helped or 0), ok, row["runtime"], row["runtime_note"])
    lesson = f"{lesson} · {how}" if lesson else how
    goal = row["goal"] or row["title"]
    if row["kind"] == "devteam":   # "bisan · spesifikasi: …" says little: the owner's request is what a similar job will look like
        req = await db.pool().fetchval("SELECT d.request FROM tasks t JOIN dev_jobs d ON d.id = t.dev_job WHERE t.id = $1", task_id)
        goal = f"{row['title'].split(' · ')[0]} (tim dev): {' '.join((req or row['title']).split())[:400]}"
    [vec] = await memory.embed([goal])
    await db.pool().execute(
        """INSERT INTO episodes (task_id, goal, approach, result, success, cost_usd, model, lesson, embedding, company_id)
           VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)""",
        task_id, goal, ("; ".join(str(s) for s in plan) or "\n".join((steps or [])[-12:]))[:600], (row["result"] or "")[:1500], ok, row["cost"],
        row["model_used"], lesson, vec, row["company_id"])
    return {"task": task_id, "success": ok}


async def similar(goal: str, limit: int = 2, company_id: str | None = None) -> list[dict]:
    """The closest earlier episodes OF THE SAME COMPANY (or personal ones when none): successes first, newest first."""
    rows = await db.pool().fetch(
        "SELECT * FROM episodes WHERE embedding IS NOT NULL AND company_id IS NOT DISTINCT FROM $1 ORDER BY created_at DESC LIMIT 400",
        company_id)
    if not rows:
        return []
    [qv] = await memory.embed([goal])
    scored = [(memory.cosine(qv, list(r["embedding"])), dict(r)) for r in rows]
    scored = [(s, r) for s, r in scored if s >= MIN_SIMILARITY]
    good = [x for x in scored if x[1]["success"]] or scored
    ranked = sorted(good, key=lambda x: (round(x[0] / 0.05), x[1]["created_at"]), reverse=True)
    return [r | {"similarity": round(s, 3)} for s, r in ranked[:limit]]


async def brief_for(goal: str, company_id: str | None = None) -> str:
    try:
        return format_brief(await similar(goal, company_id=company_id))
    except Exception as e:
        log.warning("episode brief failed: %s", e)
        return ""


_LANE = re.compile(r"jalur (ringan|openjarvis|hermes)")


def lane_hint(eps: list[dict]) -> dict:
    """What earlier, similar tasks teach about the lane (pure; unit-tested): `prefer` = a lane a similar task SUCCEEDED in (ringan / openjarvis),
    `avoid` = lanes where a similar task failed or found nothing. Newest first in `eps`."""
    prefer, avoid = None, set()
    for e in eps:
        lesson = e.get("lesson") or ""
        m = _LANE.search(lesson)
        lane = m[1] if m else None
        if "ringan tidak menemukan" in lesson:
            avoid.add("ringan")
        elif lane in ("ringan", "openjarvis") and not e["success"]:
            avoid.add(lane)
        elif lane in ("ringan", "openjarvis") and e["success"] and prefer is None:
            prefer = lane
    return {"prefer": None if prefer in avoid else prefer, "avoid": avoid}


def situation_lines(eps: list[dict], now: datetime | None = None) -> str:
    """For the main agent (ADR-074): similar work done before, one line each — so it recognises the pattern (pure; unit-tested)."""
    if not eps:
        return ""
    now = now or datetime.now(eps[0]["created_at"].tzinfo)
    lines = []
    for e in eps:
        age = (now - e["created_at"]).days
        lines.append(f"- {'hari ini' if age <= 0 else f'{age} hari lalu'}: \"{e['goal'][:90]}\" — {e.get('lesson') or ('berhasil' if e['success'] else 'gagal')}")
    return ("POLA SERUPA (pekerjaan mirip yang pernah dikerjakan pekerja — pakai untuk memperkirakan cara, waktu, model, dan bantuan yang "
            "mungkin diperlukan; sebut ke pemilik bila berguna):\n" + "\n".join(lines))


async def prune(days: int = 180) -> int:
    """Old failures stop being useful; successes are kept (they are the reusable part)."""
    done = await db.pool().execute(
        "DELETE FROM episodes WHERE NOT success AND created_at < now() - make_interval(days => $1)", days)
    return int(done.split()[-1])
