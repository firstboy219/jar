"""Bengkel otak (ADR-087, mockup 47; owner 2026-10-29: "saya sering mengutak-atik cara kerja otaknya Jarvis"): how each job of the master
flow is done is a VERSION the owner can change — by saying it in words ("ringkasan email harus selalu sebut tenggat, lebih formal") — and a
change is tried before it is trusted:

  propose   the heavy brain turns his words into a version of the job's config: the lane (auto / skill / ringan / berat), an extra rule for
            its prompt, length, temperature — or of the global thresholds Hermes decides by
  evaluate  the job's recent real inputs (flow_samples) are answered by the current version and the new one; the heavy brain judges each
            pair without knowing which is which
  canary    the new version takes 10% of the job's runs; after enough runs it is promoted, or rolled back automatically when it does worse
  history   every version, who made it and why; any earlier one can be restored

master.run asks config_for(job) before each run and records which version ran (flow_runs.brain_version)."""

import logging
import random
import time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from . import audit, db, hub
from .appauth import actor, owner, require_password

log = logging.getLogger("jarvis-core")
router = APIRouter()
API = "/api/v1/app/brain"
GLOBAL_DEFAULT = {"learn_min_runs": 5, "light_min_ok": 0.6, "skill_fail_streak": 3}
LANES = ("auto", "skill", "ringan", "berat")
CANARY_MIN_RUNS = 5          # a canary is judged after this many runs …
PROMOTE_RUNS = 15            # … and promoted after this many without doing worse
WORSE_BY = 0.2               # rolled back when its success rate is this much below the active version's
CACHE_S = 30
_cache: dict[str, tuple[float, dict | None, dict | None]] = {}


class BrainError(ValueError):
    pass


# ---------- pure ----------

def clean_config(cfg: dict, job: str) -> dict:
    """A version's config kept to what the flow understands. Pure."""
    cfg = cfg or {}
    if not job:   # global thresholds
        out = dict(GLOBAL_DEFAULT)
        for k, (lo, hi) in {"learn_min_runs": (2, 100), "light_min_ok": (0.1, 1.0), "skill_fail_streak": (1, 20)}.items():
            if k in cfg:
                try:
                    v = float(cfg[k])
                except (TypeError, ValueError):
                    raise BrainError(f"{k} harus angka")
                if not lo <= v <= hi:
                    raise BrainError(f"{k} harus antara {lo} dan {hi}")
                out[k] = int(v) if k != "light_min_ok" else round(v, 2)
        return out
    out: dict[str, Any] = {"lane": cfg.get("lane") if cfg.get("lane") in LANES else "auto",
                           "instruction": str(cfg.get("instruction") or "").strip()[:1500]}
    if cfg.get("max_tokens") not in (None, ""):
        out["max_tokens"] = max(100, min(int(cfg["max_tokens"]), 6000))
    if cfg.get("temperature") not in (None, ""):
        out["temperature"] = max(0.0, min(float(cfg["temperature"]), 1.2))
    return out


def with_rule(messages: list[dict] | None, rule: str) -> list[dict] | None:
    """The job's prompt with the owner's extra rule added to its system message (or as one). Pure."""
    if not messages or not rule:
        return messages
    msgs = [dict(m) for m in messages]
    tail = f"\n\nATURAN TAMBAHAN DARI PEMILIK (utamakan):\n{rule}"
    if msgs[0].get("role") == "system" and isinstance(msgs[0].get("content"), str):
        msgs[0]["content"] += tail
    else:
        msgs.insert(0, {"role": "system", "content": tail.strip()})
    return msgs


def pick(active: dict | None, canary: dict | None, roll: float) -> dict | None:
    """Which version a run uses: the canary for its share of runs, else the active one. Pure."""
    if canary and roll < canary["canary_pct"] / 100:
        return canary
    return active


def verdict(active: tuple[int, int], canary: tuple[int, int]) -> str:
    """'rollback' | 'promote' | 'wait' from (runs, ok) of the active version and of the canary. Pure."""
    cr, cok = canary
    if cr < CANARY_MIN_RUNS:
        return "wait"
    ar, aok = active
    base = aok / ar if ar else 0.9
    rate = cok / cr
    if rate < base - WORSE_BY:
        return "rollback"
    return "promote" if cr >= PROMOTE_RUNS else "wait"


