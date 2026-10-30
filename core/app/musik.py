"""Musik (ADR-087, mockup 4): music by mood — fokus, semangat, olahraga, santai, tidur (his own search words per mood in settings) — his
playlists, what is playing, and the mood he usually wants at this time of day, learned from what he played (owner 2026-10-29: "tiap pagi
butuh musik bermode apa sport/semangat"). The morning habit offers that mood.

Playing is a fixed procedure through the master flow (skill: licensed tracks, or the official YouTube player for a named song —
media_tools); the screen and the phone get it as a stage event, and the app's player plays it."""

import asyncio
import logging
from collections import Counter
from datetime import datetime

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from . import appsettings, db, habits, home, hub, master, media_tools, playlists, stage
from .appauth import owner
from .config import settings
from .location import WIB

log = logging.getLogger("jarvis-core")
router = APIRouter()
API = "/api/v1/app/music"
DEFAULT_BY_SLOT = {"subuh": "santai", "pagi": "semangat", "kerja": "fokus", "siang": "fokus", "sore": "santai", "malam": "santai", "larut": "tidur"}


class MusicError(ValueError):
    pass


def usual_mood(plays: list[dict], slot: str, weekday: int, moods: list[str]) -> tuple[str, str]:
    """(mood, why) for this time: the mood he played most in this part of the day (the same weekday counts double) once he did it
    at least twice; else the default for the time of day. Pure."""
    c: Counter = Counter()
    for p in plays:
        if p.get("slot") == slot and p.get("mood") in moods:
            c[p["mood"]] += 2 if p.get("weekday") == weekday else 1
    if c:
        mood, score = c.most_common(1)[0]
        if score >= 2:
            return mood, "biasanya kamu memutar ini jam segini"
    d = DEFAULT_BY_SLOT.get(slot, "santai")
    return (d if d in moods else (moods[0] if moods else "santai")), "belum ada kebiasaan: pilihan untuk jam segini"


async def _log(kind: str, mood: str, query: str, title: str) -> None:
    from . import places
    now = datetime.now(WIB)
    place = (await places.current()).get("place") or ""
    await db.pool().execute("INSERT INTO media_log (kind, mood, query, title, slot, weekday, place) VALUES ($1, $2, $3, $4, $5, $6, $7)",
                            kind, mood, query[:200], title[:200], home.slot_of(now), now.weekday(), place)


async def play(mood: str = "", query: str = "", trigger: str = "owner") -> dict:
    s = await appsettings.get("music")
    if mood and mood not in s["moods"]:
        raise MusicError(f"mood tidak dikenal: {mood}")
    q = s["moods"][mood] if mood else query.strip()
    if not q:
        raise MusicError("mau musik apa?")

    async def run():
        r = await media_tools.play(q)
        if "error" in r:
            raise RuntimeError(r["error"])
        await _log("music", mood, q, f"{r.get('playing', '')} — {r.get('artist', '')}")
        return r
    r = await master.run(master.Job("musik", "putar", f"putar musik {mood or q}", trigger=trigger, skill=run))
    if r["status"] != "done":
        raise MusicError(r.get("error") or "musik tidak bisa diputar")
    return {**r["result"], "mood": mood, "lane": r.get("lane")}


# ---------- a request for music → a list he ticks → MP3s (owner 2026-10-31) ----------

PICK_RESULTS = 10
MAX_PICK_S = 15 * 60      # a song, not a compilation


def song_options(found: list[dict]) -> list[dict]:
    """YouTube results worth offering as songs: real watch links, not hour-long compilations, no duplicates; with a cover. Pure."""
    from . import musiclib
    out, seen = [], set()
    for v in found:
        link = musiclib.youtube_link(str(v.get("url") or ""))
        if not link or link in seen or (v.get("duration_s") or 0) > MAX_PICK_S:
            continue
        seen.add(link)
        vid = link.rsplit("=", 1)[-1]
        out.append({"url": link, "title": str(v.get("title") or "")[:160], "channel": str(v.get("channel") or "")[:80],
                    "duration_s": v.get("duration_s"), "cover": f"https://i.ytimg.com/vi/{vid}/mqdefault.jpg"})
    return out


