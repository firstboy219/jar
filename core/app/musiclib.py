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
from urllib.parse import quote

from .config import settings

ROOT = Path("/data/media")
MAX_BYTES = 40_000_000
AUDIO_TYPES = {"audio/mpeg": "mp3", "audio/mp3": "mp3", "audio/ogg": "ogg", "audio/opus": "opus", "audio/flac": "flac",
               "audio/x-flac": "flac", "audio/wav": "wav", "audio/x-wav": "wav", "audio/mp4": "m4a", "audio/aac": "aac"}
_ID = re.compile(r"^[0-9a-f]{32}$")


MOODS = {   # how the owner asks (Indonesian) → what the open-music catalogues tag it as
    "santai": "chill", "rileks": "relaxing", "relax": "relaxing", "tenang": "calm", "tidur": "ambient", "fokus": "ambient", "belajar": "lofi",
    "kerja": "lofi", "semangat": "upbeat", "olahraga": "energetic", "senam": "energetic", "sedih": "sad", "galau": "melancholic",
    "romantis": "romantic", "bahagia": "happy", "senang": "happy", "pagi": "acoustic", "hujan": "piano", "jazz": "jazz", "akustik": "acoustic",
    "piano": "piano", "gitar": "guitar", "klasik": "classical", "lofi": "lofi", "chill": "chill", "instrumental": "instrumental",
}
_NOISE = re.compile(r"\b(musik|music|lagu|lagu2|lagu-lagu|putar|putarkan|play|yang|yg|dong|aja|saja|buat|untuk|sambil|suasana|nuansa)\b", re.I)


def mood_query(query: str) -> tuple[str, str]:
    """'musik santai buat kerja' → ('santai kerja', 'chill'): the words that matter, and a catalogue tag when it is a mood. Pure."""
    words = " ".join(_NOISE.sub(" ", query).split())
    tag = next((MOODS[w] for w in re.findall(r"\w+", words.lower()) if w in MOODS), "")
    return words or query.strip(), tag


async def _openverse(query: str, limit: int) -> list[dict]:
    async with httpx.AsyncClient(timeout=8, headers={"User-Agent": "JARVIS/1.0"}) as c:
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


def licence_name(url: str) -> str:
    """'http://creativecommons.org/licenses/by-nc-sa/3.0/' → 'CC BY-NC-SA 3.0'; '' for anything not open. Pure."""
    u = str(url or "").lower()
    if "publicdomain" in u:
        return "CC0 / domain publik"
    m = re.search(r"creativecommons\.org/licenses/([a-z-]+)/([\d.]+)", u)
    return f"CC {m.group(1).upper()} {m.group(2)}" if m else ""


async def _archive(words: str, tag: str, limit: int) -> list[dict]:
    """The Internet Archive's netlabel and open-audio collections (Creative Commons albums, MP3 straight from archive.org, no key) —
    reached when Openverse is not. A mood is its subject tag; anything else a search in titles and subjects."""
    what = re.sub(r'["\\()]', " ", tag or words).strip()
    if not what:
        return []
    q = f'mediatype:audio AND (collection:netlabels OR collection:opensource_audio) AND (subject:("{what}") OR title:("{what}"))'
    async with httpx.AsyncClient(timeout=15, headers={"User-Agent": "JARVIS/1.0"}) as c:
        r = await c.get("https://archive.org/advancedsearch.php", params={"q": q, "fl[]": ["identifier", "title", "creator", "licenseurl"],
                                                                          "rows": max(2, min(limit, 8)), "sort[]": "downloads desc", "output": "json"})
        r.raise_for_status()
        docs = [d for d in r.json().get("response", {}).get("docs", []) if licence_name(d.get("licenseurl"))]

        async def files(d: dict) -> list[dict]:
            try:
                m = (await c.get(f"https://archive.org/metadata/{d['identifier']}")).json()
            except (httpx.HTTPError, ValueError):
                return []
            out, mp3s = [], [f for f in m.get("files") or [] if str(f.get("name") or "").lower().endswith(".mp3") and "_64kb" not in str(f.get("name"))]
            originals = [f for f in mp3s if f.get("source") == "original"]
            for f in originals or mp3s:   # the uploaded MP3s, not archive.org's own re-encodings of them
                name = str(f.get("name") or "")
                secs = int(float(f.get("length") or 0)) if str(f.get("length") or "").replace(".", "", 1).isdigit() else 0
                if secs > MAX_SONG_S:
                    continue
                creator = d.get("creator") or ""
                out.append({"id": f"ia-{d['identifier']}-{len(out)}", "title": f.get("title") or name.rsplit(".", 1)[0].replace("_", " "),
                            "artist": creator if isinstance(creator, str) else ", ".join(creator), "url": f"https://archive.org/download/{d['identifier']}/{quote(name)}",
                            "duration_s": secs, "license": licence_name(d.get("licenseurl")), "source_url": f"https://archive.org/details/{d['identifier']}",
                            "cover_url": f"https://archive.org/services/img/{d['identifier']}"})
                if len(out) >= 2:
                    break
            return out
        lists = await asyncio.gather(*(files(d) for d in docs[:4]))
    return [t for group in zip(*[x for x in lists if x]) for t in group][:limit] or [t for x in lists for t in x][:limit]


async def search(query: str, limit: int = 6) -> list[dict]:
    """Open-licence music for a request: Openverse first, the Internet Archive when Openverse is slow or has nothing (a mood like "santai" is asked
    in its catalogue tag)."""
    words, tag = mood_query(query)
    try:
        found = await _openverse(f"{tag} {words}".strip() if tag else words, limit)
        if found:
            return found
    except (httpx.HTTPError, ValueError):
        pass
    found = await _archive(words, tag, limit)
    if not found and tag:
        found = await _archive(words, "", limit)
    return found


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
