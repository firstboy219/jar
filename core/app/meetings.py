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
import difflib
import json
import logging
import re
import shutil
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx

from . import audit, composition, db, documents, hub, llm, memory, reports, stt, voice_id
from .config import settings
from .location import WIB

log = logging.getLogger("jarvis-core.meetings")
ROOT = Path("/data/meetings")
MAX_CHUNK_BYTES = 3_000_000   # 60 s of Opus/AAC at 24–32 kbps is ~250 KB; generous for other codecs
CHUNK_EXTS = ("ogg", "aac", "m4a", "webm")  # the phone sends continuous AAC (.aac) since v0.11; older apps Ogg/Opus; the desk in a browser WebM/Opus
STALE_MINUTES = 20            # a recording with no new chunk for this long was abandoned (phone off, app killed)
LOW_CONFIDENCE = 0.40
AUDIO_RETENTION_DAYS = 30
COLLECTION = "jarvis_meetings"
_queue: asyncio.Queue | None = None


class MeetingError(ValueError):
    pass


def _dir(meeting_id: str) -> Path:
    return ROOT / str(uuid.UUID(meeting_id))


async def create(title: str, confidential: bool, consent: bool, device_id=None, actor: str = "owner",
                 participants: list[str] | None = None, agenda: str = "") -> dict:
    if not consent:
        raise MeetingError("perekaman butuh persetujuan peserta")
    title = (title or "").strip()[:150] or f"Rapat {datetime.now(WIB):%d %b %Y %H:%M}"
    context = {"participants": [p.strip()[:60] for p in (participants or []) if p.strip()][:30],
               "agenda": (agenda or "").strip()[:2000]}
    row = await db.pool().fetchrow(
        "INSERT INTO meetings (title, confidential, consent, device_id, context) VALUES ($1, $2, true, $3, $4) "
        "RETURNING id, title, status",
        title, confidential, device_id, context)
    _dir(str(row["id"])).mkdir(parents=True, exist_ok=True)
    forget_want()   # the meeting the desk card asked for has begun
    await audit.record(actor, "meeting.started", f"meeting:{row['id']}", confidential=confidential)
    return dict(row)


# ---------- the desk's meeting card (ADR-054) ----------
# "Mulai rapat" by voice or chat does not record by itself — recording others needs everyone's consent — it puts the meeting card on the
# desk with the button that starts it. The card then follows the meeting from its row (recording → processing → done), whichever device
# holds the microphone; "stop" by voice raises stop_seq, which the recording device sees and obeys.
WANT_TTL_S = 30 * 60
SHOW_DONE_S = 30 * 60
_desk: dict = {"want": None, "stop_seq": 0}


def want_to_record(title: str = "", confidential: bool = False, participants: list[str] | None = None, agenda: str = "") -> dict:
    _desk["want"] = {"title": (title or "").strip()[:150], "confidential": bool(confidential),
                     "participants": [p.strip()[:60] for p in (participants or []) if p.strip()][:30],
                     "agenda": (agenda or "").strip()[:2000], "at": time.time()}
    return _desk["want"]


async def want_to_stop(actor: str = "owner") -> bool:
    """False when no meeting is being recorded (nothing to stop). Otherwise whoever holds the microphone — the app on the phone (told by
    a meeting_cmd event) or a browser desk (sees stop_seq change) — stops and sends the recording for minutes."""
    if not await db.pool().fetchval("SELECT 1 FROM meetings WHERE status = 'recording' LIMIT 1"):
        return False
    _desk["stop_seq"] += 1
    await hub.broadcast({"type": "meeting_cmd", "cmd": "stop"})
    await audit.record(actor, "meeting.stop_requested", None)
    return True


async def request_start(title: str, confidential: bool, participants: list[str], agenda: str, actor: str) -> dict:
    """The owner ticked 'everyone agrees' on the desk card and pressed Mulai rekam in the app: the phone records. Delivered = devices told."""
    forget_want()
    await audit.record(actor, "meeting.start_requested", None, confidential=confidential)
    delivered = await hub.broadcast({"type": "meeting_cmd", "cmd": "start", "title": (title or "").strip()[:150], "confidential": bool(confidential),
                                     "participants": [p.strip()[:60] for p in participants if p.strip()][:30], "agenda": (agenda or "").strip()[:2000]})
    return {"delivered": delivered}


def forget_want() -> None:
    _desk["want"] = None


