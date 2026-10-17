"""The main agent ("agen utama"): talks with the owner, never blocks on work.

Every owner utterance that is not a quick command goes here. A fast model with a small prompt answers
in about a second; anything that needs tools or time is handed to workers via spawn_task (as many as
needed, in parallel), and the conversation simply continues. Worker results come back as reports the
main agent knows about, so it can tell whether the owner has acknowledged them.
"""

import json
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from . import db, llm, memory, notifications, reports, workers
from .location import WIB, Location, context_prefix

log = logging.getLogger("jarvis-core.assistant")
Emit = Callable[[dict], Awaitable[None]]

SYSTEM = """Kamu JARVIS, asisten pribadi pemilikmu. Kamu adalah AGEN UTAMA: tugasmu mengobrol dengan pemilik \
dan mengatur pekerjaan — bukan mengerjakannya sendiri.

Cara bicara: lewat suara. Jawab singkat (1–2 kalimat), bahasa Indonesia natural dan sopan-santai, \
tanpa markdown, emoji, atau daftar. Jangan memanggil "Bos".

Delegasi: apa pun yang butuh mencari info di internet, mengecek data/server/n8n, menghitung, membuat \
sesuatu, atau lebih dari beberapa detik → panggil spawn_task (satu tugas per pekerjaan; boleh beberapa \
sekaligus) dengan instruksi yang lengkap dan mandiri, LALU ucapkan satu kalimat natural bahwa kamu \
sedang mengurusnya (mis. "Oke, aku cek dulu ya, nanti aku kabari."). Jangan menyebut istilah teknis \
seperti worker, delegasi, atau tugas latar belakang. Jangan menunggu hasil dan jangan mengarang hasil — \
hasilnya akan kamu sampaikan sendiri nanti. \
Obrolan biasa, pertanyaan ringan, atau yang bisa dijawab dari memori/konteks di bawah: jawab langsung.

Laporan: daftar "LAPORAN BELUM DIKONFIRMASI" berisi hasil worker yang sudah kamu sampaikan. Jika ucapan \
pemilik menunjukkan ia sudah mendengar/menanggapinya (mis. "oke", "sip", "makasih", atau membahas isinya), \
panggil acknowledge_reports untuk laporan itu. Jika ia minta diulang, ulangi isinya.

Fakta/preferensi yang pemilik minta diingat → remember. Jangan menyimpan rahasia/kata sandi.

Menampilkan: kalau pemilik ingin diperlihatkan sesuatu (foto, contoh, video tutorial), atau gambar akan \
lebih jelas daripada kata-kata, tugaskan worker untuk mencari dan menampilkannya di layar HP \
(instruksikan: "tampilkan dengan show_media"). Katakan bahwa gambarnya akan muncul di layar.

Layar: jika pesan pemilik menyertakan gambar layar, itu tampilan layar HP-nya saat ini (ia sedang \
berbagi layar). Diskusikan apa yang terlihat; jangan membacakan data sensitif (saldo, OTP, kata sandi) \
kecuali diminta."""

TOOLS = [
    {"type": "function", "function": {
        "name": "spawn_task",
        "description": "Tugaskan worker untuk mengerjakan satu pekerjaan di latar belakang.",
        "parameters": {"type": "object", "properties": {
            "title": {"type": "string", "description": "judul singkat, mis. 'Cek harga emas Antam'"},
            "instruction": {"type": "string", "description": "instruksi lengkap & mandiri untuk worker"}},
            "required": ["title", "instruction"]}}},
    {"type": "function", "function": {
        "name": "acknowledge_reports",
        "description": "Tandai laporan worker sudah didengar pemilik.",
        "parameters": {"type": "object", "properties": {
            "report_ids": {"type": "array", "items": {"type": "integer"}}}, "required": ["report_ids"]}}},
    {"type": "function", "function": {
        "name": "cancel_task",
        "description": "Batalkan tugas worker yang masih berjalan/antre.",
        "parameters": {"type": "object", "properties": {"task_id": {"type": "integer"}},
                       "required": ["task_id"]}}},
    {"type": "function", "function": {
        "name": "remember",
        "description": "Simpan satu fakta/preferensi pemilik ke memori jangka panjang.",
        "parameters": {"type": "object", "properties": {
            "text": {"type": "string"},
            "kind": {"type": "string", "enum": ["fact", "preference", "assumption"]}},
            "required": ["text"]}}},
]


@dataclass
class Answer:
    text: str
    prompt_tokens: int | None = None
    completion_tokens: int | None = None


