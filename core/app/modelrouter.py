"""The model router's brain (Blueprint v2 §5, ADR-040): which model, in what order, and what a failure means.

The gateway still owns the HTTP and the owner's chain per category (composition). This module adds, around it:
  * requirements — tool calling is needed by chat and Hermes' categories; sensitive content never reaches a free
    endpoint (free endpoints may log prompts: the NO_FREE flag, set by the chat for attachments/screen text);
  * measured health — a model that fails in practice (JARVIS' own calls, the owner's "Uji sekarang") is moved
    behind the healthy ones instead of being tried first every time;
  * free-first, verified — when the owner's first choice is free, proven free models (and openrouter/free) are
    tried before any paid one;
  * diagnosis before paying — a transient failure is retried once, a rate limit or refusal goes to the next free
    option, and a paid model is tried only `paid_attempt_limit` times after a free one failed;
  * budgets — per task (a task over its budget gets no paid calls until the owner approves more).
Everything is recorded on the llm_usage row (retry, fallback_reason, task_id).
"""

import contextvars
import logging
import re
import time
from dataclasses import dataclass, field

from . import db, modelinsight

log = logging.getLogger("jarvis-core.modelrouter")
NO_FREE: contextvars.ContextVar[bool] = contextvars.ContextVar("jarvis_no_free", default=False)
NEEDS_TOOLS = {"ngobrol", "web", "coding", "produktivitas", "analisis", "latar-belakang", "berat", "review"}
FREE_FALLBACK = "openrouter/free"
RETRY_DELAY_S = 1.5
DEFAULT_TASK_USD = 0.50
HEALTH_TTL_S = 60
MIN_CALLS = 5          # fewer calls prove nothing
SICK_BELOW_PCT = 60    # moved behind the healthy models
PROVEN_PCT = 90        # a free model must be this reliable to be an "alternative"
_TRANSIENT = re.compile(r"HTTP 5\d\d|ReadTimeout|ConnectTimeout|ReadError|RemoteProtocolError|ConnectError|PoolTimeout|jawaban kosong|terputus", re.I)
_health: dict = {"at": 0.0, "value": {}}


def task_id_of(session_id: str | None) -> int | None:
    """Hermes sessions are named task-<id>. Pure."""
    m = re.match(r"task-(\d+)", session_id or "")
    return int(m.group(1)) if m else None


_TASK_MARK = re.compile(r"\[tugas #(\d+)\]")


def task_id_from_body(body: dict) -> int | None:
    """Hermes does not send its session id to the gateway, but the worker brief starts with "[tugas #N]" in the first user
    message, which stays in every request of that run — so a call can be tied to its task. Pure; unit-tested."""
    for m in body.get("messages") or []:
        if m.get("role") != "user":
            continue
        c = m.get("content")
        text = c if isinstance(c, str) else " ".join(p.get("text", "") for p in c if isinstance(p, dict)) if isinstance(c, list) else ""
        found = _TASK_MARK.search(text[:6000])
        return int(found.group(1)) if found else None
    return None


def diagnose(error_text: str) -> str:
    """credit | refused | rate | transient | other — what a failure means for the next step. Pure; unit-tested."""
    from .gateway import refused_outright
    text = error_text or ""
    if re.search(r"HTTP 402|requires more credits|can only afford", text, re.I):
        return "credit"
    if refused_outright(text):
        return "refused"
    if re.search(r"HTTP 429", text):
        return "rate"
    if _TRANSIENT.search(text):
        return "transient"
    return "other"


def unhealthy(model: str, health: dict) -> bool:
    h = health.get(model) or {}
    if h.get("tools_ok") is False:
        return True
    return (h.get("calls") or 0) >= MIN_CALLS and (h.get("ok_pct") if h.get("ok_pct") is not None else 100) < SICK_BELOW_PCT


def proven_free(health: dict, exclude: set[str]) -> list[str]:
    """Free models JARVIS has used enough, reliably, fastest first. Pure."""
    found = [(h.get("p50_ms") or 10**9, m) for m, h in health.items()
             if m.endswith(":free") and m not in exclude and (h.get("calls") or 0) >= MIN_CALLS
             and (h.get("ok_pct") or 0) >= PROVEN_PCT and h.get("tools_ok") is not False]
    return [m for _, m in sorted(found)][:2]


def order(routes: list, health: dict, *, no_free: bool, free_first: bool, alternatives: list) -> list:
    """Reorder the chain: no free model for sensitive content; sick models behind healthy ones; proven free
    alternatives right after the free models when the owner's first choice is free. Routes are gateway.Route. Pure."""
    if no_free:
        routes = [r for r in routes if not (r.cloud and r.free)]
    cloud = [r for r in routes if r.cloud]
    local = [r for r in routes if not r.cloud]
    cloud = [r for r in cloud if not unhealthy(r.model, health)] + [r for r in cloud if unhealthy(r.model, health)]
    if free_first and not no_free:
        have = {r.model for r in cloud}
        extra = [r for r in alternatives if r.model not in have]
        at = max((i + 1 for i, r in enumerate(cloud) if r.free and not unhealthy(r.model, health)), default=None)
        if at is None:
            at = next((i for i, r in enumerate(cloud) if not r.free), len(cloud))
        cloud[at:at] = extra
    return cloud + local


