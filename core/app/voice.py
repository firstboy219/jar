"""JARVIS's voice and ears around the engines (Blueprint v4 Fase 3, ADR-048). The engines stay; this layer closes their gaps.

Voice (TTS):
  android     the phone's own engine (default; free, offline, private)
  openrouter  a voice model the owner picks from OpenRouter's catalog — ElevenLabs, Gemini, Fish, Kokoro… — with its
              character ("george", "sarah", …). The phone fetches each sentence from /api/v1/voice/speak and falls back to
              its own engine whenever the server says no: private or sensitive text (never leaves for a cloud voice),
              budget used up, no key, or the call fails.
  Either way the SPOKEN copy is normalised here first (speech.py: rupiah, dates, numbers, abbreviations, pronunciations).

Ears (STT complements, each judged by voice_quality before it may change anything):
  kamus · halusinasi · gema · opini_kedua · ambang — see voice_quality.COMPLEMENTS.
Every utterance is logged in voice_events (text only; a secret is never stored); audio only with the owner's consent (K3).
The owner's corrections ("bukan UAT, maksudku Ashar") label utterances; the gate runs nightly and on demand.
"""

import asyncio
import collections
import hashlib
import logging
import math
import os
import random
import time
from pathlib import Path

import httpx

from . import audit, db, openrouter, sensitive, speech, voice_quality as vq
from .config import settings

log = logging.getLogger("jarvis-core.voice")
VOICE_DIR = Path(os.environ.get("JARVIS_VOICE_DIR", "/data/voice"))
OR_BASE = "https://openrouter.ai/api/v1"
TTS_DEFAULT = {"engine": "android", "model": "elevenlabs/eleven-multilingual-v2", "voice": "george", "speed": 1.0}
STT_MODEL_DEFAULT = "openai/whisper-large-v3-turbo"
SECOND_ENGINES = ("none", "auto", "whisper", "groq", "openrouter")
SAMPLE_TEXT = "Halo, aku JARVIS. Begini suaraku kalau membacakan laporan untukmu."
MAX_TTS_CHARS = 1200
TTS_CACHE_FILES = 300
AUDIO_CAP_BYTES = 500 * 1024 * 1024
KEEP_DAYS = 60
GEN_DELAY_S = 4          # OpenRouter's generation record (exact cost) appears a moment after the audio
_cache: dict = {"at": 0.0}
_spoken: collections.deque = collections.deque(maxlen=12)   # (monotonic time, text) JARVIS just said — for the echo filter


def _client(timeout: float) -> httpx.AsyncClient:  # one seam for tests
    return httpx.AsyncClient(timeout=timeout)


class VoiceError(RuntimeError):
    def __init__(self, message: str, status: int = 422):
        super().__init__(message)
        self.status = status


# ---------- settings ----------

async def _kv(key: str, default=None):
    v = await db.pool().fetchval("SELECT value FROM settings_kv WHERE key = $1", key)
    return default if v is None else v


async def _set_kv(key: str, value) -> None:
    await db.pool().execute("""INSERT INTO settings_kv (key, value) VALUES ($1, $2)
                               ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value""", key, value)


async def tts_settings() -> dict:
    saved = await _kv("voice:tts", {})
    return TTS_DEFAULT | (saved if isinstance(saved, dict) else {})


async def stt_model() -> str:
    return str(await _kv("voice:stt_model", STT_MODEL_DEFAULT))


async def keep_samples() -> bool:
    """K3: the owner allowed keeping utterance audio on this server as a test set (admin page only)."""
    return bool(await _kv("voice:keep_samples", False))


async def second_engine() -> str:
    return str(await _kv("voice:second_engine", "auto"))


