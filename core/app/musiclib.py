"""Music and other audio JARVIS can legally fetch and play on the phone ("putar lagu ...").

Sources:
  - Openverse audio (Creative-Commons music, mostly Jamendo — verified 2026-10-21), no key needed;
  - a named song that is not there (the owner decided 2026-10-21 to have songs fetched as MP3, ADR-029):
    the YouTube share link goes to a converter service (cobalt-compatible API, MP3_CONVERTER_URL/KEY) —
    JARVIS never downloads from YouTube itself; without a converter, the song is fetched from SoundCloud
    and converted to MP3 with ffmpeg.
The file is stored once in data/media (playback does not depend on the source staying up) and served to the
phone at /api/v1/media/<id> with Range support (seeking).
"""

import asyncio
import json
import re
import uuid
from collections.abc import Callable
from pathlib import Path

import httpx

from .config import settings

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


MAX_SONG_S = 15 * 60


def _save_meta(media_id: str, path: Path, meta: dict) -> dict:
    (ROOT / f"{media_id}.json").write_text(json.dumps(meta | {"file": path.name, "type": "audio/mpeg"}, ensure_ascii=False))
    return {"media_id": media_id, "url": f"/api/v1/media/{media_id}", "size": path.stat().st_size, **meta}


async def convert_link(link: str, title: str, artist: str) -> dict:
    """A YouTube share link → MP3 through the configured converter (cobalt API). Raises ValueError."""
    if not settings.mp3_converter_url:
        raise ValueError("converter belum diatur")
    headers = {"Accept": "application/json", "Content-Type": "application/json", "User-Agent": "JARVIS/1.0"}
    if settings.mp3_converter_key:
        headers["Authorization"] = f"Api-Key {settings.mp3_converter_key}"
    async with httpx.AsyncClient(timeout=60, follow_redirects=True) as c:
        r = await c.post(settings.mp3_converter_url, headers=headers,
                         json={"url": link, "downloadMode": "audio", "audioFormat": "mp3", "audioBitrate": "128"})
        data = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
        if data.get("status") not in ("tunnel", "redirect") or not str(data.get("url", "")).startswith("https://"):
            raise ValueError(f"converter menolak: {(data.get('error') or {}).get('code') or r.status_code}")
        ROOT.mkdir(parents=True, exist_ok=True)
        media_id = uuid.uuid4().hex
        path, size = ROOT / f"{media_id}.mp3", 0
        async with c.stream("GET", data["url"]) as audio:
            if audio.status_code != 200:
                raise ValueError(f"unduhan converter HTTP {audio.status_code}")
            with path.open("wb") as f:
                async for chunk in audio.aiter_bytes():
                    size += len(chunk)
                    if size > MAX_BYTES:
                        f.close()
                        path.unlink(missing_ok=True)
                        raise ValueError("file audio terlalu besar")
                    f.write(chunk)
    return _save_meta(media_id, path, {"title": title, "artist": artist, "license": "", "source_url": link,
                                       "cover_url": None, "duration_s": None})


def _soundcloud_mp3(query: str, accept: Callable[[dict], bool]) -> dict:
    import yt_dlp
    with yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True, "extract_flat": True, "noplaylist": True}) as y:
        found = y.extract_info(f"scsearch6:{query}", download=False).get("entries") or []
    pick = next((e for e in found if e.get("url") and (e.get("duration") or 0) <= MAX_SONG_S
                 and accept({"title": e.get("title") or "", "artist": e.get("uploader") or ""})), None)
    if not pick:
        raise ValueError("lagunya tidak ketemu di SoundCloud")
    ROOT.mkdir(parents=True, exist_ok=True)
    media_id = uuid.uuid4().hex
    opts = {"quiet": True, "no_warnings": True, "noprogress": True, "format": "bestaudio/best",
            "outtmpl": str(ROOT / f"{media_id}.%(ext)s"), "noplaylist": True, "max_filesize": MAX_BYTES,
            "postprocessors": [{"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "128"}]}
    with yt_dlp.YoutubeDL(opts) as y:
        info = y.extract_info(pick["url"], download=True)
    path = ROOT / f"{media_id}.mp3"
    if not path.is_file():
        for leftover in ROOT.glob(f"{media_id}.*"):
            leftover.unlink(missing_ok=True)
        raise ValueError("konversi MP3 gagal")
    thumb = info.get("thumbnail") or ""
    return _save_meta(media_id, path, {
        "title": info.get("title") or pick.get("title") or query, "artist": info.get("uploader") or "",
        "license": "", "source_url": info.get("webpage_url") or pick["url"],
        "cover_url": thumb if thumb.startswith("https://") else None, "duration_s": round(info.get("duration") or 0)})


async def soundcloud_mp3(query: str, accept: Callable[[dict], bool]) -> dict:
    """A song from SoundCloud, converted to MP3 (≤ 15 min). Raises ValueError when not found."""
    try:
        return await asyncio.wait_for(asyncio.to_thread(_soundcloud_mp3, query, accept), 120)
    except ValueError:
        raise
    except Exception as e:
        raise ValueError(f"SoundCloud gagal ({type(e).__name__})") from e


def purge_old(days: int = 30, keep: set[str] | frozenset = frozenset()) -> int:
    """Songs and sounds fetched for the owner are kept for a month (disk space); returns files removed."""
    import time
    if not ROOT.is_dir():
        return 0
    cutoff, removed = time.time() - days * 86400, 0
    for f in ROOT.iterdir():
        if f.is_file() and f.stat().st_mtime < cutoff and f.stem not in keep:  # starred in Simpanan: kept
            f.unlink(missing_ok=True)
            removed += 1
    return removed
