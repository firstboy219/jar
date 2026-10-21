"""jarvis-core HTTP/WebSocket API, served at https://vis1.cosger.online.

Device API (APK, bearer device token):
  POST /api/v1/chat                {"user_command", "session_id"} -> {"reply", "route"}
  WS   /ws                         same payload, plus live thought/tool/context/delta/say events (FS-101)
  GET  /api/v1/deepgram/token      short-lived Deepgram token
  GET/PUT /api/v1/composition      which AI per category + speech engine (owner devices only)
  /api/v1/console/...              everything the web admin has, for the owner's phone (scope 'owner')
Admin API (web admin only: X-Admin-Token, and never through the public proxy):
  /admin/...                       status, approvals, memories, devices, usage, audit, composition (read)
Internal (jarvis-network only, never through the proxy):
  /llm/v1/chat/completions, /llm/v1/models   LLM gateway for Hermes (bearer LLM_GATEWAY_KEY)
"""

import asyncio
import contextlib
import hmac
import json
import logging

from fastapi import Body, Depends, FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from . import (approvals, audit, awareness, brain, budget, chat, hermes_studio, meetings, composition, db, deepgram, devices, documents, gateway, hub,
               media, memory, notifications, overrides, questions, reports, self_model, selfimprove, stage, status,
               stt, usage, voice_id, workers)
from .config import settings
from .location import Location

log = logging.getLogger("jarvis-core")


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    await db.connect(settings.database_url)
    try:
        await db.grant_readonly(db.pool())
    except Exception as e:
        log.warning("read-only grants not applied: %s", e)
    try:
        await memory.ensure_collection()
    except Exception as e:  # Qdrant down must not keep chat from starting
        log.warning("memory collection not ready: %s", e)
    applied = await overrides.load_all()
    if applied:
        log.info("setting overrides: %s", applied)
    resumed = await workers.resume_after_restart()
    if resumed:
        log.info("resumed %d interrupted worker task(s)", resumed)
    ticker = asyncio.create_task(reports.run_forever())

    async def purge_daily():
        while True:
            await notifications.purge_old()
            try:
                await meetings.purge_audio()
            except Exception:
                log.exception("meeting audio purge failed")
            await asyncio.sleep(6 * 3600)

    async def selfcheck_daily():
        last_day = None
        while True:
            if await selfimprove.daily_due(last_day):
                last_day = __import__("datetime").datetime.now(awareness.WIB).date()
                await selfimprove.start()
            await asyncio.sleep(600)

    async def cron_deliveries():
        while True:
            try:
                await hermes_studio.deliver_cron_outputs()
            except Exception:
                log.exception("cron delivery failed")
            await asyncio.sleep(30)

    purger = asyncio.create_task(purge_daily())
    cron = asyncio.create_task(cron_deliveries())
    meeting_worker = asyncio.create_task(meetings.run_forever())

    async def warm_local_worker():
        # llama-worker may have restarted: put Hermes' cached prompt prefix back (see gateway.SLOT_FILE)
        for _ in range(20):
            if await gateway.restore_worker_slot():
                log.info("local worker prompt cache restored")
                return
            await asyncio.sleep(30)
    warm = asyncio.create_task(warm_local_worker())
    aware = asyncio.create_task(awareness.run_forever())
    selfcheck = asyncio.create_task(selfcheck_daily())
    yield
    for t in (ticker, purger, aware, selfcheck, cron, meeting_worker, warm):
        t.cancel()
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


def _internal_only(request: Request) -> None:
    # The public proxy always adds X-Forwarded-For; internal callers reach us directly on jarvis-network.
    if "x-forwarded-for" in request.headers or "x-real-ip" in request.headers:
        raise HTTPException(404)


async def owner_device_auth(request: Request) -> dict:
    device = await device_auth(request)
    if device.get("scope") != "owner":
        raise HTTPException(403, "perangkat ini tidak punya akses konsol pemilik")
    return device


CONSOLE = "/api/v1/console"