async def health() -> dict:
    """model → {calls, ok_pct, p50_ms, tools_ok}: JARVIS' own last 3 days (402s are the account's fault, not counted)
    plus the latest "Uji sekarang" tool check. Cached a minute."""
    if time.monotonic() - _health["at"] < HEALTH_TTL_S and _health["value"] is not None:
        return _health["value"]
    rows = await db.pool().fetch(
        """SELECT model, count(*) FILTER (WHERE ok OR coalesce(error, '') NOT LIKE '%402%') AS calls,
                  count(*) FILTER (WHERE ok) AS ok_calls,
                  percentile_cont(0.5) WITHIN GROUP (ORDER BY latency_ms) FILTER (WHERE ok) AS p50
           FROM llm_usage WHERE provider = 'openrouter' AND caller <> 'test' AND at > now() - interval '3 days' GROUP BY model""")
    value = {r["model"]: {"calls": r["calls"], "ok_pct": round(100 * r["ok_calls"] / r["calls"], 1) if r["calls"] else None,
                          "p50_ms": int(r["p50"]) if r["p50"] is not None else None} for r in rows}
    for r in await db.pool().fetch("SELECT DISTINCT ON (model) model, tools_ok FROM model_bench ORDER BY model, at DESC"):
        value.setdefault(r["model"], {})["tools_ok"] = r["tools_ok"]
    _health.update(at=time.monotonic(), value=value)
    return value


def forget_health() -> None:
    _health["at"] = 0.0


async def arrange(routes: list, *, make, needs_tools: bool, allow_free: bool, no_free: bool) -> list:
    """The gateway's hook: `make(model)` builds an OpenRouter Route (or None without a key)."""
    h = await health()
    free_first = bool(routes) and routes[0].cloud and routes[0].free
    alternatives = []
    if free_first and allow_free and not no_free:
        names = proven_free(h, {r.model for r in routes}) + [FREE_FALLBACK]
        alternatives = [r for r in (make(m) for m in names) if r is not None]
    return order(routes, h, no_free=no_free, free_first=free_first, alternatives=alternatives)


# ---------- per-request bookkeeping ----------

@dataclass
class Attempts:
    """State of ONE request walking its routes: retries, paid attempts after a free failure, why it fell back."""
    task_id: int | None
    max_retries: int
    paid_limit: int
    over_budget: bool = False
    retries: int = 0
    free_failed: bool = False
    paid_after_free: int = 0
    reason: str | None = None
    retried: set = field(default_factory=set)
    begun: set = field(default_factory=set)

    @classmethod
    async def start(cls, category: dict | None, session_id: str | None, body: dict | None = None) -> "Attempts":
        task_id = task_id_of(session_id) or (task_id_from_body(body) if body else None)
        a = cls(task_id, int((category or {}).get("max_retries", 1)), int((category or {}).get("paid_attempt_limit", 1)))
        if task_id and await task_over_budget(task_id):
            a.over_budget = True
            await ask_more_budget(task_id)
        return a

    def skip(self, route) -> str | None:
        """Why this route must not be tried now (paid ones only; free and local are never held back)."""
        if not route.cloud or route.free:
            return None
        if (route.provider, route.model) in self.begun:  # a retry of the paid model already allowed: not a new attempt
            return None
        if self.over_budget:
            return "anggaran tugas habis"
        if self.free_failed and self.paid_after_free >= self.paid_limit:
            return "batas percobaan berbayar"
        return None

    def begin(self, route) -> None:
        key = (route.provider, route.model)
        if route.cloud and not route.free and self.free_failed and key not in self.begun:
            self.paid_after_free += 1
        self.begun.add(key)

    def failed(self, route, error: str) -> bool:
        """Record a failure; True when the same route should be retried once (transient only)."""
        kind = diagnose(error)
        self.reason = modelinsight.classify_error(error)
        if route.cloud and route.free:
            self.free_failed = True
        key = (route.provider, route.model)
        if kind == "transient" and self.retries < self.max_retries and key not in self.retried:
            self.retried.add(key)
            self.retries += 1
            return True
        return False

    def note(self, why: str) -> None:
        self.reason = why

    def extra(self) -> dict:
        return {"task_id": self.task_id, "retry": self.retries, "fallback_reason": self.reason}


# ---------- task budget ----------

async def default_task_budget() -> float:
    v = await db.pool().fetchval("SELECT value FROM settings_kv WHERE key = 'budget:task_default'")
    return float(v) if isinstance(v, (int, float)) and v > 0 else DEFAULT_TASK_USD


async def task_over_budget(task_id: int) -> bool:
    row = await db.pool().fetchrow(
        """SELECT t.budget_usd::float AS cap, (SELECT coalesce(sum(cost_usd), 0) FROM llm_usage WHERE task_id = t.id)::float AS spent
           FROM tasks t WHERE t.id = $1""", task_id)
    return bool(row and row["cap"] is not None and row["spent"] >= row["cap"])


async def ask_more_budget(task_id: int) -> None:
    """Over budget: no paid calls; the task waits for the owner's say (Approval Center), once per task."""
    from . import approvals
    row = await db.pool().fetchrow("SELECT title, budget_usd::float AS cap FROM tasks WHERE id = $1", task_id)
    if not row:
        return
    await db.pool().execute("UPDATE tasks SET phase = 'waiting_approval' WHERE id = $1 AND status IN ('queued', 'running')", task_id)
    await approvals.create(
        "task_budget", f"Tambah anggaran tugas #{task_id}: {row['title'][:60]}",
        {"task_id": task_id, "add_usd": max(0.5, row["cap"]), "note": f"Anggaran ${row['cap']:.2f} terpakai; tanpa persetujuan hanya model gratis/lokal yang dipakai."},
        "jarvis-router", risk="low", idempotency_key=f"taskbudget:{task_id}:{row['cap']:.2f}")
