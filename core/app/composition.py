"""The owner's composition of JARVIS: which AI answers each category, and which speech engine listens.

Only the owner (their phone's owner-scope device token, or an owner turn in the chat) may change it. Since
ADR-038 the only permanent parts are Qdrant (memory) and n8n (automation); every model — chat, Hermes' work,
vision, drafts, minutes — is the owner's pick from OpenRouter's live catalog (there is no local model any more, ADR-080).
"""

import logging
import re
from pathlib import Path

from . import audit, db, gateway, openrouter

log = logging.getLogger("jarvis-core.composition")

CORE = ["Qdrant", "n8n"]
STT_ENGINES = {"whisper": "Whisper lokal (privat, gratis)", "groq": "Groq Whisper (cepat, ±gratis)",
               "deepgram": "Deepgram (cloud, berbayar per jam)", "openrouter": "Model OpenRouter pilihanmu (ElevenLabs Scribe, GPT, …)"}
LOCKED: set[str] = set()   # no category is locked any more: "privat" used to be local-only (ADR-080)
BUILTIN = {"ngobrol", "cepat", "penglihatan", "balas-pesan", "web", "coding", "produktivitas", "analisis", "rapat",
           "latar-belakang", "privat"}
NEEDS_TOOLS = {"ngobrol", "web", "coding", "produktivitas", "analisis", "latar-belakang", "review", "dev-bisan", "dev-coder", "dev-qaqa"}  # tool calling: chat agent, Hermes
NEEDS_VISION = {"penglihatan"}
EXPENSIVE_OUT_USD = 15.0  # per 1M output tokens: above this the owner confirms first

OR = "openrouter"


def r(provider: str, model: str) -> dict:
    return {"provider": provider, "model": model}


# Presets (model choices measured/priced 2026-10-21; free models: OpenRouter ':free', ≤20 req/min).
PRESETS: dict[str, dict] = {
    "hemat": {
        "title": "Hemat gratis", "stt": "groq",
        "summary": "Model gratis OpenRouter (butuh pembelian kredit $10 sekali) + Groq. Hampir $0/bulan.",
        "routes": {
            "ngobrol": [r(OR, "nvidia/nemotron-3-super-120b-a12b:free"), r(OR, "qwen/qwen3.7-flash")],
            "cepat": [r(OR, "nvidia/nemotron-3.5-lightning:free"), r(OR, "qwen/qwen3.7-flash")],
            "penglihatan": [r(OR, "google/gemma-4-31b-it:free"), r(OR, "qwen/qwen3.7-flash")],
            "web": [r(OR, "nvidia/nemotron-3-super-120b-a12b:free"), r(OR, "deepseek/deepseek-v4.1-flash")],
            "coding": [r(OR, "cohere/north-mini-code:free"), r(OR, "qwen/qwen3-coder-next")],
            "produktivitas": [r(OR, "nvidia/nemotron-3-super-120b-a12b:free"), r(OR, "deepseek/deepseek-v4.1-flash")],
            "analisis": [r(OR, "nvidia/nemotron-3-ultra-550b-a55b:free"), r(OR, "deepseek/deepseek-v4.1-flash")],
            "balas-pesan": [r(OR, "qwen/qwen3.7-flash")],
            "rapat": [r(OR, "deepseek/deepseek-v4.1-flash")],
            "latar-belakang": [r(OR, "nvidia/nemotron-3.5-lightning:free")],
        },
    },
    "seimbang": {
        "title": "Seimbang (rekomendasi)", "stt": "groq",
        "summary": "Cepat untuk ngobrol (Haiku), kuat & murah untuk kerja (DeepSeek + cache). ±$3–8/bulan.",
        "routes": {
            "ngobrol": [r(OR, "anthropic/claude-haiku-5.5"), r(OR, "qwen/qwen3.7-flash")],
            "cepat": [r(OR, "qwen/qwen3.7-flash"), r(OR, "nvidia/nemotron-3.5-lightning:free")],
            "penglihatan": [r(OR, "qwen/qwen3.7-flash"), r(OR, "google/gemma-4-31b-it:free")],
            "web": [r(OR, "deepseek/deepseek-v4.1-flash"), r(OR, "deepseek/deepseek-v4-flash")],
            "coding": [r(OR, "qwen/qwen3-coder-next"), r(OR, "deepseek/deepseek-v4.1-flash")],
            "produktivitas": [r(OR, "openai/gpt-5.6-luna"), r(OR, "deepseek/deepseek-v4.1-flash")],
            "analisis": [r(OR, "deepseek/deepseek-v4.1-flash"), r(OR, "qwen/qwen3.8-flash")],
            "balas-pesan": [r(OR, "qwen/qwen3.7-flash")],
            "rapat": [r(OR, "deepseek/deepseek-v4.1-flash")],
            "latar-belakang": [r(OR, "nvidia/nemotron-3.5-lightning:free"), r(OR, "qwen/qwen3.7-flash")],
        },
    },
    "pemilik": {
        "title": "Kombinasi pemilik", "stt": "groq",
        "summary": "Ngobrol Haiku 5.5, coding Sonnet 5.5 (anggaran $8), dokumen ChatGPT. ±$10–20/bulan.",
        "routes": {
            "ngobrol": [r(OR, "anthropic/claude-haiku-5.5"), r(OR, "qwen/qwen3.7-flash")],
            "cepat": [r(OR, "qwen/qwen3.7-flash")],
            "penglihatan": [r(OR, "qwen/qwen3.7-flash")],
            "web": [r(OR, "deepseek/deepseek-v4.1-flash")],
            "coding": [r(OR, "anthropic/claude-sonnet-5.5"), r(OR, "qwen/qwen3-coder-next")],
            "produktivitas": [r(OR, "openai/gpt-5.6-luna"), r(OR, "deepseek/deepseek-v4.1-flash")],
            "analisis": [r(OR, "anthropic/claude-sonnet-5.5"), r(OR, "deepseek/deepseek-v4.1-flash")],
            "balas-pesan": [r(OR, "anthropic/claude-haiku-5.5")],
            "rapat": [r(OR, "openai/gpt-5.6-luna")],
            "latar-belakang": [r(OR, "nvidia/nemotron-3.5-lightning:free")],
        },
        "budgets": {"coding": 8, "analisis": 4},
    },
}


