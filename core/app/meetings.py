"""Meeting recorder: the phone records the room (Android cannot capture Zoom/Meet/WhatsApp call audio)
in 60-second Opus chunks; here they are assembled, transcribed, split by speaker and turned into minutes.

Pipeline (one meeting at a time, lowest CPU priority so live voice and chat stay fast):
  1. speech → text with the owner's speech engine (Whisper local / Groq / Deepgram); a "Rahasia"
     (confidential) meeting is always local, end to end;
  2. who spoke when (sherpa-onnx diarization on this server); the owner's voiceprint names "Pemilik";
  3. minutes by the 'rapat' category model, map-reduce over ~10-minute blocks: summary, decisions,
     action items (who / what / due), open questions, topics;
  4. a .docx of the minutes (documents.py), a spoken report, and the transcript indexed in Qdrant so the
     owner can ask "what did we decide about X in that meeting?".
Audio is deleted after AUDIO_RETENTION_DAYS; transcript and minutes stay until the owner deletes them.
Recording others needs their consent (Indonesia's new KUHP art. 258, from 2026-01-02): the app asks.
"""

import asyncio
import json
import logging
import re
import shutil
import time
import uuid
from datetime import datetime
from pathlib import Path

import httpx

from . import audit, composition, db, documents, llm, memory, reports, stt, voice_id
from .config import settings
from .location import WIB

log = logging.getLogger("jarvis-core.meetings")
ROOT = Path("/data/meetings")
MAX_CHUNK_BYTES = 3_000_000   # 60 s of Opus at 24–32 kbps is ~250 KB; generous for other codecs
AUDIO_RETENTION_DAYS = 30
COLLECTION = "jarvis_meetings"
_queue: asyncio.Queue | None = None


class MeetingError(ValueError):
    pass


def _dir(meeting_id: str) -> Path:
    return ROOT / str(uuid.UUID(meeting_id))


async def create(title: str, confidential: bool, consent: bool, device_id=None, actor: str = "owner") -> dict:
    if not consent:
        raise MeetingError("perekaman butuh persetujuan peserta")
    title = (title or "").strip()[:150] or f"Rapat {datetime.now(WIB):%d %b %Y %H:%M}"
    row = await db.pool().fetchrow(
        "INSERT INTO meetings (title, confidential, consent, device_id) VALUES ($1, $2, true, $3) RETURNING id, title, status",
        title, confidential, device_id)
    _dir(str(row["id"])).mkdir(parents=True, exist_ok=True)
    await audit.record(actor, "meeting.started", f"meeting:{row['id']}", confidential=confidential)
    return dict(row)


async def add_chunk(meeting_id: str, n: int, data: bytes) -> dict:
    """Idempotent: re-uploading chunk n (after a dropped connection) just replaces it."""
    if not 0 <= n < 100_000 or not data or len(data) > MAX_CHUNK_BYTES:
        raise MeetingError("potongan audio tidak valid")
    m = await get(meeting_id)
    if not m or m["status"] != "recording":
        raise MeetingError("rapat tidak sedang direkam")
    path = _dir(meeting_id) / f"chunk-{n:05d}.ogg"
    path.write_bytes(data)
    count = len(list(_dir(meeting_id).glob("chunk-*.ogg")))
    await db.pool().execute("UPDATE meetings SET chunks = $2 WHERE id = $1", uuid.UUID(meeting_id), count)
    return {"chunk": n, "chunks": count}


async def mark(meeting_id: str, t: float, note: str) -> None:
    await db.pool().execute("UPDATE meetings SET marks = marks || $2::jsonb WHERE id = $1",
                            uuid.UUID(meeting_id), [{"t": round(t, 1), "note": note[:200]}])


