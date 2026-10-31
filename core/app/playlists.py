"""The owner's playlists (ADR-034). Songs are stored as title + artist; when a song's turn comes it is fetched
the usual way (licensed track → MP3 from SoundCloud/converter → official YouTube player), so a playlist never
holds stale links. Playback goes in order: the phone reports "ended"/"next"/"prev" on the music or video panel
and the next song is put on the screen.
"""

import asyncio
import logging

from . import audit, db

log = logging.getLogger("jarvis-core.playlists")
DEFAULT = "Playlist saya"
_playing: dict = {"playlist_id": None, "index": 0, "name": ""}


class PlaylistError(ValueError):
    pass


def _name(name: str | None) -> str:
    return (name or "").strip()[:80] or DEFAULT


async def _get_or_create(name: str) -> int:
    pid = await db.pool().fetchval("SELECT id FROM playlists WHERE lower(name) = lower($1)", name)
    if pid:
        return pid
    return await db.pool().fetchval(
        "INSERT INTO playlists (name) VALUES ($1) ON CONFLICT (name) DO UPDATE SET name = EXCLUDED.name RETURNING id", name)


async def add(songs: list[dict], name: str | None = None, source: str = "permintaan", actor: str = "jarvis") -> dict:
    """Append songs ({title, artist}); duplicates are skipped. Returns {playlist, added, skipped, total}."""
    name = _name(name)
    pid = await _get_or_create(name)
    pos = await db.pool().fetchval("SELECT coalesce(max(position), 0) FROM playlist_items WHERE playlist_id = $1", pid)
    added, skipped = [], 0
    for s in songs[:100]:
        title, artist = str(s.get("title") or "").strip()[:200], str(s.get("artist") or "").strip()[:200]
        if not title:
            continue
        row = await db.pool().fetchrow(
            """INSERT INTO playlist_items (playlist_id, position, title, artist, source) VALUES ($1, $2, $3, $4, $5)
               ON CONFLICT (playlist_id, title, artist) DO NOTHING RETURNING id""", pid, pos + 1, title, artist, source[:120])
        if row:
            pos += 1
            added.append({"title": title, "artist": artist})
        else:
            skipped += 1
    await audit.record(actor, "playlist.added", f"playlist:{pid}", count=len(added))
    total = await db.pool().fetchval("SELECT count(*) FROM playlist_items WHERE playlist_id = $1", pid)
    return {"playlist": name, "added": added, "skipped": skipped, "total": total}


async def items(name: str | None = None) -> list[dict]:
    rows = await db.pool().fetch(
        """SELECT i.id, i.title, i.artist, i.source, i.position FROM playlist_items i JOIN playlists p ON p.id = i.playlist_id
           WHERE lower(p.name) = lower($1) ORDER BY i.position, i.id""", _name(name))
    return [dict(r) for r in rows]


async def all_() -> list[dict]:
    rows = await db.pool().fetch(
        """SELECT p.id, p.name, p.created_at, count(i.id) AS songs FROM playlists p LEFT JOIN playlist_items i ON i.playlist_id = p.id
           GROUP BY p.id ORDER BY p.created_at""")
    return [dict(r) for r in rows]


async def remove(item_id: int, actor: str) -> bool:
    r = await db.pool().execute("DELETE FROM playlist_items WHERE id = $1", item_id)
    await audit.record(actor, "playlist.removed", f"playlist_item:{item_id}")
    return r.endswith("1")


async def clear(name: str | None, actor: str) -> int:
    r = await db.pool().execute(
        "DELETE FROM playlist_items WHERE playlist_id = (SELECT id FROM playlists WHERE lower(name) = lower($1))", _name(name))
    await audit.record(actor, "playlist.cleared", None, playlist=_name(name))
    return int(r.split()[-1])


async def play(name: str | None = None, index: int = 0) -> dict:
    """Put song number `index` of the playlist on the phone (the next ones follow when it ends)."""
    from . import media_tools
    songs = await items(name)
    if not songs:
        raise PlaylistError(f"{_name(name)} masih kosong")
    index = max(0, min(index, len(songs) - 1))
    _playing.update(playlist_id=_name(name), index=index, name=_name(name))
    song = songs[index]
    from . import musiclibrary
    musiclibrary._queue.update(ids=[], i=0)   # one queue at a time
    local = await musiclibrary.local_for(song["title"], song["artist"])
    if local:   # already in his collection: the downloaded file, no search
        shown = await media_tools._show_song({**local, "playlist": {"name": _name(name), "index": index, "total": len(songs)}}, "koleksi")
        return {**shown, "playlist": _name(name), "index": index, "total": len(songs), "song": song}
    query = f"{song['artist']} {song['title']}".strip()
    r = await media_tools.play(query, playlist={"name": _name(name), "index": index, "total": len(songs),
                                                "next": [f"{s['title']} — {s['artist']}" for s in songs[index + 1:index + 5]]})
    return {**r, "playlist": _name(name), "index": index, "total": len(songs), "song": song}


async def advance(step: int) -> None:
    """The phone said the song ended (or the owner tapped next/previous)."""
    if not _playing["playlist_id"]:
        return
    songs = await items(_playing["name"])
    nxt = _playing["index"] + step
    if not 0 <= nxt < len(songs):
        _playing.update(playlist_id=None)
        return
    try:
        r = await play(_playing["name"], nxt)
        if "error" in r:  # this one could not be found: skip it
            await advance(1 if step >= 0 else -1)
    except Exception:
        log.exception("playlist advance failed")


def on_stage_event(event: str) -> None:
    if event in ("ended", "next"):
        asyncio.create_task(advance(1))
    elif event == "prev":
        asyncio.create_task(advance(-1))
