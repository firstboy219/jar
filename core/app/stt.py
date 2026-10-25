"""Speech-to-text on the server, with the engine the owner chose in the composition.

Since v0.7 the phone cuts speech out of the microphone itself (VAD) and sends each utterance here, so
only real speech is ever transcribed — silence costs nothing, whatever the engine:
  whisper   jarvis-ears, on this server (default; private; ~3.5 s per utterance, WER ~19% measured)
  groq      Groq whisper-large-v3-turbo (cloud; ~0.5 s, WER ~10% measured locally on the same model;
            free up to ~8 h of audio/day, then $0.04/h)
  deepgram  Deepgram nova-2 prerecorded (cloud; WER 12–15% measured; ~$0.26/h)
  openrouter  the STT model the owner picked from OpenRouter (ElevenLabs Scribe, GPT transcribe, Whisper…; voice.py)
What JARVIS then does with the text (dictionary, echo/hallucination filters, second opinion) is voice.py's job.
If the chosen cloud engine fails (no key, quota, network), the local engine answers instead.
"""

import asyncio
import io
import logging
import re
import time
import wave

import httpx

from .config import settings

log = logging.getLogger("jarvis-core.stt")
SR = 16000
# Whisper's classic hallucinations on silence/noise (subtitle credits, thanks), dropped when alone.
HALLUCINATIONS = re.compile(r"^\s*(terima kasih( sudah menonton| telah menonton)?|thank you( for watching)?|"
                            r"subtitle(s)? (by|oleh).*|sampai jumpa( lagi)?|\.+|♪+)\s*[.!]*\s*$", re.IGNORECASE)


class SttError(RuntimeError):
    pass


def wav(pcm: bytes) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm)
    return buf.getvalue()


async def vocabulary() -> str:
    from .deepgram import stt_config
    return ", ".join((await stt_config())["keywords"])


async def _whisper(pcm: bytes, prompt: str) -> dict:
    async with httpx.AsyncClient(timeout=120) as c:
        r = await c.post(f"{settings.whisper_url}/transcribe", params={"prompt": prompt, "language": "id"}, content=pcm)
    if r.status_code != 200:
        raise SttError(f"whisper lokal HTTP {r.status_code}: {r.text[:200]}")
    d = r.json()
    return {"text": d["text"], "confidence": d["confidence"], "no_speech": d.get("no_speech")}


async def _groq(pcm: bytes, prompt: str) -> dict:
    if not settings.groq_api_key:
        raise SttError("GROQ_API_KEY belum diisi")
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.post("https://api.groq.com/openai/v1/audio/transcriptions",
                         headers={"Authorization": f"Bearer {settings.groq_api_key}"},
                         files={"file": ("ucapan.wav", wav(pcm), "audio/wav")},
                         data={"model": "whisper-large-v3-turbo", "language": "id", "prompt": prompt[:800],
                               "response_format": "verbose_json", "temperature": "0"})
    if r.status_code != 200:
        raise SttError(f"Groq HTTP {r.status_code}: {r.text[:200]}")
    d = r.json()
    segs = d.get("segments") or []
    import math
    conf = math.exp(sum(s.get("avg_logprob", -1) for s in segs) / len(segs)) if segs else 0.5
    return {"text": (d.get("text") or "").strip(), "confidence": round(conf, 3),
            "no_speech": max((s.get("no_speech_prob", 0) for s in segs), default=0)}


async def _deepgram(pcm: bytes, prompt: str) -> dict:
    if not settings.deepgram_api_key:
        raise SttError("DEEPGRAM_API_KEY belum diisi")
    from .deepgram import stt_config
    cfg = await stt_config()
    params = [("model", cfg["model"]), ("language", cfg["language"]), ("smart_format", "true"),
              ("diarize", "true")] + [("keywords", k) for k in cfg["keywords"][:30]]
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.post("https://api.deepgram.com/v1/listen", params=params, content=wav(pcm),
                         headers={"Authorization": f"Token {settings.deepgram_api_key}", "Content-Type": "audio/wav"})
    if r.status_code != 200:
        raise SttError(f"Deepgram HTTP {r.status_code}: {r.text[:200]}")
    alt = r.json()["results"]["channels"][0]["alternatives"][0]
    speakers = {w.get("speaker") for w in alt.get("words", []) if w.get("speaker") is not None}
    return {"text": alt.get("transcript", ""), "confidence": alt.get("confidence"), "speakers": len(speakers) or 1}


async def _openrouter(pcm: bytes, prompt: str) -> dict:
    from . import voice
    return await voice.transcribe_openrouter(pcm, prompt)


ENGINES = {"whisper": _whisper, "groq": _groq, "deepgram": _deepgram, "openrouter": _openrouter}


async def transcribe(pcm: bytes, engine: str | None = None) -> dict:
    """One utterance (PCM16 mono 16 kHz) → {"text", "confidence", "engine", "stt_ms", ...}; text "" = nothing said."""
    from . import composition
    engine = engine or await composition.stt_engine()
    prompt = await vocabulary()
    started = time.monotonic()
    tried = []
    for name in dict.fromkeys([engine, "whisper"]):
        try:
            out = await ENGINES[name](pcm, prompt)
            break
        except (SttError, httpx.HTTPError, KeyError, ValueError) as e:
            tried.append(f"{name}: {e}")
            log.warning("stt %s failed: %s", name, e)
    else:
        raise SttError("; ".join(tried))
    text = (out.get("text") or "").strip()
    if HALLUCINATIONS.match(text) or (out.get("no_speech") or 0) > 0.8:
        text = ""
    return {**out, "text": text, "engine": name, "stt_ms": int((time.monotonic() - started) * 1000),
            "fallback": bool(tried)}


async def transcribe_with_voice(pcm: bytes) -> dict:
    """Transcribe and, when the owner enrolled a voiceprint, check whose voice it is — in parallel."""
    from . import voice_id
    results = await asyncio.gather(transcribe(pcm), voice_id.check(pcm), return_exceptions=True)
    if isinstance(results[0], Exception):
        raise results[0]
    out = results[0]
    if isinstance(results[1], dict):
        out.update(results[1])
    return out
