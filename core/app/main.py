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
import re
import logging
import time
from datetime import datetime

from fastapi import Body, Depends, FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from . import assistant
from . import (approvals, spike, attachments, audit, auditor, awareness, canvas, capabilities, companies, gm, kpi, skills_pipeline, episodes, goals, library, modelinsight, openrouter, playlists, brain, budget, chat, dev, errors, hermes_studio, meetings, perf, vault, composition, db, deepgram, devices, documents, gateway, hub,
               media, memory, musiclib, notifications, ops, overrides, questions, reports, self_model, selfimprove, stage, status,
               sensitive, stt, usage, voice, voice_id, workers)
from .config import settings
from .location import Location

log = logging.getLogger("jarvis-core")


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    await db.connect(settings.database_url)
    error_writer = errors.install("core")
    try:
        await db.grant_readonly(db.pool())
    except Exception as e:
        log.warning("read-only grants not applied: %s", e)
    try:
        await memory.ensure_collection()
    except Exception as e:  # Qdrant down must not keep chat from starting
        log.warning("memory collection not ready: %s", e)
    try:
        log.info("capabilities: %s", await capabilities.sync(assistant.TOOLS))
    except Exception as e:  # the registry is a convenience: JARVIS starts without it
        log.warning("capability sync failed: %s", e)
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
            await library.purge_media()
            attachments.purge_old()
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

    async def self_improvement():
        # Performance self-improvement (ADR-026): runner results, recurring-error repairs, weekly review.
        last_review, last_sync, last_maintained = None, 0.0, None
        while True:
            try:
                if time.monotonic() - last_sync > 3600:  # skills Hermes wrote itself show up in the registry within the hour
                    last_sync = time.monotonic()
                    try:
                        await capabilities.sync(assistant.TOOLS)
                    except Exception:
                        log.exception("capability sync failed")  # never at the expense of the rest of this loop
                await ops.tick()  # CPU reading, worker-model CPU limit, orphan watchdog
                if datetime.now(awareness.WIB).hour == 3 and last_maintained != datetime.now(awareness.WIB).date() and (await ops.background_ok())[0]:
                    last_maintained = datetime.now(awareness.WIB).date()  # memory upkeep once a night (ADR-040)
                    log.info("memory upkeep: %s, old failed episodes pruned: %s", await memory.maintain(), await episodes.prune())
                await dev.poll()
                await skills_pipeline.poll()  # sandbox results of skills being tested
                await gm.tick()  # Company Federation: due sends, callback deadlines, rejections to relay (ADR-042)
                if datetime.now(awareness.WIB).hour == 4:
                    await voice.nightly()  # speech complements: prune old utterances, run the quality gate (ADR-048)
                await perf.watch_recurring_errors()
                if (await ops.background_ok())[0] and await auditor.due():  # flow watcher (ADR-028): after a conversation pauses
                    await auditor.run()
                if perf.weekly_due(last_review) and not await perf.reviewed_today():
                    last_review = __import__("datetime").datetime.now(awareness.WIB).date()
                    await perf.start_review()
            except Exception:
                log.exception("self-improvement loop failed")
            await asyncio.sleep(20)
    improver = asyncio.create_task(self_improvement())
    aware = asyncio.create_task(awareness.run_forever())
    selfcheck = asyncio.create_task(selfcheck_daily())
    yield
    for t in (ticker, purger, aware, selfcheck, cron, meeting_worker, warm, error_writer, improver):
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
    image_source: str | None = Field(default=None, pattern="^(screen|camera|attachment)$")
    # How speech recognition heard it: {"confidence": 0..1, "speakers": n}
    stt: dict | None = None
    # Text the phone read from the shared screen (ML Kit) / the WhatsApp notification thread
    screen_text: str | None = Field(default=None, max_length=20000)
    # ids from POST /api/v1/attachments (photos, PDF, Word, Excel, PowerPoint, text)
    attachments: list[str] = Field(default_factory=list, max_length=5)


class AttachmentIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    content_type: str = Field(default="", max_length=100)
    data: str = Field(min_length=4, max_length=17_000_000)  # base64, ≤ 12 MB of file
    ocr_text: str = Field(default="", max_length=20000)  # text the phone's ML Kit read from a picture


@app.post("/api/v1/attachments")
async def upload_attachment(a: AttachmentIn, device: dict = Depends(device_auth)):
    try:
        m = await attachments.save(a.name, a.content_type, a.data, a.ocr_text, f"device:{device['name']}")
    except attachments.AttachmentError as e:
        raise HTTPException(422, str(e))
    await audit.record(f"device:{device['name']}", "attachment.saved", f"attachment:{m['id']}", kind=m["kind"], size=m["size"])
    return m


@app.get("/healthz")
async def healthz():
    return {"ok": True}


YT_EMBED = """<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><meta name="referrer" content="strict-origin-when-cross-origin">
<style>html,body{margin:0;height:100%;background:#000;overflow:hidden}#p{width:100%;height:100%}</style></head><body><div id="p"></div>
<script>
function tell(s){document.title=s;try{fetch("/embed/youtube/__ID__/state?s="+encodeURIComponent(s),{keepalive:true});}catch(e){}}
var s=document.createElement("script");s.src="https://www.youtube.com/iframe_api";s.onerror=function(){tell("error:api")};
document.head.appendChild(s);
setTimeout(function(){if(!window.YT||!YT.Player)tell("error:api-timeout")},15000);
function onYouTubeIframeAPIReady(){
  new YT.Player("p",{videoId:"__ID__",width:"100%",height:"100%",
    playerVars:{autoplay:0,playsinline:1,rel:0,modestbranding:1,origin:location.origin},
    events:{onReady:function(){tell("ready")},
            onStateChange:function(e){var t={"0":"ended","1":"playing","2":"paused","3":"buffering"}[e.data];if(t)tell(t);},
            onError:function(e){tell("error:"+e.data);}}});
}
</script></body></html>"""


@app.get("/embed/youtube/{video_id}", response_class=HTMLResponse)
async def youtube_embed(video_id: str, autoplay: int = 1):
    """The official YouTube player, served from JARVIS' own https origin. YouTube refuses embeds without a valid
    origin/referrer (error 152/153), which is what a page made inside the app's WebView has (ADR-034). The page's
    title tells the app when the video ended (playlists) — no JavaScript bridge into the app."""
    import re as _re
    if not _re.fullmatch(r"[A-Za-z0-9_-]{11}", video_id):
        raise HTTPException(404)
    return HTMLResponse(YT_EMBED.replace("__ID__", video_id).replace("__AUTO__", "1" if autoplay else "0"),
                        headers={"Cache-Control": "no-cache"})


