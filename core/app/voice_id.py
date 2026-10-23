"""The owner's voiceprint: is it the owner speaking, or someone else near the phone?

Deepgram used to tell the main agent how many voices it heard; local Whisper cannot. Instead the owner
records ~10 sentences once (APK → Pengaturan → Rekam suaraku); jarvis-ears turns each into a speaker
embedding (CAM++), and their normalised mean is the voiceprint. Every utterance is then compared:
measured 2026-10-21 on two Indonesian voices, same speaker ≥ 0.86 cosine, different ≤ 0.45.
Stored only on this server (settings_kv), never sent anywhere; deleting it is one tap.
"""

import json

import httpx
import numpy as np

from . import audit, db
from .config import settings

THRESHOLD = 0.6            # default, used by name_speakers()
THRESHOLD_KEY = "voiceprint:threshold"  # dynamic override in settings_kv
KEY = "voiceprint:owner"
MIN_SAMPLES = 5


async def _threshold() -> float:
    """Cosine-similarity threshold from settings_kv, fallback 0.6."""
    v = await db.pool().fetchval("SELECT value FROM settings_kv WHERE key = $1", THRESHOLD_KEY)
    if v is not None:
        try:
            return float(v if isinstance(v, (int, float)) else json.loads(str(v)))
        except (ValueError, TypeError, json.JSONDecodeError):
            pass
    return THRESHOLD


async def _embed(pcm: bytes) -> list[float]:
    async with httpx.AsyncClient(timeout=60) as c:
        r = await c.post(f"{settings.whisper_url}/speaker/embed", content=pcm)
    if r.status_code != 200:
        raise ValueError(r.json().get("detail") if r.headers.get("content-type", "").startswith("application/json") else r.text[:200])
    return r.json()["embedding"]


async def _load() -> dict | None:
    v = await db.pool().fetchval("SELECT value FROM settings_kv WHERE key = $1", KEY)
    return v if isinstance(v, dict) else (json.loads(v) if isinstance(v, str) else None)


async def enrolled() -> dict:
    v = await _load()
    return {"enrolled": bool(v and v.get("vector")), "samples": (v or {}).get("samples", 0)}


async def add_sample(pcm: bytes, actor: str) -> dict:
    """One enrolment sentence. The voiceprint becomes active after MIN_SAMPLES."""
    vec = np.array(await _embed(pcm))
    cur = await _load() or {"sum": None, "samples": 0}
    total = vec if cur.get("sum") is None else np.array(cur["sum"]) + vec
    n = cur.get("samples", 0) + 1
    value = {"sum": total.round(5).tolist(), "samples": n}
    if n >= MIN_SAMPLES:
        value["vector"] = (total / (np.linalg.norm(total) or 1)).round(5).tolist()
    await db.pool().execute(
        """INSERT INTO settings_kv (key, value) VALUES ($1, $2)
           ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value""", KEY, value)
    if n == MIN_SAMPLES:
        await audit.record(actor, "voiceprint.enrolled", None, samples=n)
    return {"samples": n, "active": n >= MIN_SAMPLES, "needed": MIN_SAMPLES}


async def delete(actor: str) -> None:
    await db.pool().execute("DELETE FROM settings_kv WHERE key = $1", KEY)
    await audit.record(actor, "voiceprint.deleted", None)


def similarity(a: list[float], b: list[float]) -> float:
    return float(np.dot(np.array(a), np.array(b)))


async def check(pcm: bytes) -> dict:
    """{} when no voiceprint; else {"owner_voice": similarity, "is_owner": bool}."""
    v = await _load()
    if not v or not v.get("vector") or len(pcm) < 2 * 16000:  # < 1 s: too short to judge
        return {}
    try:
        sim = similarity(await _embed(pcm), v["vector"])
    except (httpx.HTTPError, ValueError, KeyError):
        return {}
    thr = await _threshold()
    return {"owner_voice": round(sim, 3), "is_owner": sim >= thr}


def name_speakers(voices: dict[str, list[float]], owner: list[float] | None, ids: list[str] | None = None) -> dict[str, str]:
    """Meeting diarization labels → 'Pemilik' for the speaker closest to the voiceprint (if close enough),
    the others 'Pembicara 2, 3, …' (or 'Pembicara 1, 2, …' when the owner is not among them)."""
    ids = sorted(set(ids or []) | set(voices), key=int)
    best = None
    if owner and voices:
        cand = max(voices, key=lambda k: similarity(voices[k], owner))
        if similarity(voices[cand], owner) >= THRESHOLD:
            best = cand
    names, n = {}, 2 if best is not None else 1
    for k in ids:
        if k == best:
            names[k] = "Pemilik"
        else:
            names[k] = f"Pembicara {n}"
            n += 1
    return names