async def admin_auth(request: Request) -> str:
    """The web admin (internal token) — or, under /api/v1/console, the owner's phone (owner-scope device
    token through the public proxy). Both are the owner; the actor records which one acted."""
    if request.url.path.startswith(CONSOLE + "/"):
        device = await owner_device_auth(request)
        return f"device:{device['name']}"
    _internal_only(request)
    token = request.headers.get("x-admin-token", "")
    if not settings.admin_token or not hmac.compare_digest(token, settings.admin_token):
        raise HTTPException(404)
    return "owner"


# ---------- device API ----------

class Command(BaseModel):
    user_command: str = Field(min_length=1, max_length=8000)
    session_id: str = Field(min_length=1, max_length=128)
    location: Location | None = None  # only when the owner enabled location sharing in the app
    # Latest frame the owner is showing (JPEG, base64), max ~1.5 MB: shared screen or camera
    screen: str | None = Field(default=None, max_length=2_000_000)
    image_source: str | None = Field(default=None, pattern="^(screen|camera)$")
    # How speech recognition heard it: {"confidence": 0..1, "speakers": n}
    stt: dict | None = None
    # Text the phone read from the shared screen (ML Kit) / the WhatsApp notification thread
    screen_text: str | None = Field(default=None, max_length=20000)


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


MAX_UTTERANCE_BYTES = 60 * 16000 * 2  # 60 s of PCM16 mono 16 kHz


@app.get("/api/v1/brain")
async def brain_graph(device: dict = Depends(device_auth)):
    try:
        return jsonable(await brain.graph())
    except Exception as e:  # Qdrant down: the phone falls back to its own idle animation
        raise HTTPException(503, f"otak belum bisa dimuat ({type(e).__name__})")


@app.get("/api/v1/brain/{mem_id}")
async def brain_card(mem_id: str, device: dict = Depends(device_auth)):
    card = await brain.memory_card(mem_id)
    if not card:
        raise HTTPException(404, "memori tidak ditemukan")
    return card


@app.get("/api/v1/voiceprint")
async def voiceprint_status(device: dict = Depends(device_auth)):
    return await voice_id.enrolled()


@app.post("/api/v1/voiceprint")
async def voiceprint_add(request: Request, device: dict = Depends(owner_device_auth)):
    """One enrolment sentence, raw PCM16 mono 16 kHz in the body."""
    pcm = await request.body()
    if not 16000 * 2 <= len(pcm) <= MAX_UTTERANCE_BYTES:
        raise HTTPException(400, "rekaman harus 1–60 detik")
    try:
        return await voice_id.add_sample(pcm, f"device:{device['name']}")
    except (ValueError, KeyError) as e:
        raise HTTPException(422, f"suara tidak bisa diproses: {e}")


@app.delete("/api/v1/voiceprint")
async def voiceprint_delete(device: dict = Depends(owner_device_auth)):
    await voice_id.delete(f"device:{device['name']}")
    return {"deleted": True}


@app.get("/api/v1/composition")
async def composition_get(device: dict = Depends(device_auth)):
    return jsonable(await composition.get())


class CompositionIn(BaseModel):
    preset: str | None = None
    changes: dict | None = None


@app.put("/api/v1/composition")
async def composition_put(c: CompositionIn, device: dict = Depends(owner_device_auth)):
    """Only the owner's phone may change which AI JARVIS uses (decision 2026-10-21)."""
    actor = f"device:{device['name']}"
    try:
        if c.preset:
            await composition.apply_preset(c.preset, actor)
        if c.changes:
            await composition.update(c.changes, actor)
    except composition.CompositionError as e:
        raise HTTPException(422, str(e))
    return jsonable(await composition.get())


class CompositionTest(BaseModel):
    category: str = "ngobrol"
    text: str = Field(default="Halo JARVIS, tes singkat. Jawab satu kalimat.", max_length=500)