# ---------- what master.run asks ----------

async def _versions(job: str) -> tuple[dict | None, dict | None]:
    hit = _cache.get(job)
    if hit and time.monotonic() - hit[0] < CACHE_S:
        return hit[1], hit[2]
    rows = await db.pool().fetch("SELECT id, config, status, canary_pct FROM brain_versions WHERE job = $1 AND status IN ('active', 'canary')", job)
    active = next((dict(r) for r in rows if r["status"] == "active"), None)
    canary = next((dict(r) for r in rows if r["status"] == "canary"), None)
    _cache[job] = (time.monotonic(), active, canary)
    return active, canary


def invalidate() -> None:
    _cache.clear()


async def config_for(job: str) -> dict | None:
    """The version a run of `job` uses ({id, config}), or None when the job runs as built."""
    active, canary = await _versions(job)
    v = pick(active, canary, random.random())
    return {"id": v["id"], "config": v["config"], "canary": v is canary} if v else None


async def global_cfg() -> dict:
    active, _ = await _versions("")
    return {**GLOBAL_DEFAULT, **(active["config"] if active else {})}


async def _stats(version_id: int | None, job: str) -> tuple[int, int]:
    feature, _, action = job.partition(":")
    r = await db.pool().fetchrow(
        """SELECT count(*) AS n, count(*) FILTER (WHERE status = 'done') AS ok FROM flow_runs
           WHERE feature = $1 AND action = $2 AND status IN ('done', 'failed') AND brain_version IS NOT DISTINCT FROM $3 AND started_at > now() - interval '30 days'""",
        feature, action, version_id)
    return int(r["n"]), int(r["ok"])


async def after_run(run_id: int) -> str | None:
    """A run ended: when it ran a canary, judge the canary against the active version (promote / roll back)."""
    run = await db.pool().fetchrow("SELECT feature, action, brain_version FROM flow_runs WHERE id = $1", run_id)
    if not run or not run["brain_version"]:
        return None
    job = f"{run['feature']}:{run['action']}"
    active, canary = await _versions(job)
    if not canary or canary["id"] != run["brain_version"]:
        return None
    v = verdict(await _stats(active["id"] if active else None, job), await _stats(canary["id"], job))
    if v == "rollback":
        await db.pool().execute("UPDATE brain_versions SET status = 'rolled_back', decided_at = now(), note = note || ' · otomatis dibatalkan: lebih sering gagal' WHERE id = $1", canary["id"])
        invalidate()
        await audit.record("jarvis-core", "brain.rolled_back", f"brain_version:{canary['id']}", job=job)
        await hub.broadcast({"type": "notify", "title": "Perubahan otak dibatalkan otomatis", "text": f"{job}: versi baru lebih sering gagal — kembali ke versi lama.",
                             "kind": "info", "route": f"#/bengkel/{job}"})
    elif v == "promote":
        await _activate(canary["id"], job, "jarvis-core")
        await hub.broadcast({"type": "notify", "title": "Perubahan otak dipakai penuh", "text": f"{job}: versi baru bekerja baik di {PROMOTE_RUNS}+ percobaan.",
                             "kind": "info", "route": f"#/bengkel/{job}"})
    return v


async def _activate(version_id: int, job: str, who: str) -> None:
    async with db.pool().acquire() as c, c.transaction():
        await c.execute("UPDATE brain_versions SET status = 'retired', decided_at = now() WHERE job = $1 AND status = 'active' AND id <> $2", job, version_id)
        await c.execute("UPDATE brain_versions SET status = 'active', activated_at = now(), decided_at = now() WHERE id = $1", version_id)
    invalidate()
    await audit.record(who, "brain.activated", f"brain_version:{version_id}", job=job)


# ---------- the workshop ----------

