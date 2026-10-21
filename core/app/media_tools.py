"""Shared by the main agent and Hermes' MCP tools: put music, a video or a route map on the phone's screen.

Music: openly-licensed tracks (Openverse/Jamendo) are downloaded and played — but only when they really are
what was asked (a genre/mood, or a title/artist match). A named commercial song is played in the official
YouTube player on the phone instead (visible, embedded — no downloading), so "putar lagu Peterpan" plays
Peterpan, not a stranger's cover.
"""

import asyncio
import re

from . import maps, musiclib, stage
from .location import Location, last


_MOOD_WORDS = set("""musik lagu lagunya yang buat untuk saat waktu sambil jazz lofi santai instrumental klasik classical piano
gitar akustik acoustic relaksasi relax tidur sleep fokus focus belajar semangat ambient meditasi hujan cafe kafe chill
orkestra epic sedih senang romantis pagi malam olahraga workout tenang kerja""".split())


def wants_specific_song(query: str) -> bool:
    """'peterpan', 'idgitaf sedia aku sebelum hujan' → a particular song; 'jazz santai buat tidur' → any fitting
    music (every word describes a mood or genre). Pure."""
    words = [w for w in re.findall(r"[\w-]+", query.lower()) if len(w) >= 3]
    return not words or not all(w in _MOOD_WORDS for w in words)


def matches(track: dict, query: str) -> bool:
    """A licensed track is only played for a specific request when it is that song/artist. Pure."""
    have = f"{track.get('title', '')} {track.get('artist', '')}".lower()
    words = [w for w in re.findall(r"\w+", query.lower()) if len(w) >= 3]
    return bool(words) and sum(w in have for w in words) >= max(1, (len(words) + 1) // 2)


def youtube_search(query: str, limit: int = 5) -> list[dict]:
    import yt_dlp
    with yt_dlp.YoutubeDL({"quiet": True, "extract_flat": True, "skip_download": True, "noplaylist": True}) as y:
        info = y.extract_info(f"ytsearch{limit}:{query}", download=False)
    return [{"url": e["url"], "title": e.get("title") or "", "channel": e.get("channel") or e.get("uploader") or "",
             "duration_s": e.get("duration")} for e in info.get("entries", []) if e.get("url")]


async def video(query: str, music: bool = False) -> dict:
    """Find a YouTube video and show it in the official player on the phone."""
    if not query.strip():
        return {"error": "video apa?"}
    try:
        found = await asyncio.wait_for(asyncio.to_thread(youtube_search, query + (" official" if music else ""), 5), 25)
    except Exception as e:
        return {"error": f"pencarian video gagal ({type(e).__name__})"}
    found = [v for v in found if str(v["url"]).startswith("https://") and (v.get("duration_s") or 1) < 4 * 3600]
    if not found:
        return {"error": "videonya tidak ketemu"}
    v = found[0]
    shown = await stage.show("video", {"url": v["url"], "title": v["title"], "channel": v["channel"]},
                             f"{'Memutar' if music else 'Video'}: {v['title']}"[:200], "jarvis")
    return {"playing": v["title"], "artist": v["channel"], "source": "YouTube", "stage_id": shown["id"]}


_FILLER = re.compile(r"\b(tapi|tetapi|pakai|pake|aja|saja|yang|versi|nya|dong|ya|tolong|lewat|di hp)\b", re.IGNORECASE)


def song_query(query: str) -> tuple[str, bool]:
    """'bunga citra lestari tapi pakai cover aja' → ('bunga citra lestari cover', True). Pure."""
    cover = bool(re.search(r"\bcover\b", query, re.IGNORECASE))
    words = " ".join(_FILLER.sub(" ", re.sub(r"\bcover(nya)?\b", " ", query, flags=re.IGNORECASE)).split())
    return (f"{words} cover" if cover else words) or query, cover


async def play(query: str) -> dict:
    if not query.strip():
        return {"error": "lagu apa?"}
    query, cover = song_query(query)
    specific = wants_specific_song(query)
    try:
        tracks = await musiclib.search(query, limit=5)
    except Exception as e:
        tracks, failure = [], f"pencarian musik gagal ({type(e).__name__})"
    else:
        failure = "tidak ada lagu berlisensi bebas yang cocok"
    if specific:  # a named song: only the real one, else the official video
        tracks = [t for t in tracks if matches(t, query)]
        if not tracks:
            yt = await video(query, music=not cover)  # a cover is by definition not the "official" one
            return yt if "error" not in yt else {"error": f"{failure}; {yt['error']}"}
    for t in tracks:
        try:
            m = await musiclib.download(t)
        except Exception:
            continue
        shown = await stage.show("music", {"title": m["title"], "artist": m["artist"], "url": m["url"],
                                           "cover_url": m.get("cover_url"), "license": m["license"],
                                           "source_url": m["source_url"], "duration_s": m["duration_s"],
                                           "queue": [{"title": x["title"], "artist": x["artist"]} for x in tracks if x is not t][:4]},
                                 f"Memutar {m['title']} — {m['artist']}", "jarvis")
        return {"playing": m["title"], "artist": m["artist"], "license": m["license"], "stage_id": shown["id"],
                "note": "musik berlisensi bebas (Openverse/Jamendo); lagu komersial hanya bisa lewat pemutar YouTube resmi"}
    if not tracks:
        return {"error": failure}
    return {"error": "lagu yang ditemukan gagal diunduh"}


async def route(destination: str, origin: str = "", mode: str = "driving", here: Location | None = None) -> dict:
    try:
        dest = await maps.geocode(destination)
        if origin.strip():
            start = await maps.geocode(origin)
        else:
            saved = None if here else await last()
            loc = here or (Location(**saved) if saved else None)
            if not loc:
                return {"error": "lokasi pemilik belum diketahui — sebutkan titik awalnya"}
            start = {"lat": loc.lat, "lon": loc.lon, "label": "Lokasimu"}
        payload = await maps.stage_payload(start, dest, mode if mode in ("driving", "motor", "walking") else "driving")
    except maps.MapsError as e:
        return {"error": str(e)}
    shown = await stage.show("map", payload, payload["title"], "jarvis")
    return {"stage_id": shown["id"], "routes": [r["label"] for r in payload["routes"]], "source": payload["source"],
            "traffic_note": payload["traffic_note"]}