@app.post("/api/v1/composition/test")
async def composition_test(t: CompositionTest, device: dict = Depends(owner_device_auth)):
    """'Tes' button: one real call through the gateway, with which model answered and how fast."""
    import time as _t
    started = _t.monotonic()
    try:
        data = await gateway.complete(t.category, {"messages": [{"role": "user", "content": t.text}], "max_tokens": 60},
                                      caller="test")
    except gateway.GatewayError as e:
        return {"ok": False, "error": str(e)[:500]}
    return {"ok": True, "route": data.get("jarvis_route"), "ms": int((_t.monotonic() - started) * 1000),
            "text": ((data.get("choices") or [{}])[0].get("message") or {}).get("content", "")[:500]}


# ---------- LLM gateway for Hermes (internal) ----------

def _gateway_auth(request: Request) -> None:
    _internal_only(request)
    key = _bearer(request.headers.get("authorization")) or ""
    if not settings.llm_gateway_key or not hmac.compare_digest(key, settings.llm_gateway_key):
        raise HTTPException(401, "invalid gateway key")


@app.get("/llm/v1/models")
async def llm_models(request: Request):
    _gateway_auth(request)
    return {"object": "list", "data": await gateway.model_list()}


@app.post("/llm/v1/chat/completions")
async def llm_chat(request: Request, body: dict = Body(...)):
    _gateway_auth(request)
    category = gateway.category_of_alias(str(body.get("model") or ""))
    if category not in await gateway.categories():
        raise HTTPException(404, f"model tidak dikenal: {body.get('model')}")
    session = request.headers.get("x-session-id") or (str(body.get("user")) if body.get("user") else None)
    private = category == "privat"
    if not body.get("stream"):
        try:
            data = await gateway.complete(category, body, caller="hermes", session_id=session, private=private, worker=True)
        except gateway.GatewayError as e:
            return JSONResponse({"error": {"message": str(e)[:1000], "type": "gateway_error"}}, status_code=502)
        data.pop("jarvis_route", None)
        return data

    agen = gateway.stream(category, body, caller="hermes", session_id=session, private=private, worker=True)
    try:  # fail over before the first byte: only commit to a 200 stream once a route has answered
        first = await agen.__anext__()
    except gateway.GatewayError as e:
        return JSONResponse({"error": {"message": str(e)[:1000], "type": "gateway_error"}}, status_code=502)
    except StopAsyncIteration:
        first = None

    async def sse():
        try:
            if first is not None:
                yield f"data: {json.dumps(first, ensure_ascii=False)}\n\n"
                async for chunk in agen:
                    yield f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"
        except gateway.GatewayError as e:
            yield f"data: {json.dumps({'error': {'message': str(e)[:500]}})}\n\n"
        finally:
            await agen.aclose()
        yield "data: [DONE]\n\n"
    return StreamingResponse(sse(), media_type="text/event-stream")


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

        caps = {c.strip() for c in (websocket.headers.get("x-app-caps") or "").split(",")}
        client_id = hub.register(send, device=device["name"], scope=device.get("scope"), caps=sorted(caps - {""}),
                                 app_version=(websocket.headers.get("x-app-version") or "")[:20] or None)
        await send({"type": "tasks", "items": jsonable(await workers.active())})
        if current_stage := stage.current():
            await send(current_stage)
        await reports.on_connect(send)

        async def run(cmd: Command) -> None:
            async def emit(event: dict) -> None:
                await send({**event, "session_id": cmd.session_id})
            try:
                turn = await chat.handle(cmd.user_command, cmd.session_id, actor=f"device:{device['name']}",
                                         device_id=device["id"], emit=emit, location=cmd.location, screen=cmd.screen,
                                         image_source=cmd.image_source, stt=cmd.stt, speak_live="say" in caps,
                                         screen_text=cmd.screen_text or "")
                await send({"type": "reply", "text": turn.reply, "route": turn.route, "spoken": turn.spoken,
                            "session_id": cmd.session_id})
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
            if kind == "context":
                try:
                    await awareness.receive(awareness.DeviceContext(**(msg.get("context") or {})))
                except ValueError:
                    pass
                continue
            if kind == "notification":
                try:
                    await notifications.receive(notifications.Notification(**(msg.get("notification") or {})), device["id"])
                except ValueError:
                    pass
                continue
            if kind == "stage_event":
                await stage.on_event(str(msg.get("id") or ""), str(msg.get("event") or ""),
                                     msg.get("detail") if isinstance(msg.get("detail"), dict) else None)
                continue
            if kind == "utterance":
                # v0.7+: the phone's VAD cut one utterance; transcribe here with the owner's chosen engine.
                import base64
                try:
                    pcm = base64.b64decode(msg.get("audio") or "", validate=True)
                except ValueError:
                    pcm = b""
                if not 3200 <= len(pcm) <= MAX_UTTERANCE_BYTES:
                    await send({"type": "error", "message": "audio ucapan tidak valid", "session_id": msg.get("session_id")})
                    continue

                async def hear(m: dict = msg, pcm: bytes = pcm) -> None:
                    sid = str(m.get("session_id") or "")[:128] or "voice"
                    try:
                        heard = await stt.transcribe_with_voice(pcm)
                    except stt.SttError as e:
                        await send({"type": "transcript", "seq": m.get("seq"), "text": "", "error": str(e)[:200], "session_id": sid})
                        return
                    await send({"type": "transcript", "seq": m.get("seq"), "text": heard["text"], "engine": heard["engine"],
                                "confidence": heard.get("confidence"), "is_owner": heard.get("is_owner"), "session_id": sid})
                    if not heard["text"]:
                        await send({"type": "reply", "text": "", "route": "silent", "spoken": False, "session_id": sid})
                        return
                    meta = {k: heard[k] for k in ("confidence", "speakers", "owner_voice", "is_owner", "stt_ms", "engine") if k in heard}
                    try:
                        cmd = Command(user_command=heard["text"], session_id=sid, location=m.get("location"),
                                      screen=m.get("screen"), image_source=m.get("image_source"), stt=meta,
                                      screen_text=m.get("screen_text"))
                    except ValueError:
                        return
                    await run(cmd)
                task = asyncio.create_task(hear())
                tasks.add(task)
                task.add_done_callback(tasks.discard)
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
                              location=msg.get("location"), screen=msg.get("screen"),
                              image_source=msg.get("image_source"), stt=msg.get("stt"), screen_text=msg.get("screen_text"))
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