async def jobs(days: int = 30) -> list[dict]:
    rows = await db.pool().fetch(
        """SELECT feature, action, count(*) AS runs, count(*) FILTER (WHERE status = 'done') AS ok, count(*) FILTER (WHERE lane = 'skill') AS no_ai,
                  coalesce(sum(cost_usd), 0)::float AS cost, avg(EXTRACT(EPOCH FROM (finished_at - started_at))) FILTER (WHERE finished_at IS NOT NULL)::float AS secs,
                  max(started_at) AS last_at, mode() WITHIN GROUP (ORDER BY lane) AS lane, max(goal) AS goal
           FROM flow_runs WHERE started_at > now() - make_interval(days => $1) GROUP BY feature, action ORDER BY count(*) DESC""", days)
    vers = {r["job"]: r for r in await db.pool().fetch("SELECT job, string_agg(status, ',') AS st FROM brain_versions WHERE status IN ('active', 'canary') GROUP BY job")}
    out = []
    for r in rows:
        job = f"{r['feature']}:{r['action']}"
        out.append({"job": job, "feature": r["feature"], "action": r["action"], "goal": r["goal"], "runs": r["runs"], "ok_pct": round(100 * r["ok"] / r["runs"]) if r["runs"] else None,
                    "no_ai_pct": round(100 * r["no_ai"] / r["runs"]) if r["runs"] else None, "cost": round(r["cost"], 4), "avg_s": round(r["secs"] or 0, 1),
                    "lane": r["lane"], "last_at": r["last_at"], "versions": (vers[job]["st"].split(",") if job in vers else [])})
    return out


async def job_view(job: str) -> dict:
    feature, _, action = job.partition(":")
    hist = [dict(r) for r in await db.pool().fetch("SELECT * FROM brain_versions WHERE job = $1 ORDER BY id DESC LIMIT 30", job)]
    for h in hist:
        h["stats"] = dict(zip(("runs", "ok"), await _stats(h["id"], job)))
    base = dict(zip(("runs", "ok"), await _stats(None, job))) if job else None
    recent = [dict(r) for r in await db.pool().fetch(
        """SELECT id, lane, status, error, model, brain_version, cost_usd::float AS cost, EXTRACT(EPOCH FROM (finished_at - started_at))::float AS seconds, started_at
           FROM flow_runs WHERE feature = $1 AND action = $2 ORDER BY id DESC LIMIT 20""", feature, action)] if job else []
    samples = await db.pool().fetchval("SELECT count(*) FROM flow_samples WHERE feature = $1 AND action = $2", feature, action) if job else 0
    active, canary = await _versions(job)
    return {"job": job, "history": hist, "built_in": base, "recent": recent, "samples": samples,
            "active": active, "canary": canary, "global": await global_cfg() if not job else None}


