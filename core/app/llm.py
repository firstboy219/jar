"""Minimal OpenRouter chat client for the main agent: streaming text + tool calls, no agent framework.

The main agent must answer in ~1 s, so it talks to a fast model directly with a small prompt; heavy
work goes to Hermes workers instead.
"""

import json
from collections.abc import AsyncIterator
from dataclasses import dataclass, field

import httpx

from .config import settings

URL = "https://openrouter.ai/api/v1/chat/completions"


class LLMError(RuntimeError):
    pass


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict


@dataclass
class Completion:
    text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    prompt_tokens: int | None = None
    completion_tokens: int | None = None


def _merge_tool_deltas(acc: dict[int, dict], deltas: list[dict]) -> None:
    """Tool calls arrive in fragments keyed by index; arguments are a JSON string split across chunks."""
    for d in deltas:
        slot = acc.setdefault(d.get("index", 0), {"id": "", "name": "", "arguments": ""})
        slot["id"] = d.get("id") or slot["id"]
        fn = d.get("function") or {}
        slot["name"] += fn.get("name") or ""
        slot["arguments"] += fn.get("arguments") or ""


def _finish_tools(acc: dict[int, dict]) -> list[ToolCall]:
    calls = []
    for i in sorted(acc):
        slot = acc[i]
        try:
            args = json.loads(slot["arguments"] or "{}")
        except ValueError:
            args = {}
        calls.append(ToolCall(slot["id"] or f"call_{i}", slot["name"], args if isinstance(args, dict) else {}))
    return calls


async def stream_chat(messages: list[dict], tools: list[dict] | None = None, model: str | None = None,
                      max_tokens: int = 400, temperature: float = 0.6) -> AsyncIterator[dict]:
    """Yields {"type": "delta", "text"} while streaming, then {"type": "done", "completion": Completion}."""
    if not settings.openrouter_api_key:
        raise LLMError("OPENROUTER_API_KEY belum diisi")
    body = {"model": model or settings.chat_model, "stream": True, "max_tokens": max_tokens,
            "temperature": temperature, "messages": messages, "reasoning": {"enabled": False},
            "stream_options": {"include_usage": True}}
    if tools:
        body["tools"] = tools
    out, tools_acc = Completion(), {}
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(60, connect=10)) as c:
            async with c.stream("POST", URL, json=body,
                                headers={"Authorization": f"Bearer {settings.openrouter_api_key}"}) as r:
                if r.status_code != 200:
                    raise LLMError(f"OpenRouter HTTP {r.status_code}: {(await r.aread())[:300]!r}")
                async for line in r.aiter_lines():
                    if not line.startswith("data:") or line.endswith("[DONE]"):
                        continue
                    o = json.loads(line[5:])
                    if o.get("usage"):
                        out.prompt_tokens = o["usage"].get("prompt_tokens")
                        out.completion_tokens = o["usage"].get("completion_tokens")
                    for choice in o.get("choices") or []:
                        delta = choice.get("delta") or {}
                        if delta.get("content"):
                            out.text += delta["content"]
                            yield {"type": "delta", "text": delta["content"]}
                        if delta.get("tool_calls"):
                            _merge_tool_deltas(tools_acc, delta["tool_calls"])
    except httpx.HTTPError as e:
        raise LLMError(f"OpenRouter tidak dapat dihubungi ({type(e).__name__})") from e
    out.text = out.text.strip()
    out.tool_calls = _finish_tools(tools_acc)
    yield {"type": "done", "completion": out}


async def complete(messages: list[dict], model: str | None = None, max_tokens: int = 300) -> str:
    """Non-streaming convenience (report wording, summaries)."""
    async for ev in stream_chat(messages, model=model, max_tokens=max_tokens, temperature=0.4):
        if ev["type"] == "done":
            return ev["completion"].text
    return ""
