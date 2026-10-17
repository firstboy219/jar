"""Client for Hermes Agent's OpenAI-compatible API (internal network only)."""

import re
import time
from dataclasses import dataclass

import httpx

from .config import settings

_SAFE_SESSION = re.compile(r"[^A-Za-z0-9_.-]")


@dataclass
class HermesReply:
    text: str
    prompt_tokens: int | None
    completion_tokens: int | None
    latency_ms: int


class HermesError(RuntimeError):
    pass


def session_header(session_id: str) -> str:
    # Hermes interpolates session ids into file names; keep them boring.
    return "jarvis-" + _SAFE_SESSION.sub("", session_id)[:64]


async def chat(text: str, session_id: str) -> HermesReply:
    started = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=settings.hermes_timeout) as c:
            r = await c.post(
                f"{settings.hermes_url}/v1/chat/completions",
                headers={"Authorization": f"Bearer {settings.hermes_api_key}",
                         "X-Hermes-Session-Id": session_header(session_id)},
                json={"model": "hermes-agent", "messages": [{"role": "user", "content": text}]},
            )
    except httpx.HTTPError as e:
        raise HermesError(f"Hermes tidak dapat dihubungi ({type(e).__name__})") from e
    if r.status_code != 200:
        raise HermesError(f"Hermes HTTP {r.status_code}: {r.text[:300]}")
    data = r.json()
    usage = data.get("usage") or {}
    return HermesReply(
        text=data["choices"][0]["message"]["content"] or "",
        prompt_tokens=usage.get("prompt_tokens"),
        completion_tokens=usage.get("completion_tokens"),
        latency_ms=int((time.monotonic() - started) * 1000),
    )