async def propose(job: str, words: str, who: str) -> dict:
    """His words → a draft version (the heavy brain writes the config; nothing changes until he deploys it)."""
    from . import master
    feature, _, action = job.partition(":")
    active, _ = await _versions(job)
    cur = active["config"] if active else (GLOBAL_DEFAULT if not job else {"lane": "auto", "instruction": ""})
    if job:
        sample = await db.pool().fetchrow("SELECT messages FROM flow_samples WHERE feature = $1 AND action = $2 ORDER BY created_at DESC LIMIT 1", feature, action)
        fails = [r["error"] for r in await db.pool().fetch("SELECT error FROM flow_runs WHERE feature = $1 AND action = $2 AND status = 'failed' ORDER BY id DESC LIMIT 5", feature, action)]
        goal = await db.pool().fetchval("SELECT goal FROM flow_runs WHERE feature = $1 AND action = $2 ORDER BY id DESC LIMIT 1", feature, action)
        system = ((sample["messages"] or [{}])[0].get("content") or "")[:1500] if sample else ""
        schema = ("{\"lane\": \"auto|skill|ringan|berat\", \"instruction\": \"aturan tambahan untuk prompt pekerjaan ini (kalimat perintah yang jelas; kosong bila tidak perlu)\", "
                  "\"max_tokens\": null|angka, \"temperature\": null|0..1.2, \"alasan\": \"…\"}")
        context = f"Pekerjaan: {job} ({goal or '-'}).\nPrompt sistemnya sekarang (awal):\n{system or '-'}\nKegagalan terakhir: {fails or '-'}"
    else:
        schema = "{\"learn_min_runs\": 2..100, \"light_min_ok\": 0.1..1.0, \"skill_fail_streak\": 1..20, \"alasan\": \"…\"}"
        context = ("Ambang global Hermes: learn_min_runs = berapa kali pekerjaan dijalankan sebelum Hermes percaya statistiknya; light_min_ok = bila tingkat "
                   "berhasil otak ringan di bawah ini, pekerjaan dipindah ke otak berat; skill_fail_streak = berapa kali cara tetap gagal berturut-turut sebelum AI mengambil alih.")
    msgs = [{"role": "system", "content": ("Kamu insinyur yang mengatur cara kerja otak JARVIS. Ubah konfigurasi sesuai permintaan pemilik, sekecil mungkin, tanpa mengubah "
                                           f"yang tidak diminta. Jawab JSON: {schema}")},
            {"role": "user", "content": f"{context}\n\nKonfigurasi sekarang: {cur}\n\nPermintaan pemilik: {words}"}]
    r = await master.run(master.Job("bengkel", "usul", f"ubah cara kerja {job or 'Hermes'} sesuai permintaan pemilik", messages=msgs, heavy=True, json_out=True,
                                    no_free=True, max_tokens=900))
    if r["status"] != "done" or not isinstance(r["result"], dict):
        raise BrainError(r.get("error") or "usulan gagal disusun")
    cfg = clean_config({**cur, **{k: v for k, v in r["result"].items() if k != "alasan"}}, job)
    vid = await db.pool().fetchval("INSERT INTO brain_versions (job, config, request, note, parent_id, created_by) VALUES ($1, $2, $3, $4, $5, $6) RETURNING id",
                                   job, cfg, words[:1000], str(r["result"].get("alasan") or "")[:600], active["id"] if active else None, who)
    return {"id": vid, "job": job, "config": cfg, "before": cur, "note": r["result"].get("alasan") or "", "lane": r.get("lane")}


async def save_manual(job: str, cfg: dict, note: str, who: str) -> dict:
    active, _ = await _versions(job)
    clean = clean_config(cfg, job)
    vid = await db.pool().fetchval("INSERT INTO brain_versions (job, config, note, parent_id, created_by) VALUES ($1, $2, $3, $4, $5) RETURNING id",
                                   job, clean, note[:600], active["id"] if active else None, who)
    return {"id": vid, "config": clean}


