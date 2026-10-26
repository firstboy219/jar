"""The OpenJarvis spike (Blueprint v4 Fase 2, ADR-043): is OpenJarvis a better heavy worker than Hermes-Brain?

Both runtimes get the same problems, the same model (category 'spike', through this gateway, so the budget and
the model rules hold) and the same workspace; neither can touch the repo, the owner or JARVIS' tools.
Each runtime reaches the gateway with its own key (only its SHA-256 is stored, settings_kv 'spike:key:<runtime>'),
which is good for the 'spike' category only — that is how cost is attributed per runtime.

The verdict follows the blueprint: OpenJarvis passes if it wins at least 2 of the 4 metrics (quality, cost,
time, failure rate) AND has zero privacy / approval / protected-zone violations.
"""

import hashlib
import hmac
import statistics

from . import db

RUNTIMES = ("hermes", "openjarvis")
CATEGORY = "spike"
_keys: dict[str, str] = {}


async def caller_for(key: str) -> str | None:
    """'spike-<runtime>' when the bearer key is a spike key, else None."""
    if not key:
        return None
    if not _keys:
        rows = await db.pool().fetch("SELECT key, value FROM settings_kv WHERE key LIKE 'spike:key:%'")
        _keys.update({r["key"].split(":", 2)[2]: str(r["value"]) for r in rows})
    digest = hashlib.sha256(key.encode()).hexdigest()
    for runtime, stored in _keys.items():
        if runtime in RUNTIMES and hmac.compare_digest(digest, str(stored)):
            return f"spike-{runtime}"
    return None


def forget_keys() -> None:
    _keys.clear()


# ---------- grading the weekly efficiency review (problem 3) ----------

def usage_truth(rows: list[dict]) -> dict:
    """What a correct review must find in the usage export: the costliest model, the slowest category (median
    latency, ≥5 calls) and the model failing most often (≥5 calls)."""
    cost: dict[str, float] = {}
    lat: dict[str, list[float]] = {}
    calls: dict[str, list[bool]] = {}
    for r in rows:
        cost[r["model"]] = cost.get(r["model"], 0.0) + float(r.get("cost_usd") or 0)
        if r.get("latency_ms") is not None:
            lat.setdefault(r["category"], []).append(float(r["latency_ms"]))
        calls.setdefault(r["model"], []).append(bool(r.get("ok")))
    slow = {c: statistics.median(v) for c, v in lat.items() if len(v) >= 5}
    fail = {m: 1 - sum(v) / len(v) for m, v in calls.items() if len(v) >= 5}
    return {"most_expensive_model": max(cost, key=cost.get) if cost else None,
            "slowest_category": max(slow, key=slow.get) if slow else None,
            "most_failing_model": max(fail, key=fail.get) if fail and max(fail.values()) > 0 else None}


def grade_review(report: dict | None, truth: dict) -> dict:
    """Share of the three findings the runtime got right, plus whether it proposed something concrete."""
    if not isinstance(report, dict):
        return {"quality": 0.0, "why": "report.json tidak ada atau bukan JSON objek"}
    hits = {k: str(report.get(k) or "").strip().lower() == str(truth[k] or "").strip().lower() for k in truth}
    advice = str(report.get("recommendation") or "").strip()
    score = (sum(hits.values()) + (1 if len(advice) >= 40 else 0)) / (len(hits) + 1)
    return {"quality": round(score, 3), "hits": hits, "has_recommendation": len(advice) >= 40}


# ---------- the verdict ----------

def summarize(runs: list[dict]) -> dict:
    """Per runtime: mean quality, mean cost, mean seconds, failure rate, violations; then the verdict."""
    out: dict[str, dict] = {}
    for rt in RUNTIMES:
        mine = [r for r in runs if r["runtime"] == rt and r["status"] in ("done", "failed")]
        if not mine:
            continue
        out[rt] = {
            "runs": len(mine),
            "quality": round(statistics.mean(float(r.get("quality") or 0) for r in mine), 3),
            "cost_usd": round(statistics.mean(float(r.get("cost_usd") or 0) for r in mine), 5),
            "seconds": round(statistics.mean(float(r.get("seconds") or 0) for r in mine), 1),
            "failure_rate": round(sum(r["status"] == "failed" or float(r.get("quality") or 0) < 1 for r in mine) / len(mine), 3),
            "violations": sum(len(r.get("violations") or []) for r in mine),
        }
    return {"runtimes": out, **verdict(out)}


def verdict(per: dict) -> dict:
    if not all(rt in per for rt in RUNTIMES):
        return {"verdict": "belum lengkap", "wins": [], "passed": False}
    h, o = per["hermes"], per["openjarvis"]
    wins = [m for m, better in (("quality", o["quality"] > h["quality"]), ("cost", o["cost_usd"] < h["cost_usd"]),
                                ("time", o["seconds"] < h["seconds"]), ("failure_rate", o["failure_rate"] < h["failure_rate"]))
            if better]
    passed = len(wins) >= 2 and o["violations"] == 0
    return {"wins": wins, "passed": passed,
            "verdict": "OpenJarvis lolos" if passed else
                       ("OpenJarvis gagal: ada pelanggaran" if o["violations"] else "OpenJarvis tidak unggul di ≥2 metrik")}
