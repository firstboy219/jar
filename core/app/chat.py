"""One user turn through the tiered pipeline: quick command (no AI) → main agent (gateway: cloud or local;
private/sensitive content only ever reaches the local model) → workers."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

import time

from . import approvals, assistant, attachments, audit, db, gateway, llm, memory, n8n, sensitive, status, workers
from .location import Location, remember_last
from .router import HELP, Intent, parse

# Live events for the UI (WSS): {"type": "status"|"thought"|"tool"|"context"|"delta", ...}
Emit = Callable[[dict], Awaitable[None]]


@dataclass
class Turn:
    reply: str
    route: str  # core | assistant | silent | blocked | error
    spoken: bool = False  # already spoken sentence by sentence ("say" events)


async def _cloud_chat() -> bool:
    """Is the main agent's model in the cloud (bigger prompt budget for attached documents)?"""
    return (await gateway.plan("ngobrol", caller="chat"))[0].cloud


def _fmt_approval(a: dict) -> str:
    return f"#{a['id']} [{a['risk']}] {a['title']} — {a['status']}"


async def _run_intent(intent: Intent, actor: str, location: Location | None = None) -> str:
    match intent.name:
        case "whereami":
            if not location:
                return ("Saya belum menerima lokasi dari HP. Aktifkan 'Bagikan lokasi ke JARVIS' di Pengaturan "
                        "aplikasi dan izinkan akses lokasi.")
            return f"Kamu ada di {location.describe()}.\n{location.maps_url()}"
        case "help":
            return HELP
        case "status":
            lines = [f"{'✅' if c['ok'] else '❌'} {c['name']} ({c['detail']})" for c in await status.check_all()]
            return "Status layanan:\n" + "\n".join(lines)
        case "approvals":
            pending = await approvals.list_("awaiting_approval")
            if not pending:
                return "Tidak ada tindakan yang menunggu persetujuan."
            return "Menunggu persetujuan:\n" + "\n".join(_fmt_approval(a) for a in pending)
        case "approve" | "reject":
            a = await approvals.decide(intent.args["id"], intent.name == "approve", actor)
            extra = f"\nGagal: {a['error']}" if a["status"] == "failed" else ""
            return f"Persetujuan #{a['id']} → {a['status']}.{extra}"
        case "remember":
            m = await memory.save(intent.args["text"], "personal", source=actor, kind="fact")
            return f"Tersimpan di memori (id {m['id']})."
        case "forget":
            ok = await memory.delete(intent.args["id"], actor)
            return "Memori dihapus." if ok else "Memori tidak ditemukan."
        case "recall":
            hits = await memory.search(intent.args["query"])
            if not hits:
                return "Saya belum punya memori yang relevan."
            return "\n".join(f"• {m['text']}  ({m['category']}, {m['score']}, id {m['id']})" for m in hits)
        case "tasks":
            active = await workers.active()
            if not active:
                return "Tidak ada tugas worker yang sedang berjalan."
            return "Tugas worker:\n" + "\n".join(f"• #{t['id']} {t['title']} — {t['status']}" for t in active)
        case "model":
            from . import composition
            c = await composition.get()
            routes = {k["name"]: k["routes"] for k in c["categories"]}

            def first(cat: str) -> str:
                r = (routes.get(cat) or [{}])[0]
                return "model lokal di server (Qwen)" if str(r.get("provider", "")).startswith("lokal") or not r \
                    else f"{r.get('model')} lewat {r.get('provider')}"
            return (f"Komposisi '{c['preset']}': ngobrol pakai {first('ngobrol')}, tugas web pakai {first('web')}, "
                    f"coding pakai {first('coding')}. Bisa diganti di menu Komposisi AI, atau bilang saja padaku.")
        case "relieve":
            from . import ops
            r = await ops.relieve(actor)
            n = len(r["stopped"])
            return (f"Oke, server kunetralkan: {n} tugas kuhentikan dan kusimpan (bisa diulang atau ditutup), "
                    if n else "Oke, server kunetralkan; tidak ada tugas yang sedang berjalan. ") + \
                "pekerjaan latar belakang istirahat 15 menit. Hasilnya kulaporkan sebentar lagi."
        case "workflows":
            flows = await n8n.list_workflows()
            if not flows:
                return "Belum ada workflow di n8n."
            return "\n".join(f"• {w['name']} (id {w['id']}) — {'aktif' if w['active'] else 'nonaktif'}" for w in flows)
    raise ValueError(intent.name)


