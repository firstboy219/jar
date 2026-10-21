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
            _probe(c, "Model lokal (ngobrol)", "http://llama-chat:8080/health"),
            _probe(c, "Model lokal (kerja)", "http://llama-worker:8080/health"),
            _probe(c, "Pendengaran lokal (Whisper)", f"{settings.whisper_url}/health"),
        ]
        if settings.n8n_api_key:
            checks.append(_probe(c, "n8n API key", f"{settings.n8n_url}/api/v1/workflows?limit=1",
                                 {"X-N8N-API-KEY": settings.n8n_api_key}))
        results = list(await asyncio.gather(*checks))
    if not settings.n8n_api_key:
        results.append({"name": "n8n API key", "ok": False, "detail": "belum diisi"})
    # Cloud keys are optional (default composition is fully local): missing = "not used", not an error.
    from . import billing, budget
    results.append({"name": "OpenRouter (opsional)", "ok": True,
                    "detail": "terisi" if settings.openrouter_api_key else "belum diisi — semua AI lokal"})
    if settings.openrouter_api_key:
        b = await billing.balance()
        results.append({"name": "Saldo OpenRouter", "ok": b is not None and b["remaining"] >= billing.LOW_BALANCE_USD,
                        "detail": "tidak diketahui" if b is None else
                        (f"${b['remaining']:.2f} tersisa" if b["remaining"] > 0 else f"HABIS (${b['remaining']:.2f}) — model lokal dipakai")})
    st = await budget.state()
    results.append({"name": "Anggaran AI bulan ini", "ok": st["level"] < 100,
                    "detail": f"${st['spent_usd']:.2f} dari ${st['budget_usd']:.0f} ({st['pct']:.0f}%)"})
    results.append({"name": "Groq (opsional)", "ok": True, "detail": "terisi" if settings.groq_api_key else "belum diisi"})
    results.append({"name": "Deepgram (opsional)", "ok": True,
                    "detail": "terisi" if settings.deepgram_api_key else "belum diisi"})
    return results