async def desk_card() -> dict | None:
    """The card's state: recording | processing | waiting (asked, not started) | done | failed — or None when there is nothing to show."""
    row = await db.pool().fetchrow(
        """SELECT id, title, status, confidential, chunks, started_at, duration_s, document_id, error, coalesce(done_at, finished_at, started_at) AS ended
           FROM meetings WHERE status IN ('recording', 'queued', 'transcribing', 'summarizing')
              OR (status IN ('done', 'failed') AND coalesce(done_at, finished_at, started_at) > now() - make_interval(secs => $1))
           ORDER BY started_at DESC LIMIT 1""", SHOW_DONE_S)
    want = _desk["want"]
    if want and time.time() - want["at"] > WANT_TTL_S:
        want = _desk["want"] = None
    live_row = row and row["status"] in ("recording", "queued", "transcribing", "summarizing")
    if live_row:
        state = "recording" if row["status"] == "recording" else "processing"
    elif want:
        return {"state": "waiting", "key": f"want:{want['at']}", "title": want["title"], "confidential": want["confidential"],
                "participants": want["participants"], "agenda": want["agenda"], "stop_seq": _desk["stop_seq"]}
    elif row:
        state = row["status"]
    else:
        return None
    return {"state": state, "key": f"{row['id']}:{state}", "id": str(row["id"]), "title": row["title"],
            "confidential": row["confidential"], "chunks": row["chunks"], "started_at": row["started_at"].timestamp(),
            "duration_s": row["duration_s"], "document_id": str(row["document_id"]) if row["document_id"] else None,
            "error": (row["error"] or "")[:200] if state == "failed" else "", "status": row["status"], "stop_seq": _desk["stop_seq"]}


def chunk_files(meeting_id: str) -> list[Path]:
    """The recorded chunks in order (whatever container the phone used)."""
    return sorted(p for p in _dir(meeting_id).glob("chunk-*.*") if p.suffix[1:] in CHUNK_EXTS)


async def add_chunk(meeting_id: str, n: int, data: bytes, ext: str = "ogg") -> dict:
    """Idempotent: re-uploading chunk n (after a dropped connection) just replaces it."""
    if ext not in CHUNK_EXTS or not 0 <= n < 100_000 or not data or len(data) > MAX_CHUNK_BYTES:
        raise MeetingError("potongan audio tidak valid")
    m = await get(meeting_id)
    if not m or m["status"] != "recording":
        raise MeetingError("rapat tidak sedang direkam")
    for other in _dir(meeting_id).glob(f"chunk-{n:05d}.*"):
        other.unlink(missing_ok=True)
    path = _dir(meeting_id) / f"chunk-{n:05d}.{ext}"
    path.write_bytes(data)
    count = len(chunk_files(meeting_id))
    await db.pool().execute("UPDATE meetings SET chunks = $2 WHERE id = $1", uuid.UUID(meeting_id), count)
    return {"chunk": n, "chunks": count}


async def mark(meeting_id: str, t: float, note: str) -> None:
    await db.pool().execute("UPDATE meetings SET marks = marks || $2::jsonb WHERE id = $1",
                            uuid.UUID(meeting_id), [{"t": round(t, 1), "note": note[:200]}])


async def finish(meeting_id: str, duration_s: float | None, expected_chunks: int | None, actor: str) -> dict:
    m = await get(meeting_id)
    if not m or m["status"] != "recording":
        raise MeetingError("rapat tidak sedang direkam")
    have = len(chunk_files(meeting_id))
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
        try:
            meeting_id = await asyncio.wait_for(_q().get(), timeout=300)
        except asyncio.TimeoutError:
            try:
                await finish_stale()
            except Exception:
                log.exception("stale meeting sweep failed")
            continue
        try:
            await process(meeting_id)
        except Exception as e:
            log.exception("meeting %s failed", meeting_id)
            await db.pool().execute("UPDATE meetings SET status = 'failed', error = $2 WHERE id = $1",
                                    uuid.UUID(meeting_id), str(e)[:500])
            await reports._create(None, "meeting", f"Maaf, notulen rapat gagal dibuat: {str(e)[:150]}")


_TERM = re.compile(r"\b(?:[A-Z]{2,}[A-Za-z0-9]*|[A-Z][a-z0-9]{2,}(?:\s[A-Z][a-z0-9]{2,})*)\b")
_COMMON = {"Rapat", "Agenda", "Hari", "Bulan", "Tahun", "Pak", "Bu", "Mas", "Mbak", "Kita", "Kami", "Dari", "Untuk", "Yang"}


