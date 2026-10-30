"""The master flow (ADR-087; owner 2026-10-29): EVERY process behind the app's screens goes the same way —

    router  →  Hermes  →  skill (no AI)  |  ringan (jar)  |  berat (OpenJarvis' brain)  |  Hermes' own runtime (work that needs tools)

  router   recognises the job: a deterministic command (router.parse) and, by meaning, the capability it is (capabilities.search).
  Hermes   decides how it is done, from the job and from what it remembers of earlier runs of the same job (flow_runs: which way
           worked) and of similar tasks (episodes): a fixed procedure when there is one (no AI), the light brain for simple writing
           and summing up, the heavy brain for judgement, analysis and planning, its own worker when the job needs tools
           (browser, the phone, documents) — and the worker's own runtime is picked by lanes.pick as before (ADR-081).
           A light answer that fails (bad JSON, an error) goes to the heavy brain; a skill that cannot do it hands the job to AI.

Every run is a row of flow_runs (router → Hermes → lane → result, cost, time) and a live `flow` event: the "Alur langsung" screen and the
effectiveness numbers read exactly this. Feature modules never call a model themselves; they describe the job and call `run`.
"""

import asyncio
import importlib
import json
import logging
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable

from . import db, gateway, hub

log = logging.getLogger("jarvis-core")

LANES = ("skill", "ringan", "berat", "hermes")
LANE_LABEL = {"skill": "skill tanpa AI", "ringan": "otak ringan", "berat": "otak berat", "hermes": "Hermes + alat"}
ROUTE_TTL_S = 3600
LEARN_MIN_RUNS = 5          # Hermes trusts what it learned of a job after this many runs …
LIGHT_MIN_OK = 0.6          # … and stops giving it to the light brain when fewer than this share succeeded there
SKILL_FAIL_STREAK = 3       # a fixed procedure that failed this many times in a row is skipped (AI does it, and the owner is told)


class SkillMiss(RuntimeError):
    """A fixed procedure could not do this one (missing data, an unexpected screen): Hermes gives the job to AI instead."""


class FlowError(RuntimeError):
    pass


@dataclass
class Job:
    feature: str                       # the app feature it serves ('brief', 'inbox', 'bisnis', …)
    action: str                        # what it does ('compose', 'triage', 'poll', …)
    goal: str                          # in words: what the router and Hermes' memory work on
    trigger: str = "owner"             # owner | habit | schedule | event
    skill: Callable[[], Awaitable[Any]] | None = None   # the way without AI, when there is one
    messages: list[dict] | None = None  # the way with AI and no tools: the prompt for the light or heavy brain
    heavy: bool = False                # needs judgement / analysis / planning
    json_out: bool = False             # the AI answer must be JSON (parsed and checked here)
    tools: bool = False                # needs Hermes' tools: a worker task (asynchronous; see on_done)
    instruction: str = ""              # for a tools job: what the worker does
    phone: dict | None = None          # {app, goal}: an app on the owner's phone (a routine replays it without AI when one is learned)
    web: dict | None = None            # {goal, url, origin}: a website worked on by the web agent (ADR-087 batch I; Hermes lane)
    title: str = ""
    private: bool = False
    no_free: bool = False              # personal content (an email, a chat): never a free endpoint that may log prompts
    vision: bool = False               # the prompt carries a picture: the brain's eyes (category 'penglihatan') do the thinking
    max_tokens: int = 1800
    temperature: float = 0.3
    on_done: str | None = None         # "module:function" called with (run_id, result dict) when an asynchronous job ends
    data: dict = field(default_factory=dict)   # kept with the run for on_done


# ---------- router ----------

_route_cache: dict[str, tuple[float, dict]] = {}