async def offer(query: str, who: str = "owner", mood: str = "") -> dict:
    """Search YouTube for what he asked and put the results before him to tick (a skill: no AI)."""
    q = query.strip()
    if not q:
        raise MusicError("mau lagu apa?")

    async def run():
        found = await asyncio.wait_for(asyncio.to_thread(media_tools.youtube_search, q, PICK_RESULTS + 6), 30)
        opts = song_options(found)[:PICK_RESULTS]
        if not opts:
            raise RuntimeError("lagunya tidak ketemu di YouTube")
        await db.pool().execute("UPDATE music_picks SET status = 'expired', updated_at = now() WHERE status = 'open'")   # one list at a time
        pid = await db.pool().fetchval("INSERT INTO music_picks (query, options, created_by) VALUES ($1, $2, $3) RETURNING id", q, opts, who)
        await hub.broadcast({"type": "notify", "title": "Pilih lagunya", "text": f"{len(opts)} lagu untuk \"{q}\" — centang yang mau diputar.",
                             "kind": "info", "route": f"#/musik?pilih={pid}"})
        await hub.broadcast({"type": "needs"})
        await _log("music", mood, q, f"daftar {len(opts)} lagu")
        return {"pick": pid, "count": len(opts), "options": opts}
    r = await master.run(master.Job("musik", "pilihan", f"daftar lagu: {q}", trigger="owner", skill=run))
    if r["status"] != "done":
        raise MusicError(r.get("error") or "daftar lagu tidak bisa dibuat")
    return r["result"]


async def open_pick() -> dict | None:
    await db.pool().execute("UPDATE music_picks SET status = 'expired', updated_at = now() WHERE status = 'open' AND created_at < now() - interval '6 hours'")
    r = await db.pool().fetchrow("SELECT * FROM music_picks WHERE status = 'open' ORDER BY id DESC LIMIT 1")
    return dict(r) if r else None


async def choose(pick_id: int, idxs: list[int], who: str = "owner") -> dict:
    """The ticked songs: made MP3 one by one in the background (the first played as soon as it is ready), all kept in his playlist."""
    row = await db.pool().fetchrow("SELECT * FROM music_picks WHERE id = $1 AND status = 'open'", pick_id)
    if not row:
        raise MusicError("daftar lagu ini sudah tidak berlaku")
    opts = row["options"]
    chosen = [opts[i] for i in dict.fromkeys(idxs) if isinstance(i, int) and 0 <= i < len(opts)]
    if not chosen:
        raise MusicError("centang minimal satu lagu")
    await db.pool().execute("UPDATE music_picks SET status = 'working', chosen = $2, updated_at = now() WHERE id = $1", pick_id, chosen)
    await hub.broadcast({"type": "needs"})
    _bg.add(t := asyncio.create_task(_process(pick_id, chosen, who)))
    t.add_done_callback(_bg.discard)
    return {"ok": True, "count": len(chosen), "converter": bool(settings.mp3_converter_url)}


_bg: set = set()