@app.get("/embed/youtube/{video_id}/state")
async def youtube_embed_state(video_id: str, s: str = ""):
    """What the player did on the phone (ready / playing / error:153 …): only logged, to diagnose playback."""
    log.info("youtube %s: %s", video_id[:11], re.sub(r"[^a-z0-9:-]", "", s.lower())[:20])
    return {"ok": True}


@app.post("/api/v1/gm/callback/{company_id}")
async def gm_callback(company_id: str, request: Request):
    """Hermes-DGM reports back (public, no device token): HMAC-SHA256 of "<X-Jarvis-Timestamp>.<body>" with the
    company's callback secret in X-Jarvis-Signature. Format = blueprint v3 draft, BELUM DIVERIFIKASI."""
    raw = await request.body()
    if len(raw) > 200_000:
        raise HTTPException(413, "terlalu besar")
    try:
        return await gm.callback(company_id, raw, request.headers.get("x-jarvis-timestamp", ""),
                                 request.headers.get("x-jarvis-signature", ""))
    except companies.CompanyError:
        raise HTTPException(404, "tidak dikenal")
    except gm.GMError as e:
        raise HTTPException(401 if "tanda tangan" in str(e) else 422, str(e))


@app.post("/api/v1/chat")
async def chat_rest(cmd: Command, device: dict = Depends(device_auth)):
    turn = await chat.handle(cmd.user_command, cmd.session_id, actor=f"device:{device['name']}",
                             device_id=device["id"], location=cmd.location, attachment_ids=cmd.attachments)
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


# ---------- password manager (owner's phone) ----------

class VaultIn(BaseModel):
    url: str = Field(min_length=3, max_length=500)
    username: str = Field(min_length=1, max_length=200)
    password: str = Field(min_length=1, max_length=500)
    label: str = Field(default="", max_length=100)
    note: str = Field(default="", max_length=500)
    allow_agent: bool = False


class VaultPatch(BaseModel):
    label: str | None = Field(default=None, max_length=100)
    username: str | None = Field(default=None, max_length=200)
    password: str | None = Field(default=None, max_length=500)
    note: str | None = Field(default=None, max_length=500)
    allow_agent: bool | None = None


class VaultMatch(BaseModel):
    url: str = Field(min_length=3, max_length=2000)


@app.get("/api/v1/vault")
async def vault_list(device: dict = Depends(owner_device_auth)):
    return jsonable(await vault.list_())


@app.post("/api/v1/vault")
async def vault_save(v: VaultIn, device: dict = Depends(owner_device_auth)):
    try:
        return jsonable(await vault.save(v.url, v.username, v.password, f"device:{device['name']}", v.label, v.note, v.allow_agent))
    except vault.VaultError as e:
        raise HTTPException(422, str(e))


@app.patch("/api/v1/vault/{entry_id}")
async def vault_update(entry_id: str, v: VaultPatch, device: dict = Depends(owner_device_auth)):
    try:
        return jsonable(await vault.update(entry_id, f"device:{device['name']}", **v.model_dump()))
    except (vault.VaultError, ValueError) as e:
        raise HTTPException(422, str(e))


@app.delete("/api/v1/vault/{entry_id}")
async def vault_delete(entry_id: str, device: dict = Depends(owner_device_auth)):
    try:
        return {"deleted": await vault.delete(entry_id, f"device:{device['name']}")}
    except ValueError:
        raise HTTPException(404)


@app.post("/api/v1/vault/{entry_id}/reveal")
async def vault_reveal(entry_id: str, device: dict = Depends(owner_device_auth)):
    try:
        return jsonable(await vault.reveal(entry_id, f"device:{device['name']}"))
    except (vault.VaultError, ValueError) as e:
        raise HTTPException(404, str(e))


@app.post("/api/v1/vault/match")
async def vault_match(m: VaultMatch, device: dict = Depends(owner_device_auth)):
    """Login page open in the phone's web panel: the saved logins for it (autofill)."""
    try:
        return jsonable(await vault.match(m.url, f"device:{device['name']}"))
    except vault.VaultError as e:
        raise HTTPException(422, str(e))


# ---------- app updates (every device) ----------

@app.get("/api/v1/app/latest")
async def app_latest(device: dict = Depends(device_auth)):
    """Newest published APK, so the app can offer "Update sekarang / Tunda"."""
    r = await _admin_internal("GET", "/internal/releases")
    releases = r.json().get("releases", []) if r.status_code == 200 else []
    if not releases:
        return {"latest": None}
    top = max(releases, key=lambda x: x.get("code", 0))
    return {"latest": {k: top.get(k) for k in ("version", "code", "file", "size", "sha256", "date", "notes")}}


@app.get("/api/v1/app/releases/{name}")
async def app_release_file(name: str, device: dict = Depends(device_auth)):
    import re as _re
    if not _re.fullmatch(r"jarvis-\d+\.\d+\.\d+\.apk", name):
        raise HTTPException(404)
    r = await _admin_internal("GET", f"/internal/releases/{name}")
    if r.status_code != 200:
        raise HTTPException(404, "rilis tidak ditemukan")
    from fastapi.responses import Response
    return Response(r.content, media_type="application/vnd.android.package-archive",
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})


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


class ModelPick(BaseModel):
    category: str = Field(min_length=2, max_length=30)
    model: str = Field(min_length=1, max_length=120)
    provider: str = Field(default="openrouter", max_length=30)
    role: str = Field(default="utama", pattern="^(utama|cadangan)$")
    confirmed: bool = False


@app.put("/api/v1/composition/model")
async def composition_model(p: ModelPick, device: dict = Depends(owner_device_auth)):
    """The app's model picker: make this model the main one (or a fallback) of a category."""
    try:
        return jsonable(await composition.set_model(p.category, p.model, f"device:{device['name']}", provider=p.provider,
                                                    role=p.role, confirmed=p.confirmed))
    except composition.CompositionError as e:
        raise HTTPException(422, str(e))


# ---------- voice (Blueprint v4 Fase 3, ADR-048): JARVIS's cloud voice and the owner's corrections ----------

@app.get("/api/v1/voice")
async def voice_get(device: dict = Depends(device_auth)):
    return jsonable(await voice.options())


class VoiceIn(BaseModel):
    tts: dict | None = None
    stt_model: str | None = Field(default=None, max_length=120)


