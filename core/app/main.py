"""jarvis-core HTTP/WebSocket API, served at https://vis1.cosger.online.

Device API (APK, bearer device token):
  POST /api/v1/chat                {"user_command", "session_id"} -> {"reply", "route"}
  WS   /ws                         same payload, plus live thought/tool/context/delta events (FS-101)
  GET  /api/v1/deepgram/token      short-lived Deepgram token
Admin API (web admin only: X-Admin-Token, and never through the public proxy):
  /admin/...                       status, approvals, memories, devices, usage, audit
"""

import asyncio
import contextlib
import hmac
import json
import logging

from fastapi import Depends, FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field

from . import approvals, audit, chat, db, deepgram, devices, hub, media, memory, reports, status, usage, workers
from .config import settings
from .location import Location

log = logging.getLogger("jarvis-core")


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    await db.connect(settings.database_url)
    try:
        await memory.ensure_collection()
    except Exception as e:  # Qdrant down must not keep chat from starting
        log.warning("memory collection not ready: %s", e)
    resumed = await workers.resume_after_restart()
    if resumed:
        log.info("resumed %d interrupted worker task(s)", resumed)
    ticker = asyncio.create_task(reports.run_forever())
    yield
    ticker.cancel()
    await db.close()


app = FastAPI(title="JARVIS core", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)


def jsonable(obj):
    return json.loads(json.dumps(obj, default=str))


# ---------- auth ----------

def _bearer(value: str | None) -> str | None:
    if value and value.lower().startswith("bearer "):
        return value[7:].strip()
    return None


async def device_auth(request: Request) -> dict:
    device = await devices.authenticate(_bearer(request.headers.get("authorization")))
    if not device:
        raise HTTPException(401, "token perangkat tidak valid")
    return device


async def admin_auth(request: Request) -> str:
    # The public proxy always adds X-Forwarded-For; the web admin calls us directly on jarvis-network.
    if "x-forwarded-for" in request.headers or "x-real-ip" in request.headers:
        raise HTTPException(404)
    token = request.headers.get("x-admin-token", "")
    if not settings.admin_token or not hmac.compare_digest(token, settings.admin_token):
        raise HTTPException(404)
    return "owner"


# ---------- device API ----------

class Command(BaseModel):
    user_command: str = Field(min_length=1, max_length=8000)
    session_id: str = Field(min_length=1, max_length=128)
    location: Location | None = None  # only when the owner enabled location sharing in the app
    # Latest screen frame while the owner is sharing their screen (JPEG, base64), max ~1.5 MB
    screen: str | None = Field(default=None, max_length=2_000_000)


@app.get("/healthz")
async def healthz():
    return {"ok": True}


@app.post("/api/v1/chat")
async def chat_rest(cmd: Command, device: dict = Depends(device_auth)):
    turn = await chat.handle(cmd.user_command, cmd.session_id, actor=f"device:{device['name']}",
                             device_id=device["id"], location=cmd.location)
    return {"reply": turn.reply, "route": turn.route, "session_id": cmd.session_id}


@app.get("/api/v1/deepgram/token")
async def deepgram_token(device: dict = Depends(device_auth)):
    try:
        return await deepgram.grant()
    except deepgram.DeepgramError as e:
        raise HTTPException(503, str(e))


@app.websocket("/ws")
async def ws(websocket: WebSocket):
    """Auth: `Authorization: Bearer <device token>` header, or a first message {"type":"auth","token":...}."""
    await websocket.accept()
    device = await devices.authenticate(_bearer(websocket.headers.get("authorization")))
    send_lock = asyncio.Lock()
    tasks: set[asyncio.Task] = set()
    client_id: int | None = None

    async def send(obj: dict) -> None:
        async with send_lock:
            await websocket.send_text(json.dumps(obj, ensure_ascii=False))

    try:
        if not device:
            try:
                first = json.loads(await asyncio.wait_for(websocket.receive_text(), timeout=10))
                device = await devices.authenticate(first.get("token") if first.get("type") == "auth" else None)
            except (asyncio.TimeoutError, ValueError, AttributeError):
                device = None
            if not device:
                await send({"type": "error", "message": "unauthorized"})
                await websocket.close(code=4401)
                return
            await send({"type": "auth_ok"})

        client_id = hub.register(send)
        await send({"type": "tasks", "items": jsonable(await workers.active())})
        await reports.on_connect(send)

        async def run(cmd: Command) -> None:
            async def emit(event: dict) -> None:
                await send({**event, "session_id": cmd.session_id})
            try:
                turn = await chat.handle(cmd.user_command, cmd.session_id, actor=f"device:{device['name']}",
                                         device_id=device["id"], emit=emit, location=cmd.location, screen=cmd.screen)
                await send({"type": "reply", "text": turn.reply, "route": turn.route, "session_id": cmd.session_id})
            except (WebSocketDisconnect, RuntimeError):
                pass  # socket gone mid-turn; the task is cancelled below anyway
            except Exception:
                log.exception("chat turn failed")
                await send({"type": "error", "message": "internal error", "session_id": cmd.session_id})

        while True:
            raw = await websocket.receive_text()
            try:
                msg = json.loads(raw)
            except ValueError:
                await send({"type": "error", "message": "invalid JSON"})
                continue
            kind = msg.get("type")
            if kind == "ping":
                await send({"type": "pong"})
                continue
            if kind in ("ack", "report_spoken", "cancel_task"):
                try:
                    ref = int(msg.get("report_id") or msg.get("task_id") or 0)
                except (TypeError, ValueError):
                    continue
                if kind == "ack":
                    await reports.acknowledge([ref], "tap")
                elif kind == "report_spoken":
                    await reports.spoken(ref)
                else:
                    await workers.cancel(ref, f"device:{device['name']}")
                continue
            try:
                cmd = Command(user_command=msg.get("user_command", ""), session_id=msg.get("session_id", ""),
                              location=msg.get("location"), screen=msg.get("screen"))
            except ValueError:
                await send({"type": "error", "message": "butuh user_command dan session_id (lokasi opsional)"})
                continue
            task = asyncio.create_task(run(cmd))
            tasks.add(task)
            task.add_done_callback(tasks.discard)
    except WebSocketDisconnect:
        pass
    finally:
        if client_id is not None:
            hub.unregister(client_id)
        # Client gone: abandon the main-agent turns in flight. Workers are independent and keep going.
        for task in list(tasks):
            task.cancel()


