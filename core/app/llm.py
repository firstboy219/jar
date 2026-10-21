"""Chat client for the main agent and core helpers: streaming text + tool calls, no agent framework.

Every call goes through the LLM gateway (gateway.py), which picks the AI for the category from the
owner's composition, fails over, falls back to the local model and records cost. The main agent must
answer fast, so it talks to its model directly with a small prompt; heavy work goes to Hermes workers.
"""

import json
from collections.abc import AsyncIterator
from dataclasses import dataclass, field

from . import gateway


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
    route: dict | None = None  # which provider/model answered (gateway.Route.public())


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


async def stream_chat(messages: list[dict], tools: list[dict] | None = None, category: str = "ngobrol",
                      max_tokens: int = 400, temperature: float = 0.6, caller: str = "chat",
                      session_id: str | None = None, private: bool = False) -> AsyncIterator[dict]:
    """Yields {"type": "delta", "text"} while streaming, then {"type": "done", "completion": Completion}."""
    body = {"max_tokens": max_tokens, "temperature": temperature, "messages": messages,
            "reasoning": {"enabled": False}}
    if tools:
        body["tools"] = tools
    out, tools_acc = Completion(), {}

    def chosen(route: gateway.Route) -> None:
        out.route = route.public()

    try:
        async for o in gateway.stream(category, body, caller=caller, session_id=session_id, private=private,
                                      on_route=chosen):
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
    except gateway.GatewayError as e:
        raise LLMError(str(e)) from e
    out.text = out.text.strip()
    out.tool_calls = _finish_tools(tools_acc)
    yield {"type": "done", "completion": out}


async def complete(messages: list[dict], category: str = "cepat", max_tokens: int = 300, caller: str = "core",
                   private: bool = False, temperature: float = 0.4) -> str:
    """Non-streaming convenience (report wording, summaries, situation checks)."""
    async for ev in stream_chat(messages, category=category, max_tokens=max_tokens, temperature=temperature,
                                caller=caller, private=private):
        if ev["type"] == "done":
            return ev["completion"].text
    return ""
