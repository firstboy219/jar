"""LLM gateway: every model call in JARVIS goes through here (ADR-017).

The owner composes JARVIS per category (ngobrol, coding, web, …) from the APK; each category has an
ordered list of routes (provider + model). For one call the gateway
  1. drops routes it may not use: provider disabled or without a key, cloud for private content,
     ':free' models where the category forbids them (free providers may log prompts);
  2. lets the budget reorder them (budget.py): near the cap, free/local routes come first;
  3. tries them in order and fails over until the FIRST BYTE (any HTTP error, timeout) — once a
     stream has started it is passed through unchanged, tool calls and images included;
  4. always ends with the local model, so JARVIS keeps answering with no key or no credit;
  5. records tokens, cache hits, cost and latency in llm_usage.
Hermes reaches the same logic over HTTP: /llm/v1/chat/completions with model "jarvis-<category>".
"""

import asyncio
import json
import logging
import os
import re
import time
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass

import httpx

from . import db, modelrouter

log = logging.getLogger("jarvis-core.gateway")

LOCAL = "lokal"              # llama-chat: small context, answers the owner
LOCAL_WORKER = "lokal-kerja"  # llama-worker: 64k context for Hermes, lowest CPU priority
LOCAL_MODEL = "qwen-lokal"
ALIAS_PREFIX = "jarvis-"
# What every alias advertises to Hermes: it refuses models under 64k, and a fixed window also bounds
# how much history a cloud call can carry (compression starts at half of it).
CONTEXT_LENGTH = 65_536
# Time to the first byte. A local CPU model reading Hermes' ~15k-token prompt needs many minutes.
FIRST_BYTE_S = {"cloud": 90.0, "local-chat": 300.0, "local-worker": 3600.0}
# Callers with their own OpenRouter key (owner sets per-key limits on openrouter.ai); others share LATAR.
CALLER_KEYS = {"chat": "OPENROUTER_KEY_CHAT", "hermes": "OPENROUTER_KEY_HERMES"}


class GatewayError(RuntimeError):
    pass


@dataclass(frozen=True)
class Route:
    provider: str
    model: str
    base_url: str
    key: str
    cloud: bool
    vision: bool

    @property
    def free(self) -> bool:
        return self.model.endswith(":free") or self.model == "openrouter/free"  # the free router never bills

    @property
    def label(self) -> str:
        return f"{self.provider}/{self.model}"

    def public(self) -> dict:
        return {"provider": self.provider, "model": self.model, "cloud": self.cloud, "free": self.free}


# When every model the owner chose for a category fails, a cheap cloud model answers BEFORE the slow local one
# (a dead pick used to mean minutes on the CPU for every message). The owner can change it (composition:safety_model).
SAFETY_MODEL = "deepseek/deepseek-v4-flash"
BAD_FOR_S = 600  # a model OpenRouter refuses outright (400/403/404/422) is skipped for 10 minutes
_bad: dict[tuple[str, str], float] = {}
_cache: dict = {"at": 0.0, "providers": {}, "categories": {}, "safety": SAFETY_MODEL}


def refused_outright(error_text: str) -> bool:
    """HTTP 400/403/404/422 from a provider = this model will not work (not a passing hiccup like 402/429/5xx). Pure."""
    m = re.match(r".*?HTTP (\d{3})", error_text or "")
    return bool(m) and int(m.group(1)) in (400, 403, 404, 422)


def _mark_failed(route: "Route", error_text: str) -> None:
    if route.cloud and refused_outright(error_text):
        _bad[(route.provider, route.model)] = time.monotonic() + BAD_FOR_S


def _is_bad(route: "Route") -> bool:
    until = _bad.get((route.provider, route.model))
    return bool(until and until > time.monotonic())


async def _load(force: bool = False) -> None:
    if not force and time.monotonic() - _cache["at"] < 15:
        return
    providers = {r["name"]: dict(r) for r in await db.pool().fetch("SELECT * FROM llm_providers")}
    categories = {r["name"]: dict(r) for r in await db.pool().fetch("SELECT * FROM llm_categories ORDER BY sort")}
    safety = await db.pool().fetchval("SELECT value FROM settings_kv WHERE key = 'composition:safety_model'")
    _cache.update(at=time.monotonic(), providers=providers, categories=categories,
                  safety=safety if isinstance(safety, str) and safety else SAFETY_MODEL)