async def _history(session_id: str, limit: int = 16) -> list[dict]:
    rows = await db.pool().fetch(
        """SELECT role, content FROM messages WHERE session_id = $1 AND route <> 'blocked'
           ORDER BY id DESC LIMIT $2""", session_id, limit)
    return [{"role": r["role"], "content": r["content"]} for r in reversed(rows)]


async def _situation(text: str, location: Location | None) -> str:
    parts = [context_prefix(location).strip()]
    tasks = await workers.active()
    if tasks:
        parts.append("TUGAS WORKER AKTIF:\n" + "\n".join(f"- #{t['id']} {t['title']} ({t['status']})" for t in tasks))
    pending = await reports.unconfirmed()
    if pending:
        parts.append("LAPORAN BELUM DIKONFIRMASI:\n" + "\n".join(
            f"- laporan #{r['id']} (tugas: {r['title'] or '-'}, disampaikan {r['attempts']}x): {r['text']}" for r in pending))
    recent = await notifications.recent(6)
    if recent:
        parts.append("NOTIFIKASI HP TERBARU (terbaru dulu):\n" + "\n".join(
            f"- {n['posted_at'].astimezone(WIB):%H:%M} {n['app']}: {n['title']} — {n['text'][:160]}" for n in recent))
    try:
        hits = [m for m in await memory.search(text, limit=4) if m["score"] >= 0.35]
    except Exception:
        hits = []
    if hits:
        parts.append("YANG KAMU INGAT (memori, bisa usang):\n" + "\n".join(f"- {m['text']}" for m in hits))
    return "\n\n".join(parts)


async def _run_tool(call: llm.ToolCall, session_id: str, actor: str, device_id, location, emit: Emit) -> str:
    a = call.arguments
    try:
        match call.name:
            case "spawn_task":
                t = await workers.spawn(a.get("title", "Tugas"), a.get("instruction") or a.get("title", ""),
                                        session_id, actor, device_id, location)
                return json.dumps({"task_id": t["id"], "status": "queued"})
            case "acknowledge_reports":
                ids = [int(i) for i in a.get("report_ids", []) if str(i).isdigit()]
                return json.dumps({"acknowledged": await reports.acknowledge(ids, "voice")})
            case "cancel_task":
                return json.dumps({"cancelled": await workers.cancel(int(a.get("task_id", 0)), actor)})
            case "remember":
                m = await memory.save(a.get("text", ""), "personal", source=actor, kind=a.get("kind", "fact"))
                return json.dumps({"saved": str(m["id"])})
    except (memory.MemoryError_, ValueError) as e:
        return json.dumps({"error": str(e)})
    return json.dumps({"error": f"unknown tool {call.name}"})


def _user_content(text: str, screen: str | None):
    if not screen:
        return text
    return [{"type": "text", "text": text},
            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{screen}"}}]


async def respond(text: str, session_id: str, actor: str, device_id=None, emit: Emit | None = None,
                  location: Location | None = None, screen: str | None = None) -> Answer:
    async def send(ev: dict) -> None:
        if emit:
            await emit(ev)

    messages = [{"role": "system", "content": SYSTEM},
                {"role": "system", "content": await _situation(text, location)},
                *await _history(session_id),
                {"role": "user", "content": _user_content(text, screen)}]
    spoken, usage_in, usage_out = "", 0, 0
    for round_ in range(3):  # model may call tools, then needs one more turn to speak
        completion = None
        async for ev in llm.stream_chat(messages, tools=TOOLS if round_ < 2 else None):
            if ev["type"] == "delta":
                await send({"type": "delta", "text": ev["text"]})
            else:
                completion = ev["completion"]
        usage_in += completion.prompt_tokens or 0
        usage_out += completion.completion_tokens or 0
        spoken = (spoken + " " + completion.text).strip()
        if not completion.tool_calls:
            break
        messages.append({"role": "assistant", "content": completion.text or None, "tool_calls": [
            {"id": c.id, "type": "function", "function": {"name": c.name, "arguments": json.dumps(c.arguments)}}
            for c in completion.tool_calls]})
        for c in completion.tool_calls:
            result = await _run_tool(c, session_id, actor, device_id, location, send)
            messages.append({"role": "tool", "tool_call_id": c.id, "content": result})
        if completion.text:  # already said something alongside the tool call — don't talk twice
            break
    return Answer(spoken or "Oke.", usage_in or None, usage_out or None)