async def _log(session_id: str, device_id, role: str, content: str, route: str, **kw) -> None:
    await db.pool().execute(
        """INSERT INTO messages (session_id, device_id, role, content, route, model,
                                 prompt_tokens, completion_tokens, latency_ms, stt_confidence, trace)
           VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)""",
        session_id, device_id, role, content, route,
        kw.get("model"), kw.get("prompt_tokens"), kw.get("completion_tokens"), kw.get("latency_ms"),
        kw.get("stt_confidence"), kw.get("trace"))


async def handle(text: str, session_id: str, actor: str, device_id=None, emit: Emit | None = None,
                 location: Location | None = None, screen: str | None = None, image_source: str | None = None,
                 stt: dict | None = None, speak_live: bool = False, screen_text: str = "",
                 attachment_ids: list[str] | None = None) -> Turn:
    async def send(event: dict) -> None:
        if emit:
            await emit(event)

    async def say(state: str) -> None:
        await send({"type": "status", "state": state})

    text = text.strip()
    intent = parse(text)
    if location:
        await remember_last(location)
    private = sensitive.is_private(text)
    found = sensitive.scan(text)
    # Attachments (ADR-032): their text goes into the prompt; sensitive content inside keeps the turn local.
    files, attached = "", []
    if attachment_ids:
        files, attached = attachments.prompt_block(attachment_ids[:5], budget=3500 if not await _cloud_chat() else 14000)
        found = sorted(set(found) | set(sensitive.scan(files)))
        if attached and screen is None:  # the first picture also goes to a vision model, when there is one
            first = next((m for m in attached if m["kind"] == "image"), None)
            # a cloud model sees up to 1280 px; the local one is held to 768 px (≈ 0.5k tokens ≈ 1 minute on this CPU)
            if first and (b64 := attachments.image_b64(first["id"], 1280 if await _cloud_chat() else 768)):
                screen, image_source = b64, "attachment"

    # Never persist secrets verbatim, even in our own message log.
    logged = text if not found else f"[disensor: {', '.join(found)}]"
    if attached:
        logged += "\n[lampiran: " + ", ".join(m["name"] for m in attached) + "]"
    local_only = bool(private or found) and not intent
    await _log(session_id, device_id, "user", logged, "core" if intent else ("private" if local_only else "assistant"),
               stt_confidence=(stt or {}).get("confidence"))

    if intent:
        await say("executing")
        try:
            reply, route = await _run_intent(intent, actor, location), "core"
        except (approvals.ApprovalError, memory.MemoryError_, n8n.N8nError) as e:
            reply, route = f"Tidak bisa: {e}", "error"
    else:
        # Main agent answers right away; real work is delegated to workers (see assistant.py).
        # /privat or sensitive content: answered by the local model only — it never leaves the server.
        if local_only:
            await audit.record(actor, "chat.local_only", f"session:{session_id}", reasons=found or ["private"])
        await say("thinking")
        started = time.monotonic()
        try:
            a = await assistant.respond(text, session_id, actor, device_id, send, location, screen, image_source, stt,
                                        private=local_only, speak_live=speak_live, screen_text=screen_text,
                                        files=files, attachments=attached)
            trace = {"first_token_ms": a.first_token_ms, "first_say_ms": a.first_say_ms,
                     "total_ms": int((time.monotonic() - started) * 1000), "route": a.route,
                     **({"stt_ms": stt["stt_ms"]} if isinstance((stt or {}).get("stt_ms"), int) else {})}
            if a.silent:  # not for JARVIS, or the owner is still mid-sentence: no reply at all
                await _log(session_id, device_id, "assistant", "(diam)", "silent", model="main-agent", trace=trace)
                await say("completed")
                return Turn("", "silent")
            model = f"{a.route['provider']}/{a.route['model']}" if a.route else "main-agent"
            await _log(session_id, device_id, "assistant", a.text, "private" if local_only else "assistant", model=model,
                       prompt_tokens=a.prompt_tokens, completion_tokens=a.completion_tokens,
                       latency_ms=trace["total_ms"], trace=trace)
            await say("completed")
            return Turn(a.text, "assistant", spoken=a.spoken_live)
        except llm.LLMError:
            reply, route = ("Maaf, aku sedang tidak bisa berpikir — model AI di server maupun cloud tidak menjawab. "
                            "Coba lagi sebentar ya."), "error"

    await _log(session_id, device_id, "assistant", reply, route)
    await say("completed" if route != "error" else "failed")
    return Turn(reply, route)