def _tools_auth(request: Request) -> None:
    # Only the MCP tool server on jarvis-network may call these; never through the public proxy.
    _internal_only(request)
    if not settings.mcp_token or not hmac.compare_digest(request.headers.get("x-internal-token", ""), settings.mcp_token):
        raise HTTPException(404)


@app.get("/internal/self")
async def internal_self(request: Request):
    _tools_auth(request)
    return {"self": await self_model.describe(full=True)}


@app.post("/internal/media")
async def internal_media(m: MediaIn, request: Request):
    _tools_auth(request)
    return await media.show(m.items, m.caption, "hermes")


class StageIn(BaseModel):
    action: str = Field(pattern="^(show|update|close)$")
    panel: str | None = None
    payload: dict = Field(default_factory=dict)
    caption: str = ""
    stage_id: str | None = None


@app.post("/internal/stage")
async def internal_stage(s: StageIn, request: Request):
    _tools_auth(request)
    try:
        if s.action == "show":
            return await stage.show(s.panel or "", s.payload, s.caption, "hermes")
        if s.action == "update":
            return await stage.update(s.stage_id or "", s.payload)
        return await stage.close(s.stage_id)
    except stage.StageError as e:
        raise HTTPException(422, str(e))


class NotifyIn(BaseModel):
    text: str = Field(min_length=1, max_length=2000)
    task_id: int | None = None


@app.post("/internal/notify")
async def internal_notify(n: NotifyIn, request: Request):
    _tools_auth(request)
    r = await reports._create(n.task_id, "system", n.text)
    return {"report_id": r["id"]}


class AskIn(BaseModel):
    question: str = Field(min_length=3, max_length=1000)
    task_id: int | None = None