async def set_settings(changes: dict, actor: str) -> dict:
    """Owner's phone (or the owner by chat): {"tts": {engine, model, voice, speed}, "stt_model": id}."""
    tts = await tts_settings()
    if isinstance(changes.get("tts"), dict):
        want = tts | {k: v for k, v in changes["tts"].items() if k in TTS_DEFAULT and v is not None}
        if want["engine"] not in ("android", "openrouter"):
            raise VoiceError("mesin suara harus 'android' atau 'openrouter'")
        try:
            want["speed"] = round(min(max(float(want["speed"]), 0.7), 1.3), 2)
        except (TypeError, ValueError):
            raise VoiceError("kecepatan suara harus angka 0,7–1,3")
        if want["engine"] == "openrouter":
            models = await openrouter.speech_catalog("speech")
            m = next((x for x in models if x["id"] == want["model"]), None)
            if models and not m:
                raise VoiceError(f"model suara tidak ada di OpenRouter: {want['model']}")
            if m and m["voices"] and want["voice"] not in m["voices"]:
                if "voice" in changes["tts"]:
                    raise VoiceError(f"karakter '{want['voice']}' tidak tersedia di {m['name']}; pilihan: {', '.join(m['voices'][:12])}")
                want["voice"] = m["voices"][0]      # a model switch keeps a valid voice
        await _set_kv("voice:tts", want)
        tts = want
    if changes.get("stt_model"):
        models = await openrouter.speech_catalog("transcription")
        if models and not any(x["id"] == changes["stt_model"] for x in models):
            raise VoiceError(f"model STT tidak ada di OpenRouter: {changes['stt_model']}")
        await _set_kv("voice:stt_model", str(changes["stt_model"]))
    await audit.record(actor, "voice.settings", None, changes=sorted(k for k in changes if k in ("tts", "stt_model")))
    return await options()


async def options() -> dict:
    """What the phone's Suara screen shows: current choices + the OpenRouter voices/ears to pick from."""
    from . import composition
    tts, tts_models, stt_models = await tts_settings(), await openrouter.speech_catalog("speech"), await openrouter.speech_catalog("transcription")
    order = lambda m: (m["provider"] != "elevenlabs", not m["free"], m["price_in"], m["id"])
    return {"tts": {**tts, "has_key": bool(settings.openrouter_api_key),
                    "models": sorted(tts_models, key=order)},
            "stt": {"engine": await composition.stt_engine(), "options": composition.STT_ENGINES, "model": await stt_model(),
                    "models": sorted(stt_models, key=lambda m: (not m["free"], m["price_in"], m["id"]))},
            "note": ("Suara cloud dipakai hanya untuk teks biasa. Mode /privat, data sensitif, lampiran, atau anggaran habis → "
                     "otomatis suara bawaan HP.")}


# ---------- learned data (versioned rows) ----------

async def _load() -> dict:
    if time.monotonic() - _cache["at"] < 30 and "data" in _cache:
        return _cache
    rows = await db.pool().fetch("SELECT id, kind, key, value, event_id FROM voice_data WHERE active ORDER BY id")
    from . import companies
    names = []
    for c in await companies.all_():
        names += [c["name"], *c.get("aliases", [])]
    from .deepgram import stt_config
    try:
        keywords = (await stt_config())["keywords"]
    except Exception:
        keywords = []
    modes = await _kv("voice:complements", {})
    _cache.update(at=time.monotonic(), data=[dict(r) for r in rows], names=names, keywords=keywords,
                  modes=modes if isinstance(modes, dict) else {})
    return _cache


def forget() -> None:
    _cache["at"] = 0.0


async def data_list(kind: str | None = None, include_removed: bool = False) -> list[dict]:
    rows = await db.pool().fetch(
        f"""SELECT * FROM voice_data WHERE ($1::text IS NULL OR kind = $1) {'' if include_removed else 'AND active'}
            ORDER BY created_at DESC LIMIT 300""", kind)
    return [dict(r) for r in rows]


async def data_add(kind: str, key: str, value: str, source: str, actor: str, event_id: int | None = None) -> dict:
    key, value = " ".join(str(key).split())[:80], " ".join(str(value).split())[:120]
    if kind not in ("lexicon", "pronounce", "hallucination") or not key:
        raise VoiceError("data suara tidak valid")
    if kind != "hallucination" and (not value or value.lower() == key.lower()):
        raise VoiceError("isi pengganti kosong atau sama")
    if sensitive.scan(key + " " + value):
        raise VoiceError("tidak menyimpan data sensitif ke kamus suara")
    async with db.pool().acquire() as con, con.transaction():
        await con.execute("""UPDATE voice_data SET active = false, removed_at = now(), removed_by = $3
                             WHERE kind = $1 AND lower(key) = lower($2) AND active""", kind, key, actor)
        row = await con.fetchrow("""INSERT INTO voice_data (kind, key, value, source, event_id) VALUES ($1, $2, $3, $4, $5)
                                    RETURNING *""", kind, key, value, source, event_id)
    await audit.record(actor, "voice.data_added", f"voice_data:{row['id']}", kind=kind)
    forget()
    return dict(row)


