"""OpenRouter balance: running out must be plain to the owner (since ADR-017 JARVIS keeps working on the
local model meanwhile, only slower).

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
MESSAGE = ("Saldo OpenRouter-ku habis, jadi hanya model gratis yang masih bisa kupakai (dan itu pun sering kena batas). "
           "Isi kredit di openrouter.ai/settings/credits supaya aku kembali normal.")

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


REAL_CALL_USD = 0.0005  # a real chat turn costs more than this; a tiny probe (a few tokens) costs far less


def judge(paid_ok, paid_fail, credits: dict | None) -> dict:
    """Is paid OpenRouter usable? paid_ok: time of the last paid call that cost >= REAL_CALL_USD and worked;
    paid_fail: time of the last 402. A 402 is final until a real call works again. Tiny probes prove nothing: with
    ~$0 left a 16-token call still passes while a 400-token one is refused ("can only afford 90"), so the
    credits number counts too. Pure; unit-tested."""
    if paid_ok is not None and (paid_fail is None or paid_ok > paid_fail):
        return {"working": True, "text": "berfungsi (panggilan berbayar sungguhan berhasil)"}
    if paid_fail is not None:
        return {"working": False, "text": "HABIS — panggilan berbayar terakhir ditolak (HTTP 402: kredit tidak cukup); hanya model gratis yang masih jalan"}
    if credits is not None:
        ok = credits["remaining"] >= LOW_BALANCE_USD
        return {"working": ok, "text": f"${credits['remaining']:.2f} tersisa" if ok else f"HABIS (${credits['remaining']:.2f}) — kredit di akun kunci ini belum ada"}
    return {"working": None, "text": "belum diketahui (belum ada panggilan berbayar)"}


async def verdict() -> dict:
    from . import db
    ok = await db.pool().fetchval(
        "SELECT max(at) FROM llm_usage WHERE provider = 'openrouter' AND ok AND cost_usd >= $1", REAL_CALL_USD)
    fail = await db.pool().fetchval(
        "SELECT max(at) FROM llm_usage WHERE provider = 'openrouter' AND NOT ok AND error LIKE '%402%'")
    return judge(ok, fail, await balance()) | {"credits_endpoint": await balance()}


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
