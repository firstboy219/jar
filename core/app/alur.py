"""Alur langsung (ADR-087, mockup 46; owner 2026-10-29: "saya ingin melihat cara kerja Jarvis secara live dan kelihatan flownya … seberapa
efektif"): every job of the master flow as it happens — router → Hermes → skill / otak ringan / otak berat / Hermes + alat — the ones
running now, what each run did step by step, and how well each job does (success, share without AI, time, cost, which brain version).

Reads flow_runs only (master writes it; the screen listens to the live `flow` events). Old runs are thinned every night: fixed-procedure
runs after 30 days, the rest after 120 (the numbers per job stay meaningful, the table stays small)."""

from fastapi import APIRouter, Depends, HTTPException

from . import appclock, db, master
from .appauth import owner

router = APIRouter()
API = "/api/v1/app/flow"


def weak_points(jobs: list[dict]) -> list[dict]:
    """Where JARVIS does badly or wastefully (a week of runs per job): often failing, slow, costly, or always thinking about a job that
    could be a fixed procedure. Worst first. Pure."""
    out = []
    for j in jobs:
        if j["runs"] < 3:
            continue
        name = f"{j['feature']} · {j['action']}"
        if j["ok_pct"] is not None and j["ok_pct"] < 80:
            out.append({"job": f"{j['feature']}:{j['action']}", "kind": "gagal", "score": 100 - j["ok_pct"],
                        "text": f"{name}: hanya {j['ok_pct']}% berhasil dari {j['runs']} kali — lihat kegagalannya, ubah cara kerjanya"})
        if j["avg_s"] > 120 and j["hermes"] < j["runs"]:
            out.append({"job": f"{j['feature']}:{j['action']}", "kind": "lambat", "score": min(60, j["avg_s"] / 10),
                        "text": f"{name}: rata-rata {round(j['avg_s'])} detik — coba otak ringan atau prompt lebih pendek"})
        if j["cost"] > 0.5:
            out.append({"job": f"{j['feature']}:{j['action']}", "kind": "mahal", "score": min(50, j["cost"] * 20),
                        "text": f"{name}: ${j['cost']:.2f} seminggu — pertimbangkan otak ringan untuk pekerjaan ini"})
        if j["runs"] >= 10 and j["no_ai_pct"] == 0 and j["ringan"] == j["runs"] and (j["ok_pct"] or 0) >= 95:
            out.append({"job": f"{j['feature']}:{j['action']}", "kind": "bisa-skill", "score": 20,
                        "text": f"{name}: {j['runs']}× selalu berhasil dengan AI — Hermes bisa menjadikannya skill tanpa AI"})
    return sorted(out, key=lambda w: -w["score"])[:8]


async def view(hours: int = 24) -> dict:
    live = [dict(r) for r in await db.pool().fetch(
        """SELECT f.id, f.feature, f.action, f.goal, f.trigger, f.lane, f.why, f.status, f.task_id, f.brain_version, f.started_at,
                  EXTRACT(EPOCH FROM (now() - f.started_at))::float AS seconds, f.steps -> -1 AS last_step, jsonb_array_length(f.steps) AS steps_n,
                  (SELECT coalesce(sum(u.cost_usd), 0)::float FROM llm_usage u WHERE u.session_id = 'flow-' || f.id) AS cost_now,
                  t.progress AS task_progress
           FROM flow_runs f LEFT JOIN tasks t ON t.id = f.task_id
           WHERE f.status IN ('routing', 'running', 'waiting') AND f.started_at > now() - interval '3 hours' ORDER BY f.id DESC LIMIT 30""")]
    for r in live:
        r["path"] = ["router", "hermes", r["lane"] or "…"]
    st = await db.pool().fetch(
        """SELECT coalesce(lane, 'routing') AS lane, count(*) AS n, count(*) FILTER (WHERE status = 'failed') AS failed,
                  count(*) FILTER (WHERE status = 'done') AS ok, coalesce(sum(cost_usd), 0)::float AS cost,
                  avg(EXTRACT(EPOCH FROM (finished_at - started_at))) FILTER (WHERE finished_at IS NOT NULL)::float AS secs
           FROM flow_runs WHERE started_at > now() - make_interval(hours => $1) GROUP BY 1""", hours)
    stations = {r["lane"]: {"runs": r["n"], "failed": r["failed"], "ok_pct": round(100 * r["ok"] / r["n"]) if r["n"] else None,
                            "cost": round(r["cost"], 4), "avg_s": round(r["secs"] or 0, 1)} for r in st}
    total = sum(v["runs"] for v in stations.values())
    feats = [dict(r) for r in await db.pool().fetch(
        """SELECT feature, action, count(*) AS runs, count(*) FILTER (WHERE status = 'done') AS ok, count(*) FILTER (WHERE lane = 'skill') AS no_ai,
                  count(*) FILTER (WHERE lane = 'ringan') AS ringan, count(*) FILTER (WHERE lane = 'berat') AS berat, count(*) FILTER (WHERE lane = 'hermes') AS hermes,
                  coalesce(sum(cost_usd), 0)::float AS cost, avg(EXTRACT(EPOCH FROM (finished_at - started_at))) FILTER (WHERE finished_at IS NOT NULL)::float AS secs,
                  max(started_at) AS last_at
           FROM flow_runs WHERE started_at > now() - make_interval(hours => $1) GROUP BY feature, action ORDER BY count(*) DESC LIMIT 60""", max(hours, 24))]
    for f in feats:
        f["ok_pct"] = round(100 * f["ok"] / f["runs"]) if f["runs"] else None
        f["no_ai_pct"] = round(100 * f["no_ai"] / f["runs"]) if f["runs"] else None
        f["avg_s"] = round(f.pop("secs") or 0, 1)
    triggers = {r["trigger"]: r["n"] for r in await db.pool().fetch(
        "SELECT trigger, count(*) AS n FROM flow_runs WHERE started_at > now() - make_interval(hours => $1) GROUP BY 1", hours)}
    rt = await db.pool().fetchrow(
        """SELECT avg(EXTRACT(EPOCH FROM ((steps->0->>'at')::timestamptz - started_at)))
                    FILTER (WHERE jsonb_array_length(steps) > 0 AND (steps->0->>'at')::timestamptz - started_at BETWEEN interval '0' AND interval '2 minutes')::float AS router_s,
                  count(*) FILTER (WHERE lane IS NOT NULL) AS decided,
                  count(*) FILTER (WHERE steps::text LIKE '%dinaikkan ke otak berat%' OR steps::text LIKE '%AI mengambil alih%') AS changed,
                  count(*) FILTER (WHERE steps::text LIKE '%"tool": "hp"%') AS phone, count(*) FILTER (WHERE steps::text LIKE '%"tool": "browser"%') AS browser
           FROM flow_runs WHERE started_at > now() - make_interval(hours => $1)""", hours)
    memory = {"skills": await db.pool().fetchval("SELECT count(DISTINCT name) FROM skill_drafts WHERE status = 'published'") if await _has("skill_drafts") else 0,
              "routines": await db.pool().fetchval("SELECT count(*) FROM routines WHERE status = 'active'") if await _has("routines") else 0,
              "used": stations.get("skill", {}).get("runs", 0)}
    queue = {"routing": await db.pool().fetchval("SELECT count(*) FROM flow_runs WHERE status = 'routing'"),
             "workers": await db.pool().fetchval("SELECT count(*) FROM tasks WHERE status = 'queued'")}
    return {"hours": hours, "total": total, "stations": stations, "live": live, "recent": await master.recent(40),
            "day": await master.summary(1), "week": await master.summary(7), "jobs": feats, "weak": weak_points(feats),
            "triggers": triggers, "router": {"avg_s": round(rt["router_s"] or 0, 2),
                                             "right_pct": round(100 * (1 - rt["changed"] / rt["decided"])) if rt["decided"] else None},
            "tools": {"hp": rt["phone"], "browser": rt["browser"]}, "memory": memory, "queue": queue}