def invalidate() -> None:
    _cache["at"] = 0.0


async def providers() -> dict[str, dict]:
    await _load()
    return _cache["providers"]


async def categories() -> dict[str, dict]:
    await _load()
    return _cache["categories"]


def provider_key(provider: dict, caller: str = "") -> str:
    env = provider.get("key_env") or ""
    if not env:
        return ""
    if env == "OPENROUTER_API_KEY":
        specific = CALLER_KEYS.get(caller, "OPENROUTER_KEY_LATAR")
        return os.getenv(specific, "").strip() or os.getenv(env, "").strip()
    return os.getenv(env, "").strip()


async def _arrange(category: str, routes: list, cat: dict, provs: dict, caller: str) -> list:
    """modelrouter: no free model for sensitive content, sick models last, proven free alternatives (ADR-040)."""
    p = provs.get("openrouter")

    def make(model: str):
        key = provider_key(p, caller) if p and p["enabled"] else ""
        return Route(p["name"], model, p["base_url"].rstrip("/"), key, True, p["vision"]) if key else None
    return await modelrouter.arrange(routes, make=make, needs_tools=category in modelrouter.NEEDS_TOOLS,
                                     allow_free=bool(cat.get("allow_free")), no_free=modelrouter.NO_FREE.get())


def _safety_route(provs: dict, caller: str, category: str, private: bool) -> "Route | None":
    p = provs.get("openrouter")
    if private or category in ("privat", "penglihatan") or not p or not p["enabled"] or not provider_key(p, caller):
        return None
    return Route(p["name"], _cache.get("safety") or SAFETY_MODEL, p["base_url"].rstrip("/"), provider_key(p, caller), True, False)


def has_key(provider: dict) -> bool:
    return not provider.get("key_env") or bool(provider_key(provider, "chat") or provider_key(provider, "latar"))


def _local_route(provider: dict | None) -> Route | None:
    if not provider:
        return None
    return Route(provider["name"], LOCAL_MODEL, provider["base_url"].rstrip("/"), "", False, provider["vision"])


async def plan(category: str, *, caller: str = "core", private: bool = False, worker: bool = False) -> list[Route]:
    """Routes to try for one call, in order; never empty (the local model closes the list)."""
    from . import budget
    await _load()
    provs, cats = _cache["providers"], _cache["categories"]
    cat = cats.get(category) or cats.get("web") or {"routes": [], "allow_free": False}
    routes: list[Route] = []
    for r in [] if private else (cat.get("routes") or []):
        p = provs.get(str(r.get("provider") or ""))
        if not p or not p["enabled"]:
            continue
        key = provider_key(p, caller)
        if p["key_env"] and not key:
            continue  # no key yet: skip silently, the next route (eventually local) answers
        route = Route(p["name"], str(r.get("model") or LOCAL_MODEL), p["base_url"].rstrip("/"), key, p["cloud"], p["vision"])
        if route.free and not cat.get("allow_free"):
            continue
        if route not in routes and not _is_bad(route):
            routes.append(route)
    if not private:
        routes = await _arrange(category, routes, cat, provs, caller)
    net = _safety_route(provs, caller, category, private)
    if net and net not in routes and not _is_bad(net):
        first_local = next((i for i, r in enumerate(routes) if not r.cloud), len(routes))
        routes.insert(first_local, net)
    routes = await budget.adjust(category, routes)
    # A local route the owner chose keeps its place; otherwise the matching local model is the last resort.
    if not any(not r.cloud for r in routes):
        fallback = _local_route(provs.get(LOCAL_WORKER if worker else LOCAL))
        if fallback:
            routes.append(fallback)
    if not routes:
        raise GatewayError("tidak ada model yang bisa dipakai")
    return routes


# ---------- request shaping ----------

def has_image(messages: list[dict]) -> bool:
    return any(isinstance(m.get("content"), list) and any(p.get("type") == "image_url" for p in m["content"]
                                                          if isinstance(p, dict)) for m in messages)