async def evaluate(version_id: int, limit: int = 4) -> dict:
    """The job's recent real inputs answered by the active version (A) and this one (B); the heavy brain judges each pair blind."""
    import json as _json
    from . import master
    v = await db.pool().fetchrow("SELECT * FROM brain_versions WHERE id = $1", version_id)
    if not v or not v["job"]:
        raise BrainError("hanya versi sebuah pekerjaan yang bisa diuji ulang")
    feature, _, action = v["job"].partition(":")
    samples = await db.pool().fetch("SELECT * FROM flow_samples WHERE feature = $1 AND action = $2 ORDER BY created_at DESC LIMIT $3", feature, action, limit)
    if not samples:
        raise BrainError("belum ada contoh nyata pekerjaan ini untuk diuji ulang (jalankan dulu beberapa kali)")
    active, _ = await _versions(v["job"])
    a_cfg, b_cfg = (active["config"] if active else {"lane": "auto", "instruction": ""}), v["config"]

    async def answer(cfg: dict, msgs: list[dict], json_out: bool) -> str:
        """One replay through the master flow too (Hermes routes it; the version's lane, rule, length and temperature applied here)."""
        r = await master.run(master.Job("bengkel", "ulang", f"uji ulang {v['job']}", trigger="owner", messages=with_rule(msgs, cfg.get("instruction", "")),
                                        heavy=cfg.get("lane") == "berat", json_out=json_out, no_free=True, max_tokens=int(cfg.get("max_tokens") or 1500),
                                        temperature=float(cfg.get("temperature") if cfg.get("temperature") is not None else 0.3)))
        if r["status"] != "done":
            raise BrainError(r.get("error") or "uji ulang gagal")
        res = r["result"]
        return res if isinstance(res, str) else _json.dumps(res, ensure_ascii=False)
    results = []
    for s in samples:
        msgs = s["messages"]
        try:
            a, b = await answer(a_cfg, msgs, s["json_out"]), await answer(b_cfg, msgs, s["json_out"])
        except Exception as e:
            results.append({"run_id": s["run_id"], "error": str(e)[:200]})
            continue
        flip = random.random() < 0.5   # the judge never knows which one is new
        x, y = (b, a) if flip else (a, b)
        judge = [{"role": "system", "content": ("Kamu juri. Bandingkan dua jawaban untuk tugas yang sama. Utamakan: mengikuti instruksi dan aturan pemilik, benar, "
                                                "jelas, ringkas. JSON: {\"pemenang\": \"1|2|seri\", \"alasan\": \"1 kalimat\"}")},
                 {"role": "user", "content": f"TUGAS (prompt):\n{str(with_rule(msgs, b_cfg.get('instruction', '')))[:5000]}\n\nJAWABAN 1:\n{x[:3000]}\n\nJAWABAN 2:\n{y[:3000]}"}]
        r = await master.run(master.Job("bengkel", "juri", "bandingkan jawaban versi lama dan baru", messages=judge, heavy=True, json_out=True, no_free=True, max_tokens=200))
        w = str((r.get("result") or {}).get("pemenang") or "seri") if r["status"] == "done" else "seri"
        winner = "seri" if w not in ("1", "2") else ("B" if (w == "1") == flip else "A")
        results.append({"run_id": s["run_id"], "a": a[:2000], "b": b[:2000], "winner": winner, "why": str((r.get("result") or {}).get("alasan") or "")[:240]})
    score = {"A": sum(1 for x in results if x.get("winner") == "A"), "B": sum(1 for x in results if x.get("winner") == "B"),
             "seri": sum(1 for x in results if x.get("winner") == "seri")}
    ev = {"samples": results, "score": score, "verdict": "lebih baik" if score["B"] > score["A"] else ("lebih buruk" if score["B"] < score["A"] else "setara")}
    await db.pool().execute("UPDATE brain_versions SET eval = $2 WHERE id = $1", version_id, ev)
    return ev


async def deploy(version_id: int, mode: str, who: str, pct: int = 10) -> dict:
    v = await db.pool().fetchrow("SELECT * FROM brain_versions WHERE id = $1", version_id)
    if not v or v["status"] not in ("draft", "retired", "rolled_back", "canary"):
        raise BrainError("versi ini tidak bisa dipasang")
    if mode == "canary" and v["job"]:
        async with db.pool().acquire() as c, c.transaction():
            await c.execute("UPDATE brain_versions SET status = 'retired', decided_at = now() WHERE job = $1 AND status = 'canary' AND id <> $2", v["job"], version_id)
            await c.execute("UPDATE brain_versions SET status = 'canary', canary_pct = $2, activated_at = now() WHERE id = $1", version_id, max(1, min(pct, 50)))
        invalidate()
        await audit.record(who, "brain.canary", f"brain_version:{version_id}", job=v["job"], pct=pct)
    else:
        await _activate(version_id, v["job"], who)
    return await job_view(v["job"])


async def rollback(job: str, who: str) -> dict:
    """Back to how it was before the current version: the canary stops, the active version gives way to its parent (or the built-in way)."""
    active, canary = await _versions(job)
    if canary:
        await db.pool().execute("UPDATE brain_versions SET status = 'rolled_back', decided_at = now() WHERE id = $1", canary["id"])
    elif active:
        parent = await db.pool().fetchval("SELECT parent_id FROM brain_versions WHERE id = $1", active["id"])
        await db.pool().execute("UPDATE brain_versions SET status = 'rolled_back', decided_at = now() WHERE id = $1", active["id"])
        if parent:
            await db.pool().execute("UPDATE brain_versions SET status = 'active', activated_at = now() WHERE id = $1 AND status IN ('retired', 'rolled_back')", parent)
    else:
        raise BrainError("tidak ada perubahan yang bisa dibatalkan")
    invalidate()
    await audit.record(who, "brain.rollback", None, job=job)
    return await job_view(job)


