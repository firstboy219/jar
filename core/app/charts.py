"""Music charts without a key (ADR-034).

"Top 10 R&B" = the most-streamed R&B songs on Deezer right now (its genre charts follow current hits; the iTunes
Store's genre sales chart was full of decades-old classics — "September", "Unchained Melody" — when measured).
"Lagu Indonesia" uses the Indonesian iTunes Store (Deezer has no country choice from this server), and iTunes is
the fallback when Deezer fails. The source is always named to the owner.
"""

import re

import httpx

GENRES = {  # words the owner uses → (iTunes genre id, display name)
    "rnb": (15, "R&B/Soul"), "r&b": (15, "R&B/Soul"), "r n b": (15, "R&B/Soul"), "soul": (15, "R&B/Soul"),
    "pop": (14, "Pop"), "hip hop": (18, "Hip-Hop/Rap"), "hiphop": (18, "Hip-Hop/Rap"), "rap": (18, "Hip-Hop/Rap"),
    "rock": (21, "Rock"), "dance": (17, "Dance"), "edm": (7, "Electronic"), "elektronik": (7, "Electronic"),
    "jazz": (11, "Jazz"), "alternative": (20, "Alternative"), "alternatif": (20, "Alternative"), "indie": (20, "Alternative"),
    "country": (6, "Country"), "kpop": (51, "K-Pop"), "k-pop": (51, "K-Pop"), "k pop": (51, "K-Pop"),
    "reggae": (24, "Reggae"), "blues": (2, "Blues"), "latin": (12, "Latin"), "klasik": (5, "Classical"),
    "classical": (5, "Classical"), "metal": (1153, "Metal"),
}
LOCAL = ("indonesia", "lokal", "indo")
DEEZER = {15: 165, 14: 132, 18: 116, 21: 152, 17: 113, 7: 106, 11: 129, 20: 85, 24: 144, 2: 153, 12: 197, 5: 98,
          1153: 464, 51: 16, None: 0}  # iTunes genre id → Deezer genre id (K-Pop → "Asian Music")


class ChartError(ValueError):
    pass


def resolve(text: str) -> tuple[int | None, str, str]:
    """'lagu RnB top 10' → (15, 'R&B/Soul', 'us'); 'lagu indonesia' → (None, 'semua genre', 'id'). Pure; unit-tested."""
    t = " " + re.sub(r"[^a-z0-9& -]", " ", text.lower()) + " "
    country = "id" if any(f" {w} " in t for w in LOCAL) else "us"
    for word in sorted(GENRES, key=len, reverse=True):
        if f" {word} " in t:
            gid, name = GENRES[word]
            return gid, name, country
    return None, "semua genre", country


async def _deezer(gid: int | None, name: str, limit: int) -> dict:
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.get(f"https://api.deezer.com/chart/{DEEZER.get(gid, 0)}/tracks", params={"limit": limit})
    data = r.json().get("data") if r.status_code == 200 else None
    if not data:
        raise ChartError(f"Deezer tidak menjawab (HTTP {r.status_code})")
    songs = [{"title": t.get("title_short") or t.get("title", ""), "artist": (t.get("artist") or {}).get("name", "")}
             for t in data][:limit]
    return {"genre": name, "country": "global", "source": f"Deezer top {name} (paling banyak diputar)", "songs": songs}


async def _itunes(gid: int | None, name: str, country: str, limit: int) -> dict:
    url = f"https://itunes.apple.com/{country}/rss/topsongs/limit={limit}" + (f"/genre={gid}" if gid else "") + "/json"
    async with httpx.AsyncClient(timeout=15, follow_redirects=True) as c:
        r = await c.get(url)
    if r.status_code != 200:
        raise ChartError(f"tangga lagu tidak bisa diambil (HTTP {r.status_code})")
    entries = (r.json().get("feed") or {}).get("entry") or []
    if isinstance(entries, dict):
        entries = [entries]
    songs = [{"title": e.get("im:name", {}).get("label", ""), "artist": e.get("im:artist", {}).get("label", "")}
             for e in entries]
    place = "Indonesia" if country == "id" else "AS"
    return {"genre": name, "country": country, "source": f"iTunes Store top {name} ({place})", "songs": songs[:limit]}


async def top(text: str, limit: int = 10) -> dict:
    gid, name, country = resolve(text)
    limit = max(1, min(int(limit or 10), 50))
    attempts = [lambda: _itunes(gid, name, country, limit)] if country == "id" else \
        [lambda: _deezer(gid, name, limit), lambda: _itunes(gid, name, country, limit)]
    errors = []
    for attempt in attempts:
        try:
            chart = await attempt()
            chart["songs"] = [s for s in chart["songs"] if s["title"]]
            if chart["songs"]:
                return chart
        except (ChartError, httpx.HTTPError, ValueError) as e:
            errors.append(str(e))
    raise ChartError("; ".join(errors) or "tangga lagu kosong")