def _strip_images(messages: list[dict]) -> list[dict]:
    """For text-only models: keep the words, say an image was there (the main agent describes it)."""
    out = []
    for m in messages:
        c = m.get("content")
        if isinstance(c, list):
            parts = [p.get("text", "") if p.get("type") == "text" else "[gambar terlampir — model ini tidak bisa melihat gambar]"
                     for p in c if isinstance(p, dict)]
            m = {**m, "content": "\n".join(p for p in parts if p)}
        out.append(m)
    return out


def _cache_breakpoint(messages: list[dict]) -> list[dict]:
    """Anthropic caches only up to an explicit breakpoint: mark the end of the (static) system prompt."""
    out, marked = [], False
    for m in messages:
        if not marked and m.get("role") == "system" and isinstance(m.get("content"), str) and len(m["content"]) > 4000:
            m = {**m, "content": [{"type": "text", "text": m["content"], "cache_control": {"type": "ephemeral"}}]}
            marked = True
        out.append(m)
    return out


def _prepare(body: dict, route: Route, session_id: str | None) -> tuple[dict, dict]:
    b = {k: v for k, v in body.items() if k not in ("model", "stream_options")}
    b["model"] = route.model
    if b.get("stream"):
        b["stream_options"] = {"include_usage": True}
    headers = {"Content-Type": "application/json"}
    if route.key:
        headers["Authorization"] = f"Bearer {route.key}"
    if "openrouter.ai" in route.base_url:
        b["usage"] = {"include": True}
        headers.update({"HTTP-Referer": "https://vis1.cosger.online", "X-Title": "JARVIS"})
        if session_id:  # keeps follow-up calls on the same provider, so its prompt cache keeps hitting
            headers["x-session-id"] = session_id[:128]
        if route.model.startswith("anthropic/"):
            b["messages"] = _cache_breakpoint(b["messages"])
    else:
        for k in ("reasoning", "usage", "provider", "models", "transforms"):
            b.pop(k, None)
    if not route.cloud:
        b["cache_prompt"] = True  # reuse the KV cache of the shared prompt prefix
        b["chat_template_kwargs"] = {**(b.get("chat_template_kwargs") or {}), "enable_thinking": False}
    if not route.vision:
        b["messages"] = _strip_images(b["messages"])
    return b, headers


# ---------- cost ----------

_prices: dict = {"at": 0.0, "models": {}}


async def _price(model: str) -> tuple[float, float, float]:
    """(prompt, completion, cache read) USD per token from OpenRouter's public list (cached 6 h)."""
    if time.monotonic() - _prices["at"] > 6 * 3600 or not _prices["models"]:
        try:
            async with httpx.AsyncClient(timeout=15) as c:
                r = await c.get("https://openrouter.ai/api/v1/models")
            _prices["models"] = {m["id"]: m.get("pricing") or {} for m in r.json()["data"]}
            _prices["at"] = time.monotonic()
        except (httpx.HTTPError, KeyError, ValueError):
            _prices["at"] = time.monotonic() - 5 * 3600  # retry in an hour
    p = _prices["models"].get(model) or {}

    def f(k: str) -> float:
        try:
            return float(p.get(k) or 0)
        except ValueError:
            return 0.0
    return f("prompt"), f("completion"), f("input_cache_read") or f("prompt")


async def cost_of(route: Route, usage: dict) -> float:
    if not route.cloud or route.free:
        return 0.0
    if isinstance(usage.get("cost"), (int, float)):
        return float(usage["cost"])
    pin, pout, pcache = await _price(route.model)
    cached = int(((usage.get("prompt_tokens_details") or {}).get("cached_tokens")) or 0)
    prompt = int(usage.get("prompt_tokens") or 0)
    return (prompt - cached) * pin + cached * pcache + int(usage.get("completion_tokens") or 0) * pout