async def data_remove(row_id: int, actor: str) -> bool:
    done = await db.pool().fetchval("""UPDATE voice_data SET active = false, removed_at = now(), removed_by = $2
                                       WHERE id = $1 AND active RETURNING id""", row_id, actor)
    if done:
        await audit.record(actor, "voice.data_removed", f"voice_data:{row_id}")
        forget()
    return bool(done)


def _map(c: dict, kind: str, skip_event: int | None = None) -> dict[str, str]:
    return {d["key"]: d["value"] for d in c["data"] if d["kind"] == kind and (skip_event is None or d["event_id"] != skip_event)}


def glossary(c: dict) -> list[str]:
    """Names and terms worth hearing right: companies, the owner's corrections, the configured keywords."""
    return list(dict.fromkeys([*c["names"], *_map(c, "lexicon").values(), *c["keywords"]]))


def correct_text(raw: str, c: dict, skip_event: int | None = None) -> str:
    """'kamus': the owner's exact corrections first, then near-miss names/terms (meetings.correct_terms)."""
    from .meetings import correct_terms
    lex = _map(c, "lexicon", skip_event)
    fixed = vq.apply_lexicon(raw, lex)
    gloss = [g for g in [*c["names"], *lex.values(), *c["keywords"]] if g]
    return correct_terms(fixed, list(dict.fromkeys(gloss)))


async def modes() -> dict:
    c = await _load()
    saved = c["modes"]
    return {name: {"mode": (saved.get(name) or {}).get("mode", vq.DEFAULT_MODES[name]),
                   "auto": (saved.get(name) or {}).get("auto", True), "eval": (saved.get(name) or {}).get("eval"),
                   "threshold": (saved.get(name) or {}).get("threshold"), "title": vq.COMPLEMENTS[name]}
            for name in vq.COMPLEMENTS}


async def set_mode(name: str, mode: str, actor: str) -> dict:
    """Admin page: a manual mode stops the automatic gate for that complement until 'auto' is chosen again."""
    if name not in vq.COMPLEMENTS or mode not in ("off", "shadow", "on", "auto"):
        raise VoiceError("pelengkap atau mode tidak dikenal")
    saved = dict((await _load())["modes"])
    cur = dict(saved.get(name) or {})
    if mode == "auto":
        cur.update(auto=True, mode=cur.get("mode") if cur.get("mode") in ("shadow", "on") else "shadow")
    else:
        cur.update(auto=False, mode=mode)
    saved[name] = cur
    await _set_kv("voice:complements", saved)
    await audit.record(actor, "voice.complement_mode", name, mode=mode)
    forget()
    return (await modes())[name]


def threshold_now(engine: str | None) -> float:
    """'Possibly misheard' below this confidence. The calibrated value only once 'ambang' passed its gate. Sync (cache)."""
    m = (_cache.get("modes") or {}).get("ambang") or {}
    if m.get("mode") == "on" and isinstance(m.get("threshold"), dict):
        t = m["threshold"].get(engine or "")
        if isinstance(t, (int, float)):
            return float(t)
    return vq.DEFAULT_THRESHOLD


# ---------- what JARVIS says ----------

def remember_spoken(text: str) -> None:
    if text:
        _spoken.append((time.monotonic(), text))


def recent_spoken(seconds: float = 25) -> list[str]:
    now = time.monotonic()
    return [t for at, t in _spoken if now - at <= seconds]


async def spoken_copy(text: str) -> str:
    c = await _load()
    return speech.normalize(text, _map(c, "pronounce"))


async def prepare(ev: dict, local_voice: bool = False) -> dict:
    """Every event to the phone passes here: what will be SPOKEN gets its normalised copy ("say" is speech only, so its
    text is replaced; replies/reports keep their text for the screen and gain "speech"). local_voice: from a private or
    sensitive turn — the phone must use its own voice."""
    kind = ev.get("type")
    if kind not in ("say", "reply", "report", "announce", "proactive") or not ev.get("text"):
        return ev
    try:
        spoken = await spoken_copy(str(ev["text"]))
    except Exception:  # never let speech polish break delivery
        log.exception("speech normalisation failed")
        return ev
    if not (kind == "reply" and ev.get("spoken")):
        remember_spoken(spoken)
    private = local_voice or bool(sensitive.scan(str(ev["text"])))
    out = {**ev, "text": spoken} if kind == "say" else {**ev, "speech": spoken}
    return out | ({"local_voice": True} if private else {})