async def finish(meeting_id: str, duration_s: float | None, expected_chunks: int | None, actor: str) -> dict:
    m = await get(meeting_id)
    if not m or m["status"] != "recording":
        raise MeetingError("rapat tidak sedang direkam")
    have = len(list(_dir(meeting_id).glob("chunk-*.ogg")))
    if expected_chunks is not None and have < expected_chunks:
        raise MeetingError(f"baru {have} dari {expected_chunks} potongan diterima — unggah sisanya dulu")
    if have == 0:
        raise MeetingError("belum ada audio")
    await db.pool().execute(
        "UPDATE meetings SET status = 'queued', finished_at = now(), duration_s = $2 WHERE id = $1",
        uuid.UUID(meeting_id), duration_s)
    await audit.record(actor, "meeting.finished", f"meeting:{meeting_id}", chunks=have)
    _q().put_nowait(meeting_id)
    return {"id": meeting_id, "status": "queued", "chunks": have}


def _q() -> asyncio.Queue:
    global _queue
    if _queue is None:
        _queue = asyncio.Queue()
    return _queue


async def run_forever() -> None:
    """Process finished meetings one by one (also the ones interrupted by a restart)."""
    rows = await db.pool().fetch(
        "SELECT id FROM meetings WHERE status IN ('queued', 'transcribing', 'summarizing') ORDER BY finished_at")
    for r in rows:
        _q().put_nowait(str(r["id"]))
    while True:
        meeting_id = await _q().get()
        try:
            await process(meeting_id)
        except Exception as e:
            log.exception("meeting %s failed", meeting_id)
            await db.pool().execute("UPDATE meetings SET status = 'failed', error = $2 WHERE id = $1",
                                    uuid.UUID(meeting_id), str(e)[:500])
            await reports._create(None, "meeting", f"Maaf, notulen rapat gagal dibuat: {str(e)[:150]}")


async def _ears(path: str, body: dict, timeout: float = 7200) -> httpx.Response:
    async with httpx.AsyncClient(timeout=timeout) as c:
        r = await c.post(f"{settings.whisper_url}{path}", json=body)
    if r.status_code != 200:
        raise RuntimeError(f"jarvis-ears {path} HTTP {r.status_code}: {r.text[:200]}")
    return r


async def _transcribe(meeting: dict, paths: list[str], prompt: str) -> tuple[list[dict], str]:
    engine = "whisper" if meeting["confidential"] else await composition.stt_engine()
    if engine == "groq" and settings.groq_api_key:
        audio = (await _ears("/meeting/concat", {"paths": paths})).content
        if len(audio) <= 24_000_000:
            async with httpx.AsyncClient(timeout=600) as c:
                r = await c.post("https://api.groq.com/openai/v1/audio/transcriptions",
                                 headers={"Authorization": f"Bearer {settings.groq_api_key}"},
                                 files={"file": ("rapat.ogg", audio, "audio/ogg")},
                                 data={"model": "whisper-large-v3-turbo", "language": "id", "prompt": prompt[:800],
                                       "response_format": "verbose_json", "temperature": "0"})
            if r.status_code == 200:
                segs = [{"start": s["start"], "end": s["end"], "text": s["text"].strip()}
                        for s in r.json().get("segments", []) if s.get("text", "").strip()]
                return segs, "groq"
            log.warning("groq meeting transcription failed (%s); falling back to local", r.status_code)
    if engine == "deepgram" and settings.deepgram_api_key:
        audio = (await _ears("/meeting/concat", {"paths": paths})).content
        async with httpx.AsyncClient(timeout=900) as c:
            r = await c.post("https://api.deepgram.com/v1/listen",
                             params={"model": settings.deepgram_model, "language": "id", "smart_format": "true",
                                     "utterances": "true"}, content=audio,
                             headers={"Authorization": f"Token {settings.deepgram_api_key}", "Content-Type": "audio/ogg"})
        if r.status_code == 200:
            utt = r.json().get("results", {}).get("utterances") or []
            return [{"start": u["start"], "end": u["end"], "text": u["transcript"]} for u in utt], "deepgram"
        log.warning("deepgram meeting transcription failed (%s); falling back to local", r.status_code)
    data = (await _ears("/meeting/transcribe", {"paths": paths, "prompt": prompt})).json()
    return data["segments"], "whisper"


