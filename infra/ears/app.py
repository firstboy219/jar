"""jarvis-ears — JARVIS' local hearing (internal network only; nothing leaves the server).

POST /transcribe        raw PCM16 mono 16 kHz body (one utterance, from the phone's VAD)
                        ?prompt=<vocabulary>&model=small → {text, confidence, no_speech, duration_s, ms}
POST /transcribe_file   any audio file (a meeting), body = file bytes → {segments[{start,end,text}], duration_s}
                        runs at low CPU priority so live speech still comes first
POST /speaker/embed     raw PCM16 → {embedding: [...]} (voiceprint enrolment / check)
POST /diarize           audio file → {segments[{start,end,speaker}], speakers}
POST /meeting/{transcribe|diarize|concat}  {"paths": [...files under /meetings...]} — a recorded meeting
                        (many chunks) treated as one recording
GET  /health

Models: faster-whisper int8 (small for live utterances, a larger one for meetings), downloaded once into
/models; sherpa-onnx CAM++ speaker embeddings + pyannote segmentation (baked into the image).
"""

import asyncio
import os
import subprocess
import tempfile
import threading
import time

import numpy as np
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel

LIVE_MODEL = os.getenv("WHISPER_LIVE_MODEL", "small")
FILE_MODEL = os.getenv("WHISPER_FILE_MODEL", "small")
THREADS = int(os.getenv("WHISPER_THREADS", "4"))
MAX_LIVE_S = 60
SR = 16000

app = FastAPI(title="jarvis-ears", docs_url=None, redoc_url=None, openapi_url=None)
_models: dict = {}
_lock = threading.Lock()          # one live transcription at a time (2 physical cores)
_file_lock = threading.Lock()     # one meeting at a time
_speaker = {}


def _whisper(name: str):
    with _lock:
        if name not in _models:
            from faster_whisper import WhisperModel
            _models[name] = WhisperModel(name, device="cpu", compute_type="int8", cpu_threads=THREADS,
                                         download_root="/models/whisper")
        return _models[name]


def _pcm(body: bytes) -> np.ndarray:
    if len(body) < 3200:  # < 0.1 s
        raise HTTPException(400, "audio terlalu pendek")
    if len(body) > MAX_LIVE_S * SR * 2:
        raise HTTPException(413, "audio terlalu panjang untuk satu ucapan")
    return np.frombuffer(body[: len(body) // 2 * 2], dtype=np.int16).astype(np.float32) / 32768.0


MEETINGS = "/meetings"


def _decode_paths(paths: list[str]) -> np.ndarray:
    """Many chunk files (same recording) → one 16 kHz mono stream, via ffmpeg's concat demuxer."""
    real = []
    for p in paths:
        full = os.path.realpath(os.path.join(MEETINGS, p))
        if not full.startswith(MEETINGS + "/") or not os.path.isfile(full):
            raise HTTPException(400, f"file tidak valid: {p}")
        real.append(full)
    if not real:
        raise HTTPException(400, "tidak ada audio")
    with tempfile.NamedTemporaryFile("w", suffix=".txt") as lst:
        lst.write("".join(f"file '{p}'\n" for p in real))
        lst.flush()
        out = subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-f", "concat", "-safe", "0", "-i", lst.name,
                              "-ac", "1", "-ar", str(SR), "-f", "s16le", "-"], capture_output=True, timeout=3600)
    if out.returncode != 0 or not out.stdout:
        raise HTTPException(400, "audio rapat tidak bisa dibaca")
    return np.frombuffer(out.stdout, dtype=np.int16).astype(np.float32) / 32768.0


def _decode_file(data: bytes) -> np.ndarray:
    """Any container/codec → 16 kHz mono float32 via ffmpeg."""
    with tempfile.NamedTemporaryFile(suffix=".bin") as f:
        f.write(data)
        f.flush()
        out = subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-i", f.name, "-ac", "1", "-ar", str(SR),
                              "-f", "s16le", "-"], capture_output=True, timeout=1800)
    if out.returncode != 0 or not out.stdout:
        raise HTTPException(400, "audio tidak bisa dibaca")
    return np.frombuffer(out.stdout, dtype=np.int16).astype(np.float32) / 32768.0


