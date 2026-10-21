"""The owner's composition of JARVIS: which AI answers each category, and which speech engine listens.

Only the owner's phone (device token with scope 'owner') may change it — decision 2026-10-21. The core
of JARVIS is not part of the composition and cannot be switched off: Hermes (the brain that works),
Qdrant + Postgres (memory) and n8n (automation) are always used, whatever models are chosen.
"""

import logging

from . import audit, db, gateway

log = logging.getLogger("jarvis-core.composition")

CORE = ["Hermes Agent", "Qdrant", "n8n"]
STT_ENGINES = {"whisper": "Whisper lokal (privat, gratis)", "groq": "Groq Whisper (cepat, ±gratis)",
               "deepgram": "Deepgram (cloud, berbayar per jam)"}
LOCKED = {"privat"}  # always local, not editable

OR = "openrouter"


def r(provider: str, model: str) -> dict:
    return {"provider": provider, "model": model}


L, LK = r("lokal", gateway.LOCAL_MODEL), r("lokal-kerja", gateway.LOCAL_MODEL)

# Presets (model choices measured/priced 2026-10-21; free models: OpenRouter ':free', ≤20 req/min).
PRESETS: dict[str, dict] = {
    "lokal": {
        "title": "Lokal penuh", "stt": "whisper",
        "summary": "Semua di server sendiri. Gratis & privat, tapi lambat (balasan pertama bisa >1 menit).",
        "routes": {c: [L] for c in ("ngobrol", "cepat", "penglihatan", "balas-pesan")}
                  | {c: [LK] for c in ("web", "coding", "produktivitas", "analisis", "rapat", "latar-belakang")},
    },
    "hemat": {
        "title": "Hemat gratis", "stt": "groq",
        "summary": "Model gratis OpenRouter (butuh pembelian kredit $10 sekali) + Groq. Hampir $0/bulan.",
        "routes": {
            "ngobrol": [r(OR, "minimax/minimax-m3.1-flash:free"), r(OR, "qwen/qwen3.7-flash"), L],
            "cepat": [r(OR, "nvidia/nemotron-3.5-lightning:free"), r(OR, "qwen/qwen3.7-flash"), L],
            "penglihatan": [r(OR, "google/gemma-4-31b-it:free"), r(OR, "qwen/qwen3.7-flash"), L],
            "web": [r(OR, "nvidia/nemotron-3-super-120b-a12b:free"), r(OR, "deepseek/deepseek-v4.1-flash"), LK],
            "coding": [r(OR, "cohere/north-mini-code:free"), r(OR, "qwen/qwen3-coder-next"), LK],
            "produktivitas": [r(OR, "nvidia/nemotron-3-super-120b-a12b:free"), r(OR, "deepseek/deepseek-v4.1-flash"), LK],
            "analisis": [r(OR, "nvidia/nemotron-3-ultra-550b-a55b:free"), r(OR, "deepseek/deepseek-v4.1-flash"), LK],
            "balas-pesan": [r(OR, "qwen/qwen3.7-flash"), L],
            "rapat": [r(OR, "deepseek/deepseek-v4.1-flash"), LK],
            "latar-belakang": [r(OR, "nvidia/nemotron-3.5-lightning:free"), LK],
        },
    },
    "seimbang": {
        "title": "Seimbang (rekomendasi)", "stt": "groq",
        "summary": "Cepat untuk ngobrol (Haiku), kuat & murah untuk kerja (DeepSeek + cache). ±$3–8/bulan.",
        "routes": {
            "ngobrol": [r(OR, "anthropic/claude-haiku-5.5"), r(OR, "qwen/qwen3.7-flash"), L],
            "cepat": [r(OR, "qwen/qwen3.7-flash"), r(OR, "nvidia/nemotron-3.5-lightning:free"), L],
            "penglihatan": [r(OR, "qwen/qwen3.7-flash"), r(OR, "google/gemma-4-31b-it:free"), L],
            "web": [r(OR, "deepseek/deepseek-v4.1-flash"), r(OR, "deepseek/deepseek-v4-flash"), LK],
            "coding": [r(OR, "qwen/qwen3-coder-next"), r(OR, "deepseek/deepseek-v4.1-flash"), LK],
            "produktivitas": [r(OR, "openai/gpt-5.6-luna"), r(OR, "deepseek/deepseek-v4.1-flash"), LK],
            "analisis": [r(OR, "deepseek/deepseek-v4.1-flash"), r(OR, "qwen/qwen3.8-flash"), LK],
            "balas-pesan": [r(OR, "qwen/qwen3.7-flash"), L],
            "rapat": [r(OR, "deepseek/deepseek-v4.1-flash"), LK],
            "latar-belakang": [r(OR, "nvidia/nemotron-3.5-lightning:free"), r(OR, "qwen/qwen3.7-flash"), LK],
        },
    },
    "pemilik": {
        "title": "Kombinasi pemilik", "stt": "groq",
        "summary": "Ngobrol Haiku 5.5, coding Sonnet 5.5 (anggaran $8), dokumen ChatGPT. ±$10–20/bulan.",
        "routes": {
            "ngobrol": [r(OR, "anthropic/claude-haiku-5.5"), r(OR, "qwen/qwen3.7-flash"), L],
            "cepat": [r(OR, "qwen/qwen3.7-flash"), L],
            "penglihatan": [r(OR, "qwen/qwen3.7-flash"), L],
            "web": [r(OR, "deepseek/deepseek-v4.1-flash"), LK],
            "coding": [r(OR, "anthropic/claude-sonnet-5.5"), r(OR, "qwen/qwen3-coder-next"), LK],
            "produktivitas": [r(OR, "openai/gpt-5.6-luna"), r(OR, "deepseek/deepseek-v4.1-flash"), LK],
            "analisis": [r(OR, "anthropic/claude-sonnet-5.5"), r(OR, "deepseek/deepseek-v4.1-flash"), LK],
            "balas-pesan": [r(OR, "anthropic/claude-haiku-5.5"), L],
            "rapat": [r(OR, "openai/gpt-5.6-luna"), LK],
            "latar-belakang": [r(OR, "nvidia/nemotron-3.5-lightning:free"), LK],
        },
        "budgets": {"coding": 8, "analisis": 4},
    },
}