async def _record(route: Route, category: str, caller: str, usage: dict, started: float,
                  first_ms: int | None, ok: bool, error: str | None, session_id: str | None,
                  extra: dict | None = None) -> None:
    extra = extra or {}
    try:
        cost = await cost_of(route, usage) if ok else 0.0
        await db.pool().execute(
            """INSERT INTO llm_usage (category, caller, provider, model, prompt_tokens, cached_tokens,
                   completion_tokens, cost_usd, latency_ms, first_token_ms, ok, error, session_id,
                   task_id, retry, fallback_reason)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16)""",
            category, caller, route.provider, route.model, usage.get("prompt_tokens"),
            (usage.get("prompt_tokens_details") or {}).get("cached_tokens"), usage.get("completion_tokens"),
            cost, int((time.monotonic() - started) * 1000), first_ms,
            ok, (error or "")[:300] or None, (session_id or "")[:128] or None,
            extra.get("task_id"), extra.get("retry") or 0, (extra.get("fallback_reason") if ok else None))
        if extra.get("task_id"):  # the task manager's live picture: what it cost, which model did the work
            await db.pool().execute(
                """UPDATE tasks SET cost_usd = cost_usd + $2, model_used = CASE WHEN $3 THEN $4 ELSE model_used END,
                          retries = greatest(retries, $5) WHERE id = $1""",
                extra["task_id"], cost, ok, route.model, extra.get("retry") or 0)
    except Exception:
        log.exception("usage not recorded")


def _client(timeout: httpx.Timeout) -> httpx.AsyncClient:
    """One HTTP client per call (tests replace this with a mock transport)."""
    return httpx.AsyncClient(timeout=timeout)


def _timeout(route: Route, worker: bool) -> httpx.Timeout:
    read = FIRST_BYTE_S["cloud"] if route.cloud else FIRST_BYTE_S["local-worker" if worker else "local-chat"]
    return httpx.Timeout(connect=10, read=read, write=60, pool=10)


async def _next_data(lines) -> dict | None:
    """Next JSON payload of an SSE stream; None at the end."""
    async for line in lines:
        if not line.startswith("data:"):
            continue
        data = line[5:].strip()
        if data == "[DONE]":
            return None
        if data:
            try:
                return json.loads(data)
            except ValueError:
                continue
    return None


# ---------- local prompt cache that survives restarts ----------
# Hermes' ~20k-token prompt prefix takes ~1 h to read on this CPU the first time, then ~seconds when
# cached. llama-server can save a slot's KV cache to disk; we save it after Hermes work and restore it
# when llama-worker starts, so a restart does not cost that hour again.
SLOT_FILE = "hermes-prefix.bin"
SLOT_MIN_TOKENS = 4000
_slot_saved_at = 0.0


async def save_worker_slot() -> None:
    global _slot_saved_at
    if time.monotonic() - _slot_saved_at < 600:
        return
    _slot_saved_at = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=120) as c:
            await c.post("http://llama-worker:8080/slots/0?action=save", json={"filename": SLOT_FILE})
    except httpx.HTTPError as e:
        log.debug("slot save failed: %s", e)


async def restore_worker_slot() -> bool:
    try:
        async with httpx.AsyncClient(timeout=300) as c:
            r = await c.post("http://llama-worker:8080/slots/0?action=restore", json={"filename": SLOT_FILE})
        return r.status_code == 200
    except httpx.HTTPError:
        return False


def _note_exhausted(route: Route, status: int, text: str) -> None:
    from . import billing
    if route.provider == "openrouter" and (status == 402 or billing.is_exhausted(text)):
        asyncio.create_task(billing.notify_exhausted())


# ---------- calls ----------

# AI calls in progress, by who asked — the phone's home screen shows what the CPU is spent on (ops.who)
_inflight: dict[int, dict] = {}
_seq = iter(range(1, 1 << 62))


def inflight() -> list[dict]:
    return list(_inflight.values())


VOLATILE_MARK = "\n\nActive Hermes profile:"


