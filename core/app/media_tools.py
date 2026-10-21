"""Shared by the main agent and Hermes' MCP tools: put music or a route map on the phone's screen."""

from . import maps, musiclib, stage
from .location import Location, last


async def play(query: str) -> dict:
    if not query.strip():
        return {"error": "lagu apa?"}
    try:
        tracks = await musiclib.search(query, limit=5)
    except Exception as e:
        return {"error": f"pencarian musik gagal ({type(e).__name__})"}
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
    return {"error": "tidak ada lagu berlisensi bebas yang cocok — untuk lagu komersial, minta tampilkan video YouTube-nya"}


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
