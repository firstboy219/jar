"""Client for Hermes Agent's OpenAI-compatible API (internal network only).

stream() turns Hermes' SSE into small typed events the APK renders as JARVIS' "thought stream":
reasoning deltas, tool start/finish, answer deltas, and a final result with usage.
Closing the stream early (client gone) makes Hermes interrupt the agent run.
"""

import json
import re
import time
from collections.abc import AsyncIterator
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


TOOL_NAMES = {
    "memory_search": "Mencari di memori",
    "memory_save": "Menyimpan ke memori",
    "request_approval": "Meminta persetujuan",
    "get_approval": "Memeriksa persetujuan",
    "n8n_list_workflows": "Melihat workflow n8n",
    "n8n_draft_workflow": "Merancang workflow n8n",
    "delegate_task": "Bertanya ke model ahli",
    "web_search": "Mencari di web",
    "web_extract": "Membaca halaman web",
    "terminal": "Menjalankan perintah",
    "read_file": "Membaca file",
    "search_files": "Mencari file",
    "browser_navigate": "Membuka browser",
}


def tool_event(raw: dict) -> dict:
    name = str(raw.get("tool", "")).removeprefix("mcp__jarvis__")
    return {"type": "tool", "id": raw.get("toolCallId", ""), "name": name,
            "title": TOOL_NAMES.get(name, name.replace("_", " ")),
            "label": str(raw.get("label") or "")[:200], "emoji": raw.get("emoji") or "",
            "status": raw.get("status", "running")}


def parse_sse(lines: list[str]) -> tuple[str | None, dict | None]:
    """One SSE frame (its lines) -> (event name, JSON payload); payload None for [DONE]/empty."""
    event, data = None, []
    for line in lines:
        if line.startswith("event:"):
            event = line[6:].strip()
        elif line.startswith("data:"):
            data.append(line[5:].strip())
    raw = "\n".join(data)
    if not raw or raw == "[DONE]":
        return event, None
    return event, json.loads(raw)


async def stream(text: str, session_id: str, image: str | None = None) -> AsyncIterator[dict]:
    """Yields {"type": "thought"|"tool"|"delta"|"done", ...}; raises HermesError on failure."""
    started = time.monotonic()
    answer: list[str] = []
    usage: dict = {}
    error: str | None = None
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(settings.hermes_timeout, connect=10)) as c:
            async with c.stream(
                "POST", f"{settings.hermes_url}/v1/chat/completions",
                headers={"Authorization": f"Bearer {settings.hermes_api_key}",
                         "X-Hermes-Session-Id": session_header(session_id)},
                json={"model": "hermes-agent", "stream": True,
                      "messages": [{"role": "user", "content": text if not image else [
                          {"type": "text", "text": text},
                          {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image}"}}]}]},
            ) as r:
                if r.status_code != 200:
                    body = (await r.aread()).decode(errors="replace")
                    raise HermesError(f"Hermes HTTP {r.status_code}: {body[:300]}")
                frame: list[str] = []
                async for line in r.aiter_lines():
                    if line:
                        frame.append(line)
                        continue
                    event, payload = parse_sse(frame)
                    frame = []
                    if payload is None:
                        continue
                    if event == "hermes.tool.progress":
                        yield tool_event(payload)
                    elif event is None and payload.get("choices"):
                        choice = payload["choices"][0]
                        delta = choice.get("delta") or {}
                        if delta.get("reasoning_content"):
                            yield {"type": "thought", "text": delta["reasoning_content"]}
                        if delta.get("content"):
                            answer.append(delta["content"])
                            yield {"type": "delta", "text": delta["content"]}
                        if choice.get("finish_reason"):
                            usage = payload.get("usage") or {}
                            if choice["finish_reason"] != "stop":
                                error = (payload.get("error") or {}).get("message") or choice["finish_reason"]
    except httpx.HTTPError as e:
        raise HermesError(f"Hermes tidak dapat dihubungi ({type(e).__name__})") from e
    if error and not answer:
        raise HermesError(f"Hermes gagal: {error[:300]}")
    yield {"type": "done", "reply": HermesReply(
        text="".join(answer).strip(),
        prompt_tokens=usage.get("prompt_tokens"),
        completion_tokens=usage.get("completion_tokens"),
        latency_ms=int((time.monotonic() - started) * 1000))}


async def chat(text: str, session_id: str) -> HermesReply:
    """Non-streaming convenience wrapper (REST endpoint, web admin)."""
    async for ev in stream(text, session_id):
        if ev["type"] == "done":
            return ev["reply"]
    raise HermesError("Hermes tidak memberi jawaban")
