"""Token/cost monitoring: our own per-message log plus OpenRouter's account-level numbers."""

import httpx

from . import db
from .config import settings


async def local_summary(days: int = 30) -> dict:
    rows = await db.pool().fetch(
        """SELECT date_trunc('day', created_at)::date AS day,
                  count(*) FILTER (WHERE role = 'user')                       AS messages,
                  count(*) FILTER (WHERE role = 'user' AND route = 'core')    AS core,
                  count(*) FILTER (WHERE role = 'user' AND route = 'hermes')  AS hermes,
                  count(*) FILTER (WHERE role = 'user' AND route = 'blocked') AS blocked,
                  coalesce(sum(prompt_tokens), 0)     AS prompt_tokens,
                  coalesce(sum(completion_tokens), 0) AS completion_tokens,
                  avg(latency_ms) FILTER (WHERE route = 'hermes')::int AS avg_latency_ms
           FROM messages WHERE created_at > now() - make_interval(days => $1)
           GROUP BY 1 ORDER BY 1 DESC""", days)
    return {"days": [dict(r) for r in rows]}


async def openrouter_summary() -> dict:
    """GET /api/v1/key: usage (all-time/daily/weekly/monthly, USD) and limit for the configured key."""
    if not settings.openrouter_api_key:
        return {"error": "OpenRouter key belum diisi"}
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.get("https://openrouter.ai/api/v1/key",
                            headers={"Authorization": f"Bearer {settings.openrouter_api_key}"})
        r.raise_for_status()
        d = r.json()["data"]
    except (httpx.HTTPError, KeyError, ValueError) as e:
        return {"error": f"gagal mengambil data OpenRouter ({type(e).__name__})"}
    keys = ("usage", "usage_daily", "usage_weekly", "usage_monthly", "limit", "limit_remaining", "is_free_tier")
    return {k: d.get(k) for k in keys}