def assign_speakers(segments: list[dict], turns: list[dict], names: dict[str, str]) -> list[dict]:
    """Label each transcript segment with the speaker who talked most during it. Pure; unit-tested."""
    out = []
    for s in segments:
        best, best_overlap = None, 0.0
        for t in turns:
            overlap = min(s["end"], t["end"]) - max(s["start"], t["start"])
            if overlap > best_overlap:
                best, best_overlap = str(t["speaker"]), overlap
        out.append({**s, "speaker": names.get(best, "Pembicara") if best is not None else "Pembicara"})
    return out


def blocks(transcript: list[dict], seconds: int = 600, max_chars: int = 16000) -> list[str]:
    """~10-minute blocks of 'mm:ss Speaker: text' lines for map-reduce summarising. Pure; unit-tested."""
    out, cur, start = [], [], None
    for s in transcript:
        if start is None:
            start = s["start"]
        line = f"{int(s['start'] // 60):02d}:{int(s['start'] % 60):02d} {s.get('speaker', '')}: {s['text']}"
        if cur and (s["start"] - start > seconds or sum(map(len, cur)) + len(line) > max_chars):
            out.append("\n".join(cur))
            cur, start = [], s["start"]
        cur.append(line)
    if cur:
        out.append("\n".join(cur))
    return out


NOTES_PROMPT = """Kamu notulis rapat JARVIS. Ini potongan transkrip rapat (bahasa Indonesia, hasil mesin — bisa ada \
salah dengar). Tulis catatan padat: poin pembahasan, keputusan, tugas (siapa, apa, tenggat bila disebut), \
pertanyaan yang belum terjawab. Jangan menambah fakta."""

FINAL_PROMPT = """Kamu notulis rapat JARVIS. Dari catatan per bagian rapat "{title}" berikut, susun NOTULEN. \
Jawab HANYA dengan JSON:
{{"ringkasan": "3–6 kalimat",
  "keputusan": ["..."],
  "action_items": [{{"siapa": "...", "apa": "...", "tenggat": "... atau kosong"}}],
  "pertanyaan": ["hal yang belum terjawab"],
  "topik": ["topik utama"]}}
Penanda penting dari pemilik selama rapat: {marks}"""


def _json(text: str) -> dict:
    m = re.search(r"\{.*\}", text or "", re.DOTALL)
    try:
        return json.loads(m.group(0)) if m else {}
    except ValueError:
        return {}


async def _summarize(meeting: dict, transcript: list[dict]) -> dict:
    private = meeting["confidential"]
    notes = []
    for b in blocks(transcript):
        notes.append(await llm.complete([{"role": "system", "content": NOTES_PROMPT}, {"role": "user", "content": b}],
                                        category="rapat", caller="meeting", private=private, max_tokens=700))
    marks = "; ".join(f"{int(m['t'] // 60):02d}:{int(m['t'] % 60):02d} {m['note']}" for m in meeting["marks"] or []) or "-"
    raw = await llm.complete([{"role": "system", "content": FINAL_PROMPT.format(title=meeting["title"], marks=marks)},
                              {"role": "user", "content": "\n\n---\n\n".join(notes)[:60000]}],
                             category="rapat", caller="meeting", private=private, max_tokens=1500, temperature=0.2)
    summary = _json(raw)
    if not summary.get("ringkasan"):
        summary = {"ringkasan": raw.strip()[:2000], "keputusan": [], "action_items": [], "pertanyaan": [], "topik": []}
    return summary


