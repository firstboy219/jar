"""KRL Commuterline schedules (ADR-087), from the open Comuline API (api.comuline.com): stations, and every train leaving a station with
its train number. A trip from A to B is a train that leaves A and later stops at B (the same train number in both schedules); when no
train runs through, one change at a hub (Manggarai, Duri, Tanah Abang, Kampung Bandan, Jatinegara) with a few minutes to cross the
platform. Schedules are cached for the day. Times in the API are UTC; here they are WIB."""

import time
from datetime import datetime, timedelta

import httpx

API = "https://api.comuline.com/v1"
HUBS = ["MRI", "THB", "DU", "KPB", "JNG"]
CHANGE_MIN = 5          # minutes to change trains at a hub
TTL_S = 6 * 3600
_cache: dict[str, tuple[float, object]] = {}


class KrlError(RuntimeError):
    pass


def _client() -> httpx.AsyncClient:  # seam for tests
    return httpx.AsyncClient(timeout=20, headers={"User-Agent": "JARVIS/1.0"})


def wib_minutes(ts: str) -> int:
    """'2024-11-12 17:19:00.277+00' (UTC) → minutes after midnight WIB. Pure."""
    h, m = int(ts[11:13]), int(ts[14:16])
    return (h * 60 + m + 7 * 60) % 1440


def hhmm(mins: int) -> str:
    mins %= 1440
    return f"{mins // 60:02d}:{mins % 60:02d}"


async def _get(path: str):
    hit = _cache.get(path)
    if hit and time.monotonic() - hit[0] < TTL_S:
        return hit[1]
    async with _client() as c:
        r = await c.get(f"{API}{path}")
        if r.status_code != 200:
            raise KrlError(f"jadwal KRL tidak bisa diambil (HTTP {r.status_code})")
        data = r.json().get("data") or []
    _cache[path] = (time.monotonic(), data)
    return data


async def stations() -> list[dict]:
    return [{"id": s["id"], "name": s["name"].title()} for s in await _get("/station") if s.get("type") == "KRL"]


def find_station(name: str, all_: list[dict]) -> dict | None:
    """The station a name means ('bogor', 'Sudirman', 'manggarai'), exact before partial. Pure."""
    n = " ".join((name or "").lower().split())
    if not n:
        return None
    for s in all_:
        if s["id"].lower() == n or s["name"].lower() == n:
            return s
    hits = [s for s in all_ if n in s["name"].lower()]
    return min(hits, key=lambda s: len(s["name"])) if hits else None


async def departures(station_id: str) -> list[dict]:
    """Every train leaving a station today: {train, dep (min WIB), dest, route, line, color}."""
    out = []
    for x in await _get(f"/schedule/{station_id}"):
        out.append({"train": x["train_id"], "dep": wib_minutes(x["departs_at"]), "dest": x["station_destination_id"], "route": x["route"],
                    "end": wib_minutes(x["arrives_at"]) if x.get("arrives_at") else None,
                    "line": x.get("line", ""), "color": ((x.get("metadata") or {}).get("origin") or {}).get("color", "")})
    return out


def direct(dep_a: list[dict], dep_b: list[dict], after: int, before: int | None = None, b_id: str | None = None) -> list[dict]:
    """Trains leaving A at or after `after` that later stop at B (same train number), sorted by departure. Pure.
    A train's time at B is its departure there (a stop) — or, when B is where the train ends (a terminus has no departure for it), its
    arrival at the end. Trains crossing midnight are skipped."""
    at_b = {}
    for x in dep_b:
        at_b.setdefault(x["train"], x["dep"])
    out = []
    for x in dep_a:
        tb = at_b.get(x["train"])
        if tb is None and b_id and x.get("dest") == b_id:
            tb = x.get("end")
        if tb is None or x["dep"] < after or tb <= x["dep"] or tb - x["dep"] > 240:
            continue
        if before is not None and x["dep"] > before:
            continue
        out.append({"train": x["train"], "dep": x["dep"], "arr": tb, "line": x["line"], "route": x["route"], "color": x["color"], "legs": 1})
    return sorted(out, key=lambda o: (o["dep"], o["arr"]))


def with_change(dep_a: list[dict], dep_hub: list[dict], dep_b: list[dict], hub: str, after: int, b_id: str | None = None) -> list[dict]:
    """A → hub on one train, hub → B on the next one leaving at least CHANGE_MIN later. Pure."""
    first = direct(dep_a, dep_hub, after, b_id=hub)
    out = []
    for f in first[:12]:
        second = direct(dep_hub, dep_b, f["arr"] + CHANGE_MIN, b_id=b_id)
        if second:
            s = second[0]
            out.append({"train": f"{f['train']} → {s['train']}", "dep": f["dep"], "arr": s["arr"], "line": f["line"], "route": f"{f['route']} · ganti di {hub}",
                        "color": f["color"], "legs": 2, "change": {"hub": hub, "arr": f["arr"], "dep": s["dep"], "train2": s["train"], "line2": s["line"]}})
    return out


async def trips(from_id: str, to_id: str, after: int, limit: int = 6) -> list[dict]:
    """The next trains (direct first, else with one change) from A to B leaving at or after `after` minutes WIB."""
    a, b = await departures(from_id), await departures(to_id)
    found = direct(a, b, after, b_id=to_id)
    if len(found) < limit:
        for hub in HUBS:
            if hub in (from_id, to_id):
                continue
            try:
                found += with_change(a, await departures(hub), b, hub, after, b_id=to_id)
            except KrlError:
                continue
            if len(found) >= limit * 2:
                break
    uniq, seen = [], set()
    for t in sorted(found, key=lambda o: (o["arr"], o["dep"])):
        if t["dep"] in seen:
            continue
        seen.add(t["dep"])
        uniq.append(t)
    return sorted(uniq, key=lambda o: o["dep"])[:limit]


def now_minutes(now: datetime | None = None) -> int:
    from .location import WIB
    t = (now or datetime.now(WIB)).astimezone(WIB)
    return t.hour * 60 + t.minute


def minutes_to_time(day: datetime, mins: int) -> datetime:
    return day.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(minutes=mins)
