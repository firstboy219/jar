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


async def view(hours: int = 24) -> dict:
    live = [dict(r) for r in await db.pool().fetch(
        """SELECT id, feature, action, goal, trigger, lane, why, status, task_id, brain_version, started_at,
                  EXTRACT(EPOCH FROM (now() - started_at))::float AS seconds, steps -> -1 AS last_step
           FROM flow_runs WHERE status IN ('routing', 'running', 'waiting') AND started_at > now() - interval '3 hours' ORDER BY id DESC LIMIT 30""")]
    st = await db.pool().fetch(
        """SELECT coalesce(lane, 'routing') AS lane, count(*) AS n, count(*) FILTER (WHERE status = 'failed') AS failed
           FROM flow_runs WHERE started_at > now() - make_interval(hours => $1) GROUP BY 1""", hours)
    stations = {r["lane"]: {"runs": r["n"], "failed": r["failed"]} for r in st}
    total = sum(v["runs"] for v in stations.values())
    feats = [dict(r) for r in await db.pool().fetch(
        """SELECT feature, action, count(*) AS runs, count(*) FILTER (WHERE status = 'done') AS ok, count(*) FILTER (WHERE lane = 'skill') AS no_ai,
                  count(*) FILTER (WHERE lane = 'ringan') AS ringan, count(*) FILTER (WHERE lane = 'berat') AS berat, count(*) FILTER (WHERE lane = 'hermes') AS hermes,
                  coalesce(sum(cost_usd), 0)::float AS cost, avg(EXTRACT(EPOCH FROM (finished_at - started_at))) FILTER (WHERE finished_at IS NOT NULL)::float AS secs,
                  max(started_at) AS last_at
           FROM flow_runs WHERE started_at > now() - interval '7 days' GROUP BY feature, action ORDER BY count(*) DESC LIMIT 60""")]
    for f in feats:
        f["ok_pct"] = round(100 * f["ok"] / f["runs"]) if f["runs"] else None
        f["no_ai_pct"] = round(100 * f["no_ai"] / f["runs"]) if f["runs"] else None
        f["avg_s"] = round(f.pop("secs") or 0, 1)
    return {"hours": hours, "total": total, "stations": stations, "live": live, "recent": await master.recent(40),
            "day": await master.summary(1), "week": await master.summary(7), "jobs": feats}


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


@router.get(API + "/{run_id}")
async def api_run(run_id: int, device: dict = Depends(owner)):
    d = await run_detail(run_id)
    if not d:
        raise HTTPException(404)
    return d
