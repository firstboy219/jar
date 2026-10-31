"""Koleksi musik (owner 2026-10-31: "kamu masukkan ke list storage berikut file hasil download nya, jadi nextnya saya tinggal play dari lokal
storage yg sudah Jarvis siapkan … siapkan management lagunya seperti Spotify").

  collect   the songs he ticks on a list (musik.offer) join his collection as "antri" and are downloaded one at a time in the background —
            through his converter (cobalt, MP3_CONVERTER_URL) when it is set, else yt-dlp with HIS YouTube cookies (uploaded once from the app,
            kept vault-encrypted, written to a private temp file only while a song downloads): YouTube refuses this server's address without a
            signed-in session. Failing those, the same song on SoundCloud (found by its cleaned title, kept only when the words match).
            When nothing works the song waits as "gagal" (saying cookies would help) and is retried when he adds them.
  play      from the local file, in the phone's music service (every screen, screen off, lock-screen controls): one song, all of them,
            shuffled, from a song on — the next follows when one ends; a playlist song that is in the collection plays from it too.
  manage    like / unlike, delete (the file goes too), add to a playlist, retry a failed download; how much space it takes.
Every download and every play goes through the master flow (a skill: no AI)."""

import asyncio
import contextlib
import json
import logging
import os
import random
import re
import tempfile
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from . import appclock, audit, db, hub, master, musiclib
from .appauth import actor, owner
from .config import settings
from .location import WIB

log = logging.getLogger("jarvis-core")
router = APIRouter()
API = "/api/v1/app/music/library"
COOKIES_KEY = "music:ytcookies"
NEED_COOKIES = "butuh cookies YouTube (YouTube menolak server tanpa sesi masuk) — unggah di Musik → Koleksi → Pengunduh"
_queue: dict = {"ids": [], "i": 0}
_worker: dict = {"task": None}


class LibraryError(ValueError):
    pass


# ---------- cookies (his own YouTube session, for the downloader) ----------

def valid_cookies(text: str) -> bool:
    """A Netscape cookies.txt with YouTube cookies in it. Pure."""
    lines = [ln for ln in (text or "").splitlines() if ln.strip() and not ln.startswith("#")]
    return any(".youtube.com" in ln.split("\t")[0] for ln in lines if ln.count("\t") >= 6)


async def set_cookies(text: str, who: str) -> None:
    from . import vault
    if not valid_cookies(text):
        raise LibraryError("bukan file cookies.txt YouTube (format Netscape, dari ekstensi 'Get cookies.txt LOCALLY')")
    enc = vault.encrypt(text).hex()
    await db.pool().execute("INSERT INTO settings_kv (key, value) VALUES ($1, $2) ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value",
                            COOKIES_KEY, {"enc": enc, "at": datetime.now(WIB).isoformat()})
    await audit.record(who, "music.cookies_set", "music:cookies")
    await db.pool().execute("UPDATE music_library SET status = 'antri', error = NULL WHERE status = 'gagal'")   # waiting for exactly this
    kick()


async def cookies_state() -> dict:
    v = await db.pool().fetchval("SELECT value FROM settings_kv WHERE key = $1", COOKIES_KEY) or {}
    return {"cookies": bool(v.get("enc")), "since": v.get("at"), "converter": bool(settings.mp3_converter_url)}


async def clear_cookies(who: str) -> None:
    await db.pool().execute("DELETE FROM settings_kv WHERE key = $1", COOKIES_KEY)
    await audit.record(who, "music.cookies_cleared", "music:cookies")


@contextlib.asynccontextmanager
async def _cookie_file():
    """His cookies decrypted into a private temp file for one download, gone right after."""
    from . import vault
    v = await db.pool().fetchval("SELECT value FROM settings_kv WHERE key = $1", COOKIES_KEY) or {}
    if not v.get("enc"):
        yield None
        return
    fd, path = tempfile.mkstemp(prefix="ytc-", suffix=".txt")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(vault.decrypt(bytes.fromhex(v["enc"])))
        yield path
    finally:
        with contextlib.suppress(OSError):
            os.unlink(path)


# ---------- the collection ----------

