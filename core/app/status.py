"""Service health checks used by the `status` command and the admin dashboard."""

import asyncio

import httpx

from .config import settings


async def _probe(client: httpx.AsyncClient, name: str, url: str, headers: dict | None = None) -> dict:
    try:
        r = await client.get(url, headers=headers or {})
        return {"name": name, "ok": r.status_code == 200, "detail": f"HTTP {r.status_code}"}
    except httpx.HTTPError as e:
        return {"name": name, "ok": False, "detail": type(e).__name__}


async def check_all() -> list[dict]:
    async with httpx.AsyncClient(timeout=5) as c:
        checks = [
            _probe(c, "Hermes Agent", f"{settings.hermes_url}/v1/models",
                   {"Authorization": f"Bearer {settings.hermes_api_key}"}),
            _probe(c, "n8n", f"{settings.n8n_url}/healthz"),
            _probe(c, "Qdrant", f"{settings.qdrant_url}/collections", {"api-key": settings.qdrant_api_key}),
            _probe(c, "Pendengaran lokal (Whisper)", f"{settings.whisper_url}/health"),
        ]
        if settings.n8n_api_key:
            checks.append(_probe(c, "n8n API key", f"{settings.n8n_url}/api/v1/workflows?limit=1",
                                 {"X-N8N-API-KEY": settings.n8n_api_key}))
        results = list(await asyncio.gather(*checks))
    if not settings.n8n_api_key:
        results.append({"name": "n8n API key", "ok": False, "detail": "belum diisi"})
    # All models run on OpenRouter since the local ones were removed (ADR-080): no key = nothing can answer.
    from . import billing, budget
    results.append({"name": "OpenRouter", "ok": bool(settings.openrouter_api_key),
                    "detail": "terisi" if settings.openrouter_api_key else "belum diisi — tidak ada model yang bisa menjawab"})
    if settings.openrouter_api_key:
        v = await billing.verdict()
        results.append({"name": "Saldo OpenRouter", "ok": v["working"] is not False, "detail": v["text"]})
    st = await budget.state()
    results.append({"name": "Anggaran AI bulan ini", "ok": st["level"] < 100,
                    "detail": f"${st['spent_usd']:.2f} dari ${st['budget_usd']:.0f} ({st['pct']:.0f}%)"})
    results.append({"name": "Groq (opsional)", "ok": True, "detail": "terisi" if settings.groq_api_key else "belum diisi"})
    results.append({"name": "Deepgram (opsional)", "ok": True,
                    "detail": "terisi" if settings.deepgram_api_key else "belum diisi"})
    return results
