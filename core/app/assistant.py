"""The main agent ("agen utama"): talks with the owner, never blocks on work.

Every owner utterance that is not a quick command goes here. A fast model with a small prompt answers
in about a second; anything that needs tools or time is handed to workers via spawn_task (as many as
needed, in parallel), and the conversation simply continues. Worker results come back as reports the
main agent knows about, so it can tell whether the owner has acknowledged them.
"""

import json
import logging
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from . import awareness, db, llm, memory, notifications, reports, self_model, workers
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

Mata: jika pesan menyertakan gambar, itu yang pemilik tunjukkan — layar HP-nya (berbagi layar) atau kamera \
(ia mengarahkan kamera ke sesuatu). Pahami, lalu LAKUKAN yang ia minta tentang itu (jawab langsung, atau \
spawn_task dengan attach_image=true bila perlu riset/aksi, mis. cari harga barang yang ditunjukkan). Jangan \
membacakan data sensitif (saldo, OTP, kata sandi) kecuali diminta.

Hidup & sadar: kamu tahu dirimu (TENTANG DIRIMU), dan tahu situasi pemilik (SITUASI SAAT INI) dari pengamatan \
worker. Pakai itu: hubungkan ucapannya dengan tempat, waktu, aktivitas, dan kebiasaannya. Jangan pernah \
menyangkal kemampuan yang tercantum di TENTANG DIRIMU; untuk hal yang tidak tercantum, bilang kamu akan \
mengecek (self_check) — jangan mengarang.

Memahami ucapan (penting — mic mendengar terus, jadi bisa ada suara lain):
- Jika ucapan jelas BUKAN untukmu (obrolan dengan orang lain, suara TV/video, potongan kalimat tanpa \
  maksud ke JARVIS) → panggil stay_silent TANPA menulis teks apa pun. Diam berarti benar-benar tidak \
  bersuara — jangan pernah mengucapkan "aku diam saja".
- Jika ucapan tampak BELUM SELESAI (berhenti di tengah kalimat, mis. "kalau titik panennya itu hijau,") → \
  stay_silent(reason="menunggu lanjutan") TANPA teks; kalimat berikutnya akan menyambung.
- Jika kamu RAGU maksudnya, transkrip berkeyakinan rendah, atau ada beberapa tafsiran → tanya balik \
  singkat dan spesifik ("Maksudnya cek jadwal UAT, ya?") — jangan menebak lalu bertindak.