def _low_priority() -> None:
    """Meetings yield the CPU to live speech and chat: nice +15 for this thread only (Linux nice is per-thread)."""
    try:
        os.setpriority(os.PRIO_PROCESS, threading.get_native_id(), 15)
    except OSError:
        pass


@app.get("/health")
async def health():
    return {"ok": True, "loaded": sorted(_models), "live_model": LIVE_MODEL}


@app.post("/transcribe")
async def transcribe(request: Request, prompt: str = "", model: str = "", language: str = "id"):
    audio = _pcm(await request.body())
    started = time.monotonic()

    def run():
        m = _whisper(model or LIVE_MODEL)
        with _lock:
            segs, info = m.transcribe(audio, language=language or None, beam_size=1, vad_filter=False,
                                      initial_prompt=prompt[:600] or None, condition_on_previous_text=False,
                                      without_timestamps=True)
            segs = list(segs)
        return segs, info

    segs, info = await asyncio.to_thread(run)
    text = " ".join(s.text.strip() for s in segs).strip()
    logprob = float(np.mean([s.avg_logprob for s in segs])) if segs else -5.0
    no_speech = float(max((s.no_speech_prob for s in segs), default=1.0))
    return {"text": text, "confidence": round(float(np.exp(logprob)), 3), "no_speech": round(no_speech, 3),
            "duration_s": round(len(audio) / SR, 2), "language": info.language,
            "ms": int((time.monotonic() - started) * 1000)}


@app.post("/transcribe_file")
async def transcribe_file(request: Request, prompt: str = "", model: str = "", language: str = "id"):
    data = await request.body()
    if len(data) > 500_000_000:
        raise HTTPException(413, "file terlalu besar")
    started = time.monotonic()

    def run():
        _low_priority()
        audio = _decode_file(data)
        m = _whisper(model or FILE_MODEL)
        with _file_lock:
            segs, info = m.transcribe(audio, language=language or None, beam_size=1, vad_filter=True,
                                      initial_prompt=prompt[:600] or None, condition_on_previous_text=False)
            out = [{"start": round(s.start, 2), "end": round(s.end, 2), "text": s.text.strip(),
                    "confidence": round(float(np.exp(s.avg_logprob)), 3)} for s in segs if s.text.strip()]
        return out, len(audio) / SR

    segments, duration = await asyncio.to_thread(run)
    return {"segments": segments, "duration_s": round(duration, 1), "ms": int((time.monotonic() - started) * 1000)}


def _extractor():
    if "embed" not in _speaker:
        import sherpa_onnx
        cfg = sherpa_onnx.SpeakerEmbeddingExtractorConfig(model="/srv/speaker/embed.onnx", num_threads=2)
        _speaker["embed"] = sherpa_onnx.SpeakerEmbeddingExtractor(cfg)
    return _speaker["embed"]


def _embed(audio: np.ndarray) -> list[float]:
    ex = _extractor()
    stream = ex.create_stream()
    stream.accept_waveform(SR, audio)
    stream.input_finished()
    v = np.array(ex.compute(stream), dtype=np.float32)
    return (v / (np.linalg.norm(v) or 1.0)).round(5).tolist()


@app.post("/speaker/embed")
async def speaker_embed(request: Request):
    audio = _pcm(await request.body())
    if len(audio) < SR:  # < 1 s is too little to recognise a voice
        raise HTTPException(400, "minimal 1 detik suara")
    return {"embedding": await asyncio.to_thread(_embed, audio), "duration_s": round(len(audio) / SR, 2)}


@app.post("/diarize")
async def diarize(request: Request, speakers: int = 0, threshold: float = 0.5):
    data = await request.body()

    def run():
        _low_priority()
        return _diarize(_decode_file(data), speakers, threshold)

    segs, voices = await asyncio.to_thread(run)
    return {"segments": segs, "speakers": len({s["speaker"] for s in segs}), "voices": voices}


