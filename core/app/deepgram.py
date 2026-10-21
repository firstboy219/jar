"""Short-lived Deepgram tokens for the APK (FS-101) so the real API key never ships in the app."""

import httpx

from .config import settings


class DeepgramError(RuntimeError):
    pass


async def grant(ttl_seconds: int = 60) -> dict:
    if not settings.deepgram_api_key:
        raise DeepgramError("DEEPGRAM_API_KEY belum diisi")
    async with httpx.AsyncClient(timeout=10) as c:
        r = await c.post("https://api.deepgram.com/v1/auth/grant",
                         headers={"Authorization": f"Token {settings.deepgram_api_key}"},
                         json={"ttl_seconds": ttl_seconds})
    if r.status_code != 200:
        raise DeepgramError(f"Deepgram HTTP {r.status_code}")
    d = r.json()
    return {"access_token": d["access_token"], "expires_in": d.get("expires_in", ttl_seconds), **await stt_config()}


async def learned_keywords() -> list[str]:
    """Terms the self-check added after noticing they were misheard (improvements table)."""
    from . import db
    try:
        rows = await db.pool().fetch(
            "SELECT payload->>'term' AS t FROM improvements WHERE kind = 'stt_keyword' AND status = 'applied' ORDER BY id")
    except Exception:  # database not ready: recognition must still work
        return []
    return [r["t"] for r in rows if r["t"]]


async def stt_config() -> dict:
    """Recognition settings the APK uses for the Deepgram stream (tunable without an app release)."""
    configured = [k.strip() for k in settings.deepgram_keywords.split(",") if k.strip()]
    keywords = list(dict.fromkeys(configured + await learned_keywords()))[:50]
    return {"model": settings.deepgram_model, "language": settings.deepgram_language, "keywords": keywords,
            "diarize": True, "endpointing_ms": settings.endpointing_ms, "utterance_end_ms": settings.utterance_end_ms}