def hoist_volatile(body: dict) -> dict:
    """Hermes ends its system prompt with per-session lines ("Conversation started: <date>", "Model:
    jarvis-<category>", runtime). The chat template puts the tool schemas AFTER the system text, so those
    lines made every new session re-read ~6k tokens of unchanged tools on the CPU (ADR-031). Move them to
    the start of the first user message: system text + tools become one prefix shared by all sessions.
    Pure; unit-tested."""
    msgs = body.get("messages") or []
    if not msgs or msgs[0].get("role") != "system" or not isinstance(msgs[0].get("content"), str):
        return body
    sysm = msgs[0]["content"]
    i = sysm.find(VOLATILE_MARK)
    first_user = next((k for k, m in enumerate(msgs) if m.get("role") == "user"), None)
    if i < 0 or first_user is None:
        return body
    tail = "[Konteks sesi]\n" + sysm[i:].strip() + "\n\n"
    user = dict(msgs[first_user])
    c = user.get("content")
    if isinstance(c, str):
        user["content"] = tail + c
    elif isinstance(c, list):
        user["content"] = [{"type": "text", "text": tail}, *c]
    else:
        return body
    new = list(msgs)
    new[0] = {**msgs[0], "content": sysm[:i]}
    new[first_user] = user
    return {**body, "messages": new}


async def stream(category: str, body: dict, *, caller: str, session_id: str | None = None, private: bool = False,
                 worker: bool = False, on_route: Callable[[Route], None] | None = None) -> AsyncIterator[dict]:
    key = next(_seq)
    _inflight[key] = {"caller": caller, "category": category, "since": time.time()}
    if caller == "hermes":
        body = hoist_volatile(body)
    try:
        async for chunk in _stream(category, body, caller=caller, session_id=session_id, private=private,
                                   worker=worker, on_route=on_route, _key=key):
            yield chunk
    finally:
        _inflight.pop(key, None)


async def _stream(category: str, body: dict, *, caller: str, session_id: str | None = None, private: bool = False,
                  worker: bool = False, on_route: Callable[[Route], None] | None = None, _key: int = 0) -> AsyncIterator[dict]:
    """Yield OpenAI `chat.completion.chunk` dicts from the first route that starts answering."""
    body = {**body, "stream": True}
    errors: list[str] = []
    att = await modelrouter.Attempts.start(_cache["categories"].get(category), session_id, body if caller == "hermes" else None)
    queue = list(await plan(category, caller=caller, private=private, worker=worker))
    while queue:
        route = queue.pop(0)
        if why := att.skip(route):
            errors.append(f"{route.label}: dilewati ({why})")
            att.note(why)
            continue
        att.begin(route)
        if _key in _inflight:
            _inflight[_key]["provider"] = route.provider
        b, headers = _prepare(body, route, session_id)
        started = time.monotonic()
        client = _client(_timeout(route, worker))
        resp = None
        try:
            resp = await client.send(client.build_request("POST", f"{route.base_url}/chat/completions",
                                                          json=b, headers=headers), stream=True)
            if resp.status_code != 200:
                text = (await resp.aread()).decode(errors="replace")[:300]
                _note_exhausted(route, resp.status_code, text)
                raise GatewayError(f"HTTP {resp.status_code}: {text}")
            lines = resp.aiter_lines()
            chunk = await _next_data(lines)
            if chunk is None:
                raise GatewayError("jawaban kosong")
            if chunk.get("error") and not chunk.get("choices"):
                raise GatewayError(str(chunk["error"])[:300])
        except (httpx.HTTPError, GatewayError) as e:
            err = f"{route.label}: {e if isinstance(e, GatewayError) else type(e).__name__}"
            errors.append(err)
            log.warning("route failed, trying next: %s", err)
            _mark_failed(route, err)
            if resp is not None:
                await resp.aclose()
            await client.aclose()
            retry = att.failed(route, err)
            await _record(route, category, caller, {}, started, None, False, err, session_id, att.extra())
            if retry:
                await asyncio.sleep(modelrouter.RETRY_DELAY_S)
                queue.insert(0, route)
            continue
        # Committed: from here on the stream is passed through as is.
        first_ms = int((time.monotonic() - started) * 1000)
        if on_route:
            on_route(route)
        usage: dict = {}
        ok, err = True, None
        try:
            while chunk is not None:
                if chunk.get("usage"):
                    usage = chunk["usage"]
                if chunk.get("error") and not chunk.get("choices"):
                    ok, err = False, str(chunk["error"])[:300]
                    raise GatewayError(f"{route.label} berhenti di tengah jalan: {err}")
                yield chunk
                chunk = await _next_data(lines)
        except httpx.HTTPError as e:
            ok, err = False, type(e).__name__
            raise GatewayError(f"{route.label} terputus ({err})") from e
        except BaseException as e:  # caller stopped reading (client gone) or cancelled
            if ok:
                ok, err = False, f"dihentikan ({type(e).__name__})"
            raise
        finally:
            await resp.aclose()
            await client.aclose()
            await _record(route, category, caller, usage, started, first_ms, ok, err, session_id, att.extra())
            if ok and route.provider == LOCAL_WORKER and caller == "hermes" and (usage.get("prompt_tokens") or 0) >= SLOT_MIN_TOKENS:
                # only Hermes' own long prompt is worth keeping on disk: a small call saved here once replaced
                # the 22k-token Hermes prefix with 279 tokens, and every restore then forced a full re-read
                asyncio.create_task(save_worker_slot())
        return
    raise GatewayError("semua model gagal: " + " | ".join(errors))


