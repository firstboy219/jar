"""The owner's places (ADR-087): where "rumah" and "kantor" are, and when he arrives at or leaves one.

The phone's location (opt-in in the app, now also sent every few minutes in the background) is kept as a trail for 60 days. From the
trail JARVIS learns the places by itself — where the phone sleeps is rumah, where it spends weekday office hours is kantor — unless the
owner set them. Crossing a place's edge becomes an event ('arrive'/'leave') that the habits and the front page react to.
"""

import math
from datetime import datetime, timedelta

from . import db, hub
from .location import WIB

MIN_GAP_S = 120          # a point closer in time than this to the last one …
MIN_MOVE_M = 40          # … and closer in space is not kept again
KEEP_DAYS = 60
FRESH_S = 1800           # a location older than this says nothing about where the owner is now
CELL = 0.002             # ≈ 220 m: the grid the trail is counted on to find where the phone stays
MIN_POINTS = 6           # a place needs at least this many points in its hours before it is learned


def distance_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in metres."""
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def at_place(lat: float, lon: float, places: list[dict], accuracy_m: float | None = None) -> str | None:
    """The place the point is in (the nearest one whose circle, widened by a bad fix, holds it)."""
    best, best_d = None, None
    for p in places:
        d = distance_m(lat, lon, p["lat"], p["lon"])
        if d <= p["radius_m"] + min(float(accuracy_m or 0), 150.0) and (best_d is None or d < best_d):
            best, best_d = p["name"], d
    return best


def is_night(t: datetime) -> bool:
    return t.hour >= 22 or t.hour < 5


def is_office_hours(t: datetime) -> bool:
    return t.weekday() < 5 and 9 <= t.hour < 16


def densest(points: list[tuple[float, float]]) -> tuple[float, float, int] | None:
    """The centre of the busiest grid cell (and how many points are near it): where the phone stays."""
    if not points:
        return None
    cells: dict[tuple[int, int], list[tuple[float, float]]] = {}
    for lat, lon in points:
        cells.setdefault((round(lat / CELL), round(lon / CELL)), []).append((lat, lon))
    key = max(cells, key=lambda k: len(cells[k]))
    cx, cy = key[0] * CELL, key[1] * CELL
    near = [(a, b) for a, b in points if distance_m(a, b, cx, cy) <= 250]
    lat = sum(a for a, _ in near) / len(near)
    lon = sum(b for _, b in near) / len(near)
    return lat, lon, len(near)


def learn(trail: list[dict]) -> dict[str, tuple[float, float, int]]:
    """rumah from the nights, kantor from weekday office hours (at least 500 m from rumah). Pure; the trail is [{lat, lon, at}]."""
    nights = [(p["lat"], p["lon"]) for p in trail if is_night(p["at"].astimezone(WIB))]
    out: dict[str, tuple[float, float, int]] = {}
    home = densest(nights)
    if home and home[2] >= MIN_POINTS:
        out["rumah"] = home
    office_pts = [(p["lat"], p["lon"]) for p in trail if is_office_hours(p["at"].astimezone(WIB))]
    if "rumah" in out:
        office_pts = [pt for pt in office_pts if distance_m(pt[0], pt[1], out["rumah"][0], out["rumah"][1]) > 500]
    office = densest(office_pts)
    if office and office[2] >= MIN_POINTS:
        out["kantor"] = office
    return out


async def listing() -> list[dict]:
    return [dict(r) for r in await db.pool().fetch("SELECT * FROM places ORDER BY name")]


async def set_place(name: str, lat: float, lon: float, label: str = "", radius_m: int = 200) -> dict:
    """The owner names a place himself; a learned place never overwrites it."""
    name = " ".join((name or "").lower().split())[:40]
    if not name:
        raise ValueError("nama tempat kosong")
    row = await db.pool().fetchrow(
        """INSERT INTO places (name, label, lat, lon, radius_m, source) VALUES ($1, $2, $3, $4, $5, 'owner')
           ON CONFLICT (name) DO UPDATE SET label = EXCLUDED.label, lat = EXCLUDED.lat, lon = EXCLUDED.lon,
             radius_m = EXCLUDED.radius_m, source = 'owner', updated_at = now() RETURNING *""",
        name, label[:200], lat, lon, max(50, min(5000, int(radius_m))))
    return dict(row)


async def remove(name: str) -> bool:
    return (await db.pool().execute("DELETE FROM places WHERE name = $1", name)).endswith("1")


async def relearn() -> dict:
    """Nightly: learn rumah/kantor again from the last 30 days (owner-set places stay as they are)."""
    rows = await db.pool().fetch("SELECT lat, lon, at FROM location_history WHERE at > now() - interval '30 days'")
    found = learn([dict(r) for r in rows])
    for name, (lat, lon, n) in found.items():
        await db.pool().execute(
            """INSERT INTO places (name, lat, lon, source) VALUES ($1, $2, $3, 'learned')
               ON CONFLICT (name) DO UPDATE SET lat = EXCLUDED.lat, lon = EXCLUDED.lon, updated_at = now()
               WHERE places.source = 'learned'""", name, lat, lon)
    await db.pool().execute("DELETE FROM location_history WHERE at < now() - make_interval(days => $1)", KEEP_DAYS)
    return {k: v[2] for k, v in found.items()}


async def observe(lat: float, lon: float, accuracy_m: float | None = None) -> str | None:
    """One location from the phone: kept on the trail, and an arrival/departure when it crosses a place's edge. Returns the place it is in."""
    last = await db.pool().fetchrow("SELECT lat, lon, at FROM location_history ORDER BY at DESC LIMIT 1")
    now = datetime.now(WIB)
    if not last or (now - last["at"]).total_seconds() >= MIN_GAP_S or distance_m(lat, lon, last["lat"], last["lon"]) >= MIN_MOVE_M:
        await db.pool().execute("INSERT INTO location_history (lat, lon, accuracy_m) VALUES ($1, $2, $3)", lat, lon, accuracy_m)
    if accuracy_m is not None and accuracy_m > 500:   # too rough to tell which side of a place's edge the owner is
        return None
    here = at_place(lat, lon, await listing(), accuracy_m)
    before = await db.pool().fetchval("SELECT value FROM settings_kv WHERE key = 'place_state'")
    before_place = (before or {}).get("place")
    if here != before_place:
        if before_place:
            await _event(before_place, "leave")
        if here:
            await _event(here, "arrive")
        await db.pool().execute(
            """INSERT INTO settings_kv (key, value) VALUES ('place_state', $1)
               ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value""", {"place": here, "since": now.isoformat()})
    return here


async def _event(place: str, kind: str) -> None:
    await db.pool().execute("INSERT INTO place_events (place, kind) VALUES ($1, $2)", place, kind)
    await hub.broadcast({"type": "place", "place": place, "kind": kind})


async def current() -> dict:
    """Where the owner is now: {'place': 'kantor'|None, 'since': iso, 'fresh': bool}."""
    state = await db.pool().fetchval("SELECT value FROM settings_kv WHERE key = 'place_state'") or {}
    last = await db.pool().fetchval("SELECT at FROM location_history ORDER BY at DESC LIMIT 1")
    fresh = bool(last and (datetime.now(WIB) - last).total_seconds() < FRESH_S)
    return {"place": state.get("place") if fresh else None, "since": state.get("since"), "fresh": fresh}


async def last_event(place: str, kind: str, within: timedelta) -> datetime | None:
    return await db.pool().fetchval(
        "SELECT at FROM place_events WHERE place = $1 AND kind = $2 AND at > now() - $3::interval ORDER BY at DESC LIMIT 1",
        place, kind, within)