def _tts_path(model: str, voice: str, speed: float, text: str) -> Path:
    h = hashlib.sha256(f"{model}|{voice}|{speed}|{text}".encode()).hexdigest()[:32]
    return VOICE_DIR / "tts-cache" / f"{h}.mp3"


async def synthesize(text: str, model: str | None = None, voice: str | None = None, *, preview: bool = False) -> bytes:
    """MP3 of `text` in the owner's cloud voice. VoiceError(status) tells the phone to use its own voice instead:
    409 private/sensitive, 402 budget, 503 no key/unreachable, 422 not configured."""
    text = " ".join(str(text or "").split())[:MAX_TTS_CHARS]
    if not text:
        raise VoiceError("teks kosong")
    if sensitive.is_private(text) or sensitive.scan(text):
        raise VoiceError("teks pribadi/sensitif dibacakan suara HP", 409)
    cfg = await tts_settings()
    if cfg["engine"] != "openrouter" and not preview:
        raise VoiceError("suara cloud tidak dipilih", 422)
    model, voice = model or cfg["model"], voice or cfg["voice"]
    if not settings.openrouter_api_key:
        raise VoiceError("API key OpenRouter belum diisi", 503)
    from . import budget
    if (await budget.state())["level"] >= 100:
        raise VoiceError("anggaran AI bulan ini habis — pakai suara HP", 402)
    path = _tts_path(model, voice, cfg["speed"], text)
    if path.exists():
        return path.read_bytes()
    body = {"model": model, "input": text, "voice": voice, "response_format": "mp3"}
    if cfg["speed"] != 1.0:
        body["speed"] = cfg["speed"]
    started = time.monotonic()
    try:
        async with _client(timeout=30) as c:
            r = await c.post(f"{OR_BASE}/audio/speech", json=body, headers={"Authorization": f"Bearer {settings.openrouter_api_key}"})
    except httpx.HTTPError as e:
        await _usage("tts", model, 0.0, int((time.monotonic() - started) * 1000), False, type(e).__name__)
        raise VoiceError(f"OpenRouter tidak terjangkau ({type(e).__name__})", 503)
    ms = int((time.monotonic() - started) * 1000)
    if r.status_code != 200 or not r.headers.get("content-type", "").startswith("audio"):
        err = f"HTTP {r.status_code}: {r.text[:160]}"
        await _usage("tts", model, 0.0, ms, False, err)
        raise VoiceError(f"suara cloud gagal ({err})", 402 if r.status_code == 402 else 503)
    audio = r.content
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(audio)
        _trim_cache(path.parent)
    except OSError as e:
        log.warning("tts cache not written: %s", e)
    estimate = await _tts_estimate(model, text)
    asyncio.create_task(_record_tts(r.headers.get("x-generation-id"), model, estimate, ms))
    return audio


def _trim_cache(folder: Path) -> None:
    files = sorted(folder.glob("*.mp3"), key=lambda p: p.stat().st_mtime)
    for p in files[:-TTS_CACHE_FILES]:
        p.unlink(missing_ok=True)


async def _tts_estimate(model: str, text: str) -> float:
    m = next((x for x in await openrouter.speech_catalog("speech") if x["id"] == model), None)
    if not m:
        return 0.0
    return round(m["price_in"] * len(text) + m["price_out"] * len(text) * 2, 6)


async def _record_tts(gen_id: str | None, model: str, estimate: float, ms: int) -> None:
    """The exact cost comes from OpenRouter's generation record a moment later; the estimate stands in if it does not."""
    cost = estimate
    if gen_id:
        await asyncio.sleep(GEN_DELAY_S)
        try:
            async with _client(timeout=15) as c:
                r = await c.get(f"{OR_BASE}/generation", params={"id": gen_id},
                                headers={"Authorization": f"Bearer {settings.openrouter_api_key}"})
            if r.status_code == 200 and isinstance((r.json().get("data") or {}).get("total_cost"), (int, float)):
                cost = float(r.json()["data"]["total_cost"])
        except (httpx.HTTPError, ValueError):
            pass
    await _usage("tts", model, cost, ms, True, None)


async def _usage(caller: str, model: str, cost: float, ms: int, ok: bool, err: str | None) -> None:
    try:  # category 'suara' counts toward the monthly budget like any model call
        await db.pool().execute("""INSERT INTO llm_usage (category, caller, provider, model, cost_usd, latency_ms, ok, error)
                                   VALUES ('suara', $1, 'openrouter', $2, $3, $4, $5, $6)""", caller, model, cost, ms, ok, err)
    except Exception:
        log.exception("voice usage not recorded")