def minutes_markdown(meeting: dict, summary: dict, transcript: list[dict], speakers: dict) -> str:
    when = meeting["started_at"].astimezone(WIB).strftime("%A, %d %B %Y %H:%M WIB")
    lines = [f"Waktu: {when}", f"Durasi: {int((meeting.get('duration_s') or 0) // 60)} menit",
             f"Peserta terdeteksi: {', '.join(sorted(set(speakers.values()))) or '-'}", "",
             "## Ringkasan", summary.get("ringkasan", ""), "", "## Keputusan"]
    lines += [f"- {k}" for k in summary.get("keputusan") or ["(tidak ada)"]]
    lines += ["", "## Action items", "| Siapa | Apa | Tenggat |", "|---|---|---|"]
    lines += [f"| {a.get('siapa', '')} | {a.get('apa', '')} | {a.get('tenggat', '')} |" for a in summary.get("action_items") or []]
    lines += ["", "## Pertanyaan terbuka"] + [f"- {q}" for q in summary.get("pertanyaan") or ["(tidak ada)"]]
    lines += ["", "## Transkrip"]
    lines += [f"**{int(s['start'] // 60):02d}:{int(s['start'] % 60):02d} {s.get('speaker', '')}:** {s['text']}" for s in transcript]
    return "\n".join(lines)


async def _index(meeting_id: str, title: str, transcript: list[dict]) -> None:
    """Transcript in ~1-minute passages, embedded locally, for questions about this meeting later."""
    passages, cur, start = [], [], None
    for s in transcript:
        start = s["start"] if start is None else start
        cur.append(f"{s.get('speaker', '')}: {s['text']}")
        if s["end"] - start >= 60:
            passages.append((start, " ".join(cur)))
            cur, start = [], None
    if cur:
        passages.append((start or 0, " ".join(cur)))
    if not passages:
        return
    vectors = await memory.embed([p[1][:2000] for p in passages])
    async with memory._qdrant() as q:
        r = await q.get(f"/collections/{COLLECTION}")
        if r.status_code == 404:
            await q.put(f"/collections/{COLLECTION}", json={"vectors": {"size": len(vectors[0]), "distance": "Cosine"}})
        await q.put(f"/collections/{COLLECTION}/points?wait=true", json={"points": [
            {"id": str(uuid.uuid4()), "vector": v, "payload": {"meeting_id": meeting_id, "title": title, "t": p[0], "text": p[1][:2000]}}
            for p, v in zip(passages, vectors)]})


async def process(meeting_id: str) -> None:
    mid = uuid.UUID(meeting_id)
    meeting = await get(meeting_id)
    if not meeting:
        return
    paths = [f"{mid}/{p.name}" for p in sorted(_dir(meeting_id).glob("chunk-*.ogg"))]
    started = time.monotonic()
    await db.pool().execute("UPDATE meetings SET status = 'transcribing', error = NULL WHERE id = $1", mid)
    prompt = await stt.vocabulary()
    segments, engine = await _transcribe(meeting, paths, prompt)
    segments = [s for s in segments if not stt.HALLUCINATIONS.match(s["text"])]
    diar = (await _ears("/meeting/diarize", {"paths": paths})).json()
    owner = await voice_id._load()
    names = voice_id.name_speakers(diar.get("voices") or {}, (owner or {}).get("vector"),
                                   [str(t["speaker"]) for t in diar.get("segments", [])])
    transcript = assign_speakers(segments, diar.get("segments", []), names)
    await db.pool().execute(
        "UPDATE meetings SET status = 'summarizing', transcript = $2, speakers = $3, engine = $4 WHERE id = $1",
        mid, transcript, names, engine)
    meeting = await get(meeting_id)
    summary = await _summarize(meeting, transcript) if transcript else {
        "ringkasan": "Tidak ada ucapan yang terdengar jelas dalam rekaman ini.", "keputusan": [], "action_items": [],
        "pertanyaan": [], "topik": []}
    doc = await documents.create(f"Notulen — {meeting['title']}", "docx",
                                 minutes_markdown(meeting, summary, transcript, names), "jarvis-meeting")
    await db.pool().execute(
        "UPDATE meetings SET status = 'done', summary = $2, document_id = $3, done_at = now() WHERE id = $1",
        mid, summary, doc["id"])
    try:
        await _index(meeting_id, meeting["title"], transcript)
    except Exception:
        log.exception("meeting %s not indexed", meeting_id)
    n_items = len(summary.get("action_items") or [])
    await reports._create(None, "meeting",
                          f"Notulen rapat {meeting['title']} sudah siap. {summary.get('ringkasan', '')[:300]} "
                          f"Ada {n_items} action item; dokumennya bisa dibuka di menu Rapat.")
    log.info("meeting %s done in %.0f s (%s)", meeting_id, time.monotonic() - started, engine)


