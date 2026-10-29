"""A meeting while it is recorded (ADR-087, mockup "Rekam rapat"): each 60-second chunk is transcribed as it arrives (the owner's speech
engine; a confidential meeting only by the local Whisper), and every few chunks one master-flow job picks out what was decided and who
has to do what so far — so the owner sees decisions and his tasks during the meeting, and can ask "tadi Sari bilang apa?".
The full minutes (speakers, map-reduce, the .docx) still come after the meeting ends (meetings.process)."""

import asyncio
import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from . import db, hub, master, stt
from .appauth import owner

log = logging.getLogger("jarvis-core")
router = APIRouter()
API = "/api/v1/app/meeting"
EXTRACT_EVERY = 3
_locks: dict[str, asyncio.Lock] = {}


async def _pcm(path: str) -> bytes:
    """Any chunk (AAC, Ogg/Opus, WebM) → 16 kHz mono 16-bit PCM, by ffmpeg."""
    p = await asyncio.create_subprocess_exec("ffmpeg", "-loglevel", "error", "-i", path, "-f", "s16le", "-ac", "1", "-ar", "16000", "pipe:1",
                                             stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    out, err = await asyncio.wait_for(p.communicate(), 120)
    if p.returncode != 0:
        raise RuntimeError(err.decode()[:200])
    return out


async def live(meeting_id: str) -> dict:
    return await db.pool().fetchval("SELECT live FROM meetings WHERE id = $1", uuid.UUID(meeting_id)) or {}


async def on_chunk(meeting_id: str, n: int, path: str, confidential: bool) -> None:
    lock = _locks.setdefault(meeting_id, asyncio.Lock())
    async with lock:   # chunks in order, one transcription at a time per meeting
        try:
            pcm = await _pcm(path)
            res = await stt.transcribe(pcm, "whisper" if confidential else None)
            text = (res.get("text") or "").strip()
        except Exception as e:
            log.warning("live transcript chunk %s/%s: %s", meeting_id, n, e)
            return
        if not text:
            return
        await db.pool().execute(
            """UPDATE meetings SET live = jsonb_set(coalesce(live, '{}'::jsonb), '{transcript}',
                 coalesce(live->'transcript', '[]'::jsonb) || $2::jsonb) WHERE id = $1""", uuid.UUID(meeting_id), [{"n": n, "text": text[:4000]}])
        await hub.broadcast({"type": "meeting_live", "id": meeting_id, "n": n, "text": text[:600]})
        lv = await live(meeting_id)
        if not confidential and len(lv.get("transcript") or []) % EXTRACT_EVERY == 0:
            await extract(meeting_id, lv)


def transcript_text(lv: dict, last: int = 20) -> str:
    rows = sorted(lv.get("transcript") or [], key=lambda x: x["n"])[-last:]
    return "\n".join(f"[menit {r['n'] + 1}] {r['text']}" for r in rows)


async def extract(meeting_id: str, lv: dict) -> dict:
    title = await db.pool().fetchval("SELECT title FROM meetings WHERE id = $1", uuid.UUID(meeting_id))
    msgs = [{"role": "system", "content": ("Dari transkrip rapat yang sedang berjalan, catat yang SUDAH jelas: keputusan, dan tugas (siapa, apa, kapan) — terutama "
                                           "tugas untuk pemilik (yang merekam; disebut 'saya'/'Bapak'/'Mas' oleh orang lain). Jangan mengarang. JSON: "
                                           "{\"keputusan\": [\"…\"], \"tugas\": [{\"siapa\": \"…\", \"apa\": \"…\", \"kapan\": \"…\", \"pemilik\": true|false}], \"topik\": \"…\"}")},
            {"role": "user", "content": f"Rapat: {title}\n\n{transcript_text(lv)}"}]
    r = await master.run(master.Job("rapat", "catat-langsung", "catat keputusan dan tugas rapat yang sedang berjalan", trigger="event",
                                    messages=msgs, json_out=True, no_free=True, max_tokens=800))
    if r["status"] != "done" or not isinstance(r["result"], dict):
        return {}
    got = {"keputusan": [str(x)[:200] for x in r["result"].get("keputusan") or []][:10],
           "tugas": [t for t in r["result"].get("tugas") or [] if isinstance(t, dict) and t.get("apa")][:12], "topik": str(r["result"].get("topik") or "")[:120]}
    await db.pool().execute("UPDATE meetings SET live = coalesce(live, '{}'::jsonb) || $2::jsonb WHERE id = $1", uuid.UUID(meeting_id), got)
    await hub.broadcast({"type": "meeting_live", "id": meeting_id, "notes": got})
    return got


class AskIn(BaseModel):
    question: str = Field(min_length=2, max_length=500)


@router.get(API)
async def api_state(device: dict = Depends(owner)):
    """The Rekam rapat screen: the meeting card (recording / processing / waiting / done), the next calendar meeting, the last few meetings."""
    from . import meetings
    card = await meetings.desk_card()
    nxt = await db.pool().fetchrow(
        "SELECT title, start_at, end_at, location, attendees, online FROM calendar_events WHERE end_at > now() AND start_at < now() + interval '12 hours' ORDER BY start_at LIMIT 1")
    recent = await meetings.list_(8)
    pages = {str(r["meeting_id"]): str(r["id"]) for r in await db.pool().fetch(
        "SELECT id, meeting_id FROM note_pages WHERE meeting_id = ANY($1::uuid[]) AND NOT archived", [m["id"] for m in recent])}
    for m in recent:
        m["page_id"] = pages.get(str(m["id"]))
    return {"card": card, "next": dict(nxt) if nxt else None, "recent": recent,
            "live": (await live(card["id"])) if card and card.get("id") and card["state"] in ("recording", "processing") else None}


@router.get(API + "/{meeting_id}/live")
async def api_live(meeting_id: str, device: dict = Depends(owner)):
    try:
        uuid.UUID(meeting_id)
    except ValueError:
        raise HTTPException(404)
    m = await db.pool().fetchrow("SELECT id, title, status, confidential, started_at, chunks, live FROM meetings WHERE id = $1", uuid.UUID(meeting_id))
    if not m:
        raise HTTPException(404)
    return dict(m)


@router.post(API + "/{meeting_id}/ask")
async def api_ask(meeting_id: str, body: AskIn, device: dict = Depends(owner)):
    """A question during the meeting, answered from what was said so far (after the meeting, the full transcript answers it)."""
    m = await db.pool().fetchrow("SELECT title, status, confidential, live FROM meetings WHERE id = $1", uuid.UUID(meeting_id))
    if not m:
        raise HTTPException(404)
    if m["confidential"]:
        raise HTTPException(409, "rapat rahasia: transkripnya tidak dikirim ke AI")
    if m["status"] == "done":
        from . import meetings
        return await meetings.ask(meeting_id, body.question)
    msgs = [{"role": "system", "content": "Jawab pertanyaan pemilik tentang rapat yang sedang berjalan HANYA dari transkrip di bawah. Singkat. Kalau tidak ada di transkrip, bilang belum terdengar."},
            {"role": "user", "content": f"Transkrip sejauh ini:\n{transcript_text(m['live'] or {}, 40)}\n\nPertanyaan: {body.question}"}]
    r = await master.run(master.Job("rapat", "tanya", "jawab pertanyaan tentang rapat yang sedang berjalan", messages=msgs, no_free=True, max_tokens=400))
    if r["status"] != "done":
        raise HTTPException(502, r.get("error") or "gagal")
    return {"answer": r["result"], "lane": r.get("lane")}