async def route(job: Job) -> dict:
    """What the router recognises in the job: a deterministic command, and the capability it is by meaning (cached per job for an hour)."""
    from . import router
    key = f"{job.feature}:{job.action}"
    hit = _route_cache.get(key)
    if hit and time.monotonic() - hit[0] < ROUTE_TTL_S:
        return hit[1]
    out: dict = {"job": key}
    intent = router.parse(job.goal)
    if intent:
        out["intent"] = intent.name
    try:
        from . import capabilities
        found = await asyncio.wait_for(capabilities.search(job.goal, limit=1), 3.0)
        if found:
            out["capability"], out["score"] = found[0]["name"], round(float(found[0].get("score") or 0), 3)
    except Exception:   # no embeddings: the job's own name is the route
        pass
    _route_cache[key] = (time.monotonic(), out)
    return out


# ---------- Hermes decides ----------

def choose(*, has_skill: bool, skill_streak: int, tools: bool, phone: bool, routine: bool, heavy: bool, has_prompt: bool,
           light_on: bool, stats: dict, forced: str = "auto", learn_min_runs: int = LEARN_MIN_RUNS, light_min_ok: float = LIGHT_MIN_OK,
           skill_fail_streak: int = SKILL_FAIL_STREAK) -> tuple[str, str]:
    """(lane, why). Pure; unit-tested. `stats` = {lane: (runs, ok)} of this job's recent runs (Hermes' memory of it). `forced` = the lane the
    owner set for this job in the brain workshop (honoured when the job can be done that way); the thresholds come from the workshop too."""
    if phone:
        return ("skill", "rutin HP sudah dipelajari: diputar ulang tanpa AI") if routine else ("hermes", "aplikasi HP: Hermes mengoperasikannya dengan AI (lalu dipelajari jadi rutin)")
    if forced == "skill" and has_skill:
        return "skill", "diatur pemilik di Bengkel otak: tanpa AI"
    if forced in ("ringan", "berat") and has_prompt and not tools:
        return forced, f"diatur pemilik di Bengkel otak: {LANE_LABEL[forced]}"
    if has_skill and skill_streak < skill_fail_streak:
        return "skill", "ada cara tetap: tanpa AI"
    if tools:
        return "hermes", "butuh alat (browser/dokumen/HP): Hermes yang mengerjakan"
    if not has_prompt:
        raise FlowError("pekerjaan ini tidak punya cara tanpa AI maupun perintah untuk AI")
    why_skill = f"cara tetap gagal {skill_streak}× berturut-turut — " if has_skill else ""
    if heavy:
        return "berat", why_skill + "butuh pertimbangan/analisa: otak berat"
    runs, ok = stats.get("ringan", (0, 0))
    if runs >= learn_min_runs and ok / runs < light_min_ok:
        return "berat", why_skill + f"otak ringan sering gagal di pekerjaan ini ({ok}/{runs}): otak berat"
    if not light_on:
        return "berat", why_skill + "jalur ringan dimatikan: otak berat"
    return "ringan", why_skill + "cukup otak ringan"


async def _stats(job: Job) -> dict:
    rows = await db.pool().fetch(
        """SELECT lane, count(*) AS n, count(*) FILTER (WHERE status = 'done') AS ok FROM (
             SELECT lane, status FROM flow_runs WHERE feature = $1 AND action = $2 AND status IN ('done', 'failed')
             ORDER BY id DESC LIMIT 40) r GROUP BY lane""", job.feature, job.action)
    return {r["lane"]: (r["n"], r["ok"]) for r in rows if r["lane"]}


async def _skill_streak(job: Job) -> int:
    rows = await db.pool().fetch(
        "SELECT status FROM flow_runs WHERE feature = $1 AND action = $2 AND lane = 'skill' AND status IN ('done', 'failed') ORDER BY id DESC LIMIT $3",
        job.feature, job.action, SKILL_FAIL_STREAK)
    streak = 0
    for r in rows:
        if r["status"] != "failed":
            break
        streak += 1
    return streak