REGISTRY_FILE = Path(__file__).resolve().parent.parent / "config" / "model_registry.yaml"


def registry_preset(path: Path = REGISTRY_FILE) -> dict | None:
    """config/model_registry.yaml (Blueprint v2 §4.5) as a preset the owner can apply. Pure apart from reading the
    file; None when the file is missing/unreadable (the other presets still work)."""
    try:
        import yaml
        data = yaml.safe_load(path.read_text())
    except (OSError, ImportError, ValueError):
        return None
    routes, limits, new = {}, {}, {}
    for cat, spec in (data.get("categories") or {}).items():
        chain = [r(OR, m) for m in [spec["primary"], *(spec.get("fallback") or [])] if m]
        routes[cat] = chain
        limits[cat] = {"paid_attempt_limit": int(spec.get("paid_attempt_limit", 1))}
        if cat not in BUILTIN:
            new[cat] = {"title": spec.get("title") or cat, "description": spec.get("description") or ""}
    return {"title": "Blueprint v2 (free-first terukur)", "stt": None,
            "summary": "Templat blueprint: model gratis dulu untuk kerja latar belakang/riset/coding, berbayar hanya setelah diagnosis; "
                       "ngobrol tetap model cepat yang terbukti. Id model divalidasi ke katalog OpenRouter saat diterapkan.",
            "routes": routes, "limits": limits, "new_categories": new, "free_fallback": data.get("free_fallback")}


class CompositionError(ValueError):
    pass


