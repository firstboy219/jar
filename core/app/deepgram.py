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
    return {"access_token": d["access_token"], "expires_in": d.get("expires_in", ttl_seconds)}