async def decide(job: Job, forced: str = "auto") -> tuple[str, str]:
    from . import bengkel, lanes
    routine = False
    if job.phone:
        from . import routines
        routine = bool(await routines.find(job.phone["app"], job.phone["goal"]))
    g = await bengkel.global_cfg()
    return choose(has_skill=job.skill is not None, skill_streak=await _skill_streak(job) if job.skill else 0, tools=job.tools,
                  phone=bool(job.phone), routine=routine, heavy=job.heavy, has_prompt=bool(job.messages),
                  light_on=await lanes.light_enabled(), stats=await _stats(job), forced=forced, learn_min_runs=int(g["learn_min_runs"]),
                  light_min_ok=float(g["light_min_ok"]), skill_fail_streak=int(g["skill_fail_streak"]))


# ---------- the run ----------

def parse_json(text: str):
    """The JSON in a model's answer (a ```json fence, or the outermost {...} / [...]); ValueError when there is none."""
    t = (text or "").strip()
    m = re.search(r"```(?:json)?\s*(.+?)```", t, re.S)
    if m:
        t = m.group(1).strip()
    for opener, closer in (("{", "}"), ("[", "]")):
        i, j = t.find(opener), t.rfind(closer)
        if i != -1 and j > i:
            try:
                return json.loads(t[i:j + 1])
            except json.JSONDecodeError:
                continue
    raise ValueError("jawaban AI bukan JSON")


async def _step(run_id: int, stage: str, text: str, extra: dict | None = None, **cols) -> None:
    step = {"at": datetime.now(timezone.utc).isoformat(), "stage": stage, "text": text[:300], **(extra or {})}
    sets = "".join(f", {k} = ${i + 3}" for i, k in enumerate(cols))
    await db.pool().execute(f"UPDATE flow_runs SET steps = steps || $2::jsonb{sets} WHERE id = $1", run_id, [step], *cols.values())
    await hub.broadcast({"type": "flow", "run": run_id, "stage": stage, "text": text[:300], **{k: v for k, v in cols.items() if k in ("lane", "status")}})


THINK_ROOM = 3000


async def _complete(job: Job, lane: str, body: dict, run_id: int) -> dict:
    from . import modelrouter
    token = modelrouter.NO_FREE.set(True) if job.no_free else None
    try:
        return await gateway.complete("penglihatan" if job.vision else lane, body, caller=f"master:{job.feature}", session_id=f"flow-{run_id}", private=job.private)
    finally:
        if token is not None:
            modelrouter.NO_FREE.reset(token)


async def _think(job: Job, lane: str, run_id: int) -> tuple[Any, str | None]:
    # Today's models think before they answer and the thinking counts against max_tokens: unchecked, it ate the whole budget and the
    # answer came back empty. The light brain (and sight) answer straight away; the heavy brain thinks a little, with room left for the answer.
    body = {"messages": job.messages, "max_tokens": job.max_tokens, "temperature": job.temperature,
            "reasoning": {"effort": "low"} if lane == "berat" and not job.vision else {"enabled": False}}
    if lane == "berat" and not job.vision:
        body["max_tokens"] = job.max_tokens + THINK_ROOM
    if job.json_out:
        body["response_format"] = {"type": "json_object"}
    data = await _complete(job, lane, body, run_id)
    choice = (data.get("choices") or [{}])[0]
    text = (choice.get("message") or {}).get("content") or ""
    if not text.strip() and body["reasoning"] != {"enabled": False}:   # it thought until the budget ran out: once more, answering directly
        await _step(run_id, "hermes", "otak berat kehabisan token saat berpikir — dijawab langsung")
        data = await _complete(job, lane, {**body, "reasoning": {"enabled": False}, "max_tokens": job.max_tokens}, run_id)
        choice = (data.get("choices") or [{}])[0]
        text = (choice.get("message") or {}).get("content") or ""
    model = (data.get("jarvis_route") or {}).get("model")
    if not text.strip():
        raise FlowError("AI tidak menjawab")
    u = data.get("usage") or {}
    await _step(run_id, "jawab", f"{model or lane} menjawab", extra={"model": model, "tokens": u.get("total_tokens"), "cost": u.get("cost"), "lane": lane})
    return (parse_json(text) if job.json_out else text.strip()), model