if (_blueprint := registry_preset()) is not None:
    PRESETS["blueprint"] = _blueprint


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
    from . import billing, budget
    st = await budget.state()
    catalog = await openrouter.catalog() or []
    bal = await billing.balance()
    verdict = await billing.verdict()

    def label(route: dict) -> dict:
        info = openrouter.get(catalog, route.get("model", "")) if route.get("provider") == OR else None
        return route | ({"name": info["name"], "price_in": info["price_in"], "price_out": info["price_out"],
                         "free": info["free"], "context": info["context"]} if info else {})
    return {
        "openrouter": {"has_key": any(p["name"] == OR and gateway.has_key(p) for p in provs.values()),
                       "balance_usd": bal["remaining"] if bal else None,
                       "working": verdict["working"], "status": verdict["text"], "models": len(catalog)},
        "preset": await _kv("composition:preset", "seimbang"),
        "core": CORE,
        "stt": {"engine": await stt_engine(), "options": STT_ENGINES},
        "strong_mode": await strong_mode(),
        "presets": [{"name": k, "title": v["title"], "summary": v["summary"]} for k, v in PRESETS.items()],
        "providers": [{"name": p["name"], "cloud": p["cloud"], "enabled": p["enabled"], "has_key": gateway.has_key(p)}
                      for p in provs.values()],
        "categories": [{"name": c["name"], "title": c["title"], "description": c["description"],
                        "routes": [label(x) for x in c["routes"]], "builtin": c["name"] in BUILTIN, "budget_usd": float(c["budget_usd"]) if c["budget_usd"] is not None else None,
                        "allow_free": c["allow_free"], "confirm_cloud": c["confirm_cloud"], "worker": c["worker"],
                        "paid_attempt_limit": c["paid_attempt_limit"], "max_retries": c["max_retries"],
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
    models = await openrouter.catalog() if any(x["provider"] == OR for x in out) else None
    if models is not None:
        for x in out:
            if x["provider"] == OR and not openrouter.get(models, x["model"]):
                hint = openrouter.closest(models, x["model"])
                raise CompositionError(f"model {x['model']} tidak ada di OpenRouter" + (f" — maksudmu {', '.join(hint)}?" if hint else ""))
    return out


async def apply_preset(name: str, actor: str) -> dict:
    preset = PRESETS.get(name)
    if not preset:
        raise CompositionError(f"preset tidak dikenal: {name}")
    models = await openrouter.catalog()
    async with db.pool().acquire() as conn, conn.transaction():
        for new, spec in (preset.get("new_categories") or {}).items():  # e.g. "review": a reviewer other than the author
            await conn.execute(
                """INSERT INTO llm_categories (name, title, description, routes, allow_free, confirm_cloud, worker, sort)
                   VALUES ($1, $2, $3, '[]'::jsonb, true, false, false, 150) ON CONFLICT (name) DO NOTHING""",
                new, spec["title"][:60], spec["description"][:200])
        for cat, lim in (preset.get("limits") or {}).items():
            await conn.execute("UPDATE llm_categories SET paid_attempt_limit = $2 WHERE name = $1", cat, lim["paid_attempt_limit"])
        for cat, routes in preset["routes"].items():
            if models is not None:  # a preset must never write a model OpenRouter does not have
                routes = [x for x in routes if x["provider"] != OR or openrouter.get(models, x["model"])]
            await conn.execute("UPDATE llm_categories SET routes = $2 WHERE name = $1", cat, routes)
        for cat, cap in (preset.get("budgets") or {}).items():
            await conn.execute("UPDATE llm_categories SET budget_usd = $2 WHERE name = $1", cat, cap)
    await _set_kv("composition:preset", name)
    if preset.get("stt"):
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
        raise CompositionError("Qdrant (memori) dan n8n (otomasi) adalah inti JARVIS dan tidak bisa diganti atau dimatikan")
    unknown = set(changes) - {"categories", "stt", "strong_mode", "budget_total"}
    if unknown:
        raise CompositionError(f"field tidak dikenal: {', '.join(sorted(unknown))}")
    cats = await gateway.categories()
    for name, c in (changes.get("categories") or {}).items():
        if name not in cats:
            raise CompositionError(f"kategori tidak dikenal: {name}")
        if name in LOCKED:
            raise CompositionError(f"kategori {name} tidak bisa diubah")
        if "routes" in c:
            await db.pool().execute("UPDATE llm_categories SET routes = $2 WHERE name = $1",
                                    name, await _validate_routes(c["routes"]))
        for knob, top in (("paid_attempt_limit", 5), ("max_retries", 5)):
            if knob in c:
                if not isinstance(c[knob], int) or not 0 <= c[knob] <= top:
                    raise CompositionError(f"{knob} harus bilangan bulat 0–{top}")
                await db.pool().execute(f"UPDATE llm_categories SET {knob} = $2 WHERE name = $1", name, c[knob])
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
    if "budget_total" in changes:
        await set_total_budget(changes["budget_total"], actor)
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
    """Hermes on a cloud model gets everything eager (ADR-031); the lean prompt was for the local CPU model, now gone (ADR-080). Pure."""
    return "full" if web_route_is_cloud else "lean"


async def sync_hermes_profile(actor: str) -> str | None:
    """Follow the composition: when Hermes' model moves between the local CPU and the cloud, switch its
    profile (jarvis-admin writes .env; jarvis-apply recreates only Hermes). Returns the new profile, if changed."""
    import httpx
    from .config import settings
    want = hermes_profile_for(True)
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


# ---------- changes by name (chat tool, phone picker) ----------

def _price_text(m: dict | None) -> str:
    if not m:
        return "harga tidak diketahui"
    return "gratis" if m["free"] else f"${m['price_in']:g} masuk / ${m['price_out']:g} keluar per 1 juta token"


async def _probe(model: str) -> str | None:
    """One small REAL request to the model: the catalog lists models that OpenRouter then refuses (a ':free' one
    "only for agentic harnesses" → HTTP 403 on every chat turn, which sent JARVIS to the slow local model).
    Returns the reason when the model is refused outright, None when it works or cannot be judged (no credit,
    rate limit, network)."""
    import httpx
    from .config import settings
    if not settings.openrouter_api_key:
        return None
    try:
        async with httpx.AsyncClient(timeout=45) as c:
            r = await c.post("https://openrouter.ai/api/v1/chat/completions",
                             headers={"Authorization": f"Bearer {settings.openrouter_api_key}"},
                             json={"model": model, "messages": [{"role": "user", "content": "Balas satu kata: siap"}], "max_tokens": 200})
        if r.status_code in (400, 403, 404, 422):
            msg = str((r.json().get("error") or {}).get("message") or r.text)[:160]
            return f"OpenRouter menolak model ini (HTTP {r.status_code}): {msg}"
    except (httpx.HTTPError, ValueError):
        pass
    return None


async def set_model(category: str, model: str, actor: str, *, provider: str = OR, role: str = "utama",
                    confirmed: bool = False) -> dict:
    """Make `model` the main (role 'utama') or a fallback ('cadangan') of one category; the rest of its chain stays.
    Returns what changed in words, or {"needs_confirmation": True, "say": …} for a costly model."""
    cats = await gateway.categories()
    category = category.strip().lower()
    if category not in cats:
        raise CompositionError(f"kategori tidak dikenal: {category} (ada: {', '.join(sorted(cats))})")
    if category in LOCKED:
        raise CompositionError(f"kategori {category} tidak bisa diubah")
    model = model.strip()
    info = None
    if provider == OR:
        models = await openrouter.catalog()
        if models is not None:
            info = openrouter.get(models, model)
            if not info:
                hint = openrouter.closest(models, model)
                raise CompositionError(f"model {model} tidak ada di OpenRouter" + (f" — maksudmu {', '.join(hint)}?" if hint else ""))
            if category in NEEDS_TOOLS and not info["tools"]:
                raise CompositionError(f"{info['name']} tidak bisa memakai alat (tool calling), jadi tidak cocok untuk {category}")
            if category in NEEDS_VISION and not info["vision"]:
                raise CompositionError(f"{info['name']} tidak bisa melihat gambar, jadi tidak cocok untuk {category}")
            if info["price_out"] > EXPENSIVE_OUT_USD and not confirmed:
                return {"needs_confirmation": True,
                        "say": f"{info['name']} mahal ({_price_text(info)}). Tetap pakai untuk {category}?"}
    elif provider not in await gateway.providers():
        raise CompositionError(f"penyedia tidak dikenal: {provider}")
    if provider == OR and (problem := await _probe(model)):
        raise CompositionError(problem)
    old = cats[category]["routes"] or []
    entry = {"provider": provider, "model": model}
    rest = [x for x in old if x != entry]
    routes = ([entry] + rest if role != "cadangan" else rest[:1] + [entry] + rest[1:])[:4]
    await update({"categories": {category: {"routes": routes}}}, actor)
    return {"category": category, "main": routes[0]["model"], "chain": [x["model"] for x in routes],
            "price": _price_text(info)}


async def set_total_budget(usd: float, actor: str) -> float:
    if not isinstance(usd, (int, float)) or not 0 < usd <= 1000:
        raise CompositionError("anggaran bulanan harus antara $0 dan $1000")
    await _set_kv("budget:total", float(usd))
    from . import budget
    budget.forget()
    await audit.record(actor, "composition.budget", None, total=float(usd))
    return float(usd)


async def set_daily_budget(usd: float | None, actor: str) -> float | None:
    """Optional daily cap; when today's spend reaches it, paid models stop until tomorrow (None removes it)."""
    if usd is not None and (not isinstance(usd, (int, float)) or not 0 < usd <= 1000):
        raise CompositionError("anggaran harian harus antara $0 dan $1000 (kosong = tanpa batas harian)")
    await _set_kv("budget:daily", float(usd) if usd else 0)
    from . import budget
    budget.forget()
    await audit.record(actor, "composition.budget_daily", None, daily=usd)
    return float(usd) if usd else None


async def set_task_budget(usd: float, actor: str) -> float:
    """Default budget each new task starts with (per-task cap, blueprint §5)."""
    if not isinstance(usd, (int, float)) or not 0 < usd <= 100:
        raise CompositionError("anggaran per tugas harus antara $0 dan $100")
    await _set_kv("budget:task_default", float(usd))
    await audit.record(actor, "composition.budget_task", None, task=float(usd))
    return float(usd)


async def create_category(name: str, title: str, description: str, model: str, actor: str, provider: str = OR) -> dict:
    """A new kind of work with its own model (e.g. "terjemahan"), so Hermes and the agent are never stuck on
    "this was never set up". Workers can use it straight away (workers.spawn reads worker categories)."""
    name = name.strip().lower()
    if not re.fullmatch(r"[a-z][a-z0-9-]{2,24}", name):
        raise CompositionError("nama kategori: huruf kecil/angka/strip, 3–25 karakter")
    if name in await gateway.categories():
        raise CompositionError(f"kategori {name} sudah ada")
    routes = await _validate_routes([{"provider": provider, "model": model}])
    await db.pool().execute(
        """INSERT INTO llm_categories (name, title, description, routes, allow_free, confirm_cloud, worker, sort)
           VALUES ($1, $2, $3, $4, true, false, true, 200)""", name, (title.strip() or name)[:60], description.strip()[:200], routes)
    gateway.invalidate()
    await audit.record(actor, "composition.category_created", None, name=name, model=model)
    return {"category": name, "main": model}


async def delete_category(name: str, actor: str) -> bool:
    name = name.strip().lower()
    if name in BUILTIN:
        raise CompositionError("kategori bawaan tidak bisa dihapus (hanya diganti modelnya)")
    done = (await db.pool().execute("DELETE FROM llm_categories WHERE name = $1", name)).endswith(" 1")
    if done:
        gateway.invalidate()
        await audit.record(actor, "composition.category_deleted", None, name=name)
    return done


async def summary() -> dict:
    """The whole composition in a few lines — what the chat agent shows the owner and reasons from."""
    c = await get()
    models = await openrouter.catalog() or []
    out = []
    for cat in c["categories"]:
        chain = []
        for x in cat["routes"]:
            info = openrouter.get(models, x["model"]) if x["provider"] == OR else None
            chain.append(x["model"] + (f" ({_price_text(info)})" if info else "" if x["provider"] == OR else ""))
        out.append({"kategori": cat["name"], "model": chain or ["(belum ada model — pilih di Komposisi AI)"],
                    **({"anggaran": cat["budget_usd"]} if cat["budget_usd"] is not None else {}),
                    **({"terkunci": "tidak bisa diubah"} if cat["locked"] else {})})
    from . import billing
    verdict = await billing.verdict()
    return {"preset": c["preset"], "kategori": out, "suara": c["stt"]["engine"], "mode_kuat": c["strong_mode"],
            "anggaran_bulan_ini": c["budget"], "openrouter": verdict["text"],
            "inti_permanen": CORE}


async def check_openrouter(actor: str) -> dict:
    """Is the key alive, what is left, and does a real call work now? (also forgets the cached 'exhausted' state)"""
    import httpx
    from . import billing
    from .config import settings
    billing.forget_cache()
    gateway.invalidate()
    if not settings.openrouter_api_key:
        return {"key": False, "say": "Belum ada API key OpenRouter (isi di Lainnya → Pengaturan server)."}
    out: dict = {"key": True}
    try:
        async with httpx.AsyncClient(timeout=15) as c:
            k = (await c.get("https://openrouter.ai/api/v1/key",
                             headers={"Authorization": f"Bearer {settings.openrouter_api_key}"})).json().get("data", {})
        out |= {"batas_key_usd": k.get("limit"), "sisa_batas_key_usd": k.get("limit_remaining"),
                "terpakai_usd": k.get("usage"), "akun_gratis": k.get("is_free_tier")}
    except (httpx.HTTPError, ValueError):
        out["error"] = "OpenRouter tidak terjangkau"
    bal = await billing.balance()
    if bal:
        out["kredit_menurut_openrouter_usd"], out["saldo_menurut_openrouter_usd"] = bal["credits"], bal["remaining"]
    import time
    # A PAID model is the real test (free ones answer even with no credit): the chat's own paid model, else a cheap one.
    chain = (await gateway.categories()).get("ngobrol", {}).get("routes") or []
    model = next((x["model"] for x in chain if x["provider"] == OR and not x["model"].endswith(":free")), "qwen/qwen3.7-flash")
    t0, ok, err, cost = time.monotonic(), False, None, 0.0
    try:
        async with httpx.AsyncClient(timeout=60) as c:
            r = await c.post("https://openrouter.ai/api/v1/chat/completions",
                             headers={"Authorization": f"Bearer {settings.openrouter_api_key}"},
                             json={"model": model, "messages": [{"role": "user", "content": "Balas satu kata: siap"}], "max_tokens": 400})  # as big as a real chat turn: OpenRouter checks affordability against max_tokens
        body = r.json()
        ok = r.status_code == 200 and "choices" in body
        cost = float((body.get("usage") or {}).get("cost") or 0)
        err = None if ok else f"HTTP {r.status_code}: {str(body.get('error', {}).get('message', ''))[:160]}"
    except (httpx.HTTPError, ValueError) as e:
        err = f"{type(e).__name__}"
    ms = int((time.monotonic() - t0) * 1000)
    await db.pool().execute(  # so the health verdict (billing.verdict) sees this call
        """INSERT INTO llm_usage (category, caller, provider, model, cost_usd, latency_ms, ok, error)
           VALUES ('test', 'test', 'openrouter', $1, $2, $3, $4, $5)""", model, cost, ms, ok, err)
    out["tes_model_berbayar"] = {"model": model, "ok": ok, "ms": ms, **({"biaya_usd": cost} if ok else {"error": err})}
    out["kesimpulan"] = (f"OpenRouter berfungsi: {model} menjawab dalam {ms} ms." if ok else
                         f"OpenRouter belum bisa dipakai untuk model berbayar: {err}. Cek bahwa kredit masuk ke akun/workspace "
                         "yang sama dengan API key ini (openrouter.ai/settings/credits).")
    await audit.record(actor, "composition.check_openrouter", None)
    return out