# ---------- ears ----------

async def transcribe_openrouter(pcm: bytes, prompt: str) -> dict:
    """stt.ENGINES['openrouter']: the STT model the owner picked on OpenRouter."""
    from .stt import SttError, wav
    if not settings.openrouter_api_key:
        raise SttError("API key OpenRouter belum diisi")
    model = await stt_model()
    started = time.monotonic()
    async with _client(timeout=30) as c:
        r = await c.post(f"{OR_BASE}/audio/transcriptions", headers={"Authorization": f"Bearer {settings.openrouter_api_key}"},
                         files={"file": ("ucapan.wav", wav(pcm), "audio/wav")},
                         data={"model": model, "language": "id", "prompt": prompt[:800], "response_format": "verbose_json"})
    ms = int((time.monotonic() - started) * 1000)
    if r.status_code != 200:
        await _usage("stt", model, 0.0, ms, False, f"HTTP {r.status_code}")
        raise SttError(f"OpenRouter STT HTTP {r.status_code}: {r.text[:200]}")
    d = r.json()
    await _usage("stt", model, float((d.get("usage") or {}).get("cost") or 0), ms, True, None)
    segs = d.get("segments") or []
    conf = math.exp(sum(s.get("avg_logprob", -1) for s in segs) / len(segs)) if segs else None
    return {"text": (d.get("text") or "").strip(), "confidence": round(conf, 3) if conf is not None else None,
            "no_speech": max((s.get("no_speech_prob", 0) for s in segs), default=0), "model": model}


def _second_choice(primary: str, chosen: str) -> str | None:
    if chosen == "none":
        return None
    if chosen == "auto":   # never sends audio to a cloud the owner did not choose: a cloud primary is checked locally
        return "whisper" if primary != "whisper" else None
    return chosen if chosen != primary else None


async def _second(engine: str, pcm: bytes) -> dict | None:
    from . import stt
    try:
        return await asyncio.wait_for(stt.ENGINES[engine](pcm, await stt.vocabulary()), timeout=8)
    except Exception as e:
        log.info("second opinion %s failed: %s", engine, e)
        return None


async def process(heard: dict, pcm: bytes, session_id: str) -> dict:
    """After the engine: run the complements (live where ON, logged where SHADOW), log the utterance, keep audio with
    consent. Returns heard with the final text ("" when dropped) and voice_event."""
    raw = (heard.get("text") or "").strip()
    if not raw:
        return heard
    c, m = await _load(), await modes()
    engine, conf = heard.get("engine") or "", heard.get("confidence")
    text, applied, shadow, dropped, second = raw, [], [], None, None
    secret = bool(sensitive.is_private(raw) or sensitive.scan(raw))

    def step(name: str, after: str) -> None:
        nonlocal text, dropped
        if after == text:
            return
        mode = m[name]["mode"]
        if mode == "on":
            applied.append({"complement": name, "before": text[:300], "after": after[:300]})
            if not after and not dropped:
                dropped = name
            text = after
        elif mode == "shadow":
            shadow.append({"complement": name, "after": after[:300]})

    step("gema", "" if vq.is_echo(raw, recent_spoken()) else raw)
    if text:
        step("halusinasi", "" if vq.is_hallucination(raw, list(_map(c, "hallucination"))) else raw)
    if text:
        step("kamus", correct_text(text, c))
    low = isinstance(conf, (int, float)) and conf < threshold_now(engine)
    other = _second_choice(engine, await second_engine())
    if text and low and other and m["opini_kedua"]["mode"] == "on":
        if (alt := await _second(other, pcm)) is not None:
            pick = vq.choose(heard, alt, glossary(c))
            second = {"engine": other, "text": (alt.get("text") or "")[:300], "confidence": alt.get("confidence"), "chosen": pick}
            if pick == "second" and (alt.get("text") or "").strip():
                applied.append({"complement": "opini_kedua", "before": text[:300], "after": alt["text"][:300]})
                text = alt["text"].strip()
    row_id = await db.pool().fetchval(
        """INSERT INTO voice_events (session_id, engine, model, confidence, stt_ms, raw_text, final_text, applied, shadow,
                                     second_opinion, dropped)
           VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11) RETURNING id""",
        session_id[:128], engine, heard.get("model"), conf if isinstance(conf, (int, float)) else None, heard.get("stt_ms"),
        "[disensor]" if secret else raw, "[disensor]" if secret else text, [] if secret else applied,
        [] if secret else shadow, second, dropped)
    if text and low and other and m["opini_kedua"]["mode"] == "shadow" and not secret:
        asyncio.create_task(_shadow_second(row_id, other, pcm, heard))
    if not secret and await keep_samples() and (low or random.random() < 0.2):
        await _keep_audio(row_id, pcm)
    return {**heard, "text": text, "raw_text": raw, "voice_event": row_id} | ({"dropped": dropped} if dropped else {})