@app.put("/api/v1/voice")
async def voice_put(v: VoiceIn, device: dict = Depends(owner_device_auth)):
    try:
        return jsonable(await voice.set_settings(v.model_dump(exclude_none=True), f"device:{device['name']}"))
    except voice.VoiceError as e:
        raise HTTPException(e.status, str(e))


class SpeakIn(BaseModel):
    text: str = Field(min_length=1, max_length=4000)


@app.post("/api/v1/voice/speak")
async def voice_speak(s: SpeakIn, device: dict = Depends(device_auth)):
    """One sentence in the owner's cloud voice (audio/mpeg). Any error status = the phone speaks it with its own voice."""
    from fastapi.responses import Response
    try:
        return Response(await voice.synthesize(s.text), media_type="audio/mpeg")
    except voice.VoiceError as e:
        raise HTTPException(e.status, str(e))


class VoicePreviewIn(BaseModel):
    model: str = Field(min_length=3, max_length=120)
    voice: str = Field(default="", max_length=60)


@app.post("/api/v1/voice/preview")
async def voice_preview(p: VoicePreviewIn, device: dict = Depends(owner_device_auth)):
    """'Coba' on the Suara screen: a short sample of a model + character, without choosing it."""
    from fastapi.responses import Response
    try:
        return Response(await voice.synthesize(voice.SAMPLE_TEXT, p.model, p.voice or None, preview=True), media_type="audio/mpeg")
    except voice.VoiceError as e:
        raise HTTPException(e.status, str(e))


class VoiceCorrectIn(BaseModel):
    event_id: int
    text: str | None = Field(default=None, max_length=1000)   # what the owner really said
    not_me: bool = False                                       # it was not the owner speaking (or nobody)


@app.post("/api/v1/voice/correct")
async def voice_correct(c: VoiceCorrectIn, device: dict = Depends(owner_device_auth)):
    try:
        return await voice.correct(event_id=c.event_id, full=c.text, not_me=c.not_me, source="owner_app",
                                   actor=f"device:{device['name']}")
    except voice.VoiceError as e:
        raise HTTPException(e.status, str(e))


# ---------- the 3D canvas (Blueprint v4 Fase 4, ADR-049): galaxies of cards, layout only ----------

def _canvas_error(e: Exception) -> HTTPException:
    return HTTPException(404 if "tidak ada" in str(e) else 422, str(e))


@app.get("/api/v1/canvases")
async def canvases_list(device: dict = Depends(device_auth)):
    return jsonable(await canvas.contexts())


class CanvasIn(BaseModel):
    context: str = Field(min_length=1, max_length=80)     # "utama", "project:Toko Online", "company:renature"
    title: str | None = Field(default=None, max_length=80)


@app.post("/api/v1/canvases")
async def canvases_open(c: CanvasIn, device: dict = Depends(owner_device_auth)):
    try:
        return jsonable(await canvas.ensure(c.context, c.title))
    except (canvas.CanvasError, companies.CompanyError) as e:
        raise _canvas_error(e)


@app.get("/api/v1/canvases/{canvas_id}")
async def canvases_view(canvas_id: int, since: int | None = None, device: dict = Depends(device_auth)):
    try:
        return jsonable(await canvas.view(canvas_id, since))
    except canvas.CanvasError as e:
        raise _canvas_error(e)


@app.get("/api/v1/canvases/{canvas_id}/search")
async def canvases_search(canvas_id: int, q: str = "", device: dict = Depends(owner_device_auth)):
    try:
        row = await canvas._canvas_row(canvas_id)
        return jsonable(await canvas.search_refs(row["context"], q[:80]))
    except canvas.CanvasError as e:
        raise _canvas_error(e)


class CardIn(BaseModel):
    ref: str = Field(min_length=3, max_length=80)
    x: float | None = None
    y: float | None = None
    z: float | None = None


@app.post("/api/v1/canvases/{canvas_id}/cards")
async def canvases_add_card(canvas_id: int, c: CardIn, device: dict = Depends(owner_device_auth)):
    try:
        row = await canvas._canvas_row(canvas_id)
        pos = (c.x, c.y, c.z) if None not in (c.x, c.y, c.z) else None
        return jsonable(await canvas.add(row["context"], c.ref, f"device:{device['name']}", pos))
    except (canvas.CanvasError, companies.CompanyError) as e:
        raise _canvas_error(e)


class CardPatch(BaseModel):
    x: float | None = None
    y: float | None = None
    z: float | None = None
    size: float | None = None
    pinned: bool | None = None


@app.patch("/api/v1/canvas/cards/{node_id}")
async def canvases_move_card(node_id: int, p: CardPatch, device: dict = Depends(owner_device_auth)):
    try:
        return jsonable(await canvas.move(node_id, f"device:{device['name']}", **p.model_dump()))
    except canvas.CanvasError as e:
        raise _canvas_error(e)


@app.delete("/api/v1/canvas/cards/{node_id}")
async def canvases_hide_card(node_id: int, device: dict = Depends(owner_device_auth)):
    """Takes the card off the canvas only; what it points at is never deleted from here."""
    try:
        return {"hidden": await canvas.hide(node_id, f"device:{device['name']}")}
    except canvas.CanvasError as e:
        raise _canvas_error(e)


class EdgeIn(BaseModel):
    a: int
    b: int
    label: str = Field(default="", max_length=60)


@app.post("/api/v1/canvases/{canvas_id}/edges")
async def canvases_link(canvas_id: int, e: EdgeIn, device: dict = Depends(owner_device_auth)):
    try:
        return jsonable(await canvas.link(e.a, e.b, f"device:{device['name']}", e.label))
    except canvas.CanvasError as err:
        raise _canvas_error(err)


@app.delete("/api/v1/canvases/{canvas_id}/edges/{edge_id}")
async def canvases_unlink(canvas_id: int, edge_id: int, device: dict = Depends(owner_device_auth)):
    try:
        return {"removed": await canvas.unlink(edge_id, canvas_id, f"device:{device['name']}")}
    except canvas.CanvasError as e:
        raise _canvas_error(e)


@app.get("/api/v1/canvases/{canvas_id}/versions")
async def canvases_versions(canvas_id: int, device: dict = Depends(device_auth)):
    try:
        return jsonable(await canvas.versions(canvas_id))
    except canvas.CanvasError as e:
        raise _canvas_error(e)


class RestoreIn(BaseModel):
    version: int


