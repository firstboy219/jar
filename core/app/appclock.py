"""The app's clock (ADR-087): the recurring work behind the screens — prayer reminders, the morning brief, syncing business APIs,
habits that fire at a time, the evening recap … Each feature registers its tick here; one loop runs them, each isolated from the others.

  @every(60)              runs at most once per 60 s
  @daily(lambda: "05:45") runs once a day at that WIB time (the time is read each pass, so a setting change applies the same day); the
                          day it last ran is kept in settings_kv, so a restart never runs it twice nor skips it when started late the same day
"""

import asyncio
import logging
import time
from datetime import datetime
from typing import Awaitable, Callable

from . import db
from .location import WIB

log = logging.getLogger("jarvis-core")
PASS_S = 20

_every: dict[str, tuple[float, Callable[[], Awaitable[None]]]] = {}
_daily: dict[str, tuple[Callable[[], Awaitable[str] | str], Callable[[], Awaitable[None]]]] = {}
_last: dict[str, float] = {}


def every(seconds: float, name: str | None = None):
    def wrap(fn):
        _every[name or f"{fn.__module__}.{fn.__name__}"] = (seconds, fn)
        return fn
    return wrap


def daily(at: Callable[[], Awaitable[str] | str], name: str | None = None):
    """`at` returns "HH:MM" (WIB) or "" to skip today."""
    def wrap(fn):
        _daily[name or f"{fn.__module__}.{fn.__name__}"] = (at, fn)
        return fn
    return wrap


def hhmm_due(at: str, now: datetime) -> bool:
    """Is it at or past "HH:MM" today? Pure."""
    try:
        h, m = (int(x) for x in at.replace(".", ":").split(":")[:2])
    except (ValueError, AttributeError):
        return False
    return (now.hour, now.minute) >= (h, m)


async def _ran_today(name: str, today: str) -> bool:
    return await db.pool().fetchval("SELECT value FROM settings_kv WHERE key = $1", f"clock:{name}") == today


async def _mark(name: str, today: str) -> None:
    await db.pool().execute("""INSERT INTO settings_kv (key, value) VALUES ($1, $2) ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value""",
                            f"clock:{name}", today)


async def run_once(now: datetime | None = None) -> list[str]:
    """One pass: every due tick, each with its own error handling. Returns what ran (for tests and the log)."""
    now = (now or datetime.now(WIB)).astimezone(WIB)
    ran = []
    for name, (secs, fn) in list(_every.items()):
        if time.monotonic() - _last.get(name, 0.0) < secs:
            continue
        _last[name] = time.monotonic()
        try:
            await asyncio.wait_for(fn(), timeout=max(30.0, secs))
            ran.append(name)
        except Exception:
            log.exception("app clock: %s failed", name)
    today = now.date().isoformat()
    for name, (at_fn, fn) in list(_daily.items()):
        try:
            at = at_fn()
            if asyncio.iscoroutine(at):
                at = await at
            if not at or not hhmm_due(at, now) or await _ran_today(name, today):
                continue
            await _mark(name, today)          # marked first: a failing job is not retried every 20 s all day
            await asyncio.wait_for(fn(), timeout=600)
            ran.append(name)
        except Exception:
            log.exception("app clock: daily %s failed", name)
    return ran


async def run_forever() -> None:
    from . import features   # noqa: F401  every feature module registers its ticks on import
    while True:
        try:
            await run_once()
        except Exception:
            log.exception("app clock pass failed")
        await asyncio.sleep(PASS_S)
