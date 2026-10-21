"""Client for Hermes Agent's API server (internal network only).

stream() starts a run (/v1/runs) and turns its event stream into small typed events the APK renders
as JARVIS' "thought stream": reasoning, tool start/finish, answer deltas, approval requests (bridged to
the owner's Approval Center) and a final result with usage.
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
    "delegate_task": "Membagi tugas ke sub-agen",
    "ask_owner": "Bertanya ke pemilik",
    "notify_owner": "Memberi kabar pemilik",
    "create_document": "Membuat dokumen",
    "stage_show": "Menampilkan di layar HP",
    "db_query_ro": "Membaca database",
    "host_metrics": "Memeriksa server",
    "read_logs": "Membaca log",
    "skill_manage": "Mengelola skill",
    "cronjob_manage": "Mengatur jadwal",
    "execute_code": "Menjalankan kode",
    "vision_analyze": "Melihat gambar",
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


async def stream(text: str, session_id: str, image: str | None = None, model: str = "jarvis-web",
                 on_run=None) -> AsyncIterator[dict]:
    """Run one Hermes turn via the durable runs API (/v1/runs), which — unlike /v1/chat/completions —
    carries approval requests. Yields {"type": "thought"|"tool"|"delta"|"approval"|"done", ...};
    raises HermesError on failure. `model` is a gateway alias (jarvis-<category>) mapped by Hermes'
    api_server.model_routes. The image is not sent: workers receive its description in the text."""
    started = time.monotonic()
    answer: list[str] = []
    headers = {"Authorization": f"Bearer {settings.hermes_api_key}"}
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(30, connect=10)) as c:
            r = await c.post(f"{settings.hermes_url}/v1/runs", headers=headers,
                             json={"input": text, "session_id": session_header(session_id), "model": model})
            if r.status_code not in (200, 201, 202):
                raise HermesError(f"Hermes HTTP {r.status_code}: {r.text[:300]}")
            run_id = r.json().get("run_id") or r.json().get("id")
        if not run_id:
            raise HermesError("Hermes tidak memberi run_id")
        if on_run:
            await on_run(run_id)
        async with httpx.AsyncClient(timeout=httpx.Timeout(settings.hermes_timeout, connect=10)) as c:
            async with c.stream("GET", f"{settings.hermes_url}/v1/runs/{run_id}/events", headers=headers) as r:
                if r.status_code != 200:
                    raise HermesError(f"Hermes HTTP {r.status_code}: {(await r.aread())[:300]!r}")
                frame: list[str] = []
                async for line in r.aiter_lines():
                    if line:
                        frame.append(line)
                        continue
                    _, payload = parse_sse(frame)
                    frame = []
                    if not payload:
                        continue
                    ev = payload.get("event")
                    if ev == "message.delta" and payload.get("delta"):
                        answer.append(payload["delta"])
                        yield {"type": "delta", "text": payload["delta"]}
                    elif ev == "reasoning.available" and payload.get("text"):
                        yield {"type": "thought", "text": payload["text"]}
                    elif ev in ("tool.started", "tool.completed", "tool.failed"):
                        yield tool_event({"tool": payload.get("tool"), "label": payload.get("preview"),
                                          "toolCallId": f"{payload.get('tool')}-{payload.get('seq', '')}",
                                          "status": {"tool.started": "running", "tool.completed": "error" if payload.get("error") else "completed",
                                                     "tool.failed": "error"}[ev]})
                    elif ev == "approval.request":
                        yield {"type": "approval", "run_id": run_id, "request_id": payload.get("request_id"),
                               "command": str(payload.get("command") or "")[:2000],
                               "description": str(payload.get("description") or "")[:500],
                               "choices": payload.get("choices") or ["once", "deny"]}
                    elif ev == "run.completed":
                        usage = payload.get("usage") or {}
                        text_out = str(payload.get("output") or "").strip() or "".join(answer).strip()
                        yield {"type": "done", "reply": HermesReply(
                            text=text_out, prompt_tokens=usage.get("input_tokens") or usage.get("prompt_tokens"),
                            completion_tokens=usage.get("output_tokens") or usage.get("completion_tokens"),
                            latency_ms=int((time.monotonic() - started) * 1000))}
                        return
                    elif ev in ("run.failed", "run.cancelled", "run.interrupted"):
                        raise HermesError(f"Hermes gagal: {str(payload.get('error') or ev)[:300]}")
    except httpx.HTTPError as e:
        raise HermesError(f"Hermes tidak dapat dihubungi ({type(e).__name__})") from e
    raise HermesError("Hermes berhenti tanpa hasil")


async def answer_approval(run_id: str, approve: bool, request_id: str | None = None) -> bool:
    """Owner's decision on a dangerous command Hermes paused for."""
    body = {"choice": "once" if approve else "deny"}
    if request_id:
        body["request_id"] = request_id
    try:
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.post(f"{settings.hermes_url}/v1/runs/{run_id}/approval", json=body,
                             headers={"Authorization": f"Bearer {settings.hermes_api_key}"})
        return r.status_code == 200
    except httpx.HTTPError:
        return False


async def stop(run_id: str) -> None:
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            await c.post(f"{settings.hermes_url}/v1/runs/{run_id}/stop",
                         headers={"Authorization": f"Bearer {settings.hermes_api_key}"})
    except httpx.HTTPError:
        pass


async def chat(text: str, session_id: str) -> HermesReply:
    """Non-streaming convenience wrapper (REST endpoint, web admin)."""
    async for ev in stream(text, session_id):
        if ev["type"] == "done":
            return ev["reply"]
    raise HermesError("Hermes tidak memberi jawaban")
