"""jarvis-tools: MCP server that gives Hermes policy-enforced tools (memory, approvals, n8n).

Hermes never gets the n8n API key or direct DB access; every side effect goes through these tools,
and anything risky becomes an approval request instead of an action.

Run: python -m app.mcp_server   (streamable HTTP on :8100/mcp, bearer MCP_TOKEN)
"""

import contextlib
import hashlib
import hmac
import json
import re

import httpx
import uvicorn
from mcp.server import MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from starlette.responses import JSONResponse

from . import approvals, db, memory, n8n
from .config import settings

ACTOR = "hermes"


@contextlib.asynccontextmanager
async def lifespan(server):
    await db.connect(settings.database_url)
    try:
        yield {}
    finally:
        await db.close()


mcp = MCPServer(
    "jarvis",
    instructions=(
        "JARVIS owner tools. Use memory_search before answering questions about the owner, their projects or "
        "past decisions, and memory_save for durable facts/preferences the owner states (never secrets). "
        "Anything destructive, external or production-affecting must go through request_approval; "
        "n8n workflows are created inactive and only the owner can activate them."),
    lifespan=lifespan,
)


def _jsonable(obj):
    return json.loads(json.dumps(obj, default=str))


@mcp.tool()
async def memory_search(query: str, limit: int = 5) -> list[dict]:
    """Semantic search over the owner's long-term memory (personal, project, knowledge, experience,
    operational). Returns text, category, kind (fact/assumption/preference), score and id."""
    hits = await memory.search(query, limit=max(1, min(limit, 20)))
    return _jsonable([{k: m[k] for k in ("id", "text", "category", "kind", "score", "updated_at")} for m in hits])


@mcp.tool()
async def memory_save(text: str, category: str = "personal", kind: str = "fact") -> dict:
    """Save one durable, self-contained statement to long-term memory.
    category: personal | project | knowledge | experience | operational. kind: fact | assumption | preference.
    Do not save secrets, credentials, or one-off chit-chat."""
    try:
        m = await memory.save(text, category, source=ACTOR, kind=kind)
    except memory.MemoryError_ as e:
        return {"saved": False, "reason": str(e)}
    return {"saved": True, "id": str(m["id"])}


@mcp.tool()
async def request_approval(title: str, detail: str, risk: str = "medium") -> dict:
    """Ask the owner to approve an action you want to take (destructive, external, financial, production).
    Do NOT perform the action until get_approval shows status 'completed' for kind 'manual' approvals.
    risk: low | medium | high."""
    if risk not in ("low", "medium", "high"):
        risk = "medium"
    key = "manual:" + hashlib.sha256(f"{title}\n{detail}".encode()).hexdigest()[:32]
    a = await approvals.create("manual", title[:200], {"detail": detail[:4000]}, ACTOR, risk, key)
    return {"approval_id": a["id"], "status": a["status"],
            "note": "Owner sees this in the Approval Queue (web admin / 'persetujuan' command)."}


@mcp.tool()
async def get_approval(approval_id: int) -> dict:
    """Current status of an approval request: awaiting_approval, approved, rejected, executing,
    completed, failed, cancelled, or expired."""
    a = await approvals.get(approval_id)
    if not a:
        return {"error": "not found"}
    return _jsonable({k: a[k] for k in ("id", "kind", "title", "status", "result", "error", "decided_at")})


@mcp.tool()
async def n8n_list_workflows() -> list[dict]:
    """List workflows in the owner's n8n (id, name, active)."""
    try:
        return await n8n.list_workflows()
    except n8n.N8nError as e:
        return [{"error": str(e)}]


_CODER_PROMPT = """You generate n8n workflow JSON (n8n 2.x). Output ONLY a JSON object with keys
"name", "nodes", "connections" (and optional "settings"). No markdown, no commentary.
Use real n8n node types (e.g. n8n-nodes-base.scheduleTrigger, n8n-nodes-base.webhook,
n8n-nodes-base.httpRequest, n8n-nodes-base.code, n8n-nodes-base.if, n8n-nodes-base.set).
Every node needs: id (uuid), name (unique), type, typeVersion, position [x, y], parameters.
Never embed credentials or secrets; leave credential selection to the owner."""