def meeting_terms(meeting: dict, base: list[str] | None = None) -> dict:
    """What the recogniser should expect to hear in THIS meeting: names, projects, abbreviations — from the
    participants and agenda the owner typed, the title and the vocabulary JARVIS already learned. Pure; unit-tested.
    Returns {"prompt" (for Whisper's initial prompt), "hotwords", "glossary"}."""
    ctx = meeting.get("context") or {}
    people = [p for p in (ctx.get("participants") or []) if p]
    found: list[str] = []
    for text in (meeting.get("title") or "", ctx.get("agenda") or ""):
        for m in _TERM.finditer(text):
            t = m.group(0).strip()
            starts_sentence = m.start() == 0 or text[:m.start()].rstrip().endswith((".", "!", "?", ":", "\n"))
            special = t.isupper() or any(c.isdigit() for c in t) or any(c.isupper() for c in t[1:])  # UAT, n8n, JavaScript
            if (starts_sentence and not special) or t in _COMMON or t in found or t in people:
                continue  # an ordinary word that merely begins a sentence
            found.append(t)
    terms = list(dict.fromkeys([*people, *found, *(base or [])]))
    glossary = [t for t in terms if len(t) >= 5]
    parts = [f"Rapat \"{(meeting.get('title') or '').strip()}\"."]
    if people:
        parts.append("Peserta: " + ", ".join(people[:12]) + ".")
    if terms:
        parts.append("Istilah: " + ", ".join(terms[:25]) + ".")
    return {"prompt": " ".join(parts)[:700], "hotwords": " ".join(terms[:20])[:300], "glossary": glossary}


def correct_terms(text: str, glossary: list[str], threshold: float = 0.86) -> str:
    """Fix near-miss spellings of known names/terms ("Deep Drum" → "Deepgram", "Bu Rinah" → "Bu Rina").
    A word or a pair of words is replaced only when it is very close to a glossary entry and starts with the
    same letter — everyday words are left alone. Pure; unit-tested."""
    if not glossary or not text:
        return text
    norm = lambda s: re.sub(r"\W+", "", s.lower())
    entries = {norm(g): g for g in glossary if len(norm(g)) >= 5}
    words, out, i = text.split(" "), [], 0
    while i < len(words):
        for span in (2, 1):
            if i + span > len(words):
                continue
            chunk = " ".join(words[i:i + span])
            lead, core, tail = re.match(r"^(\W*)(.*?)(\W*)$", chunk, re.DOTALL).groups()
            n = norm(core)
            if len(n) < 5:
                continue
            best, ratio = None, 0.0
            for k, g in entries.items():
                if k[0] != n[0]:
                    continue
                r = 1.0 if k == n else difflib.SequenceMatcher(None, n, k).ratio()
                if r > ratio:
                    best, ratio = g, r
            if best and ratio >= threshold:
                out.append(lead + best + tail)
                i += span
                break
        else:
            out.append(words[i])
            i += 1
    return " ".join(out)


def flag_unclear(segments: list[dict]) -> list[dict]:
    """Mark segments the recogniser itself was unsure about; the minutes must not turn them into facts. Pure."""
    return [{**s, "low": True} if (s.get("confidence") is not None and s["confidence"] < LOW_CONFIDENCE) else s
            for s in segments]


async def finish_stale() -> int:
    """Recordings abandoned mid-way (phone switched off, app killed): after STALE_MINUTES without a new chunk,
    process what was received instead of leaving the meeting 'recording' forever."""
    rows = await db.pool().fetch("SELECT id, title FROM meetings WHERE status = 'recording'")
    done = 0
    for r in rows:
        mid = str(r["id"])
        files = chunk_files(mid)
        newest = max((f.stat().st_mtime for f in files), default=None)
        if newest is None:
            newest = (await get(mid))["started_at"].timestamp()
        if time.time() - newest < STALE_MINUTES * 60:
            continue
        if not files:
            await db.pool().execute("UPDATE meetings SET status = 'failed', error = $2 WHERE id = $1", r["id"],
                                    "rekaman terhenti sebelum ada audio yang terunggah")
            continue
        await db.pool().execute(
            "UPDATE meetings SET status = 'queued', finished_at = now(), duration_s = $2 WHERE id = $1",
            r["id"], len(files) * 60.0)
        await audit.record("jarvis-core", "meeting.auto_finished", f"meeting:{mid}", chunks=len(files))
        _q().put_nowait(mid)
        await reports._create(None, "meeting", f"Rekaman rapat {r['title']} berhenti tanpa ditutup. "
                                                f"Kuproses {len(files)} menit audio yang sudah masuk.")
        done += 1
    return done