@app.post("/internal/ask")
async def internal_ask(a: AskIn, request: Request):
    _tools_auth(request)
    q = await questions.ask(a.question, a.task_id)
    return {"question_id": q["id"]}


class PlayIn(BaseModel):
    query: str = Field(min_length=1, max_length=200)


@app.post("/internal/play_music")
async def internal_play(p: PlayIn, request: Request):
    _tools_auth(request)
    from . import media_tools
    return await media_tools.play(p.query)


class RouteIn(BaseModel):
    destination: str = Field(min_length=1, max_length=200)
    origin: str = Field(default="", max_length=200)
    mode: str = "driving"


@app.post("/internal/route")
async def internal_route(r: RouteIn, request: Request):
    _tools_auth(request)
    from . import media_tools
    return await media_tools.route(r.destination, r.origin, r.mode)


class MemorySearchIn(BaseModel):
    query: str = Field(min_length=1, max_length=4000)
    limit: int = Field(default=6, ge=1, le=20)


@app.post("/internal/memory/search")
async def internal_memory_search(m: MemorySearchIn, request: Request):
    """Hermes' jarvis-memory provider: recall before each turn."""
    _tools_auth(request)
    hits = await memory.search(m.query, limit=m.limit)
    return {"hits": jsonable([{k: h[k] for k in ("id", "text", "category", "kind", "score")} for h in hits])}


class InternalMemoryIn(BaseModel):
    text: str = Field(min_length=1, max_length=4000)
    category: str = "experience"
    kind: str = "fact"


@app.post("/internal/memory/save")
async def internal_memory_save(m: InternalMemoryIn, request: Request):
    """Hermes' built-in memory tool writes are mirrored into JARVIS' one memory."""
    _tools_auth(request)
    try:
        row = await memory.save(m.text, m.category, source="hermes", kind=m.kind)
    except memory.MemoryError_ as e:
        return {"saved": False, "reason": str(e)}
    return {"saved": True, "id": str(row["id"])}


# ---------- meetings (owner's phone) ----------

class MeetingIn(BaseModel):
    title: str = Field(default="", max_length=150)
    confidential: bool = False
    consent: bool


@app.post("/api/v1/meetings")
async def meeting_create(m: MeetingIn, device: dict = Depends(owner_device_auth)):
    try:
        return jsonable(await meetings.create(m.title, m.confidential, m.consent, device["id"], f"device:{device['name']}"))
    except meetings.MeetingError as e:
        raise HTTPException(422, str(e))


@app.put("/api/v1/meetings/{meeting_id}/chunks/{n}")
async def meeting_chunk(meeting_id: str, n: int, request: Request, device: dict = Depends(owner_device_auth)):
    try:
        return await meetings.add_chunk(meeting_id, n, await request.body())
    except (meetings.MeetingError, ValueError) as e:
        raise HTTPException(422, str(e))


class MarkIn(BaseModel):
    t: float = Field(ge=0)
    note: str = Field(default="penting", max_length=200)


@app.post("/api/v1/meetings/{meeting_id}/marks")
async def meeting_mark(meeting_id: str, m: MarkIn, device: dict = Depends(owner_device_auth)):
    await meetings.mark(meeting_id, m.t, m.note)
    return {"ok": True}


class FinishIn(BaseModel):
    duration_s: float | None = None
    chunks: int | None = None


@app.post("/api/v1/meetings/{meeting_id}/finish")
async def meeting_finish(meeting_id: str, f: FinishIn, device: dict = Depends(owner_device_auth)):
    try:
        return await meetings.finish(meeting_id, f.duration_s, f.chunks, f"device:{device['name']}")
    except meetings.MeetingError as e:
        raise HTTPException(422, str(e))


@app.get("/api/v1/meetings")
async def meeting_list(device: dict = Depends(owner_device_auth)):
    return jsonable(await meetings.list_())


@app.get("/api/v1/meetings/{meeting_id}")
async def meeting_get(meeting_id: str, device: dict = Depends(owner_device_auth)):
    m = await meetings.get(meeting_id)
    if not m:
        raise HTTPException(404, "rapat tidak ditemukan")
    return jsonable(m)