async def _shadow_second(row_id: int, engine: str, pcm: bytes, primary: dict) -> None:
    alt = await _second(engine, pcm)
    if alt is None:
        return
    pick = vq.choose(primary, alt, glossary(await _load()))
    await db.pool().execute("UPDATE voice_events SET second_opinion = $2 WHERE id = $1", row_id,
                            {"engine": engine, "text": (alt.get("text") or "")[:300], "confidence": alt.get("confidence"),
                             "chosen": pick, "shadow": True})


async def _keep_audio(row_id: int, pcm: bytes) -> None:
    try:
        VOICE_DIR.mkdir(parents=True, exist_ok=True)
        if sum(p.stat().st_size for p in VOICE_DIR.glob("*.pcm")) + len(pcm) > AUDIO_CAP_BYTES:
            return
        (VOICE_DIR / f"{row_id}.pcm").write_bytes(pcm)
        await db.pool().execute("UPDATE voice_events SET audio_kept = true WHERE id = $1", row_id)
    except OSError as e:
        log.warning("voice sample not kept: %s", e)


# ---------- the owner's corrections ----------

async def correct(*, session_id: str | None = None, event_id: int | None = None, heard: str = "", meant: str = "",
                  full: str | None = None, not_me: bool = False, source: str, actor: str) -> dict:
    """Label one utterance with what the owner really said. heard/meant = the misheard part and the right words (also
    taught to the dictionary); full = the whole utterance; not_me = it was not the owner speaking (or nobody)."""
    if event_id:
        row = await db.pool().fetchrow("SELECT * FROM voice_events WHERE id = $1", event_id)
    else:
        row = await db.pool().fetchrow(
            """SELECT * FROM voice_events WHERE session_id = $1 AND at > now() - interval '15 minutes'
                 AND raw_text <> '[disensor]' AND ($2 = '' OR raw_text ILIKE '%' || $2 || '%')
               ORDER BY id DESC LIMIT 1""", session_id or "", heard.strip())
    if not row or row["raw_text"] == "[disensor]":
        raise VoiceError("ucapan yang dimaksud tidak ketemu (hanya 15 menit terakhir, sesi ini)")
    raw = row["raw_text"]
    if not_me:
        reference = ""
    elif full is not None:
        reference = " ".join(full.split())
    else:
        reference = vq.apply_reference_fix(raw, heard, meant)
        if reference is None:
            raise VoiceError(f"'{heard}' tidak ada di yang kudengar: \"{raw[:120]}\"")
    if sensitive.scan(reference):
        raise VoiceError("koreksi berisi data sensitif — tidak disimpan")
    c = await _load()
    echo = any(s.get("complement") == "gema" for s in (row["shadow"] or [])) or any(
        a.get("complement") == "gema" for a in (row["applied"] or []))
    kind = vq.classify_error(raw, reference, echo, glossary(c))
    await db.pool().execute("UPDATE voice_events SET reference = $2, reference_source = $3, error_kind = $4 WHERE id = $1",
                            row["id"], reference, source, kind)
    learned = None
    if heard and meant and not not_me and heard.strip().lower() != meant.strip().lower():
        learned = await data_add("lexicon", heard, meant, source, actor, event_id=row["id"])
    if not_me and len(vq.words(raw)) <= 6:  # the same short phrase disowned twice → a learned hallucination candidate
        times = await db.pool().fetchval("SELECT count(*) FROM voice_events WHERE reference = '' AND lower(raw_text) = lower($1)", raw)
        if times >= 2 and not any(d["kind"] == "hallucination" and d["key"].lower() == raw.lower() for d in c["data"]):
            learned = await data_add("hallucination", raw, "", "learned", actor, event_id=row["id"])
    await audit.record(actor, "voice.corrected", f"voice_event:{row['id']}", kind=kind)
    return {"event": row["id"], "heard": raw, "reference": reference, "error_kind": kind,
            "learned": {"kind": learned["kind"], "key": learned["key"], "value": learned["value"]} if learned else None}