async def _has(table: str) -> bool:
    return bool(await db.pool().fetchval("SELECT to_regclass($1)", table))


async def replay(day: str) -> dict:
    """A day of the flow to play back: every run with its minute, lane, job and outcome."""
    from datetime import date as _date, datetime, timedelta
    from .location import WIB
    d = _date.fromisoformat(day)
    t0 = datetime(d.year, d.month, d.day, tzinfo=WIB)
    rows = await db.pool().fetch(
        """SELECT id, feature, action, lane, status, trigger, EXTRACT(EPOCH FROM (started_at - $1))::int AS t,
                  EXTRACT(EPOCH FROM (coalesce(finished_at, started_at) - started_at))::float AS secs
           FROM flow_runs WHERE started_at >= $1 AND started_at < $2 ORDER BY started_at LIMIT 3000""", t0, t0 + timedelta(days=1))
    return {"day": day, "runs": [dict(r) for r in rows]}


async def run_detail(run_id: int) -> dict | None:
    r = await db.pool().fetchrow(
        """SELECT f.*, EXTRACT(EPOCH FROM (coalesce(f.finished_at, now()) - f.started_at))::float AS seconds, s.messages IS NOT NULL AS has_sample,
                  b.config AS brain_config, b.status AS brain_status
           FROM flow_runs f LEFT JOIN flow_samples s ON s.run_id = f.id LEFT JOIN brain_versions b ON b.id = f.brain_version WHERE f.id = $1""", run_id)
    if not r:
        return None
    d = dict(r)
    d["cost_usd"] = float(d["cost_usd"] or 0)
    res = d.get("result")
    d["result_preview"] = (str(res.get("value") if isinstance(res, dict) and "value" in res else res) or "")[:1500] if res is not None else ""
    d.pop("result", None)
    return d


@appclock.daily(lambda: "03:30", "flow.thin")
async def thin() -> int:
    a = await db.pool().execute("DELETE FROM flow_runs WHERE lane = 'skill' AND started_at < now() - interval '30 days'")
    b = await db.pool().execute("DELETE FROM flow_runs WHERE started_at < now() - interval '120 days'")
    await db.pool().execute("DELETE FROM flow_samples s WHERE NOT EXISTS (SELECT 1 FROM flow_runs f WHERE f.id = s.run_id)")
    return int(a.split()[-1]) + int(b.split()[-1])


@router.get(API)
async def api_view(hours: int = 24, device: dict = Depends(owner)):
    return await view(max(1, min(hours, 168)))


@router.get(API + "/replay")
async def api_replay(day: str, device: dict = Depends(owner)):
    try:
        return await replay(day[:10])
    except ValueError:
        raise HTTPException(422, "tanggal tidak dimengerti")


@router.get(API + "/{run_id}")
async def api_run(run_id: int, device: dict = Depends(owner)):
    d = await run_detail(run_id)
    if not d:
        raise HTTPException(404)
    return d