- Kata yang terdengar aneh mungkin salah dengar (mis. "Deep Drum" = Deepgram); tafsirkan wajar."""

TOOLS = [
    {"type": "function", "function": {
        "name": "spawn_task",
        "description": "Tugaskan worker untuk mengerjakan satu pekerjaan di latar belakang.",
        "parameters": {"type": "object", "properties": {
            "title": {"type": "string", "description": "judul singkat, mis. 'Cek harga emas Antam'"},
            "instruction": {"type": "string", "description": "instruksi lengkap & mandiri untuk worker"},
            "attach_image": {"type": "boolean", "description": "sertakan gambar kamera/layar yang sedang ditunjukkan"}},
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
        "name": "stay_silent",
        "description": "Jangan menjawab ucapan ini (bukan untukmu, atau kalimatnya belum selesai).",
        "parameters": {"type": "object", "properties": {"reason": {"type": "string"}}, "required": ["reason"]}}},
    {"type": "function", "function": {
        "name": "self_check",
        "description": "Minta pengecekan & perbaikan diri JARVIS (kemampuan, kesalahan, kekurangan).",
        "parameters": {"type": "object", "properties": {"focus": {"type": "string", "description": "hal yang ingin dicek"}}}}},
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
    silent: bool = False  # the owner was not talking to JARVIS (or not finished): say nothing


async def _history(session_id: str, limit: int = 16) -> list[dict]:
    rows = await db.pool().fetch(
        """SELECT role, content FROM messages WHERE session_id = $1 AND route NOT IN ('blocked', 'silent')
           ORDER BY id DESC LIMIT $2""", session_id, limit)
    return [{"role": r["role"], "content": r["content"]} for r in reversed(rows)]


async def _situation(text: str, location: Location | None) -> str:
    parts = [context_prefix(location).strip(), "TENTANG DIRIMU:\n" + await self_model.describe()]
    if block := awareness.situation_block():
        parts.append(block)
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


async def _run_tool(call: llm.ToolCall, session_id: str, actor: str, device_id, location, emit: Emit,
                    image: str | None = None) -> str:
    a = call.arguments
    try:
        match call.name:
            case "spawn_task":
                if len(str(a.get("instruction") or "").strip()) < 10:
                    # A task without instructions makes a worker report "the task was empty" (seen in real use).
                    return json.dumps({"error": "instruction kosong — tulis instruksi lengkap, atau tanya pemilik dulu"})
                t = await workers.spawn(a.get("title", "Tugas"), a.get("instruction") or a.get("title", ""),
                                        session_id, actor, device_id, location,
                                        image=image if a.get("attach_image") else None)
                return json.dumps({"task_id": t["id"], "status": "queued"})
            case "stay_silent":
                return json.dumps({"silent": True})
            case "self_check":
                from . import selfimprove
                t = await selfimprove.start(str(a.get("focus") or ""), actor)
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


def _user_content(text: str, image: str | None, image_source: str | None = None, stt: dict | None = None):
    """The owner's words, with how they were heard and what they are showing."""
    notes = []
    if stt:
        conf = stt.get("confidence")
        speakers = stt.get("speakers")
        notes.append("diucapkan lewat suara"
                     + (f", keyakinan transkrip {conf:.2f}" if isinstance(conf, (int, float)) else "")
                     + (f", {speakers} pembicara terdeteksi" if isinstance(speakers, int) and speakers > 1 else ""))
    if image:
        notes.append("terlampir gambar dari " + ("kamera" if image_source == "camera" else "layar HP"))
    body = f"[{'; '.join(notes)}] {text}" if notes else text
    if not image:
        return body
    return [{"type": "text", "text": body},
            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image}"}}]


async def respond(text: str, session_id: str, actor: str, device_id=None, emit: Emit | None = None,
                  location: Location | None = None, screen: str | None = None, image_source: str | None = None,
                  stt: dict | None = None) -> Answer:
    async def send(ev: dict) -> None:
        if emit:
            await emit(ev)

    messages = [{"role": "system", "content": SYSTEM},
                {"role": "system", "content": await _situation(text, location)},
                *await _history(session_id),
                {"role": "user", "content": _user_content(text, screen, image_source, stt)}]
    spoken, usage_in, usage_out, silent = "", 0, 0, False
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
            result = await _run_tool(c, session_id, actor, device_id, location, send, screen)
            messages.append({"role": "tool", "tool_call_id": c.id, "content": result})
            silent = silent or c.name == "stay_silent"
        if completion.text or silent:  # said something already, or chose silence — don't talk (again)
            break
    # Silence wins: if the model chose (or merely announced) silence, nothing is said.
    if silent or announces_silence(spoken):
        return Answer("", usage_in or None, usage_out or None, silent=True)
    return Answer(spoken or "Oke.", usage_in or None, usage_out or None)


_SILENCE = re.compile(
    r"(aku|saya) (diam|tidak (akan )?(menjawab|merespons))|bukan untuk(ku|ku| saya)|"
    r"(aku|saya) tunggu lanjutan|tunggu lanjutannya|kalimatnya belum selesai", re.IGNORECASE)


def announces_silence(text: str) -> bool:
    """The model said it would stay quiet instead of calling stay_silent — treat it as silence."""
    return bool(text) and len(text) < 160 and bool(_SILENCE.search(text))
