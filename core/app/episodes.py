"""Episodic memory (Blueprint v2 §8): what each finished task was about, how it was done and how it ended.

A task that comes back ("cek lagi harga emas", "laporan tren minggu ini") starts from the previous result and approach
instead of researching from zero — and a failed attempt leaves its lesson. Stored in Postgres (with the goal's embedding;
a few hundred episodes need no vector index). Always best-effort: a failure here never touches the task.
"""

import json
import logging
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
        state = "berhasil" if e["success"] else f"GAGAL ({e['lesson'] or 'penyebab tidak tercatat'})"
        stale = "; mungkin sudah usang, periksa ulang bagian yang bisa berubah" if age > FRESH_DAYS else ""
        body = f" Hasil: {e['result'][:500]}" if e["result"] else ""
        how = f" Cara: {e['approach'][:200]}." if e["approach"] else ""
        lines.append(f"- {when}, {state}{stale}.{how}{body}")
    return "TUGAS SERUPA PERNAH DIKERJAKAN (mulai dari sini, jangan riset ulang yang masih berlaku):\n" + "\n".join(lines) + "\n\n"


async def record(task_id: int) -> dict | None:
    """Write the finished task into episodic memory (owner tasks that had a goal)."""
    row = await db.pool().fetchrow(
        """SELECT goal, plan, result, error, status, cost_usd::float AS cost, model_used, artifacts FROM tasks
           WHERE id = $1 AND kind = 'owner' AND status IN ('completed', 'failed')""", task_id)
    if not row or not row["goal"]:
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
    [vec] = await memory.embed([row["goal"]])
    await db.pool().execute(
        """INSERT INTO episodes (task_id, goal, approach, result, success, cost_usd, model, lesson, embedding)
           VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)""",
        task_id, row["goal"], "; ".join(str(s) for s in plan)[:600], (row["result"] or "")[:1500], ok, row["cost"],
        row["model_used"], lesson, vec)
    return {"task": task_id, "success": ok}


async def similar(goal: str, limit: int = 2) -> list[dict]:
    """The closest earlier episodes: successes first (a failure only when nothing succeeded), newest first."""
    rows = await db.pool().fetch("SELECT * FROM episodes WHERE embedding IS NOT NULL ORDER BY created_at DESC LIMIT 400")
    if not rows:
        return []
    [qv] = await memory.embed([goal])
    scored = [(memory.cosine(qv, list(r["embedding"])), dict(r)) for r in rows]
    scored = [(s, r) for s, r in scored if s >= MIN_SIMILARITY]
    good = [x for x in scored if x[1]["success"]] or scored
    ranked = sorted(good, key=lambda x: (round(x[0] / 0.05), x[1]["created_at"]), reverse=True)
    return [r | {"similarity": round(s, 3)} for s, r in ranked[:limit]]


async def brief_for(goal: str) -> str:
    try:
        return format_brief(await similar(goal))
    except Exception as e:
        log.warning("episode brief failed: %s", e)
        return ""


async def prune(days: int = 180) -> int:
    """Old failures stop being useful; successes are kept (they are the reusable part)."""
    done = await db.pool().execute(
        "DELETE FROM episodes WHERE NOT success AND created_at < now() - make_interval(days => $1)", days)
    return int(done.split()[-1])