async def _ears(path: str, body: dict, timeout: float = 7200) -> httpx.Response:
    async with httpx.AsyncClient(timeout=timeout) as c:
        r = await c.post(f"{settings.whisper_url}{path}", json=body)
    if r.status_code != 200:
        raise RuntimeError(f"jarvis-ears {path} HTTP {r.status_code}: {r.text[:200]}")
    return r


async def _transcribe(meeting: dict, paths: list[str], prompt: str, hotwords: str = "") -> tuple[list[dict], str]:
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
    data = (await _ears("/meeting/transcribe", {"paths": paths, "prompt": prompt, "hotwords": hotwords})).json()
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
        line = f"{int(s['start'] // 60):02d}:{int(s['start'] % 60):02d} {s.get('speaker', '')}: {s['text']}" + (" [?]" if s.get("low") else "")
        if cur and (s["start"] - start > seconds or sum(map(len, cur)) + len(line) > max_chars):
            out.append("\n".join(cur))
            cur, start = [], s["start"]
        cur.append(line)
    if cur:
        out.append("\n".join(cur))
    return out


NOTES_PROMPT = """Kamu notulis rapat JARVIS. Ini potongan transkrip rapat (bahasa Indonesia, hasil mesin — bisa ada \
salah dengar). Tulis catatan padat: poin pembahasan, keputusan, tugas (siapa, apa, tenggat bila disebut), \
pertanyaan yang belum terjawab. Jangan menambah fakta. Baris bertanda [?] suaranya tidak jelas: jangan dijadikan \
keputusan atau tugas. Pakai nama peserta dari konteks bila ucapannya jelas menyebut atau menunjuk orangnya.

KONTEKS RAPAT:
{context}"""

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


async def context_text(meeting: dict) -> str:
    """Agenda, participants and what JARVIS remembers about the topic — for the minutes' prompts."""
    ctx = meeting.get("context") or {}
    lines = [f"Judul: {meeting['title']}"]
    if ctx.get("participants"):
        lines.append("Peserta: " + ", ".join(ctx["participants"]))
    if ctx.get("agenda"):
        lines.append("Agenda/topik: " + ctx["agenda"][:1200])
    try:
        hits = [m["text"] for m in await memory.search(f"{meeting['title']} {ctx.get('agenda', '')}"[:300], limit=4) if m["score"] >= 0.4]
    except Exception:
        hits = []
    if hits:
        lines.append("Yang JARVIS ingat terkait (bisa usang): " + " | ".join(h[:200] for h in hits))
    return "\n".join(lines)


async def _summarize(meeting: dict, transcript: list[dict]) -> dict:
    private = meeting["confidential"]
    notes = []
    system = NOTES_PROMPT.format(context=await context_text(meeting))
    for b in blocks(transcript):
        notes.append(await llm.complete([{"role": "system", "content": system}, {"role": "user", "content": b}],
                                        category="rapat", caller="meeting", private=private, max_tokens=700))
    marks = "; ".join(f"{int(m['t'] // 60):02d}:{int(m['t'] % 60):02d} {m['note']}" for m in meeting["marks"] or []) or "-"
    raw = await llm.complete([{"role": "system", "content": FINAL_PROMPT.format(title=meeting["title"], marks=marks)
                                              + "\n\nKONTEKS RAPAT:\n" + await context_text(meeting)},
                              {"role": "user", "content": "\n\n---\n\n".join(notes)[:60000]}],
                             category="rapat", caller="meeting", private=private, max_tokens=1500, temperature=0.2)
    summary = _json(raw)
    if not summary.get("ringkasan"):
        summary = {"ringkasan": raw.strip()[:2000], "keputusan": [], "action_items": [], "pertanyaan": [], "topik": []}
    return summary