def _extract_json(text: str) -> dict:
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.DOTALL)
    if fence:
        text = fence.group(1)
    start, end = text.find("{"), text.rfind("}")
    return json.loads(text[start:end + 1])


def validate_workflow(wf: dict) -> list[str]:
    problems = []
    if not isinstance(wf.get("name"), str) or not wf["name"].strip():
        problems.append("name kosong")
    nodes = wf.get("nodes")
    if not isinstance(nodes, list) or not nodes:
        problems.append("nodes kosong")
        return problems
    names = set()
    for n in nodes:
        for key in ("name", "type", "typeVersion", "position", "parameters"):
            if key not in n:
                problems.append(f"node {n.get('name', '?')}: tidak ada '{key}'")
        names.add(n.get("name"))
    if len(names) != len(nodes):
        problems.append("nama node tidak unik")
    conns = wf.get("connections")
    if not isinstance(conns, dict):
        problems.append("connections bukan object")
    else:
        for src, outputs in conns.items():
            if src not in names:
                problems.append(f"connection dari node tak dikenal: {src}")
            for branch in (outputs or {}).get("main", []) or []:
                for link in branch or []:
                    if link.get("node") not in names:
                        problems.append(f"connection ke node tak dikenal: {link.get('node')}")
    return problems


async def _generate_workflow(description: str) -> dict:
    if not settings.openrouter_api_key:
        raise RuntimeError("OPENROUTER_API_KEY belum diisi")
    async with httpx.AsyncClient(timeout=120) as c:
        r = await c.post("https://openrouter.ai/api/v1/chat/completions",
                         headers={"Authorization": f"Bearer {settings.openrouter_api_key}"},
                         json={"model": settings.coder_model, "temperature": 0.1, "max_tokens": 8000,
                               "messages": [{"role": "system", "content": _CODER_PROMPT},
                                            {"role": "user", "content": description}]})
    if r.status_code != 200:
        try:
            msg = r.json()["error"]["message"]
        except (ValueError, KeyError, TypeError):
            msg = r.text[:200]
        raise RuntimeError(f"OpenRouter HTTP {r.status_code}: {msg}")
    return _extract_json(r.json()["choices"][0]["message"]["content"])


@mcp.tool()
async def n8n_draft_workflow(description: str) -> dict:
    """Design a new n8n automation from a plain-language description (BR-002). The coder model writes the
    workflow JSON, it is validated and created INACTIVE in n8n, and an approval request to activate it is
    queued for the owner. Describe trigger, steps, and expected output precisely."""
    # A retried or timed-out turn must not create a second copy of the same pending workflow.
    pending = await db.pool().fetchrow(
        """SELECT id, detail FROM approvals WHERE kind = 'n8n_activate_workflow'
           AND status = 'awaiting_approval' AND detail->>'description' = $1""", description[:2000])
    if pending:
        return {"created": False, "already_pending": True, "workflow_id": pending["detail"]["workflow_id"],
                "approval_id": pending["id"], "note": "Workflow yang sama sudah dibuat dan menunggu persetujuan."}
    try:
        wf = await _generate_workflow(description)
    except (httpx.HTTPError, ValueError, KeyError, RuntimeError) as e:
        return {"created": False, "reason": f"gagal membuat JSON workflow: {e}"}
    if problems := validate_workflow(wf):
        return {"created": False, "reason": "JSON workflow tidak valid", "problems": problems[:10]}
    try:
        created = await n8n.create_inactive(wf)
    except n8n.N8nError as e:
        return {"created": False, "reason": str(e)}
    a = await approvals.create(
        "n8n_activate_workflow", f"Aktifkan workflow n8n: {created['name']}",
        {"workflow_id": created["id"], "name": created["name"], "description": description[:2000],
         "nodes": [n["name"] for n in wf["nodes"]]},
        ACTOR, "medium", idempotency_key=f"n8n_activate:{created['id']}")
    return {"created": True, "workflow_id": created["id"], "name": created["name"], "active": False,
            "approval_id": a["id"],
            "note": "Workflow dibuat nonaktif; pemilik harus menyetujui aktivasi."}