async def _brain(job: Job, run_id: int) -> dict | None:
    """The brain workshop's version of this job (ADR-087 Bengkel otak), applied to the job; None = the job as built."""
    from . import bengkel
    try:
        v = await bengkel.config_for(f"{job.feature}:{job.action}")
    except Exception as e:   # the workshop must never stop the work
        log.warning("brain version for %s:%s unavailable: %s", job.feature, job.action, e)
        return None
    if not v:
        return None
    cfg = v["config"]
    job.messages = bengkel.with_rule(job.messages, cfg.get("instruction", ""))
    job.max_tokens = int(cfg.get("max_tokens") or job.max_tokens)
    if cfg.get("temperature") is not None:
        job.temperature = float(cfg["temperature"])
    await db.pool().execute("UPDATE flow_runs SET brain_version = $2 WHERE id = $1", run_id, v["id"])
    await _step(run_id, "bengkel", f"versi otak #{v['id']}{' (uji 10%)' if v.get('canary') else ''}")
    return cfg


SAMPLES_PER_JOB = 20


async def _sample(run_id: int, job: Job, messages: list[dict], result) -> None:
    """A real input of this job kept for replaying in the workshop (only the last few per job; never a private one)."""
    try:
        await db.pool().execute("INSERT INTO flow_samples (run_id, feature, action, messages, json_out, result) VALUES ($1, $2, $3, $4, $5, $6) ON CONFLICT DO NOTHING",
                                run_id, job.feature, job.action, messages, job.json_out, _jsonish(result))
        await db.pool().execute(
            """DELETE FROM flow_samples WHERE feature = $1 AND action = $2 AND run_id NOT IN (
                 SELECT run_id FROM flow_samples WHERE feature = $1 AND action = $2 ORDER BY created_at DESC LIMIT $3)""", job.feature, job.action, SAMPLES_PER_JOB)
    except Exception as e:
        log.warning("flow sample %s not kept: %s", run_id, e)


async def _cost(run_id: int) -> float:
    return float(await db.pool().fetchval("SELECT coalesce(sum(cost_usd), 0) FROM llm_usage WHERE session_id = $1", f"flow-{run_id}") or 0)


async def _finish(run_id: int, status: str, result=None, error: str | None = None, model: str | None = None, extra_cost: float = 0.0) -> None:
    cost = await _cost(run_id) + extra_cost
    await db.pool().execute(
        "UPDATE flow_runs SET status = $2, result = $3, error = $4, model = coalesce($5, model), cost_usd = $6, finished_at = now() WHERE id = $1",
        run_id, status, _jsonish(result), (error or "")[:1000] or None, model, cost)
    await hub.broadcast({"type": "flow", "run": run_id, "stage": "selesai" if status == "done" else "gagal", "status": status,
                         "text": (error or "selesai")[:200]})
    try:   # a canary version is judged on every run it does (promoted or rolled back by the workshop)
        from . import bengkel
        await bengkel.after_run(run_id)
    except Exception as e:
        log.warning("brain verdict for run %s: %s", run_id, e)


def _jsonish(v):
    if v is None:
        return None
    try:
        json.dumps(v)
        return v if isinstance(v, (dict, list)) else {"value": v}
    except TypeError:
        return {"value": str(v)[:4000]}


