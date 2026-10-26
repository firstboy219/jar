"""OpenJarvis as a heavy worker (Blueprint v4 Fase 2, ADR-043) — optional, off until the owner switches it on.

A separate container (service `openjarvis`, jarvis-network only) that JARVIS hands a task to over its OpenAI-compatible API
and that thinks through JARVIS' own LLM gateway (so the budget, the model rules and the usage log hold; /privat never goes
there). It can read and write files in its own work folder and run Python — nothing else: no JARVIS tools, no repo, no
memory. Hermes-Brain stays the default worker and the fallback: if OpenJarvis fails, or answers with something that is not
an answer (the spike showed it can end with the model's raw tool-call markup), the task is done by Hermes as if nothing happened.

Handover — in: the task text (starts with "[tugas #N]", which also ties the gateway's cost to the task) and the gateway
category; out: the answer text. The gateway key of this worker is good for worker categories only (never privat/ngobrol);
only its SHA-256 is stored (settings_kv 'worker:key:openjarvis'); the key itself lives in data/openjarvis/openjarvis.env.
"""

import hashlib
import hmac
import logging
import re
from pathlib import Path

import httpx

from . import db

log = logging.getLogger("jarvis-core.openjarvis")
URL = "http://jarvis-openjarvis:8765"
ENV_FILE = Path("/data/openjarvis/openjarvis.env")
TIMEOUT_S = 1500
KEY = "worker:key:openjarvis"
SETTING = "worker:openjarvis"
CALLER = "openjarvis"
# what a model emits when its tool calls were not parsed as tool calls: the run "finished" without doing the work
_RAW_MARKUP = re.compile(r"<[｜|]DSML[｜|]|<tool_call>|<function_calls>|<\|?tool_calls?")


class OpenJarvisError(RuntimeError):
    pass


async def enabled() -> bool:
    v = await db.pool().fetchval("SELECT value FROM settings_kv WHERE key = $1", SETTING)
    return bool(isinstance(v, dict) and v.get("enabled"))


async def set_enabled(on: bool) -> dict:
    await db.pool().execute(
        "INSERT INTO settings_kv (key, value) VALUES ($1, $2) ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value",
        SETTING, {"enabled": bool(on)})
    return await status()


def usable(text: str | None) -> tuple[bool, str]:
    """Is this an answer? Pure; unit-tested."""
    t = (text or "").strip()
    if len(t) < 20:
        return False, "jawaban kosong atau terlalu pendek"
    if _RAW_MARKUP.search(t):
        return False, "model mengirim panggilan alat sebagai teks mentah, tidak dijalankan"
    return True, ""


async def caller_for(key: str) -> str | None:
    """'openjarvis' when the bearer key is this worker's gateway key."""
    if not key:
        return None
    stored = await db.pool().fetchval("SELECT value FROM settings_kv WHERE key = $1", KEY)
    digest = hashlib.sha256(key.encode()).hexdigest()
    return CALLER if isinstance(stored, str) and hmac.compare_digest(digest, stored) else None


def _api_key() -> str:
    try:
        for line in ENV_FILE.read_text().splitlines():
            if line.startswith("OPENJARVIS_API_KEY="):
                return line.split("=", 1)[1].strip()
    except OSError:
        pass
    return ""


def _client(timeout: float) -> httpx.AsyncClient:  # seam for tests
    return httpx.AsyncClient(timeout=httpx.Timeout(timeout, connect=10))


async def healthy() -> bool:
    try:
        async with _client(5) as c:
            return (await c.get(f"{URL}/health")).status_code == 200
    except httpx.HTTPError:
        return False


async def status() -> dict:
    return {"enabled": await enabled(), "reachable": await healthy(), "configured": bool(_api_key()),
            "recent": [dict(r) for r in await db.pool().fetch(
                """SELECT id, title, status, runtime, runtime_note, cost_usd FROM tasks
                   WHERE runtime = 'openjarvis' OR runtime_note IS NOT NULL ORDER BY id DESC LIMIT 15""")]}


async def run(text: str, category: str, session_id: str) -> str:
    """One task through OpenJarvis → its answer. Raises OpenJarvisError for anything that is not a usable answer."""
    key = _api_key()
    if not key:
        raise OpenJarvisError("OpenJarvis belum disiapkan (kunci tidak ada)")
    try:
        async with _client(TIMEOUT_S) as c:
            r = await c.post(f"{URL}/v1/chat/completions", headers={"Authorization": f"Bearer {key}"},
                             json={"model": f"jarvis-{category}", "stream": False, "user": session_id,
                                   "messages": [{"role": "user", "content": text}]})
    except httpx.HTTPError as e:
        raise OpenJarvisError(f"OpenJarvis tidak dapat dihubungi ({type(e).__name__})") from e
    if r.status_code != 200:
        raise OpenJarvisError(f"OpenJarvis HTTP {r.status_code}: {r.text[:200]}")
    answer = (((r.json().get("choices") or [{}])[0].get("message") or {}).get("content")) or ""
    ok, why = usable(answer)
    if not ok:
        raise OpenJarvisError(why)
    return answer
