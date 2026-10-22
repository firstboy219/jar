"""Monthly AI budget (BR-004: under $20/month), enforced by the gateway.

Spend is what the gateway recorded in llm_usage this month (WIB). Levels, for the total and for each
category with its own cap:
  60%  shown in the admin/APK only
  80%  background categories switch to free/local models; one report to the owner per month
  95%  every category prefers its cheapest route (free/local first)
  100% paid cloud models stop; free and local models keep JARVIS alive; report at most every 12 h
The hard cap lives on openrouter.ai (key limits only the owner can set); this is the soft one that
keeps JARVIS from ever hitting it by surprise.
"""

import os
import time
from datetime import datetime

from . import audit, db
from .location import WIB

BACKGROUND = {"latar-belakang", "cepat"}
LEVELS = (100, 95, 80, 60)
_state: dict = {"at": 0.0, "value": None}
_notified: dict[str, float] = {}


_total_override: float | None = None  # set from the chat/APK (settings_kv 'budget:total'); .env is the default


def total_budget() -> float:
    if _total_override:
        return _total_override
    try:
        return float(os.getenv("JARVIS_BUDGET_USD", "20") or 20)
    except ValueError:
        return 20.0


def _level(spent: float, cap: float | None) -> int:
    if not cap or cap <= 0:
        return 0
    pct = spent / cap * 100
    return next((lv for lv in LEVELS if pct >= lv), 0)


def month_start() -> datetime:
    now = datetime.now(WIB)
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


async def state(force: bool = False) -> dict:
    if not force and _state["value"] and time.monotonic() - _state["at"] < 60:
        return _state["value"]
    global _total_override
    saved = await db.pool().fetchval("SELECT value FROM settings_kv WHERE key = 'budget:total'")
    _total_override = float(saved) if isinstance(saved, (int, float)) and saved > 0 else None
    rows = await db.pool().fetch(
        "SELECT category, coalesce(sum(cost_usd), 0)::float AS spent FROM llm_usage WHERE at >= $1 GROUP BY category",
        month_start())
    spent = {r["category"]: r["spent"] for r in rows}
    caps = {r["name"]: (float(r["budget_usd"]) if r["budget_usd"] is not None else None)
            for r in await db.pool().fetch("SELECT name, budget_usd FROM llm_categories")}
    total = sum(spent.values())
    cap = total_budget()
    value = {
        "month": month_start().strftime("%Y-%m"), "spent_usd": round(total, 4), "budget_usd": cap,
        "pct": round(total / cap * 100, 1) if cap else 0, "level": _level(total, cap),
        "categories": {name: {"spent_usd": round(spent.get(name, 0.0), 4), "budget_usd": c,
                              "level": _level(spent.get(name, 0.0), c)} for name, c in caps.items()},
    }
    _state.update(at=time.monotonic(), value=value)
    await _maybe_notify(value)
    return value


def forget() -> None:
    _state["at"] = 0.0


def _cheapness(route) -> float:
    if not route.cloud or route.free:
        return 0.0
    from .gateway import _prices
    p = _prices["models"].get(route.model) or {}
    try:
        return float(p.get("prompt") or 1) + float(p.get("completion") or 1)
    except ValueError:
        return 1.0


async def adjust(category: str, routes: list) -> list:
    st = await state()
    level = max(st["level"], st["categories"].get(category, {}).get("level", 0))
    if level >= 100:
        return [r for r in routes if r.free or not r.cloud]
    if level >= 80 and category in BACKGROUND:
        return [r for r in routes if r.free or not r.cloud]
    if level >= 95:
        return sorted(routes, key=_cheapness)
    return routes


async def _maybe_notify(st: dict) -> None:
    from . import reports
    level = st["level"]
    if level >= 100:
        now = datetime.now(WIB)
        key, every = f"100:{now:%d}{'pm' if now.hour >= 12 else 'am'}", 12 * 3600
        text = (f"Anggaran AI bulan ini (${st['budget_usd']:.0f}) sudah habis terpakai. Aku tetap jalan memakai "
                "model gratis dan model lokal di server, jadi mungkin lebih lambat sampai bulan depan — "
                "atau naikkan anggarannya di menu Komposisi AI.")
    elif level >= 80:
        key, every = f"80:{st['month']}", 40 * 86400
        text = (f"Anggaran AI bulan ini sudah terpakai {st['pct']:.0f}% (${st['spent_usd']:.2f} dari "
                f"${st['budget_usd']:.0f}). Tugas latar belakang kupindah ke model gratis/lokal supaya hemat.")
    else:
        return
    if time.monotonic() - _notified.get(key, -1e12) < every:
        return
    _notified[key] = time.monotonic()
    if await db.pool().fetchval("SELECT 1 FROM settings_kv WHERE key = $1", f"budget:notified:{key}:{st['month']}"):
        return
    await db.pool().execute(
        """INSERT INTO settings_kv (key, value) VALUES ($1, to_jsonb(now()::text))
           ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value""", f"budget:notified:{key}:{st['month']}")
    await reports._create(None, "system", text)
    await audit.record("jarvis-core", "budget.level", None, level=level, spent=st["spent_usd"])