@app.post("/api/v1/canvases/{canvas_id}/restore")
async def canvases_restore(canvas_id: int, r: RestoreIn, device: dict = Depends(owner_device_auth)):
    try:
        return await canvas.restore(canvas_id, r.version, f"device:{device['name']}")
    except canvas.CanvasError as e:
        raise _canvas_error(e)


_CANVAS_DIR = __import__("pathlib").Path(__file__).parent / "web" / "canvas"
# The viewer and the gesture prototype: static, same origin as the API. Hand tracking (MediaPipe) runs in the browser:
# its code and model come from jsdelivr / Google storage, camera frames never leave the device.
_CANVAS_CSP = ("default-src 'self'; script-src 'self' 'wasm-unsafe-eval' https://cdn.jsdelivr.net; "
               "connect-src 'self' https://cdn.jsdelivr.net https://storage.googleapis.com; img-src 'self' https: data: blob:; "
               "media-src 'self' https: blob:; style-src 'self' 'unsafe-inline'; worker-src 'self' blob:; frame-ancestors 'none'")


@app.get("/canvas")
async def canvas_root():
    from fastapi.responses import RedirectResponse
    return RedirectResponse("/canvas/")


@app.get("/canvas/{path:path}")
async def canvas_static(path: str):
    name = path or "index.html"
    target = (_CANVAS_DIR / name).resolve()
    if not str(target).startswith(str(_CANVAS_DIR.resolve())) or not target.is_file():
        raise HTTPException(404)
    return FileResponse(target, headers={"Content-Security-Policy": _CANVAS_CSP, "X-Content-Type-Options": "nosniff",
                                         "Cache-Control": "no-cache"})


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

async def _gateway_auth(request: Request) -> str:
    """The caller: 'hermes' (LLM_GATEWAY_KEY) or 'spike-<runtime>' (a spike key, category 'spike' only, ADR-043)."""
    _internal_only(request)
    key = _bearer(request.headers.get("authorization")) or ""
    if settings.llm_gateway_key and hmac.compare_digest(key, settings.llm_gateway_key):
        return "hermes"
    if caller := await spike.caller_for(key):
        return caller
    raise HTTPException(401, "invalid gateway key")


@app.get("/llm/v1/models")
async def llm_models(request: Request):
    caller = await _gateway_auth(request)
    models = await gateway.model_list()
    if caller != "hermes":
        models = [m for m in models if gateway.category_of_alias(str(m.get("id") or "")) == spike.CATEGORY]
    return {"object": "list", "data": models}


@app.post("/llm/v1/chat/completions")
async def llm_chat(request: Request, body: dict = Body(...)):
    caller = await _gateway_auth(request)
    category = gateway.category_of_alias(str(body.get("model") or ""))
    if category not in await gateway.categories():
        raise HTTPException(404, f"model tidak dikenal: {body.get('model')}")
    if caller != "hermes" and category != spike.CATEGORY:
        raise HTTPException(403, "kunci uji hanya untuk kategori spike")
    session = request.headers.get("x-session-id") or (str(body.get("user")) if body.get("user") else None)
    private = category == "privat"
    if not body.get("stream"):
        try:
            data = await gateway.complete(category, body, caller=caller, session_id=session, private=private, worker=True)
        except gateway.GatewayError as e:
            return JSONResponse({"error": {"message": str(e)[:1000], "type": "gateway_error"}}, status_code=502)
        data.pop("jarvis_route", None)
        return data

    agen = gateway.stream(category, body, caller=caller, session_id=session, private=private, worker=True)
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

    async def send(obj: dict, local_voice: bool = False) -> None:
        obj = await voice.prepare(obj, local_voice)  # the spoken copy (rupiah, dates, pronunciations); private → phone's voice
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
        stopped = [{**t, "status": "stopped"} for t in await workers.stopped()]  # still waiting for retry/close
        await send({"type": "tasks", "items": jsonable(await workers.active() + stopped)})
        if current_stage := stage.current():
            await send(current_stage)
        await reports.on_connect(send)

        async def run(cmd: Command) -> None:
            # a private or sensitive turn, or one about attachments/screen text, is never read out by a cloud voice
            local_voice = bool(sensitive.is_private(cmd.user_command) or sensitive.scan(cmd.user_command)
                               or cmd.attachments or cmd.screen_text)

            async def emit(event: dict) -> None:
                await send({**event, "session_id": cmd.session_id}, local_voice)
            try:
                turn = await chat.handle(cmd.user_command, cmd.session_id, actor=f"device:{device['name']}",
                                         device_id=device["id"], emit=emit, location=cmd.location, screen=cmd.screen,
                                         image_source=cmd.image_source, stt=cmd.stt, speak_live="say" in caps,
                                         screen_text=cmd.screen_text or "", attachment_ids=cmd.attachments)
                await send({"type": "reply", "text": turn.reply, "route": turn.route, "spoken": turn.spoken,
                            "session_id": cmd.session_id}, local_voice)
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
                    try:  # Fase 3 complements: dictionary, echo/hallucination filters, second opinion (each behind its gate)
                        heard = await voice.process(heard, pcm, sid)
                    except Exception:
                        log.exception("voice complements failed; using the engine's text")
                    await send({"type": "transcript", "seq": m.get("seq"), "text": heard["text"], "engine": heard["engine"],
                                "confidence": heard.get("confidence"), "is_owner": heard.get("is_owner"), "session_id": sid,
                                "voice_event": heard.get("voice_event"), "dropped": heard.get("dropped")})
                    if not heard["text"]:
                        await send({"type": "reply", "text": "", "route": "silent", "spoken": False, "session_id": sid})
                        return
                    meta = {k: heard[k] for k in ("confidence", "speakers", "owner_voice", "is_owner", "stt_ms", "engine", "voice_event") if k in heard}
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
                              image_source=msg.get("image_source"), stt=msg.get("stt"), screen_text=msg.get("screen_text"),
                              attachments=msg.get("attachments") or [])
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


@app.get("/internal/attachments/{attachment_id}")
async def internal_attachment_read(attachment_id: str, request: Request, offset: int = 0, limit: int = 6000):
    _tools_auth(request)
    try:
        return attachments.read(attachment_id, offset, limit)
    except attachments.AttachmentError as e:
        raise HTTPException(404, str(e))


class SeeIn(BaseModel):
    question: str = Field(default="Jelaskan isi gambar ini selengkap mungkin.", max_length=500)


@app.post("/internal/attachments/{attachment_id}/see")
async def internal_attachment_see(attachment_id: str, body: SeeIn, request: Request):
    _tools_auth(request)
    try:
        return await attachments.see(attachment_id, body.question)
    except attachments.AttachmentError as e:
        raise HTTPException(404, str(e))