async def set_pronunciation(word: str, say_as: str, actor: str) -> dict:
    return await data_add("pronounce", word, say_as, "owner_chat" if actor.startswith("device:") else "admin", actor)


# ---------- the gate ----------

async def _labeled(days: int = 120) -> list[dict]:
    rows = await db.pool().fetch(
        """SELECT id, engine, confidence, raw_text, reference, applied, shadow, second_opinion FROM voice_events
           WHERE reference IS NOT NULL AND raw_text <> '[disensor]' AND at > now() - make_interval(days => $1)
           ORDER BY id DESC LIMIT 2000""", days)
    return [dict(r) for r in rows]


def _flag(row: dict, name: str) -> bool:
    return any(x.get("complement") == name for x in [*(row["shadow"] or []), *(row["applied"] or [])])


async def evaluate(actor: str = "auto") -> dict:
    """Judge every complement on the owner's corrected utterances and move it between shadow and on (ADR-048 §3.4)."""
    c, cur = await _load(), await modes()
    rows = await _labeled()
    samples = {
        "kamus": [{"raw": r["raw_text"], "after": correct_text(r["raw_text"], c, skip_event=r["id"]), "reference": r["reference"]}
                  for r in rows],
        "halusinasi": [{"raw": r["raw_text"], "reference": r["reference"],
                        "after": "" if vq.is_hallucination(r["raw_text"], list(_map(c, "hallucination", r["id"]))) else r["raw_text"]}
                       for r in rows],
        "gema": [{"raw": r["raw_text"], "after": "" if _flag(r, "gema") else r["raw_text"], "reference": r["reference"]} for r in rows],
        "opini_kedua": [{"raw": r["raw_text"], "reference": r["reference"],
                         "after": r["second_opinion"]["text"] if r["second_opinion"].get("chosen") == "second" else r["raw_text"]}
                        for r in rows if isinstance(r["second_opinion"], dict)],
    }
    out, saved, changed = {}, dict(c["modes"]), []
    for name, s in samples.items():
        verdict = vq.judge(s, name)
        state = dict(saved.get(name) or {})
        mode = state.get("mode", vq.DEFAULT_MODES[name])
        new = vq.next_mode(mode, state.get("auto", True), verdict)
        if new != mode:
            changed.append(f"{name}: {mode} → {new}")
        saved[name] = state | {"mode": new, "eval": verdict | {"at": time.strftime("%Y-%m-%d %H:%M")}}
        out[name] = saved[name]
    by_engine: dict[str, list] = {}
    for r in rows:
        if isinstance(r["confidence"], (int, float)) and r["reference"]:
            by_engine.setdefault(r["engine"], []).append((r["confidence"], vq.wer(r["raw_text"], r["reference"]) > 0.25))
    thresholds = {e: t for e, pts in by_engine.items() if (t := vq.calibrate(pts)) is not None}
    state = dict(saved.get("ambang") or {})
    mode = state.get("mode", vq.DEFAULT_MODES["ambang"])
    verdict = {"complement": "ambang", "samples": sum(len(p) for p in by_engine.values()), "passes": bool(thresholds),
               "reason": ("dikalibrasi: " + ", ".join(f"{e} {t:.2f}" for e, t in thresholds.items())) if thresholds
               else "butuh ≥30 ucapan terkoreksi per mesin"}
    new = vq.next_mode(mode, state.get("auto", True), verdict | {"samples": verdict["samples"] if thresholds else 0})
    if new != mode:
        changed.append(f"ambang: {mode} → {new}")
    saved["ambang"] = state | {"mode": new, "threshold": thresholds or state.get("threshold"),
                               "eval": verdict | {"at": time.strftime("%Y-%m-%d %H:%M")}}
    out["ambang"] = saved["ambang"]
    await _set_kv("voice:complements", saved)
    forget()
    if changed:
        await audit.record(actor, "voice.gate", None, changed=changed)
    return {"complements": out, "changed": changed, "labeled": len(rows)}