@app.get("/api/v1/meetings/{meeting_id}/chunks/{n}")
async def meeting_audio(meeting_id: str, n: int, device: dict = Depends(owner_device_auth)):
    path = meetings.chunk_path(meeting_id, n)
    if not path:
        raise HTTPException(404, "audio tidak ada (mungkin sudah dihapus otomatis)")
    return FileResponse(path, media_type="audio/ogg")


class AskMeetingIn(BaseModel):
    question: str = Field(min_length=2, max_length=500)


@app.post("/api/v1/meetings/{meeting_id}/ask")
async def meeting_ask(meeting_id: str, q: AskMeetingIn, device: dict = Depends(owner_device_auth)):
    try:
        return await meetings.ask(meeting_id, q.question)
    except meetings.MeetingError as e:
        raise HTTPException(422, str(e))


@app.delete("/api/v1/meetings/{meeting_id}")
async def meeting_delete(meeting_id: str, device: dict = Depends(owner_device_auth)):
    return {"deleted": await meetings.delete(meeting_id, f"device:{device['name']}")}


# ---------- media JARVIS fetched (music) ----------

@app.get("/api/v1/media/{media_id}")
async def media_file(media_id: str, device: dict = Depends(device_auth)):
    from . import musiclib
    found = musiclib.find(media_id)
    if not found:
        raise HTTPException(404, "media tidak ditemukan")
    path, ctype = found
    return FileResponse(path, media_type=ctype)  # Range requests supported (seeking)


# ---------- documents ----------

@app.get("/api/v1/documents/{doc_id}")
async def document_get(doc_id: str, device: dict = Depends(device_auth)):
    found = await documents.get(doc_id)
    if not found:
        raise HTTPException(404, "dokumen tidak ditemukan")
    row, path = found
    return FileResponse(path, media_type=documents.FORMATS[row["format"]],
                        filename=f"{row['title'][:60]}.{row['format']}")


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
    scope: str = Field(default="owner", pattern="^(owner|basic)$")


@app.get("/admin/devices")
async def admin_devices(_: str = admin):
    return await devices.list_()


@app.post("/admin/devices")
async def admin_device_create(d: DeviceIn, actor: str = admin):
    device, token = await devices.create(d.name, actor, d.scope)
    return {**device, "token": token}  # shown once in the admin UI


@app.delete("/admin/devices/{device_id}")
async def admin_device_revoke(device_id: str, actor: str = admin):
    return {"revoked": await devices.revoke(device_id, actor)}


@app.get("/admin/usage")
async def admin_usage(_: str = admin):
    return {"local": await usage.local_summary(), "openrouter": await usage.openrouter_summary()}


@app.get("/admin/documents")
async def admin_documents(_: str = admin):
    return jsonable(await documents.list_())


@app.get("/admin/documents/{doc_id}")
async def admin_document_get(doc_id: str, _: str = admin):
    found = await documents.get(doc_id)
    if not found:
        raise HTTPException(404, "dokumen tidak ditemukan")
    row, path = found
    return FileResponse(path, media_type=documents.FORMATS[row["format"]], filename=f"{row['title'][:60]}.{row['format']}")


@app.get("/admin/meetings")
async def admin_meetings(_: str = admin):
    return jsonable(await meetings.list_())


@app.get("/admin/hermes-studio")
async def admin_hermes_studio(_: str = admin):
    return jsonable(hermes_studio.studio())


@app.get("/admin/composition")
async def admin_composition(_: str = admin):
    return jsonable(await composition.get())


