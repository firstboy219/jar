"""OpenRouter's model catalog, so the owner PICKS a model instead of typing its id (ADR-038).

GET https://openrouter.ai/api/v1/models is public (no key): ~470 models with price, context length, input
modalities and supported parameters. Cached for an hour; when OpenRouter cannot be reached the stale copy is
used, and with no copy at all ids are accepted unchecked (a typo then fails at the first call and falls back).
Prices are per 1 million tokens, in USD.
"""

import difflib
import logging
import time

import httpx

log = logging.getLogger("jarvis-core.openrouter")
URL = "https://openrouter.ai/api/v1/models"
TTL_S = 3600
SORTS = ("termurah", "terbaru", "konteks", "nama")
_cache: dict = {"at": 0.0, "models": None}


def _per_million(value) -> float:
    try:
        return round(float(value) * 1_000_000, 4)
    except (TypeError, ValueError):
        return 0.0


def normalize(raw: dict) -> dict:
    """One catalog entry in the shape the app and the agent use. Pure; unit-tested."""
    arch = raw.get("architecture") or {}
    pricing = raw.get("pricing") or {}
    inputs = arch.get("input_modalities") or []
    mid = str(raw.get("id") or "")
    price_in, price_out = _per_million(pricing.get("prompt")), _per_million(pricing.get("completion"))
    return {
        "id": mid, "name": str(raw.get("name") or mid), "context": int(raw.get("context_length") or 0),
        "price_in": price_in, "price_out": price_out,
        "free": mid.endswith(":free") or (price_in == 0 and price_out == 0),
        "tools": "tools" in (raw.get("supported_parameters") or []),
        "vision": "image" in inputs, "audio": "audio" in inputs,
        "created": int(raw.get("created") or 0),
        "reasoning": "reasoning" in (raw.get("supported_parameters") or []),
        "reasoning_forced": bool((raw.get("reasoning") or {}).get("mandatory")),
        "expires": str(raw.get("expiration_date") or "")[:10] or None,
        "description": " ".join(str(raw.get("description") or "").split())[:200],
    }


async def catalog(force: bool = False) -> list[dict] | None:
    """All models (None when never fetched and OpenRouter is unreachable)."""
    if not force and _cache["models"] is not None and time.monotonic() - _cache["at"] < TTL_S:
        return _cache["models"]
    try:
        async with httpx.AsyncClient(timeout=20) as c:
            r = await c.get(URL)
        r.raise_for_status()
        _cache.update(models=[normalize(m) for m in r.json()["data"] if m.get("id")], at=time.monotonic())
    except (httpx.HTTPError, KeyError, ValueError) as e:
        log.warning("OpenRouter catalog not refreshed: %s", e)
    return _cache["models"]


def search(models: list[dict], query: str = "", *, free: bool | None = None, vision: bool | None = None,
           tools: bool | None = None, max_price_out: float | None = None, sort: str = "termurah",
           limit: int = 40) -> list[dict]:
    """Filter + sort the catalog. query: every word must appear in the id or name. Pure; unit-tested."""
    words = query.lower().split()
    out = []
    for m in models:
        hay = f"{m['id']} {m['name']}".lower()
        if words and not all(w in hay for w in words):
            continue
        if free is not None and m["free"] != free:
            continue
        if vision is not None and m["vision"] != vision:
            continue
        if tools is not None and m["tools"] != tools:
            continue
        if max_price_out is not None and m["price_out"] > max_price_out:
            continue
        out.append(m)
    key = {"termurah": lambda m: (m["price_in"] + m["price_out"], m["id"]), "terbaru": lambda m: (-m["created"], m["id"]),
           "konteks": lambda m: (-m["context"], m["id"]), "nama": lambda m: m["name"].lower()}.get(sort)
    return sorted(out, key=key or key_default)[:max(1, min(limit, 200))]


def key_default(m: dict):
    return (m["price_in"] + m["price_out"], m["id"])


def get(models: list[dict], model_id: str) -> dict | None:
    return next((m for m in models if m["id"] == model_id), None)


def closest(models: list[dict], model_id: str, n: int = 3) -> list[str]:
    """Ids that look like what was typed — for "tidak ada, maksudmu …?". Pure."""
    ids = [m["id"] for m in models]
    return difflib.get_close_matches(model_id, ids, n=n, cutoff=0.5) or [i for i in ids if model_id.split("/")[-1] in i][:n]


def short(m: dict) -> dict:
    """What the agent sees of a model (small: it all goes into a local model's context)."""
    return {"id": m["id"], "nama": m["name"], "harga_per_juta_token": f"${m['price_in']:g} masuk / ${m['price_out']:g} keluar"
            if not m["free"] else "gratis", "konteks": m["context"], "alat": m["tools"], "gambar": m["vision"]}