async def _process(pick_id: int, chosen: list[dict], who: str) -> None:
    from . import musiclib

    async def run():
        results, played = [], False
        for i, song in enumerate(chosen):
            try:
                if settings.mp3_converter_url:
                    m = await musiclib.convert_link(song["url"], song["title"], song["channel"])
                    if not played:
                        await media_tools._show_song(m, "converter")
                        played = True
                    results.append({"title": song["title"], "ok": True, "media": m["url"]})
                else:
                    if not played:   # no converter yet: the official YouTube player plays it (its terms: visible, not extracted)
                        await media_tools._show("video", {"url": song["url"], "title": song["title"], "channel": song["channel"]},
                                                f"Memutar {song['title']}"[:200], "jarvis")
                        played = True
                    results.append({"title": song["title"], "ok": True, "youtube": True})
                await playlists.add([{"title": song["title"], "artist": song["channel"]}], None, "pilihan", who)
            except Exception as e:
                results.append({"title": song["title"], "ok": False, "error": str(e)[:160]})
            await db.pool().execute("UPDATE music_picks SET results = $2, updated_at = now() WHERE id = $1", pick_id, results)
            await hub.broadcast({"type": "notify", "title": f"Lagu {i + 1}/{len(chosen)}", "kind": "info", "route": "#/musik",
                                 "text": (f"✓ {song['title']}" if results[-1]["ok"] else f"✗ {song['title']}: {results[-1]['error']}")[:160]})
        ok = sum(1 for r in results if r["ok"])
        await db.pool().execute("UPDATE music_picks SET status = 'done', updated_at = now() WHERE id = $1", pick_id)
        await hub.broadcast({"type": "notify", "title": "Lagu pilihanmu siap", "kind": "info", "route": "#/musik",
                             "text": f"{ok} dari {len(chosen)} lagu {'jadi MP3' if settings.mp3_converter_url else 'diputar lewat YouTube'} dan masuk playlist."})
        return {"ok": ok, "total": len(chosen)}
    r = await master.run(master.Job("musik", "konversi-pilihan", f"jadikan MP3 {len(chosen)} lagu pilihan", trigger="owner", skill=run))
    if r["status"] != "done":
        await db.pool().execute("UPDATE music_picks SET status = 'done', updated_at = now() WHERE id = $1", pick_id)
        await hub.broadcast({"type": "notify", "title": "Lagu pilihan gagal diproses", "kind": "warn", "route": "#/musik", "text": str(r.get("error"))[:160]})


async def dismiss(pick_id: int) -> bool:
    return (await db.pool().execute("UPDATE music_picks SET status = 'dismissed', updated_at = now() WHERE id = $1 AND status = 'open'", pick_id)).endswith("1")


async def state() -> dict:
    s = await appsettings.get("music")
    now = datetime.now(WIB)
    plays = [dict(r) for r in await db.pool().fetch("SELECT mood, slot, weekday FROM media_log WHERE kind = 'music' AND at > now() - interval '60 days'")]
    mood, why = usual_mood(plays, home.slot_of(now), now.weekday(), list(s["moods"]))
    recent = [dict(r) for r in await db.pool().fetch("SELECT mood, query, title, at FROM media_log WHERE kind = 'music' ORDER BY id DESC LIMIT 10")]
    return {"now": stage.desk_player(), "moods": s["moods"], "usual": {"mood": mood, "why": why, "slot": home.slot_of(now)},
            "recent": recent, "playlists": await playlists.all_(), "converter": bool(settings.mp3_converter_url), "pick": await open_pick()}


@habits.action("music.mood", "Putar musik sesuai mood yang biasa")
async def _habit(h: dict) -> dict:
    st = await state()
    r = await play(st["usual"]["mood"], trigger="habit")
    return {"mood": r["mood"], "playing": r.get("playing")}


@home.provider("music")
async def _home(m: home.Moment) -> list[dict]:
    if stage.desk_player():
        return []   # the player card is already there
    if m.slot not in ("pagi", "kerja", "malam"):
        return []
    st = await state()
    return [{"id": "music", "title": f"Musik {st['usual']['mood']}", "sub": st["usual"]["why"], "route": "#/musik", "icon": "music", "tone": "violet",
             "score": 30 if m.slot == "pagi" else 18, "cta": "Putar"}]


class PlayIn(BaseModel):
    mood: str = Field(default="", max_length=40)
    query: str = Field(default="", max_length=200)


class PlaylistIn(BaseModel):
    name: str | None = Field(default=None, max_length=80)
    index: int = Field(default=0, ge=0, le=500)
    shuffle: bool = False


class ConvertIn(BaseModel):
    url: str = Field(min_length=10, max_length=300)
    save: bool = True