class SkillSubmitIn(BaseModel):
    name: str = Field(min_length=3, max_length=41)
    description: str = Field(min_length=15, max_length=300)
    content: str = Field(min_length=50, max_length=20_000)
    cases: list[dict] = Field(min_length=2, max_length=8)
    scripts: dict[str, str] = Field(default_factory=dict, max_length=3)


@app.post("/internal/skills/submit")
async def internal_skill_submit(body: SkillSubmitIn, request: Request):
    _tools_auth(request)
    try:
        return await skills_pipeline.submit(body.name, body.description, body.content, body.cases, body.scripts)
    except skills_pipeline.SkillError as e:
        raise HTTPException(429, str(e))


@app.get("/internal/skills/{name}")
async def internal_skill_status(name: str, request: Request):
    _tools_auth(request)
    return jsonable(await skills_pipeline.status(name))


@app.get("/internal/capabilities/search")
async def internal_capability_search(request: Request, q: str = "", limit: int = 5):
    _tools_auth(request)
    return {"capabilities": [{k: c[k] for k in ("id", "kind", "name", "description", "status", "tested", "runs", "success_pct", "score")}
                             for c in await capabilities.search(q[:300], limit=max(1, min(limit, 10)))]}


class PlanIn(BaseModel):
    goal: str = Field(default="", max_length=500)
    criteria: list[str] = Field(min_length=1, max_length=8)
    steps: list[str] = Field(min_length=1, max_length=12)


@app.post("/internal/tasks/{task_id}/plan")
async def internal_task_plan(task_id: int, body: PlanIn, request: Request):
    _tools_auth(request)
    if not await workers.set_plan(task_id, body.goal, [c[:200] for c in body.criteria], [s[:200] for s in body.steps]):
        raise HTTPException(409, "tugas itu tidak sedang berjalan")
    return {"saved": True, "phase": "executing"}


class VerifyIn(BaseModel):
    ok: bool
    evidence: str = Field(min_length=1, max_length=2000)
    capabilities_used: list[str] = Field(default_factory=list, max_length=8)


@app.post("/internal/tasks/{task_id}/verify")
async def internal_task_verify(task_id: int, body: VerifyIn, request: Request):
    _tools_auth(request)
    if not await workers.verify(task_id, body.ok, body.evidence, body.capabilities_used):
        raise HTTPException(409, "tugas itu tidak sedang berjalan")
    return {"recorded": True}


@app.get("/internal/self")
async def internal_self(request: Request):
    _tools_auth(request)
    return {"self": await self_model.describe(full=True)}


@app.post("/internal/media")
async def internal_media(m: MediaIn, request: Request):
    _tools_auth(request)
    return await media.show(m.items, m.caption, "hermes")


class StageIn(BaseModel):
    action: str = Field(pattern="^(show|show_any|update|close)$")
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
        if s.action == "show_any":
            return await stage.show_any(s.payload.get("items") or [], s.caption, "hermes")
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


@app.get("/internal/vault/agent")
async def internal_vault_agent(request: Request):
    """Hermes' jarvis plugin syncs owner-allowed logins into its model-blind browser vault."""
    _tools_auth(request)
    try:
        return {"entries": await vault.agent_entries()}
    except vault.VaultError:
        return {"entries": []}


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
    participants: list[str] = Field(default_factory=list, max_length=30)
    agenda: str = Field(default="", max_length=2000)


@app.post("/api/v1/meetings")
async def meeting_create(m: MeetingIn, device: dict = Depends(owner_device_auth)):
    try:
        return jsonable(await meetings.create(m.title, m.confidential, m.consent, device["id"], f"device:{device['name']}",
                                              m.participants, m.agenda))
    except meetings.MeetingError as e:
        raise HTTPException(422, str(e))


@app.put("/api/v1/meetings/{meeting_id}/chunks/{n}")
async def meeting_chunk(meeting_id: str, n: int, request: Request, ext: str = "ogg", device: dict = Depends(owner_device_auth)):
    try:
        return await meetings.add_chunk(meeting_id, n, await request.body(), ext)
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


class SpeakerIn(BaseModel):
    from_: str = Field(alias="from", min_length=1, max_length=60)
    to: str = Field(min_length=1, max_length=60)


@app.post("/api/v1/meetings/{meeting_id}/speakers")
async def meeting_speaker(meeting_id: str, s: SpeakerIn, device: dict = Depends(owner_device_auth)):
    try:
        return await meetings.rename_speaker(meeting_id, s.from_, s.to, f"device:{device['name']}")
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


@app.get("/admin/server-usage")
async def admin_server_usage(_: str = admin):
    """CPU, memory, disk, running work and AI spend — the strip on the phone's home screen."""
    from . import hostinfo
    tasks = await workers.active()
    b = await budget.state()
    snap = await hostinfo.snapshot()
    return {**snap,
            "tasks": {"owner": sum(t["kind"] == "owner" for t in tasks), "background": sum(t["kind"] != "owner" for t in tasks)},
            "ai": {"spent_usd": round(b["spent_usd"], 4), "budget_usd": b["budget_usd"], "pct": b["pct"]},
            "containers": ops.containers(snap["cpu_cores"] or 1)[:6], "who": await ops.who()}


@app.get("/admin/background")
async def admin_background(_: str = admin):
    """What JARVIS does behind the scenes: now, scheduled, last 24 hours, its log — and the 50% rule."""
    return jsonable(await ops.background())


@app.post("/admin/relieve")
async def admin_relieve(actor: str = admin):
    """Netralkan: stop (and keep) all work, quiet background work, free Hermes/worker-model memory on the host."""
    return jsonable(await ops.relieve(actor))


@app.post("/admin/tasks/{task_id}/retry")
async def admin_task_retry(task_id: int, actor: str = admin):
    r = await workers.retry(task_id, actor)
    if not r:
        raise HTTPException(409, "tugas ini tidak bisa diulang")
    return r


@app.post("/admin/tasks/{task_id}/close")
async def admin_task_close(task_id: int, actor: str = admin):
    if not await workers.close(task_id, actor):
        raise HTTPException(409, "tugas ini tidak bisa ditutup")
    return {"closed": task_id}


@app.get("/admin/approvals")
async def admin_approvals(status_: str | None = None, _: str = admin):
    return await approvals.list_(status_)


class Decision(BaseModel):
    approve: bool


