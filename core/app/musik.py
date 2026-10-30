"""Musik (ADR-087, mockup 4): music by mood — fokus, semangat, olahraga, santai, tidur (his own search words per mood in settings) — his
playlists, what is playing, and the mood he usually wants at this time of day, learned from what he played (owner 2026-10-29: "tiap pagi
butuh musik bermode apa sport/semangat"). The morning habit offers that mood.

Playing is a fixed procedure through the master flow (skill: licensed tracks, or the official YouTube player for a named song —
media_tools); the screen and the phone get it as a stage event, and the app's player plays it."""

import logging
from collections import Counter
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from . import appsettings, db, habits, home, master, media_tools, playlists, stage
from .appauth import owner
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


async def state() -> dict:
    s = await appsettings.get("music")
    now = datetime.now(WIB)
    plays = [dict(r) for r in await db.pool().fetch("SELECT mood, slot, weekday FROM media_log WHERE kind = 'music' AND at > now() - interval '60 days'")]
    mood, why = usual_mood(plays, home.slot_of(now), now.weekday(), list(s["moods"]))
    recent = [dict(r) for r in await db.pool().fetch("SELECT mood, query, title, at FROM media_log WHERE kind = 'music' ORDER BY id DESC LIMIT 10")]
    return {"now": stage.desk_player(), "moods": s["moods"], "usual": {"mood": mood, "why": why, "slot": home.slot_of(now)},
            "recent": recent, "playlists": await playlists.all_()}


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


@router.get(API)
async def api_state(device: dict = Depends(owner)):
    return await state()


@router.post(API + "/play")
async def api_play(body: PlayIn, device: dict = Depends(owner)):
    try:
        return await play(body.mood, body.query, "owner")
    except MusicError as e:
        raise HTTPException(409, str(e))


@router.post(API + "/playlist")
async def api_playlist(body: PlaylistIn, device: dict = Depends(owner)):
    async def run():
        r = await playlists.play(body.name, body.index)
        if "error" in r:
            raise RuntimeError(r["error"])
        return r
    r = await master.run(master.Job("musik", "playlist", f"putar playlist {body.name or 'utama'}", skill=run))
    if r["status"] != "done":
        raise HTTPException(409, r.get("error") or "playlist tidak bisa diputar")
    return r["result"]


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