async def add(songs: list[dict], who: str, source: str = "pilihan") -> list[int]:
    """Songs he ticked (url, title, channel, duration_s, cover) join his collection; new ones are queued for download."""
    ids = []
    for s in songs:
        link = musiclib.youtube_link(str(s.get("url") or ""))
        if not link:
            continue
        vid = link.rsplit("=", 1)[-1]
        rid = await db.pool().fetchval(
            """INSERT INTO music_library (video_id, source_url, title, artist, duration_s, cover, source) VALUES ($1, $2, $3, $4, $5, $6, $7)
               ON CONFLICT (video_id) DO UPDATE SET status = CASE WHEN music_library.status = 'gagal' THEN 'antri' ELSE music_library.status END
               RETURNING id""", vid, link, str(s.get("title") or "")[:160], str(s.get("channel") or s.get("artist") or "")[:80],
            s.get("duration_s"), str(s.get("cover") or "")[:300], source)
        ids.append(rid)
    await audit.record(who, "music.collected", "music:library", songs=len(ids))
    kick()
    return ids


async def listing() -> dict:
    rows = [dict(r) for r in await db.pool().fetch(
        """SELECT id, title, artist, duration_s, cover, status, error, size_bytes, liked, plays, last_played, added_at, media_id
           FROM music_library ORDER BY (status = 'siap') DESC, added_at DESC""")]
    return {"songs": rows, "count": sum(1 for r in rows if r["status"] == "siap"), "bytes": sum(r["size_bytes"] for r in rows),
            "waiting": sum(1 for r in rows if r["status"] in ("antri", "unduh")), "failed": sum(1 for r in rows if r["status"] == "gagal"),
            "downloader": await cookies_state(), "queue": dict(_queue)}


# ---------- downloading, one at a time ----------

def kick() -> None:
    """Start the downloader if it is not running (it stops by itself when the queue is empty)."""
    if _worker["task"] is None or _worker["task"].done():
        _worker["task"] = asyncio.create_task(_drain())


async def _drain() -> None:
    while True:
        row = await db.pool().fetchrow("UPDATE music_library SET status = 'unduh' WHERE id = (SELECT id FROM music_library WHERE status = 'antri' "
                                       "ORDER BY added_at LIMIT 1 FOR UPDATE SKIP LOCKED) RETURNING *")
        if not row:
            return
        row = dict(row)
        r = await master.run(master.Job("musik", "unduh", f"unduh lagu: {row['title'][:80]}", trigger="event", skill=lambda row=row: _download(row)))
        if r["status"] == "done":
            m = r["result"]
            await db.pool().execute("UPDATE music_library SET status = 'siap', media_id = $2, size_bytes = $3, error = NULL, ready_at = now() WHERE id = $1",
                                    row["id"], m["media_id"], int(m.get("size") or 0))
            await hub.broadcast({"type": "notify", "title": "Lagu siap di koleksi", "text": row["title"][:120], "kind": "info", "route": "#/musik"})
        else:
            await db.pool().execute("UPDATE music_library SET status = 'gagal', error = $2 WHERE id = $1", row["id"], str(r.get("error") or "gagal")[:300])
        await hub.broadcast({"type": "music_library", "id": row["id"]})


_NOISE = re.compile(r"\(.*?\)|\[.*?\]|【.*?】|\b(official|music|video|audio|lyrics?|lirik|mv|hd|4k|visualizer|live)\b|[|•]", re.I)


def song_words(title: str, artist: str) -> str:
    """'Tulus - Hati-Hati di Jalan (Official Music Video)' / channel 'TULUS' → 'Tulus - Hati-Hati di Jalan': what to look for elsewhere. Pure."""
    t = re.sub(r"\s{2,}", " ", _NOISE.sub(" ", title or "")).strip(" -–")
    who = re.sub(r"\s*-\s*Topic$|VEVO$|\s*Official$", "", artist or "", flags=re.I).strip()
    return t if " - " in t or not who or who.lower() in t.lower() else f"{who} - {t}"


def same_song(track: dict, words: str) -> bool:
    """A SoundCloud upload counts only when it carries the song's own title (most of its words), not just the artist's name. Pure."""
    title = words.split(" - ", 1)[-1]
    want = [w for w in re.findall(r"\w+", title.lower()) if len(w) >= 2] or re.findall(r"\w+", words.lower())
    have = set(re.findall(r"\w+", f"{track.get('title', '')} {track.get('artist', '')}".lower()))
    return bool(want) and sum(w in have for w in want) * 3 >= len(want) * 2