@app.post("/admin/approvals/{approval_id}")
async def admin_decide(approval_id: int, d: Decision, request: Request, actor: str = admin):
    # the same handler serves the admin page and (under /api/v1/console) the app; only the former is the control point
    channel = "device" if request.url.path.startswith(CONSOLE + "/") else "admin"
    try:
        return await approvals.decide(approval_id, d.approve, actor, channel=channel)
    except approvals.AdminOnly as e:
        raise HTTPException(403, str(e))
    except approvals.ApprovalError as e:
        raise HTTPException(409, str(e))


def admin_page_only(request: Request) -> None:
    """Some switches belong to the admin page alone (the control point JARVIS cannot change): never the app console."""
    if request.url.path.startswith(CONSOLE + "/"):
        raise HTTPException(403, "hanya bisa diubah di halaman admin")


@app.get("/admin/voice")
async def admin_voice(_: str = admin):
    """Fase 3: how well JARVIS hears (baseline), the complements and their gate, recent utterances, learned data."""
    return jsonable({"baseline": await voice.baseline(), "complements": await voice.modes(),
                     "recent": await voice.recent(40), "data": await voice.data_list(), "tts": await voice.tts_settings()})


class VoiceAdminIn(BaseModel):
    keep_samples: bool | None = None
    second_engine: str | None = None


@app.post("/admin/voice/settings")
async def admin_voice_settings(v: VoiceAdminIn, request: Request, actor: str = admin):
    admin_page_only(request)  # K3 consent and sending audio to a second engine: the owner decides at the control point
    try:
        await voice.set_admin(v.model_dump(exclude_none=True), actor)
    except voice.VoiceError as e:
        raise HTTPException(422, str(e))
    return await voice.baseline()


class VoiceModeIn(BaseModel):
    mode: str


@app.post("/admin/voice/complements/{name}")
async def admin_voice_mode(name: str, m: VoiceModeIn, request: Request, actor: str = admin):
    admin_page_only(request)
    try:
        return await voice.set_mode(name, m.mode, actor)
    except voice.VoiceError as e:
        raise HTTPException(422, str(e))


@app.post("/admin/voice/evaluate")
async def admin_voice_evaluate(actor: str = admin):
    return jsonable(await voice.evaluate(actor))


class VoiceDataIn(BaseModel):
    kind: str
    key: str = Field(min_length=1, max_length=80)
    value: str = Field(default="", max_length=120)


@app.post("/admin/voice/data")
async def admin_voice_data_add(d: VoiceDataIn, actor: str = admin):
    try:
        return jsonable(await voice.data_add(d.kind, d.key, d.value, "admin", actor))
    except voice.VoiceError as e:
        raise HTTPException(422, str(e))


@app.delete("/admin/voice/data/{row_id}")
async def admin_voice_data_remove(row_id: int, actor: str = admin):
    return {"removed": await voice.data_remove(row_id, actor)}


class VoiceRefIn(BaseModel):
    text: str | None = Field(default=None, max_length=1000)
    not_me: bool = False


@app.post("/admin/voice/events/{event_id}/reference")
async def admin_voice_reference(event_id: int, r: VoiceRefIn, actor: str = admin):
    try:
        return await voice.correct(event_id=event_id, full=r.text, not_me=r.not_me, source="admin", actor=actor)
    except voice.VoiceError as e:
        raise HTTPException(e.status, str(e))


@app.get("/admin/selfdev/control")
async def admin_selfdev_control(_: str = admin):
    return await dev.control()


class SelfdevControlIn(BaseModel):
    paused: bool | None = None
    t2_enabled: bool | None = None


@app.post("/admin/selfdev/control")
async def admin_selfdev_set(c: SelfdevControlIn, request: Request, actor: str = admin):
    admin_page_only(request)
    return await dev.set_control(actor, paused=c.paused, t2_enabled=c.t2_enabled)


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


@app.get("/admin/vault")
async def admin_vault(_: str = admin):
    return jsonable(await vault.list_())


@app.delete("/admin/vault/{entry_id}")
async def admin_vault_delete(entry_id: str, actor: str = admin):
    return {"deleted": await vault.delete(entry_id, actor)}


@app.get("/admin/dev-changes")
async def admin_dev_changes(_: str = admin):
    return jsonable(await dev.list_())


@app.post("/admin/efficiency-review")
async def admin_efficiency_review(actor: str = admin):
    t = await perf.start_review(actor)
    return {"task_id": t["id"]}


@app.get("/admin/playlists")
async def admin_playlists(name: str = "", _: str = admin):
    return jsonable({"playlists": await playlists.all_(), "songs": await playlists.items(name or None),
                     "name": name or playlists.DEFAULT})


class PlaylistPlayIn(BaseModel):
    name: str = Field(default="", max_length=80)
    index: int = Field(default=0, ge=0)


@app.post("/admin/playlists/play")
async def admin_playlist_play(body: PlaylistPlayIn, _: str = admin):
    try:
        return jsonable(await playlists.play(body.name or None, body.index))
    except playlists.PlaylistError as e:
        raise HTTPException(422, str(e))


@app.delete("/admin/playlists/items/{item_id}")
async def admin_playlist_remove(item_id: int, actor: str = admin):
    return {"removed": await playlists.remove(item_id, actor)}


@app.get("/admin/library")
async def admin_library(kind: str = "", q: str = "", _: str = admin):
    try:
        return jsonable({"items": await library.items(kind, q[:80]), "kinds": library.KINDS})
    except library.LibraryError as e:
        raise HTTPException(422, str(e))


@app.post("/admin/library/{key}/show")
async def admin_library_show(key: str, _: str = admin):
    try:
        return jsonable(await library.show(key))
    except (library.LibraryError, stage.StageError, playlists.PlaylistError) as e:
        raise HTTPException(422, str(e))


class KeepIn(BaseModel):
    keep: bool = True


@app.post("/admin/library/{key}/keep")
async def admin_library_keep(key: str, body: KeepIn, actor: str = admin):
    try:
        return {"kept": await library.keep(key, body.keep, actor)}
    except library.LibraryError as e:
        raise HTTPException(422, str(e))


@app.delete("/admin/library/{key}")
async def admin_library_delete(key: str, actor: str = admin):
    try:
        return {"deleted": await library.delete(key, actor)}
    except library.LibraryError as e:
        raise HTTPException(422, str(e))


@app.get("/admin/skills")
async def admin_skills(_: str = admin):
    return jsonable({"skills": await skills_pipeline.listing()})