def _diarize(audio: np.ndarray, speakers: int, threshold: float):
    """Who spoke when (pyannote segmentation + CAM++ clustering) and one voice embedding per speaker."""
    import sherpa_onnx
    cfg = sherpa_onnx.OfflineSpeakerDiarizationConfig(
        segmentation=sherpa_onnx.OfflineSpeakerSegmentationModelConfig(
            pyannote=sherpa_onnx.OfflineSpeakerSegmentationPyannoteModelConfig(model="/srv/speaker/segment.onnx"),
            num_threads=2),
        embedding=sherpa_onnx.SpeakerEmbeddingExtractorConfig(model="/srv/speaker/embed.onnx", num_threads=2),
        clustering=sherpa_onnx.FastClusteringConfig(num_clusters=speakers if speakers > 0 else -1, threshold=threshold),
        min_duration_on=0.3, min_duration_off=0.5)
    sd = sherpa_onnx.OfflineSpeakerDiarization(cfg)
    result = sd.process(audio).sort_by_start_time()
    segs = [{"start": round(r.start, 2), "end": round(r.end, 2), "speaker": int(r.speaker)} for r in result]
    # one embedding per speaker (longest turns), so the owner's voiceprint can name them
    per: dict[int, list[np.ndarray]] = {}
    for s in sorted(segs, key=lambda s: s["start"] - s["end"])[:200]:
        chunk = audio[int(s["start"] * SR):int(s["end"] * SR)]
        if len(chunk) >= SR and len(per.setdefault(s["speaker"], [])) < 3:
            per[s["speaker"]].append(np.array(_embed(chunk)))
    voices = {str(k): (np.mean(v, axis=0) / (np.linalg.norm(np.mean(v, axis=0)) or 1)).round(5).tolist()
              for k, v in per.items() if v}
    return segs, voices


class MeetingIn(BaseModel):
    paths: list[str]
    prompt: str = ""
    model: str = ""
    speakers: int = 0


def _transcribe_audio(audio: np.ndarray, model: str, prompt: str) -> list[dict]:
    m = _whisper(model or FILE_MODEL)
    with _file_lock:
        segs, _ = m.transcribe(audio, language="id", beam_size=1, vad_filter=True,
                               initial_prompt=prompt[:600] or None, condition_on_previous_text=False)
        return [{"start": round(s.start, 2), "end": round(s.end, 2), "text": s.text.strip(),
                 "confidence": round(float(np.exp(s.avg_logprob)), 3)} for s in segs if s.text.strip()]


@app.post("/meeting/transcribe")
async def meeting_transcribe(m: MeetingIn):
    started = time.monotonic()

    def run():
        _low_priority()
        audio = _decode_paths(m.paths)
        return _transcribe_audio(audio, m.model, m.prompt), len(audio) / SR

    segments, duration = await asyncio.to_thread(run)
    return {"segments": segments, "duration_s": round(duration, 1), "ms": int((time.monotonic() - started) * 1000)}


@app.post("/meeting/diarize")
async def meeting_diarize(m: MeetingIn):
    def run():
        _low_priority()
        return _diarize(_decode_paths(m.paths), m.speakers, 0.5)
    segs, voices = await asyncio.to_thread(run)
    return {"segments": segs, "speakers": len({s["speaker"] for s in segs}), "voices": voices}


@app.post("/meeting/concat")
async def meeting_concat(m: MeetingIn):
    """One Opus/Ogg file for cloud transcription (Groq/Deepgram take a single upload)."""
    def run():
        _low_priority()
        audio = _decode_paths(m.paths)
        pcm = (audio * 32767).astype(np.int16).tobytes()
        out = subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-f", "s16le", "-ar", str(SR), "-ac", "1", "-i", "-",
                              "-c:a", "libopus", "-b:a", "24k", "-f", "ogg", "-"], input=pcm, capture_output=True, timeout=1800)
        if out.returncode != 0:
            raise HTTPException(500, "gagal menyatukan audio")
        return out.stdout
    return Response(await asyncio.to_thread(run), media_type="audio/ogg")