async def ask(meeting_id: str, question: str) -> dict:
    """Answer a question about one meeting from its transcript (local embeddings + the 'rapat' model)."""
    meeting = await get(meeting_id)
    if not meeting or meeting["status"] != "done":
        raise MeetingError("notulen rapat ini belum siap")
    [vector] = await memory.embed([question])
    async with memory._qdrant() as q:
        r = await q.post(f"/collections/{COLLECTION}/points/search", json={
            "vector": vector, "limit": 6, "with_payload": True,
            "filter": {"must": [{"key": "meeting_id", "match": {"value": meeting_id}}]}})
    hits = r.json().get("result", []) if r.status_code == 200 else []
    context = "\n".join(f"[{int(h['payload']['t'] // 60):02d}:{int(h['payload']['t'] % 60):02d}] {h['payload']['text']}" for h in hits)
    answer = await llm.complete([
        {"role": "system", "content": "Jawab pertanyaan pemilik tentang rapat ini hanya dari kutipan transkrip dan "
                                      "notulen. Sebut menit-nya. Kalau tidak ada, katakan tidak dibahas. Singkat."},
        {"role": "user", "content": f"Notulen: {json.dumps(meeting['summary'], ensure_ascii=False)[:4000]}\n\n"
                                    f"Kutipan:\n{context}\n\nPertanyaan: {question}"}],
        category="rapat", caller="meeting", private=meeting["confidential"], max_tokens=400)
    return {"answer": answer, "sources": [{"t": h["payload"]["t"], "text": h["payload"]["text"][:300]} for h in hits]}


async def get(meeting_id: str) -> dict | None:
    try:
        mid = uuid.UUID(meeting_id)
    except ValueError:
        return None
    row = await db.pool().fetchrow("SELECT * FROM meetings WHERE id = $1", mid)
    return dict(row) if row else None


async def list_(limit: int = 50) -> list[dict]:
    rows = await db.pool().fetch(
        """SELECT id, title, status, confidential, chunks, duration_s, started_at, done_at, document_id,
                  summary->>'ringkasan' AS ringkasan, jsonb_array_length(coalesce(summary->'action_items', '[]')) AS action_items
           FROM meetings ORDER BY started_at DESC LIMIT $1""", limit)
    return [dict(r) for r in rows]


def chunk_path(meeting_id: str, n: int) -> Path | None:
    p = _dir(meeting_id) / f"chunk-{n:05d}.ogg"
    return p if p.is_file() else None


async def delete(meeting_id: str, actor: str) -> bool:
    mid = uuid.UUID(meeting_id)
    done = await db.pool().execute("DELETE FROM meetings WHERE id = $1", mid)
    shutil.rmtree(_dir(meeting_id), ignore_errors=True)
    try:
        async with memory._qdrant() as q:
            await q.post(f"/collections/{COLLECTION}/points/delete?wait=true",
                         json={"filter": {"must": [{"key": "meeting_id", "match": {"value": meeting_id}}]}})
    except httpx.HTTPError:
        pass
    await audit.record(actor, "meeting.deleted", f"meeting:{meeting_id}")
    return done.endswith("1")


async def purge_audio() -> int:
    rows = await db.pool().fetch(
        f"""UPDATE meetings SET audio_purged = true WHERE NOT audio_purged AND status IN ('done', 'failed')
            AND started_at < now() - interval '{AUDIO_RETENTION_DAYS} days' RETURNING id""")
    for r in rows:
        for f in _dir(str(r["id"])).glob("chunk-*.ogg"):
            f.unlink(missing_ok=True)
    return len(rows)