# ---------- internal API (jarvis-tools → core) ----------

class MediaIn(BaseModel):
    items: list[dict] = Field(min_length=1, max_length=12)
    caption: str = ""


@app.post("/internal/media")
async def internal_media(m: MediaIn, request: Request):
    # Only the MCP tool server on jarvis-network may call this; never through the public proxy.
    if "x-forwarded-for" in request.headers or "x-real-ip" in request.headers:
        raise HTTPException(404)
    if not settings.mcp_token or not hmac.compare_digest(request.headers.get("x-internal-token", ""), settings.mcp_token):
        raise HTTPException(404)
    return await media.show(m.items, m.caption, "hermes")


# ---------- admin API ----------

admin = Depends(admin_auth)


@app.get("/admin/status")
async def admin_status(_: str = admin):
    return await status.check_all()


@app.get("/admin/approvals")
async def admin_approvals(status_: str | None = None, _: str = admin):
    return await approvals.list_(status_)


class Decision(BaseModel):
    approve: bool


@app.post("/admin/approvals/{approval_id}")
async def admin_decide(approval_id: int, d: Decision, actor: str = admin):
    try:
        return await approvals.decide(approval_id, d.approve, actor)
    except approvals.ApprovalError as e:
        raise HTTPException(409, str(e))


@app.get("/admin/memories")
async def admin_memories(q: str | None = None, category: str | None = None, _: str = admin):
    return await memory.search(q, limit=20, include_stale=True) if q else await memory.list_(category)


class MemoryIn(BaseModel):
    text: str = Field(min_length=1, max_length=4000)
    category: str = "personal"
    kind: str = "fact"


class MemoryPatch(BaseModel):
    text: str | None = Field(default=None, max_length=4000)
    category: str | None = None
    kind: str | None = None
    stale: bool | None = None


@app.post("/admin/memories")
async def admin_memory_create(m: MemoryIn, actor: str = admin):
    try:
        return await memory.save(m.text, m.category, source=actor, kind=m.kind)
    except memory.MemoryError_ as e:
        raise HTTPException(422, str(e))


@app.patch("/admin/memories/{mem_id}")
async def admin_memory_update(mem_id: str, m: MemoryPatch, actor: str = admin):
    try:
        return await memory.update(mem_id, actor, **m.model_dump())
    except memory.MemoryError_ as e:
        raise HTTPException(422, str(e))


@app.delete("/admin/memories/{mem_id}")
async def admin_memory_delete(mem_id: str, actor: str = admin):
    if not await memory.delete(mem_id, actor):
        raise HTTPException(404, "memori tidak ditemukan")
    return {"deleted": True}


class DeviceIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)


@app.get("/admin/devices")
async def admin_devices(_: str = admin):
    return await devices.list_()


@app.post("/admin/devices")
async def admin_device_create(d: DeviceIn, actor: str = admin):
    device, token = await devices.create(d.name, actor)
    return {**device, "token": token}  # shown once in the admin UI


@app.delete("/admin/devices/{device_id}")
async def admin_device_revoke(device_id: str, actor: str = admin):
    return {"revoked": await devices.revoke(device_id, actor)}


@app.get("/admin/usage")
async def admin_usage(_: str = admin):
    return {"local": await usage.local_summary(), "openrouter": await usage.openrouter_summary()}


@app.get("/admin/tasks")
async def admin_tasks(_: str = admin):
    return {"tasks": await workers.recent(), "reports": await reports.recent()}


@app.post("/admin/tasks/{task_id}/cancel")
async def admin_task_cancel(task_id: int, actor: str = admin):
    return {"cancelled": await workers.cancel(task_id, actor)}


@app.post("/admin/reports/{report_id}/ack")
async def admin_report_ack(report_id: int, actor: str = admin):
    return {"acknowledged": await reports.acknowledge([report_id], "admin")}


@app.get("/admin/audit")
async def admin_audit(_: str = admin):
    return await audit.recent()


class AdminChat(BaseModel):
    message: str = Field(min_length=1, max_length=8000)
    session_id: str = "web-admin"


@app.post("/admin/chat")
async def admin_chat(c: AdminChat, actor: str = admin):
    turn = await chat.handle(c.message, c.session_id, actor="web-admin")
    return {"reply": turn.reply, "route": turn.route}