def minutes_markdown(meeting: dict, summary: dict, transcript: list[dict], speakers: dict) -> str:
    when = meeting["started_at"].astimezone(WIB).strftime("%A, %d %B %Y %H:%M WIB")
    ctx = meeting.get("context") or {}
    lines = [f"Waktu: {when}", f"Durasi: {int((meeting.get('duration_s') or 0) // 60)} menit",
             f"Peserta terdeteksi: {', '.join(sorted(set(speakers.values()))) or '-'}"]
    if ctx.get("participants"):
        lines.append("Peserta (dari pemilik): " + ", ".join(ctx["participants"]))
    if ctx.get("agenda"):
        lines.append("Agenda: " + ctx["agenda"])
    lines.append("")
    lines += [
             "## Ringkasan", summary.get("ringkasan", ""), "", "## Keputusan"]
    lines += [f"- {k}" for k in summary.get("keputusan") or ["(tidak ada)"]]
    lines += ["", "## Action items", "| Siapa | Apa | Tenggat |", "|---|---|---|"]
    lines += [f"| {a.get('siapa', '')} | {a.get('apa', '')} | {a.get('tenggat', '')} |" for a in summary.get("action_items") or []]
    lines += ["", "## Pertanyaan terbuka"] + [f"- {q}" for q in summary.get("pertanyaan") or ["(tidak ada)"]]
    lines += ["", "## Transkrip"]
    lines += [f"**{int(s['start'] // 60):02d}:{int(s['start'] % 60):02d} {s.get('speaker', '')}:** {s['text']}"
              + (" *(suara kurang jelas)*" if s.get("low") else "") for s in transcript]
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
    paths = [f"{mid}/{p.name}" for p in chunk_files(meeting_id)]
    started = time.monotonic()
    await db.pool().execute("UPDATE meetings SET status = 'transcribing', error = NULL WHERE id = $1", mid)
    base = [k.strip() for k in (await stt.vocabulary()).split(",") if k.strip()]
    terms = meeting_terms(meeting, base)
    segments, engine = await _transcribe(meeting, paths, terms["prompt"], terms["hotwords"])
    segments = [s for s in segments if not stt.HALLUCINATIONS.match(s["text"])]
    segments = flag_unclear([{**s, "text": correct_terms(s["text"], terms["glossary"])} for s in segments])
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
    try:   # the minutes become a page in Catatan, their action items its to-dos (ADR-060)
        from . import notes
        await notes.from_meeting(str(meeting_id))
    except Exception:
        log.exception("meeting %s: no notes page", meeting_id)
    await reports._create(None, "meeting",
                          f"Notulen rapat {meeting['title']} sudah siap. {summary.get('ringkasan', '')[:300]} "
                          f"Ada {n_items} action item; dokumennya bisa dibuka di menu Rapat, tugasnya ada di Catatan.")
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
    found = list(_dir(meeting_id).glob(f"chunk-{n:05d}.*"))
    return found[0] if found else None


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
        for f in chunk_files(str(r["id"])):
            f.unlink(missing_ok=True)
    return len(rows)


async def rename_speaker(meeting_id: str, old: str, new: str, actor: str) -> dict:
    """The owner tells who "Pembicara 2" is: relabel the transcript, rebuild the minutes document and the
    search index. The summary text is left as it is (it already used whatever names the recording gave)."""
    new = (new or "").strip()[:60]
    old = (old or "").strip()
    m = await get(meeting_id)
    if not m or m["status"] != "done":
        raise MeetingError("notulen rapat ini belum siap")
    if not new or old == "Pemilik" or old not in (m["speakers"] or {}).values():
        raise MeetingError("pembicara tidak dikenal")
    transcript = [{**s, "speaker": new} if s.get("speaker") == old else s for s in m["transcript"] or []]
    speakers = {k: (new if v == old else v) for k, v in (m["speakers"] or {}).items()}
    summary = json.loads(json.dumps(m["summary"] or {}, ensure_ascii=False).replace(old, new))
    doc = await documents.create(f"Notulen — {m['title']}", "docx",
                                 minutes_markdown(m, summary, transcript, speakers), "jarvis-meeting")
    await db.pool().execute(
        "UPDATE meetings SET transcript = $2, speakers = $3, summary = $4, document_id = $5 WHERE id = $1",
        uuid.UUID(meeting_id), transcript, speakers, summary, doc["id"])
    try:
        async with memory._qdrant() as q:
            await q.post(f"/collections/{COLLECTION}/points/delete?wait=true",
                         json={"filter": {"must": [{"key": "meeting_id", "match": {"value": meeting_id}}]}})
        await _index(meeting_id, m["title"], transcript)
    except Exception:
        log.exception("meeting %s not re-indexed", meeting_id)
    await audit.record(actor, "meeting.speaker_renamed", f"meeting:{meeting_id}")
    return {"renamed": old, "to": new, "document_id": str(doc["id"])}
