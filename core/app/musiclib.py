"""Music and other audio JARVIS can legally fetch and play on the phone ("putar lagu ...").

Source: Openverse audio (Creative-Commons music, mostly Jamendo — verified 2026-10-21), no key needed.
The track is downloaded once to data/media (so playback does not depend on the source staying up) and
served to the phone at /api/v1/media/<id> with Range support (seeking). Copyrighted commercial songs are
NOT downloaded (YouTube terms forbid it); for those JARVIS shows the official YouTube player instead.
"""

import json
import re
import uuid
from pathlib import Path

import httpx

ROOT = Path("/data/media")
MAX_BYTES = 40_000_000
AUDIO_TYPES = {"audio/mpeg": "mp3", "audio/mp3": "mp3", "audio/ogg": "ogg", "audio/opus": "opus", "audio/flac": "flac",
               "audio/x-flac": "flac", "audio/wav": "wav", "audio/x-wav": "wav", "audio/mp4": "m4a", "audio/aac": "aac"}
_ID = re.compile(r"^[0-9a-f]{32}$")


async def search(query: str, limit: int = 6) -> list[dict]:
    async with httpx.AsyncClient(timeout=15, headers={"User-Agent": "JARVIS/1.0"}) as c:
        r = await c.get("https://api.openverse.org/v1/audio/",
                        params={"q": query, "page_size": max(1, min(limit, 20)), "category": "music", "mature": "false"})
    r.raise_for_status()
    out = []
    for t in r.json().get("results", []):
        if not str(t.get("url", "")).startswith("https://"):
            continue
        out.append({"id": t["id"], "title": t.get("title") or "", "artist": t.get("creator") or "",
                    "url": t["url"], "duration_s": round((t.get("duration") or 0) / 1000),
                    "license": (t.get("license") or "").upper(), "source_url": t.get("foreign_landing_url") or "",
                    "cover_url": t.get("thumbnail") if str(t.get("thumbnail", "")).startswith("https://") else None})
    return out


async def download(track: dict) -> dict:
    """Fetch the audio into data/media; returns {media_id, url (/api/v1/media/..), size}."""
    ROOT.mkdir(parents=True, exist_ok=True)
    media_id = uuid.uuid4().hex
    async with httpx.AsyncClient(timeout=120, follow_redirects=True, headers={"User-Agent": "JARVIS/1.0"}) as c:
        async with c.stream("GET", track["url"]) as r:
            if r.status_code != 200:
                raise ValueError(f"sumber audio HTTP {r.status_code}")
            ctype = r.headers.get("content-type", "").split(";")[0].strip().lower()
            ext = AUDIO_TYPES.get(ctype)
            if not ext:
                raise ValueError(f"bukan file audio ({ctype or 'tanpa tipe'})")
            size, path = 0, ROOT / f"{media_id}.{ext}"
            with path.open("wb") as f:
                async for chunk in r.aiter_bytes():
                    size += len(chunk)
                    if size > MAX_BYTES:
                        f.close()
                        path.unlink(missing_ok=True)
                        raise ValueError("file audio terlalu besar")
                    f.write(chunk)
    meta = {k: track.get(k) for k in ("title", "artist", "license", "source_url", "cover_url", "duration_s")}
    (ROOT / f"{media_id}.json").write_text(json.dumps(meta | {"file": path.name, "type": ctype}, ensure_ascii=False))
    return {"media_id": media_id, "url": f"/api/v1/media/{media_id}", "size": size, **meta}


def find(media_id: str) -> tuple[Path, str] | None:
    if not _ID.match(media_id or ""):
        return None
    meta_path = ROOT / f"{media_id}.json"
    if not meta_path.is_file():
        return None
    meta = json.loads(meta_path.read_text())
    path = ROOT / meta["file"]
    return (path, meta.get("type") or "audio/mpeg") if path.is_file() else None