async def baseline(days: int = 30) -> dict:
    """Fase 3.1: how well JARVIS hears today, per engine — the numbers every complement is judged against."""
    rows = await db.pool().fetch(
        """SELECT engine, count(*) n, avg(confidence)::float conf,
                  percentile_cont(0.5) WITHIN GROUP (ORDER BY stt_ms) p50, percentile_cont(0.9) WITHIN GROUP (ORDER BY stt_ms) p90,
                  count(*) FILTER (WHERE dropped IS NOT NULL) dropped, count(*) FILTER (WHERE reference IS NOT NULL) labeled,
                  count(*) FILTER (WHERE confidence < 0.45) low
           FROM voice_events WHERE at > now() - make_interval(days => $1) GROUP BY engine ORDER BY n DESC""", days)
    labeled = await _labeled(days)
    kinds = collections.Counter(r["error_kind"] for r in await db.pool().fetch(
        "SELECT error_kind FROM voice_events WHERE error_kind IS NOT NULL AND at > now() - make_interval(days => $1)", days))
    werr = {}
    for r in labeled:
        werr.setdefault(r["engine"], []).append(vq.wer(r["raw_text"], r["reference"]))
    return {"days": days,
            "engines": [{"engine": r["engine"], "utterances": r["n"], "avg_confidence": round(r["conf"] or 0, 3),
                         "stt_ms_p50": int(r["p50"] or 0), "stt_ms_p90": int(r["p90"] or 0), "dropped": r["dropped"],
                         "low_confidence": r["low"], "corrected": r["labeled"],
                         "wer": round(sum(werr[r["engine"]]) / len(werr[r["engine"]]), 3) if werr.get(r["engine"]) else None}
                        for r in rows],
            "error_kinds": dict(kinds),
            "keep_samples": await keep_samples(), "second_engine": await second_engine()}


async def recent(limit: int = 40, only_doubtful: bool = False) -> list[dict]:
    rows = await db.pool().fetch(
        f"""SELECT id, at, engine, model, confidence, stt_ms, raw_text, final_text, applied, shadow, second_opinion, dropped,
                   reference, error_kind, audio_kept FROM voice_events
            {"WHERE confidence < 0.6 OR dropped IS NOT NULL OR shadow <> '[]'::jsonb" if only_doubtful else ""}
            ORDER BY id DESC LIMIT $1""", limit)
    return [dict(r) for r in rows]


async def set_admin(changes: dict, actor: str) -> None:
    """Admin page only: consent to keep audio (K3) and the second-opinion engine."""
    if "keep_samples" in changes:
        await _set_kv("voice:keep_samples", bool(changes["keep_samples"]))
    if "second_engine" in changes:
        if changes["second_engine"] not in SECOND_ENGINES:
            raise VoiceError("mesin opini kedua tidak dikenal")
        await _set_kv("voice:second_engine", changes["second_engine"])
    await audit.record(actor, "voice.admin", None, changes=sorted(changes))


async def prune() -> int:
    """Nightly: utterances older than KEEP_DAYS go (corrected ones stay — they are the test set), with their audio."""
    gone = await db.pool().fetch(f"""DELETE FROM voice_events WHERE at < now() - interval '{KEEP_DAYS} days' AND reference IS NULL
                                     RETURNING id, audio_kept""")
    for r in gone:
        if r["audio_kept"]:
            (VOICE_DIR / f"{r['id']}.pcm").unlink(missing_ok=True)
    return len(gone)


async def nightly() -> None:
    """Called from the self-improvement loop; does its work at most once a day."""
    today = time.strftime("%Y-%m-%d")
    if await _kv("voice:nightly", "") == today:
        return
    await _set_kv("voice:nightly", today)
    try:
        await prune()
        await evaluate("auto")
    except Exception:
        log.exception("voice nightly failed")


# ---------- 🔤 / 🎧: how the main agent takes in what the owner says (ADR-085) ----------
INPUT_KEY = "voice:input"
INPUT_MODES = ("stt", "audio")


async def input_mode() -> str:
    """'stt' (the transcript only — the default) or 'audio' (the model also hears the recording)."""
    v = await db.pool().fetchval("SELECT value FROM settings_kv WHERE key = $1", INPUT_KEY)
    return v if v in INPUT_MODES else "stt"


async def set_input_mode(mode: str, actor: str) -> str:
    if mode not in INPUT_MODES:
        raise VoiceError("mode: stt atau audio", 422)
    await db.pool().execute("""INSERT INTO settings_kv (key, value) VALUES ($1, $2::jsonb)
                               ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value""", INPUT_KEY, mode)
    from . import audit
    await audit.record(actor, "voice.input_mode", None, mode=mode)
    return mode