async def models(days: int = 7) -> dict:
    """Which models each brain uses (chosen in Komposisi AI on the admin site) and how each model actually did."""
    from . import gateway
    cats = await gateway.categories()
    lanes = {}
    for lane, cat in (("ringan", "ringan"), ("berat", "berat"), ("penglihatan", "penglihatan")):
        c = cats.get(cat) or {}
        lanes[lane] = {"title": c.get("title") or cat, "routes": [{"provider": r.get("provider"), "model": r.get("model")} for r in (c.get("routes") or [])][:4],
                       "allow_free": bool(c.get("allow_free"))}
    usage = [dict(r) for r in await db.pool().fetch(
        """SELECT model, lane, count(*) AS runs, round(100.0 * count(*) FILTER (WHERE status = 'done') / count(*))::int AS ok_pct,
                  coalesce(sum(cost_usd), 0)::float AS cost, round(avg(EXTRACT(EPOCH FROM (finished_at - started_at))) FILTER (WHERE finished_at IS NOT NULL)::numeric, 1)::float AS avg_s
           FROM flow_runs WHERE model IS NOT NULL AND started_at > now() - make_interval(days => $1) GROUP BY model, lane ORDER BY count(*) DESC LIMIT 20""", days)]
    return {"lanes": lanes, "usage": usage, "days": days}


# ---------- API ----------

class ProposeIn(BaseModel):
    words: str = Field(min_length=5, max_length=1000)


class ManualIn(BaseModel):
    config: dict
    note: str = Field(default="", max_length=600)


class DeployIn(BaseModel):
    mode: str = Field(pattern="^(canary|all)$")
    pct: int = Field(default=10, ge=1, le=50)
    password: str = Field(default="", max_length=200)


class PasswordIn(BaseModel):
    password: str = Field(default="", max_length=200)


def _job(job: str) -> str:
    return "" if job in ("global", "_") else job


@router.get(API)
async def api_jobs(device: dict = Depends(owner)):
    return {"jobs": await jobs(), "global": await job_view("")}


@router.get(API + "/models")
async def api_models(device: dict = Depends(owner)):
    return await models()


@router.get(API + "/{job}")
async def api_job(job: str, device: dict = Depends(owner)):
    return await job_view(_job(job))


@router.post(API + "/{job}/propose")
async def api_propose(job: str, body: ProposeIn, device: dict = Depends(owner)):
    try:
        return await propose(_job(job), body.words, actor(device))
    except BrainError as e:
        raise HTTPException(409, str(e))


@router.post(API + "/{job}/manual")
async def api_manual(job: str, body: ManualIn, device: dict = Depends(owner)):
    try:
        return await save_manual(_job(job), body.config, body.note, actor(device))
    except (BrainError, TypeError, ValueError) as e:
        raise HTTPException(422, str(e))


@router.post(API + "/version/{version_id}/evaluate")
async def api_evaluate(version_id: int, device: dict = Depends(owner)):
    try:
        return await evaluate(version_id)
    except BrainError as e:
        raise HTTPException(409, str(e))


@router.post(API + "/version/{version_id}/deploy")
async def api_deploy(version_id: int, body: DeployIn, device: dict = Depends(owner)):
    """Changing how the brain works for real is his decision: the admin password, like a phone run (a draft or an evaluation needs none)."""
    await require_password(device, body.password, f"brain_version:{version_id}")
    try:
        return await deploy(version_id, body.mode, actor(device), body.pct)
    except BrainError as e:
        raise HTTPException(409, str(e))


@router.post(API + "/{job}/rollback")
async def api_rollback(job: str, body: PasswordIn | None = None, device: dict = Depends(owner)):
    await require_password(device, (body.password if body else ""), f"brain_rollback:{job}")
    try:
        return await rollback(_job(job), actor(device))
    except BrainError as e:
        raise HTTPException(409, str(e))