@mcp.tool()
async def self_info() -> dict:
    """JARVIS' own architecture, capabilities, limits, health and learned lessons — the source of truth
    about yourself. Check this before claiming JARVIS has or lacks a capability (e.g. speech recognition
    runs on the phone via Deepgram, not inside this container)."""
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.get("http://jarvis-core:8000/internal/self", headers={"X-Internal-Token": settings.mcp_token})
    return r.json() if r.status_code == 200 else {"error": f"core HTTP {r.status_code}"}


# ---------- showing things on the owner's phone ----------

@mcp.tool()
async def find_images(query: str, limit: int = 6) -> list[dict]:
    """Search openly-licensed images (Openverse). Returns url, title, source, license. Indonesian queries
    may return few results — try English keywords too. Then call show_media with the best ones."""
    try:
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.get("https://api.openverse.org/v1/images/",
                            params={"q": query, "page_size": max(1, min(limit, 12)), "mature": "false"})
        r.raise_for_status()
        return [{"url": i["url"], "title": i.get("title") or "", "source": i.get("foreign_landing_url") or "",
                 "license": i.get("license") or ""} for i in r.json().get("results", []) if i.get("url", "").startswith("https://")]
    except (httpx.HTTPError, ValueError) as e:
        return [{"error": f"pencarian gambar gagal: {type(e).__name__}"}]


def _yt_search(query: str, limit: int) -> list[dict]:
    import yt_dlp
    with yt_dlp.YoutubeDL({"quiet": True, "extract_flat": True, "skip_download": True, "noplaylist": True}) as y:
        info = y.extract_info(f"ytsearch{limit}:{query}", download=False)
    return [{"url": e["url"], "title": e.get("title") or "", "channel": e.get("channel") or e.get("uploader") or "",
             "duration_s": e.get("duration")} for e in info.get("entries", []) if e.get("url")]


@mcp.tool()
async def find_videos(query: str, limit: int = 5) -> list[dict]:
    """Search YouTube videos (title, channel, duration, url). Use for tutorials/demos, then show_media
    with kind 'video'."""
    import asyncio
    try:
        return await asyncio.to_thread(_yt_search, query, max(1, min(limit, 10)))
    except Exception as e:
        return [{"error": f"pencarian video gagal: {type(e).__name__}"}]


@mcp.tool()
async def show_media(items: list[dict], caption: str = "") -> dict:
    """Show pictures/videos on the owner's phone right now. items: [{"url": "https://…", "kind":
    "image"|"video"|"link", "title": "…", "source": "…"}]. Images must be direct https image URLs (from
    find_images, or an image you found on a web page); videos are YouTube URLs. caption: one short line
    explaining what the owner is looking at."""
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.post("http://jarvis-core:8000/internal/media", json={"items": items, "caption": caption},
                         headers={"X-Internal-Token": settings.mcp_token})
    if r.status_code != 200:
        return {"shown": 0, "reason": f"core HTTP {r.status_code}"}
    return r.json()


def build_app():
    app = mcp.streamable_http_app(
        stateless_http=True, json_response=True,
        transport_security=TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=["jarvis-tools:8100", "localhost:8100", "127.0.0.1:8100"],
            allowed_origins=[]),
    )

    async def auth(scope, receive, send):
        if scope["type"] == "http":
            headers = dict(scope.get("headers") or [])
            token = headers.get(b"authorization", b"").decode()
            expected = f"Bearer {settings.mcp_token}"
            if not settings.mcp_token or not hmac.compare_digest(token, expected):
                await JSONResponse({"error": "unauthorized"}, status_code=401)(scope, receive, send)
                return
        await app(scope, receive, send)

    return auth


if __name__ == "__main__":
    uvicorn.run(build_app(), host="0.0.0.0", port=8100)