async def _download(row: dict) -> dict:
    """His converter → yt-dlp with his YouTube cookies → the same song on SoundCloud (needs nothing from him)."""
    meta, errors = {"title": row["title"], "artist": row["artist"]}, []
    if settings.mp3_converter_url:
        try:
            return await musiclib.convert_link(row["source_url"], row["title"], row["artist"])
        except ValueError as e:
            errors.append(f"converter: {e}")
    async with _cookie_file() as cookies:
        if cookies:
            try:
                return await asyncio.to_thread(_ytdlp_mp3, row["source_url"], cookies, meta | {"cover_url": row["cover"], "duration_s": row["duration_s"]})
            except RuntimeError as e:
                errors.append(str(e))
    q = song_words(row["title"], row["artist"])
    try:
        m = await musiclib.soundcloud_mp3(q, lambda t: same_song(t, q))
        return m | {"via": "soundcloud"}
    except ValueError as e:
        errors.append(str(e))
    if not (await cookies_state())["cookies"]:
        errors.append(NEED_COOKIES)
    raise RuntimeError("; ".join(errors))


def _ytdlp_mp3(url: str, cookies: str, meta: dict) -> dict:
    """bestaudio → MP3 with his session; saved into the media folder like every other song."""
    import yt_dlp
    musiclib.ROOT.mkdir(parents=True, exist_ok=True)
    media_id = uuid.uuid4().hex
    base = musiclib.ROOT / media_id
    opts = {"format": "bestaudio/best", "outtmpl": f"{base}.%(ext)s", "quiet": True, "no_warnings": True, "noplaylist": True,
            "cookiefile": cookies, "max_filesize": musiclib.MAX_BYTES,
            "postprocessors": [{"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "160"}]}
    try:
        with yt_dlp.YoutubeDL(opts) as y:
            y.extract_info(url, download=True)
    except Exception as e:
        msg = str(e)
        raise RuntimeError("YouTube masih menolak — cookies kedaluwarsa? unggah ulang" if "confirm you" in msg or "Sign in" in msg else f"unduhan gagal: {msg[:160]}")
    path = base.with_suffix(".mp3")
    if not path.exists():
        raise RuntimeError("file MP3 tidak terbentuk")
    return musiclib._save_meta(media_id, path, {**meta, "license": "", "source_url": url})


@appclock.every(120, "music.download")
async def _tick() -> None:
    """After a restart (or when a download stopped half-way) the queue carries on by itself."""
    if (_worker["task"] is None or _worker["task"].done()) and await db.pool().fetchval("SELECT 1 FROM music_library WHERE status IN ('antri', 'unduh') LIMIT 1"):
        await db.pool().execute("UPDATE music_library SET status = 'antri' WHERE status = 'unduh'")   # nothing is downloading now: start those again
        kick()


# ---------- playing ----------

def _song(row: dict) -> dict:
    return {"title": row["title"], "artist": row["artist"], "url": f"/api/v1/media/{row['media_id']}", "cover_url": row["cover"] or None,
            "source_url": f"https://www.youtube.com/watch?v={row['video_id']}" if row.get("video_id") else "", "duration_s": row["duration_s"]}


async def play(ids: list[int], start: int = 0, shuffle: bool = False) -> dict:
    """Play songs of the collection in this order (or shuffled) from `start`; the next follows when one ends."""
    from . import playlists
    ready = {r["id"]: dict(r) for r in await db.pool().fetch("SELECT * FROM music_library WHERE id = ANY($1) AND status = 'siap'", ids)}
    order = [i for i in ids if i in ready]
    if not order:
        raise LibraryError("belum ada lagu yang siap diputar")
    if shuffle:
        random.shuffle(order)
        start = 0
    _queue.update(ids=order, i=max(0, min(start, len(order) - 1)))
    playlists._playing.update(playlist_id=None)   # one queue at a time
    return await _play_current()


async def _play_current() -> dict:
    from . import media_tools
    rid = _queue["ids"][_queue["i"]]
    row = dict(await db.pool().fetchrow("SELECT * FROM music_library WHERE id = $1", rid))

    async def run():
        shown = await media_tools._show_song(_song(row), "koleksi")
        await db.pool().execute("UPDATE music_library SET plays = plays + 1, last_played = now() WHERE id = $1", rid)
        return shown
    r = await master.run(master.Job("musik", "putar-koleksi", f"putar {row['title'][:80]}", skill=run))
    if r["status"] != "done":
        raise LibraryError(r.get("error") or "lagu tidak bisa diputar")
    return {**r["result"], "index": _queue["i"], "total": len(_queue["ids"]), "id": rid}


def on_stage_event(event: str) -> bool:
    """The phone said the song ended (or next / previous was tapped): True when the collection's queue took it."""
    if not _queue["ids"] or event not in ("ended", "next", "prev"):
        return False
    step = -1 if event == "prev" else 1
    nxt = _queue["i"] + step
    if not 0 <= nxt < len(_queue["ids"]):
        _queue.update(ids=[], i=0)
        return True
    _queue["i"] = nxt
    asyncio.create_task(_play_current())
    return True


async def local_for(title: str, artist: str) -> dict | None:
    """A playlist song that is already in the collection: its local file."""
    row = await db.pool().fetchrow("SELECT * FROM music_library WHERE status = 'siap' AND lower(title) = lower($1) AND ($2 = '' OR lower(artist) = lower($2)) LIMIT 1",
                                   title, artist or "")
    return _song(dict(row)) if row else None


async def remove(rid: int, who: str) -> bool:
    row = await db.pool().fetchrow("DELETE FROM music_library WHERE id = $1 RETURNING media_id, title", rid)
    if not row:
        return False
    if row["media_id"]:
        for ext in ("mp3", "json", "m4a", "ogg", "opus", "webm"):
            with contextlib.suppress(OSError):
                (musiclib.ROOT / f"{row['media_id']}.{ext}").unlink()
    if rid in _queue["ids"]:
        _queue.update(ids=[i for i in _queue["ids"] if i != rid], i=0)
    await audit.record(who, "music.removed", f"music_library:{rid}", title=row["title"][:80])
    return True


# ---------- API ----------

class PlayIn(BaseModel):
    ids: list[int] = Field(min_length=1, max_length=500)
    start: int = Field(default=0, ge=0)
    shuffle: bool = False


class CookiesIn(BaseModel):
    text: str = Field(min_length=20, max_length=200_000)


class ToPlaylistIn(BaseModel):
    name: str | None = Field(default=None, max_length=80)


@router.get(API)
async def api_list(device: dict = Depends(owner)):
    return json.loads(json.dumps(await listing(), default=str))


@router.post(API + "/play")
async def api_play(body: PlayIn, device: dict = Depends(owner)):
    try:
        return await play(body.ids, body.start, body.shuffle)
    except LibraryError as e:
        raise HTTPException(409, str(e))


class LinkIn(BaseModel):
    url: str = Field(min_length=10, max_length=300)


@router.post(API + "/link")
async def api_link(body: LinkIn, device: dict = Depends(owner)):
    """A YouTube / YouTube Music link pasted by him: into the collection (title and channel from YouTube's oEmbed)."""
    import httpx
    link = musiclib.youtube_link(body.url)
    if not link:
        raise HTTPException(422, "tempel link YouTube atau YouTube Music")
    title, artist = "Lagu dari YouTube", ""
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            o = (await c.get("https://www.youtube.com/oembed", params={"url": link, "format": "json"})).json()
        title, artist = o.get("title") or title, o.get("author_name") or ""
    except Exception:
        pass
    vid = link.rsplit("=", 1)[-1]
    ids = await add([{"url": link, "title": title, "channel": artist, "cover": f"https://i.ytimg.com/vi/{vid}/mqdefault.jpg"}], actor(device), "link")
    return {"id": ids[0] if ids else None, "title": title, **await cookies_state()}


@router.post(API + "/{rid}/like")
async def api_like(rid: int, device: dict = Depends(owner)):
    liked = await db.pool().fetchval("UPDATE music_library SET liked = NOT liked WHERE id = $1 RETURNING liked", rid)
    if liked is None:
        raise HTTPException(404, "lagu tidak ada")
    return {"liked": liked}


@router.post(API + "/{rid}/retry")
async def api_retry(rid: int, device: dict = Depends(owner)):
    await db.pool().execute("UPDATE music_library SET status = 'antri', error = NULL WHERE id = $1 AND status = 'gagal'", rid)
    kick()
    return {"ok": True}


@router.post(API + "/{rid}/playlist")
async def api_to_playlist(rid: int, body: ToPlaylistIn, device: dict = Depends(owner)):
    from . import playlists
    row = await db.pool().fetchrow("SELECT title, artist FROM music_library WHERE id = $1", rid)
    if not row:
        raise HTTPException(404, "lagu tidak ada")
    r = await playlists.add([{"title": row["title"], "artist": row["artist"]}], body.name, "koleksi", actor(device))
    return r


@router.delete(API + "/{rid}")
async def api_remove(rid: int, device: dict = Depends(owner)):
    if not await remove(rid, actor(device)):
        raise HTTPException(404, "lagu tidak ada")
    return {"ok": True}


@router.put(API + "/cookies")
async def api_cookies(body: CookiesIn, device: dict = Depends(owner)):
    try:
        await set_cookies(body.text, actor(device))
    except LibraryError as e:
        raise HTTPException(422, str(e))
    return await cookies_state()


@router.delete(API + "/cookies")
async def api_cookies_clear(device: dict = Depends(owner)):
    await clear_cookies(actor(device))
    return await cookies_state()
