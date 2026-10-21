"""OpenRouter balance: JARVIS cannot think without it, so running out must be loud and plain.

From 2026-10-17 20:23 to 10-21 the account sat at $0 credits: every model call failed with HTTP 402 and
the owner only saw raw error text ("hi" → "OpenRouter HTTP 402: …"). Now: the balance is a health check,
402s are recognised everywhere, and the owner gets one plain-language report per 12 hours.
"""

import re
import time

import httpx

from . import audit
from .config import settings

EXHAUSTED = re.compile(r"HTTP 402|requires more credits|credits exhausted|can only afford", re.IGNORECASE)
NOTIFY_EVERY_S = 12 * 3600
LOW_BALANCE_USD = 0.5
MESSAGE = ("Saldo OpenRouter-ku habis, jadi aku tidak bisa berpikir atau mengerjakan tugas. "
           "Tolong isi kredit di openrouter.ai/settings/credits — lima dolar cukup untuk berbulan-bulan.")

_cache: tuple[float, dict | None] = (0.0, None)
_last_notified = 0.0


def is_exhausted(text: str | None) -> bool:
    return bool(text) and bool(EXHAUSTED.search(text))


async def balance() -> dict | None:
    """{"credits": total bought, "usage": total spent, "remaining": credits - usage} (cached 5 min)."""
    global _cache
    if time.monotonic() - _cache[0] < 300 and _cache[1] is not None:
        return _cache[1]
    if not settings.openrouter_api_key:
        return None
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.get("https://openrouter.ai/api/v1/credits",
                            headers={"Authorization": f"Bearer {settings.openrouter_api_key}"})
        d = r.json()["data"]
        info = {"credits": d["total_credits"], "usage": d["total_usage"],
                "remaining": round(d["total_credits"] - d["total_usage"], 4)}
    except (httpx.HTTPError, KeyError, ValueError):
        return None
    _cache = (time.monotonic(), info)
    return info


def forget_cache() -> None:
    global _cache
    _cache = (0.0, None)


async def notify_exhausted() -> bool:
    """Tell the owner (urgent report, repeated until confirmed) — at most once per 12 h."""
    global _last_notified
    if time.monotonic() - _last_notified < NOTIFY_EVERY_S and _last_notified:
        return False
    _last_notified = time.monotonic()
    from . import reports
    await reports._create(None, "system", MESSAGE)
    await audit.record("jarvis-core", "billing.exhausted", None)
    forget_cache()
    return True
