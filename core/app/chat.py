"""One user turn through the tiered pipeline: core command → privacy gate → Hermes."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from . import approvals, audit, db, hermes, memory, n8n, sensitive, status
from .router import HELP, Intent, parse

# Live events for the UI (WSS): {"type": "status"|"thought"|"tool"|"context"|"delta", ...}
Emit = Callable[[dict], Awaitable[None]]


@dataclass
class Turn:
    reply: str
    route: str  # core | hermes | blocked | error


def _fmt_approval(a: dict) -> str:
    return f"#{a['id']} [{a['risk']}] {a['title']} — {a['status']}"


async def _run_intent(intent: Intent, actor: str) -> str:
    match intent.name:
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
        case "workflows":
            flows = await n8n.list_workflows()
            if not flows:
                return "Belum ada workflow di n8n."
            return "\n".join(f"• {w['name']} (id {w['id']}) — {'aktif' if w['active'] else 'nonaktif'}" for w in flows)
    raise ValueError(intent.name)


async def _memory_context(query: str) -> dict:
    """What Hermes is looking at: re-run its memory query locally (CPU embeddings, cheap) for the UI."""
    try:
        hits = await memory.search(query, limit=4)
    except Exception:
        hits = []
    return {"type": "context", "source": "memory", "query": query,
            "items": [{"text": m["text"][:240], "category": m["category"], "score": m["score"]} for m in hits]}


async def _log(session_id: str, device_id, role: str, content: str, route: str, **kw) -> None:
    await db.pool().execute(
        """INSERT INTO messages (session_id, device_id, role, content, route, model,
                                 prompt_tokens, completion_tokens, latency_ms)
           VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)""",
        session_id, device_id, role, content, route,
        kw.get("model"), kw.get("prompt_tokens"), kw.get("completion_tokens"), kw.get("latency_ms"))


async def handle(text: str, session_id: str, actor: str, device_id=None, emit: Emit | None = None) -> Turn:
    async def send(event: dict) -> None:
        if emit:
            await emit(event)

    async def say(state: str) -> None:
        await send({"type": "status", "state": state})

    text = text.strip()
    intent = parse(text)
    private = sensitive.is_private(text)
    found = sensitive.scan(text)

    # Never persist secrets verbatim, even in our own message log.
    logged = text if not found else f"[disensor: {', '.join(found)}]"
    await _log(session_id, device_id, "user", logged, "core" if intent else ("blocked" if private or found else "hermes"))

    if intent:
        await say("executing")
        try:
            reply, route = await _run_intent(intent, actor), "core"
        except (approvals.ApprovalError, memory.MemoryError_, n8n.N8nError) as e:
            reply, route = f"Tidak bisa: {e}", "error"
    elif private or found:
        reply, route = (
            "Pesan ini tidak saya kirim ke model cloud"
            + (f" karena terdeteksi data sensitif ({', '.join(found)})." if found else " (mode /privat).")
            + " Perintah cepat tetap bisa dipakai — ketik 'bantuan'."), "blocked"
        await audit.record(actor, "chat.blocked", f"session:{session_id}", reasons=found or ["private"])
    else:
        await say("thinking")
        try:
            r = None
            async for ev in hermes.stream(text, session_id):
                if ev["type"] == "done":
                    r = ev["reply"]
                    continue
                await send(ev)
                if ev["type"] == "tool" and ev["name"] == "memory_search" and ev["status"] == "running":
                    await send(await _memory_context(ev["label"]))
            await _log(session_id, device_id, "assistant", r.text, "hermes", model="hermes-agent",
                       prompt_tokens=r.prompt_tokens, completion_tokens=r.completion_tokens,
                       latency_ms=r.latency_ms)
            await say("completed")
            return Turn(r.text, "hermes")
        except hermes.HermesError as e:
            reply, route = f"Maaf, JARVIS sedang bermasalah: {e}", "error"

    await _log(session_id, device_id, "assistant", reply, route)
    await say("completed" if route != "error" else "failed")
    return Turn(reply, route)