async def run(job: Job) -> dict:
    """Run one job through the master flow. Synchronous lanes (skill, ringan, berat) return {'status': 'done', 'result': …};
    a Hermes job returns {'status': 'waiting', 'task_id': …} and calls job.on_done when its worker ends."""
    if job.trigger not in ("owner", "habit", "schedule", "event"):
        job.trigger = "owner"
    run_id = await db.pool().fetchval(
        "INSERT INTO flow_runs (feature, action, goal, trigger) VALUES ($1, $2, $3, $4) RETURNING id",
        job.feature, job.action, job.goal[:500], job.trigger)
    original = job.messages
    try:
        r = await route(job)
        await _step(run_id, "router", " · ".join(f"{k}: {v}" for k, v in r.items() if k != "job") or "dikenali sebagai " + r["job"], router=r)
        version = await _brain(job, run_id)
        lane, why = await decide(job, (version or {}).get("lane", "auto"))
        await _step(run_id, "hermes", f"{LANE_LABEL[lane]} — {why}", lane=lane, why=why, status="running")
        if lane == "skill" and not job.phone:
            try:
                result = await job.skill()
                await _step(run_id, "skill", "cara tetap selesai", extra={"lane": "skill", "no_ai": True})
                await _finish(run_id, "done", result)
                return {"run_id": run_id, "status": "done", "lane": "skill", "why": why, "result": result}
            except SkillMiss as e:
                if not job.messages and not job.tools:
                    raise FlowError(f"cara tetap tidak bisa: {e}")
                lane, why = ("hermes" if job.tools else ("berat" if job.heavy else "ringan")), f"cara tetap tidak bisa ({e}) — AI mengambil alih"
                await _step(run_id, "hermes", f"{LANE_LABEL[lane]} — {why}", lane=lane, why=why)
        if lane in ("ringan", "berat") and not job.tools:
            try:
                result, model = await _think(job, lane, run_id)
            except (ValueError, FlowError, gateway.GatewayError) as e:
                if lane != "ringan":
                    raise
                await _step(run_id, "hermes", f"otak ringan gagal ({str(e)[:120]}) — dinaikkan ke otak berat", lane="berat")
                lane = "berat"
                result, model = await _think(job, lane, run_id)
            await _finish(run_id, "done", result, model=model)
            if original and not job.private and job.feature != "bengkel":
                await _sample(run_id, job, original, result)
            return {"run_id": run_id, "status": "done", "lane": lane, "why": why, "result": result, "model": model}
        # Hermes' own runtime: a worker task (the phone, the browser, documents)
        task_id = await _spawn(job, run_id, lane)
        await db.pool().execute("UPDATE flow_runs SET status = 'waiting', task_id = $2, on_done = $3, data = $4 WHERE id = $1",
                                run_id, task_id, job.on_done, _jsonish(job.data) or {})
        _pending[run_id] = job
        await _step(run_id, "lane", f"misi #{task_id} dimulai", extra={"tool": "hp" if job.phone else ("web" if job.web else "browser"), "lane": "hermes"})
        return {"run_id": run_id, "status": "waiting", "lane": lane, "why": why, "task_id": task_id}
    except Exception as e:
        log.warning("flow %s %s:%s failed: %s", run_id, job.feature, job.action, e)
        await _finish(run_id, "failed", error=str(e))
        return {"run_id": run_id, "status": "failed", "error": str(e)}


async def ask(job: Job) -> Any:
    """For a call site that only needs the answer of a synchronous job: its result, or FlowError when the flow did not finish it."""
    r = await run(job)
    if r["status"] != "done":
        raise FlowError(r.get("error") or "pekerjaan tidak selesai")
    return r["result"]


_pending: dict[int, Job] = {}   # jobs whose worker is still running (for tests and the live view; the row is the source of truth)


async def _spawn(job: Job, run_id: int, lane: str) -> int:
    from . import phone_agent, workers
    if job.web:   # the web agent: a session on the phone (or the server's browser), every step through this flow
        from . import webagent
        try:
            w = await webagent.request(job.web.get("goal") or job.goal, job.web.get("url") or "", f"master:{job.feature}",
                                       job.web.get("origin") or ("app" if job.trigger == "owner" else "schedule"), job.feature, job.title)
        except webagent.WebError as e:
            raise FlowError(str(e)) from None
        return int(w["task_id"])
    if job.phone:
        # the owner's own tap in the app (with the admin password checked there), a habit he set or a schedule: no second approval
        row = await phone_agent.request(job.phone["goal"], job.phone["app"], actor=f"master:{job.feature}", scheduled=True, by="jadwal")
        if not row.get("task_id"):
            raise FlowError("operasi HP tidak bisa dimulai")
        return int(row["task_id"])
    t = await workers.spawn(job.title or f"{job.feature}: {job.action}", job.instruction or job.goal, session_id=f"flow-{run_id}",
                            actor=f"master:{job.feature}", kind="feature", heavy=job.heavy, private=job.private)
    return int(t["id"])