async def convert(url: str, save: bool, who: str = "owner") -> dict:
    """A YouTube / YouTube Music link → MP3 through the owner's converter, played at once and (by default) kept in his playlist."""
    from . import musiclib
    link = musiclib.youtube_link(url)
    if not link:
        raise MusicError("tempel link YouTube atau YouTube Music")
    if not settings.mp3_converter_url:
        raise MusicError("converter MP3 belum dinyalakan di server")

    async def run():
        title, artist = "Lagu dari YouTube", ""
        try:
            async with httpx.AsyncClient(timeout=10) as c:
                o = (await c.get("https://www.youtube.com/oembed", params={"url": link, "format": "json"})).json()
            title, artist = o.get("title") or title, o.get("author_name") or ""
        except Exception:
            pass
        m = await musiclib.convert_link(link, title, artist)
        shown = await media_tools._show_song(m, "converter")
        if save:
            await playlists.add([{"title": title, "artist": artist}], None, "converter", who)
        return {**shown, "media_url": m["url"], "saved": save}
    r = await master.run(master.Job("musik", "konversi", f"jadikan MP3: {link}", skill=run))
    if r["status"] != "done":
        raise MusicError(r.get("error") or "konversi gagal")
    return r["result"]


@router.post(API + "/convert")
async def api_convert(body: ConvertIn, device: dict = Depends(owner)):
    try:
        return await convert(body.url, body.save, "owner")
    except MusicError as e:
        raise HTTPException(409, str(e))


class SaveIn(BaseModel):
    name: str | None = Field(default=None, max_length=80)


@router.get(API)
async def api_state(device: dict = Depends(owner)):
    return await state()


@router.post(API + "/play")
async def api_play(body: PlayIn, device: dict = Depends(owner)):
    """What he asks for becomes a list to tick (owner 2026-10-31); the habits still play by themselves (play())."""
    try:
        s = await appsettings.get("music")
        if body.mood and body.mood not in s["moods"]:
            raise MusicError(f"mood tidak dikenal: {body.mood}")
        return await offer(s["moods"][body.mood] if body.mood else body.query, "owner", body.mood)
    except MusicError as e:
        raise HTTPException(409, str(e))


class ChooseIn(BaseModel):
    choose: list[int] = Field(min_length=1, max_length=10)


@router.post(API + "/picks/{pick_id}")
async def api_choose(pick_id: int, body: ChooseIn, device: dict = Depends(owner)):
    try:
        return await choose(pick_id, body.choose, "owner")
    except MusicError as e:
        raise HTTPException(409, str(e))


@router.post(API + "/playlist")
async def api_playlist(body: PlaylistIn, device: dict = Depends(owner)):
    async def run():
        index = body.index
        if body.shuffle:
            import random
            songs = await playlists.items(body.name)
            index = random.randrange(len(songs)) if songs else 0
        r = await playlists.play(body.name, index)
        if "error" in r:
            raise RuntimeError(r["error"])
        return r
    r = await master.run(master.Job("musik", "playlist", f"putar playlist {body.name or 'utama'}", skill=run))
    if r["status"] != "done":
        raise HTTPException(409, r.get("error") or "playlist tidak bisa diputar")
    return r["result"]


@router.post(API + "/save")
async def api_save(body: SaveIn, device: dict = Depends(owner)):
    """What is playing now → a playlist (his main one unless he names another)."""
    now = stage.desk_player()
    if not now or not now.get("title"):
        raise HTTPException(409, "tidak ada lagu yang sedang diputar")
    async def keep():
        return await playlists.add([{"title": now["title"], "artist": now.get("artist") or ""}], body.name, "simpan", "owner")
    r = await master.run(master.Job("musik", "simpan", f"simpan {now['title']} ke playlist", skill=keep))
    if r["status"] != "done":
        raise HTTPException(409, r.get("error") or "lagu tidak bisa disimpan")
    res = r["result"]
    return {"saved": now["title"], **({"playlist": res.get("playlist")} if isinstance(res, dict) else {})}


@router.post(API + "/{action}")
async def api_control(action: str, device: dict = Depends(owner)):
    if action == "next":
        await playlists.advance(1)
    elif action == "prev":
        await playlists.advance(-1)
    elif action == "stop":
        cur = stage.current()
        if cur and cur.get("panel") in ("music", "audio", "video"):
            await stage.close(cur["id"])
    else:
        raise HTTPException(404)
    return {"ok": True}