class CompositionError(ValueError):
    pass


async def _kv(key: str, default=None):
    v = await db.pool().fetchval("SELECT value FROM settings_kv WHERE key = $1", key)
    return default if v is None else v


async def _set_kv(key: str, value) -> None:
    await db.pool().execute(  # the jsonb codec (db.py) encodes the Python value
        """INSERT INTO settings_kv (key, value) VALUES ($1, $2)
           ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value""", key, value)


async def stt_engine() -> str:
    return str(await _kv("composition:stt", "whisper"))


async def strong_mode() -> bool:
    return bool(await _kv("composition:strong", False))


async def get() -> dict:
    cats = await gateway.categories()
    provs = await gateway.providers()
    from . import budget
    st = await budget.state()
    return {
        "preset": await _kv("composition:preset", "lokal"),
        "core": CORE,
        "stt": {"engine": await stt_engine(), "options": STT_ENGINES},
        "strong_mode": await strong_mode(),
        "presets": [{"name": k, "title": v["title"], "summary": v["summary"]} for k, v in PRESETS.items()],
        "providers": [{"name": p["name"], "cloud": p["cloud"], "enabled": p["enabled"], "has_key": gateway.has_key(p)}
                      for p in provs.values()],
        "categories": [{"name": c["name"], "title": c["title"], "description": c["description"],
                        "routes": c["routes"], "budget_usd": float(c["budget_usd"]) if c["budget_usd"] is not None else None,
                        "allow_free": c["allow_free"], "confirm_cloud": c["confirm_cloud"], "worker": c["worker"],
                        "locked": c["name"] in LOCKED, "spent_usd": st["categories"].get(c["name"], {}).get("spent_usd", 0)}
                       for c in cats.values()],
        "budget": {k: st[k] for k in ("month", "spent_usd", "budget_usd", "pct", "level")},
    }


async def _validate_routes(routes) -> list[dict]:
    if not isinstance(routes, list) or not routes or len(routes) > 5:
        raise CompositionError("routes harus berisi 1–5 pilihan model")
    provs = await gateway.providers()
    out = []
    for item in routes:
        if not isinstance(item, dict):
            raise CompositionError("route tidak valid")
        p, m = str(item.get("provider") or ""), str(item.get("model") or "").strip()
        if p not in provs:
            raise CompositionError(f"penyedia tidak dikenal: {p}")
        if not m or len(m) > 120 or any(ch.isspace() for ch in m):
            raise CompositionError(f"nama model tidak valid: {m!r}")
        out.append({"provider": p, "model": m})
    return out