@app.post("/admin/skills/{name}/rollback")
async def admin_skill_rollback(name: str, actor: str = admin):
    try:
        return await skills_pipeline.rollback(name, actor)
    except skills_pipeline.SkillError as e:
        raise HTTPException(409, str(e))


@app.post("/admin/skills/{name}/retire")
async def admin_skill_retire(name: str, actor: str = admin):
    return {"retired": await skills_pipeline.retire(name, actor)}


@app.get("/admin/companies")
async def admin_companies(_: str = admin):
    return jsonable({"companies": await companies.all_(include_inactive=True), "vault_kinds": companies.VAULT_KINDS,
                     "decision_kinds": companies.DECISION_KINDS, "actions": gm.ACTIONS})


class CompanyIn(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    aliases: list[str] = Field(default_factory=list, max_length=20)


@app.post("/admin/companies")
async def admin_company_add(c: CompanyIn, actor: str = admin):
    try:
        return jsonable(await companies.create(c.name, actor, c.aliases))
    except companies.CompanyError as e:
        raise HTTPException(422, str(e))


class CompanyConfigIn(BaseModel):
    name: str | None = Field(default=None, max_length=120)
    aliases: list[str] | None = None
    active: bool | None = None
    adapter: str | None = Field(default=None, pattern="^(mock|http)$")
    dgm_url: str | None = Field(default=None, max_length=300)
    dgm_token: str | None = Field(default=None, max_length=500)
    contract_verified: bool | None = None
    callback_timeout_s: int | None = Field(default=None, ge=60, le=604800)
    max_retries: int | None = Field(default=None, ge=0, le=10)
    budget_usd_month: float | None = Field(default=None, ge=0, le=1_000_000)


@app.patch("/admin/companies/{company_id}")
async def admin_company_configure(company_id: str, c: CompanyConfigIn, request: Request, actor: str = admin):
    fields = c.model_dump(exclude_none=True)
    if {"dgm_token", "dgm_url", "adapter", "contract_verified"} & set(fields):
        admin_page_only(request)  # where directives go and with which key: the admin page only
    try:
        return jsonable(await companies.configure(company_id, actor, **fields))
    except companies.CompanyError as e:
        raise HTTPException(422, str(e))


@app.post("/admin/companies/{company_id}/callback-secret")
async def admin_company_secret(company_id: str, request: Request, actor: str = admin):
    admin_page_only(request)
    try:
        return {"callback_secret": await companies.rotate_callback_secret(company_id, actor),
                "callback_url": gm.callback_url(company_id),
                "note": "Tampil sekali. Berikan ke server Hermes-DGM untuk menandatangani callback."}
    except companies.CompanyError as e:
        raise HTTPException(422, str(e))


@app.get("/admin/companies/{company_id}")
async def admin_company_detail(company_id: str, _: str = admin):
    try:
        return jsonable({"company": await companies.get(company_id), "vault": await companies.vault_list(company_id),
                         "decisions": await companies.decisions_list("company", company_id),
                         "relations": await companies.related("company", company_id, company_id),
                         "directives": await gm.list_(company_id)})
    except companies.CompanyError as e:
        raise HTTPException(404, str(e))


class VaultEntryIn(BaseModel):
    kind: str
    title: str = Field(min_length=1, max_length=200)
    body: str = Field(default="", max_length=8000)
    data: dict | None = None
    verified: bool = False


@app.post("/admin/companies/{company_id}/vault")
async def admin_company_vault_add(company_id: str, e: VaultEntryIn, actor: str = admin):
    try:
        return jsonable(await companies.vault_add(company_id, e.kind, e.title, actor, e.body, e.data, e.verified))
    except companies.CompanyError as err:
        raise HTTPException(422, str(err))


@app.delete("/admin/companies/{company_id}/vault/{entry_id}")
async def admin_company_vault_delete(company_id: str, entry_id: int, actor: str = admin):
    return {"deleted": await companies.vault_delete(company_id, entry_id, actor)}


class DirectiveIn(BaseModel):
    action: str = Field(min_length=2, max_length=40)
    instruction: str = Field(min_length=10, max_length=4000)
    budget_usd: float | None = Field(default=None, ge=0)
    deadline_hours: float | None = Field(default=None, gt=0, le=2000)


@app.post("/admin/companies/{company_id}/directives")
async def admin_directive(company_id: str, d: DirectiveIn, actor: str = admin):
    try:
        return jsonable(await gm.create(company_id, d.action, d.instruction, actor,
                                        constraints={k: v for k, v in (("budget_usd", d.budget_usd), ("deadline_hours", d.deadline_hours)) if v}))
    except (companies.CompanyError, gm.GMError) as e:
        raise HTTPException(422, str(e))


@app.post("/admin/companies/{company_id}/directives/{directive_id}/cancel")
async def admin_directive_cancel(company_id: str, directive_id: int, actor: str = admin):
    try:
        return jsonable(await gm.cancel(company_id, directive_id, actor))
    except (companies.CompanyError, gm.GMError) as e:
        raise HTTPException(422, str(e))


@app.get("/admin/kpi")
async def admin_kpi(days: int = 7, _: str = admin):
    """Blueprint §15 measures: task success, evidence-checked results, recovery, skill reuse, cost, interventions, latency."""
    return jsonable(await kpi.summary(days))


@app.get("/admin/goals")
async def admin_goals(status: str = "active", _: str = admin):
    return jsonable({"goals": await goals.list_(status if status in goals.STATUSES else "")})


class GoalIn(BaseModel):
    text: str = Field(min_length=1, max_length=300)
    priority: int = Field(default=3, ge=1, le=5)
    due: str | None = None


@app.post("/admin/goals")
async def admin_goal_add(g: GoalIn, actor: str = admin):
    from datetime import date as _date
    try:
        return jsonable(await goals.add(g.text, actor, g.priority, _date.fromisoformat(g.due) if g.due else None))
    except (goals.GoalError, ValueError) as e:
        raise HTTPException(422, str(e))


class GoalPatch(BaseModel):
    status: str | None = None
    priority: int | None = Field(default=None, ge=1, le=5)


@app.patch("/admin/goals/{goal_id}")
async def admin_goal_update(goal_id: int, g: GoalPatch, actor: str = admin):
    try:
        return jsonable(await goals.update(goal_id, actor, status=g.status, priority=g.priority))
    except goals.GoalError as e:
        raise HTTPException(422, str(e))


class CorrectIn(BaseModel):
    text: str = Field(min_length=1, max_length=2000)
    evidence: str = Field(default="", max_length=300)


@app.post("/admin/memory/{mem_id}/correct")
async def admin_memory_correct(mem_id: str, c: CorrectIn, actor: str = admin):
    try:
        done = await memory.correct(mem_id, c.text, actor, evidence=c.evidence or None)
    except memory.MemoryError_ as e:
        raise HTTPException(422, str(e))
    return jsonable({"old": done["old"]["id"], "new": done["new"]})


@app.get("/admin/episodes")
async def admin_episodes(limit: int = 30, _: str = admin):
    rows = await db.pool().fetch(
        "SELECT id, task_id, goal, approach, result, success, cost_usd::float AS cost_usd, model, lesson, created_at "
        "FROM episodes ORDER BY id DESC LIMIT $1", max(1, min(limit, 100)))
    return jsonable({"episodes": [dict(r) for r in rows]})


@app.get("/admin/capabilities")
async def admin_capabilities(kind: str = "", q: str = "", _: str = admin):
    return jsonable({"capabilities": await capabilities.listing(kind, q[:100])})


@app.get("/admin/flow-issues")
async def admin_flow_issues(_: str = admin):
    return jsonable(await auditor.list_())


@app.post("/admin/flow-check")
async def admin_flow_check(actor: str = admin):
    r = await auditor.run(actor)
    return jsonable({"task_id": r["task_id"], "new": len(r["new"]), "fix_task_id": r["fix_task_id"]})


class FlowIssueIn(BaseModel):
    status: str = Field(pattern="^(open|ignored|fixed)$")


@app.post("/admin/flow-issues/{issue_id}")
async def admin_flow_issue(issue_id: int, body: FlowIssueIn, _: str = admin):
    if not await auditor.set_status(issue_id, body.status):
        raise HTTPException(404)
    return {"ok": True}


@app.get("/admin/errors")
async def admin_errors(_: str = admin):
    return jsonable(await errors.recent())


@app.get("/admin/meetings")
async def admin_meetings(_: str = admin):
    return jsonable(await meetings.list_())


@app.get("/admin/hermes-studio")
async def admin_hermes_studio(_: str = admin):
    return jsonable(hermes_studio.studio())


@app.get("/admin/openrouter/models")
async def admin_openrouter_models(q: str = "", free: bool = False, vision: bool = False, tools: bool = False,
                                  sort: str = "termurah", limit: int = 60, _: str = admin):
    """OpenRouter's live catalog for the app's model picker (filtered and sorted here, small answers)."""
    models = await openrouter.catalog()
    if models is None:
        raise HTTPException(503, "daftar model OpenRouter belum bisa diambil")
    found = openrouter.search(models, q[:80], free=True if free else None, vision=True if vision else None,
                              tools=True if tools else None, sort=sort if sort in openrouter.SORTS else "termurah", limit=limit)
    own = await modelinsight.usage(14)  # a badge per model JARVIS already used: how often it worked, how fast
    return jsonable({"total": len(models), "models": [
        m | ({"jarvis": {k: own[m["id"]][k] for k in ("calls", "ok_pct", "p50_ms")}} if m["id"] in own else {}) for m in found]})


@app.get("/admin/models/stats")
async def admin_models_stats(days: int = 7, _: str = admin):
    """Every model JARVIS called: how many calls, how often they failed and why, how fast (the app's "Statistik model")."""
    stats = await modelinsight.usage(days)
    return jsonable({"days": max(1, min(days, 90)),
                     "models": sorted(stats.values(), key=lambda s: -s["calls"])})


@app.get("/admin/models/{model_id:path}/insight")
async def admin_model_insight(model_id: str, category: str = "", _: str = admin):
    """Pros, cons, failures and speed of one model, from four sources (modelinsight.py)."""
    return jsonable(await modelinsight.insight(model_id, category))


class BenchIn(BaseModel):
    model: str = Field(min_length=1, max_length=120)


_bench_lock = asyncio.Lock()


@app.post("/admin/models/bench")
async def admin_model_bench(b: BenchIn, actor: str = admin):
    """"Uji sekarang": two small real requests to this model (≈ $0.0001): speed of a short answer + tool calling."""
    if _bench_lock.locked():
        raise HTTPException(429, "Masih ada uji yang berjalan — tunggu sebentar.")
    models = await openrouter.catalog()
    if models is not None and not openrouter.get(models, b.model):
        raise HTTPException(422, f"model {b.model} tidak ada di OpenRouter")
    async with _bench_lock:
        return jsonable(await modelinsight.run_bench(b.model, actor))


@app.post("/admin/openrouter/check")
async def admin_openrouter_check(actor: str = admin):
    return jsonable(await composition.check_openrouter(actor))


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


class PairIn(BaseModel):
    password: str = Field(min_length=1, max_length=200)
    device_name: str = Field(default="HP", max_length=80)


_pair_failures: dict[str, list[float]] = {}


@app.post("/api/v1/devices/pair")
async def device_pair(body: PairIn, request: Request):
    """The owner's phone signs in with the web admin password instead of a pasted token (ADR-037): a new
    owner-scope device token is made for it. 5 wrong passwords per IP per 15 minutes, 10 per hour overall (admin)."""
    client = request.headers.get("x-real-ip") or (request.client.host if request.client else "?")
    now = time.time()
    recent = [t for t in _pair_failures.get(client, []) if now - t < 900]
    _pair_failures[client] = recent
    if len(recent) >= 5:
        raise HTTPException(429, "Terlalu banyak percobaan. Coba lagi dalam 15 menit.")
    r = await _admin_internal("POST", "/internal/check-admin-password", json={"password": body.password})
    if r.status_code != 200:
        if r.status_code == 401:
            recent.append(now)
        await audit.record(f"ip:{client}", "device.pair_failed", None, status=r.status_code)
        detail = r.json().get("error") if r.headers.get("content-type", "").startswith("application/json") else None
        raise HTTPException(r.status_code if r.status_code in (401, 429) else 502, detail or "Gagal memeriksa password")
    _pair_failures.pop(client, None)
    device, token = await devices.create(body.device_name or "HP", f"pair:{client}", scope="owner")
    return {"token": token, "device": jsonable(device)}


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


@app.post(CONSOLE + "/admin-password")
async def console_admin_password(body: dict = Body(...), device: dict = Depends(owner_device_auth)):
    r = await _admin_internal("POST", "/internal/admin-password",
                              json={"current": str(body.get("current") or ""), "new": str(body.get("new") or "")})
    if r.status_code == 200:
        await audit.record(f"device:{device['name']}", "admin.password_changed", None)
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