async def complete(category: str, body: dict, *, caller: str, session_id: str | None = None,
                   private: bool = False, worker: bool = False) -> dict:
    key = next(_seq)
    _inflight[key] = {"caller": caller, "category": category, "since": time.time()}
    if caller == "hermes":
        body = hoist_volatile(body)
    try:
        return await _complete(category, body, caller=caller, session_id=session_id, private=private, worker=worker, _key=key)
    finally:
        _inflight.pop(key, None)


async def _complete(category: str, body: dict, *, caller: str, session_id: str | None = None,
                    private: bool = False, worker: bool = False, _key: int = 0) -> dict:
    """Non-streaming call with the same routing and failover; returns the OpenAI response JSON."""
    body = {**body, "stream": False}
    errors: list[str] = []
    att = await modelrouter.Attempts.start(_cache["categories"].get(category), session_id, body if caller == "hermes" else None)
    queue = list(await plan(category, caller=caller, private=private, worker=worker))
    while queue:
        route = queue.pop(0)
        if why := att.skip(route):
            errors.append(f"{route.label}: dilewati ({why})")
            att.note(why)
            continue
        att.begin(route)
        if _key in _inflight:
            _inflight[_key]["provider"] = route.provider
        b, headers = _prepare(body, route, session_id)
        started = time.monotonic()
        try:
            async with _client(_timeout(route, worker)) as c:
                r = await c.post(f"{route.base_url}/chat/completions", json=b, headers=headers)
            if r.status_code != 200:
                _note_exhausted(route, r.status_code, r.text[:300])
                raise GatewayError(f"HTTP {r.status_code}: {r.text[:300]}")
            data = r.json()
            if data.get("error") and not data.get("choices"):
                raise GatewayError(str(data["error"])[:300])
        except (httpx.HTTPError, GatewayError, ValueError) as e:
            err = f"{route.label}: {e if isinstance(e, GatewayError) else type(e).__name__}"
            errors.append(err)
            _mark_failed(route, err)
            retry = att.failed(route, err)
            await _record(route, category, caller, {}, started, None, False, err, session_id, att.extra())
            if retry:  # a passing hiccup (5xx/network): the same model once more before moving on
                await asyncio.sleep(modelrouter.RETRY_DELAY_S)
                queue.insert(0, route)
            continue
        await _record(route, category, caller, data.get("usage") or {}, started, None, True, None, session_id, att.extra())
        data["jarvis_route"] = route.public()
        return data
    raise GatewayError("semua model gagal: " + " | ".join(errors))


def category_of_alias(model: str) -> str:
    """'jarvis-coding' → 'coding'; a bare category name is accepted too."""
    return model.removeprefix(ALIAS_PREFIX) if model else "web"


async def model_list() -> list[dict]:
    """OpenAI /v1/models for Hermes: one alias per category, with a context length it accepts."""
    cats = await categories()
    return [{"id": ALIAS_PREFIX + name, "object": "model", "owned_by": "jarvis",
             "context_length": CONTEXT_LENGTH, "description": c["description"]} for name, c in cats.items()]