async def apply_preset(name: str, actor: str) -> dict:
    preset = PRESETS.get(name)
    if not preset:
        raise CompositionError(f"preset tidak dikenal: {name}")
    async with db.pool().acquire() as conn, conn.transaction():
        for cat, routes in preset["routes"].items():
            await conn.execute("UPDATE llm_categories SET routes = $2 WHERE name = $1 AND name <> 'privat'", cat, routes)
        for cat, cap in (preset.get("budgets") or {}).items():
            await conn.execute("UPDATE llm_categories SET budget_usd = $2 WHERE name = $1", cat, cap)
    await _set_kv("composition:preset", name)
    await _set_kv("composition:stt", preset["stt"])
    gateway.invalidate()
    await audit.record(actor, "composition.preset", None, preset=name)
    await sync_hermes_profile(actor)
    return await get()


async def update(changes: dict, actor: str) -> dict:
    """Partial update: {"categories": {name: {"routes", "budget_usd"}}, "stt": engine, "strong_mode": bool}.
    Anything about the permanent core is refused."""
    forbidden = {k for k in changes if k.lower() in ("hermes", "qdrant", "n8n", "core", "memory", "memori")}
    if forbidden:
        raise CompositionError("Hermes, Qdrant, dan n8n adalah inti JARVIS dan tidak bisa diganti atau dimatikan")
    unknown = set(changes) - {"categories", "stt", "strong_mode"}
    if unknown:
        raise CompositionError(f"field tidak dikenal: {', '.join(sorted(unknown))}")
    cats = await gateway.categories()
    for name, c in (changes.get("categories") or {}).items():
        if name not in cats:
            raise CompositionError(f"kategori tidak dikenal: {name}")
        if name in LOCKED:
            raise CompositionError("kategori privat selalu memakai model lokal")
        if "routes" in c:
            await db.pool().execute("UPDATE llm_categories SET routes = $2 WHERE name = $1",
                                    name, await _validate_routes(c["routes"]))
        if "budget_usd" in c:
            cap = c["budget_usd"]
            if cap is not None and not (isinstance(cap, (int, float)) and 0 <= cap <= 100):
                raise CompositionError("anggaran kategori harus 0–100 dolar")
            await db.pool().execute("UPDATE llm_categories SET budget_usd = $2 WHERE name = $1", name, cap)
    if "stt" in changes:
        if changes["stt"] not in STT_ENGINES:
            raise CompositionError(f"mesin suara tidak dikenal: {changes['stt']}")
        await _set_kv("composition:stt", changes["stt"])
    if "strong_mode" in changes:
        await _set_kv("composition:strong", bool(changes["strong_mode"]))
    if changes.get("categories"):
        await _set_kv("composition:preset", "kustom")
    gateway.invalidate()
    from . import budget
    budget.forget()
    await audit.record(actor, "composition.updated", None, changes=list(changes))
    if changes.get("categories"):
        await sync_hermes_profile(actor)
    return await get()


ADMIN_URL = "http://jarvis-admin:8000"


def hermes_profile_for(web_route_is_cloud: bool) -> str:
    """Hermes on the local CPU gets the lean prompt; on a cloud model everything eager (ADR-031). Pure."""
    return "full" if web_route_is_cloud else "lean"


async def sync_hermes_profile(actor: str) -> str | None:
    """Follow the composition: when Hermes' model moves between the local CPU and the cloud, switch its
    profile (jarvis-admin writes .env; jarvis-apply recreates only Hermes). Returns the new profile, if changed."""
    import httpx
    from .config import settings
    want = hermes_profile_for((await gateway.plan("web", caller="hermes", worker=True))[0].cloud)
    headers = {"X-Admin-Token": settings.admin_token}
    try:
        async with httpx.AsyncClient(timeout=20) as c:
            fields = (await c.get(ADMIN_URL + "/internal/settings", headers=headers)).json().get("fields", [])
            have = next((f.get("value") for f in fields if f.get("key") == "HERMES_PROFILE"), "") or "lean"
            if have == want:
                return None
            r = await c.post(ADMIN_URL + "/internal/settings", headers=headers, json={"HERMES_PROFILE": want})
            r.raise_for_status()
    except (httpx.HTTPError, ValueError) as e:
        log.warning("could not switch the Hermes profile: %s", e)
        return None
    await audit.record(actor, "hermes.profile", None, profile=want)
    return want