@app.get("/admin/llm-usage")
async def admin_llm_usage(days: int = 30, _: str = admin):
    rows = await db.pool().fetch(
        """SELECT date_trunc('day', at AT TIME ZONE 'Asia/Jakarta')::date AS day, category, provider, model,
                  count(*) AS calls, count(*) FILTER (WHERE NOT ok) AS failed,
                  coalesce(sum(prompt_tokens), 0) AS prompt_tokens, coalesce(sum(cached_tokens), 0) AS cached_tokens,
                  coalesce(sum(completion_tokens), 0) AS completion_tokens, coalesce(sum(cost_usd), 0)::float AS cost_usd,
                  avg(first_token_ms)::int AS first_token_ms
           FROM llm_usage WHERE at > now() - make_interval(days => $1)
           GROUP BY 1, 2, 3, 4 ORDER BY 1 DESC, cost_usd DESC""", min(days, 90))
    latency = await db.pool().fetch(
        """SELECT created_at, trace FROM messages WHERE trace IS NOT NULL ORDER BY id DESC LIMIT 50""")
    return jsonable({"budget": await budget.state(force=True), "rows": [dict(r) for r in rows],
                     "latency": [dict(r) for r in latency]})


@app.get("/admin/self")
async def admin_self(_: str = admin):
    ctx = awareness.current()
    return {"self": await self_model.describe(full=True), "improvements": await selfimprove.recent(),
            "situation": awareness.situation(), "context": ctx.model_dump() if ctx else None}


@app.post("/admin/selfcheck")
async def admin_selfcheck(actor: str = admin):
    t = await selfimprove.start("", actor)
    return {"task_id": t["id"]}


@app.post("/admin/improvements/{improvement_id}/revert")
async def admin_improvement_revert(improvement_id: int, actor: str = admin):
    return {"reverted": await selfimprove.revert(improvement_id, actor)}


@app.get("/admin/notifications")
async def admin_notifications(_: str = admin):
    return await notifications.recent(50)


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


# ---------- console extras that live in jarvis-admin (.env settings, APK releases) ----------

ADMIN_URL = "http://jarvis-admin:8000"


async def _admin_internal(method: str, path: str, **kw):
    import httpx
    try:
        async with httpx.AsyncClient(timeout=60) as c:
            return await c.request(method, ADMIN_URL + path, headers={"X-Admin-Token": settings.admin_token}, **kw)
    except httpx.HTTPError as e:
        raise HTTPException(502, f"web admin tidak dapat dihubungi ({type(e).__name__})")


@app.get(CONSOLE + "/settings")
async def console_settings(device: dict = Depends(owner_device_auth)):
    r = await _admin_internal("GET", "/internal/settings")
    return JSONResponse(r.json(), status_code=r.status_code)


@app.post(CONSOLE + "/settings")
async def console_settings_save(body: dict = Body(...), device: dict = Depends(owner_device_auth)):
    r = await _admin_internal("POST", "/internal/settings", json=body)
    if r.status_code == 200 and r.json().get("saved"):
        await audit.record(f"device:{device['name']}", "settings.saved", None, keys=r.json()["saved"])
    return JSONResponse(r.json(), status_code=r.status_code)


@app.get(CONSOLE + "/releases")
async def console_releases(device: dict = Depends(owner_device_auth)):
    r = await _admin_internal("GET", "/internal/releases")
    return JSONResponse(r.json(), status_code=r.status_code)


@app.get(CONSOLE + "/releases/{name}")
async def console_release_file(name: str, device: dict = Depends(owner_device_auth)):
    import re as _re
    if not _re.fullmatch(r"jarvis-\d+\.\d+\.\d+\.apk", name):
        raise HTTPException(404)
    r = await _admin_internal("GET", f"/internal/releases/{name}")
    if r.status_code != 200:
        raise HTTPException(404, "rilis tidak ditemukan")
    from fastapi.responses import Response
    return Response(r.content, media_type="application/vnd.android.package-archive",
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})


# ---------- console: the web admin, on the owner's phone ----------
# Every /admin/* endpoint is also served at /api/v1/console/* (owner-scope device token, through the
# public proxy). Same handlers, same audit trail; admin_auth tells the two callers apart.
for _route in list(app.routes):
    _path = getattr(_route, "path", "")
    if _path.startswith("/admin/") and _path != "/admin/chat":
        app.add_api_route(CONSOLE + _path[len("/admin"):], _route.endpoint, methods=list(_route.methods),
                          include_in_schema=False)