async def on_task_finished(task_id: int) -> None:
    """A Hermes job's worker ended: close its run and hand the result to the feature."""
    run = None
    for _ in range(10):   # a worker that ends at once can finish before its run is marked waiting
        run = await db.pool().fetchrow("SELECT id, feature, action, on_done, data FROM flow_runs WHERE task_id = $1 AND status = 'waiting'", task_id)
        if run or not await db.pool().fetchval("SELECT 1 FROM flow_runs WHERE status = 'running' AND lane = 'hermes'"):
            break
        await asyncio.sleep(0.5)
    if not run:
        return
    t = await db.pool().fetchrow("SELECT status, result, error, cost_usd::float AS cost, model_used, runtime FROM tasks WHERE id = $1", task_id)
    ok = bool(t and t["status"] == "completed")
    result = {"text": t["result"] if t else "", "task_id": task_id, "runtime": t["runtime"] if t else None}
    await _finish(run["id"], "done" if ok else "failed", result, error=None if ok else (t["error"] if t else "misi hilang") or t["status"],
                  model=t["model_used"] if t else None, extra_cost=float(t["cost"] or 0) if t else 0.0)
    _pending.pop(run["id"], None)
    if run["on_done"]:   # kept on the row, so a restart while the worker ran still hands the result over
        try:
            mod, fn = run["on_done"].split(":")
            await getattr(importlib.import_module(f"app.{mod}"), fn)(run["id"], {"ok": ok, **result, "data": run["data"] or {}})
        except Exception:
            log.exception("flow %s on_done %s failed", run["id"], run["on_done"])


# ---------- what the live flow view and the effectiveness numbers read ----------

async def recent(limit: int = 30, feature: str | None = None) -> list[dict]:
    rows = await db.pool().fetch(
        """SELECT id, feature, action, goal, trigger, router, lane, why, status, steps, task_id, model, cost_usd::float AS cost, error,
                  started_at, finished_at, EXTRACT(EPOCH FROM (coalesce(finished_at, now()) - started_at))::float AS seconds
           FROM flow_runs WHERE ($2::text IS NULL OR feature = $2) ORDER BY id DESC LIMIT $1""", limit, feature)
    return [dict(r) for r in rows]


async def summary(days: int = 7) -> dict:
    rows = await db.pool().fetch(
        """SELECT lane, count(*) AS n, count(*) FILTER (WHERE status = 'done') AS ok, coalesce(sum(cost_usd), 0)::float AS cost,
                  avg(EXTRACT(EPOCH FROM (finished_at - started_at))) FILTER (WHERE finished_at IS NOT NULL)::float AS secs
           FROM flow_runs WHERE started_at > now() - make_interval(days => $1) AND lane IS NOT NULL GROUP BY lane""", days)
    lanes = {r["lane"]: {"runs": r["n"], "ok": r["ok"], "cost": r["cost"], "avg_s": round(r["secs"] or 0, 1)} for r in rows}
    total = sum(v["runs"] for v in lanes.values())
    ok = sum(v["ok"] for v in lanes.values())
    return {"days": days, "runs": total, "ok": ok, "ok_pct": round(100 * ok / total) if total else None,
            "no_ai_pct": round(100 * lanes.get("skill", {}).get("runs", 0) / total) if total else None,
            "cost": round(sum(v["cost"] for v in lanes.values()), 4), "lanes": lanes,
            "running": await db.pool().fetchval("SELECT count(*) FROM flow_runs WHERE status IN ('routing', 'running', 'waiting')")}
