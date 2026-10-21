"""Places and routes for the phone's map panel ("berapa jauh ke …", "lewat mana yang lebih cepat").

Geocoding: Nominatim (OpenStreetMap; 1 request/s, identified User-Agent).
Routes (with alternatives):
  TomTom   when TOMTOM_API_KEY is set — times include live traffic (free 2,500 requests/day)
  ORS      when ORS_API_KEY is set — up to 3 alternatives ≤ 100 km (free 2,000/day, non-commercial)
  OSRM     public demo otherwise — light use only, no traffic
Without traffic data the panel says so, so a 28-minute estimate is not mistaken for rush-hour reality.
"""

import os

import httpx

UA = {"User-Agent": "JARVIS-personal-assistant/1.0 (vis1.cosger.online)"}
MAX_POINTS = 300


class MapsError(RuntimeError):
    pass


async def geocode(query: str) -> dict:
    async with httpx.AsyncClient(timeout=15, headers=UA) as c:
        r = await c.get("https://nominatim.openstreetmap.org/search",
                        params={"q": query, "format": "jsonv2", "limit": 1, "countrycodes": "id", "accept-language": "id"})
    hits = r.json() if r.status_code == 200 else []
    if not hits:
        raise MapsError(f"tempat '{query}' tidak ditemukan")
    h = hits[0]
    return {"lat": float(h["lat"]), "lon": float(h["lon"]), "label": h.get("display_name", query).split(",")[0],
            "address": h.get("display_name", "")}


def thin(points: list[list[float]], limit: int = MAX_POINTS) -> list[list[float]]:
    """Keep the shape, drop points the phone does not need. Pure; unit-tested."""
    if len(points) <= limit:
        return [[round(p[0], 5), round(p[1], 5)] for p in points]
    step = (len(points) - 1) / (limit - 1)
    return [[round(points[round(i * step)][0], 5), round(points[round(i * step)][1], 5)] for i in range(limit)]


async def _tomtom(a: dict, b: dict, mode: str, key: str) -> list[dict]:
    travel = {"driving": "car", "motor": "motorcycle", "walking": "pedestrian"}.get(mode, "car")
    url = f"https://api.tomtom.com/routing/1/calculateRoute/{a['lat']},{a['lon']}:{b['lat']},{b['lon']}/json"
    async with httpx.AsyncClient(timeout=20) as c:
        r = await c.get(url, params={"key": key, "maxAlternatives": 2, "traffic": "true", "travelMode": travel,
                                     "routeRepresentation": "polyline"})
    if r.status_code != 200:
        raise MapsError(f"TomTom HTTP {r.status_code}")
    out = []
    for rt in r.json().get("routes", []):
        s = rt["summary"]
        pts = [[p["latitude"], p["longitude"]] for leg in rt["legs"] for p in leg["points"]]
        out.append({"distance_km": round(s["lengthInMeters"] / 1000, 1), "duration_min": round(s["travelTimeInSeconds"] / 60),
                    "delay_min": round(s.get("trafficDelayInSeconds", 0) / 60), "traffic": True, "polyline": thin(pts)})
    return out


async def _ors(a: dict, b: dict, mode: str, key: str) -> list[dict]:
    profile = {"walking": "foot-walking", "cycling": "cycling-regular"}.get(mode, "driving-car")
    async with httpx.AsyncClient(timeout=20) as c:
        r = await c.post(f"https://api.openrouteservice.org/v2/directions/{profile}/geojson",
                         headers={"Authorization": key},
                         json={"coordinates": [[a["lon"], a["lat"]], [b["lon"], b["lat"]]],
                               "alternative_routes": {"target_count": 3, "share_factor": 0.6, "weight_factor": 1.6}})
    if r.status_code != 200:
        raise MapsError(f"ORS HTTP {r.status_code}")
    out = []
    for f in r.json().get("features", []):
        s = f["properties"]["summary"]
        out.append({"distance_km": round(s["distance"] / 1000, 1), "duration_min": round(s["duration"] / 60), "traffic": False,
                    "polyline": thin([[p[1], p[0]] for p in f["geometry"]["coordinates"]])})
    return out


async def _osrm(a: dict, b: dict, mode: str) -> list[dict]:
    profile = {"walking": "foot", "cycling": "bike"}.get(mode, "driving")
    async with httpx.AsyncClient(timeout=20, headers=UA) as c:
        r = await c.get(f"https://router.project-osrm.org/route/v1/{profile}/{a['lon']},{a['lat']};{b['lon']},{b['lat']}",
                        params={"alternatives": "true", "overview": "full", "geometries": "geojson"})
    if r.status_code != 200 or r.json().get("code") != "Ok":
        raise MapsError(f"OSRM HTTP {r.status_code}")
    return [{"distance_km": round(rt["distance"] / 1000, 1), "duration_min": round(rt["duration"] / 60), "traffic": False,
             "polyline": thin([[p[1], p[0]] for p in rt["geometry"]["coordinates"]])} for rt in r.json()["routes"]]


async def routes(a: dict, b: dict, mode: str = "driving") -> tuple[list[dict], str]:
    tomtom, ors = os.getenv("TOMTOM_API_KEY", ""), os.getenv("ORS_API_KEY", "")
    sources = ([("TomTom", lambda: _tomtom(a, b, mode, tomtom))] if tomtom else []) + \
              ([("OpenRouteService", lambda: _ors(a, b, mode, ors))] if ors else []) + [("OSRM", lambda: _osrm(a, b, mode))]
    errors = []
    for name, fn in sources:
        try:
            found = await fn()
            if found:
                return found, name
        except (httpx.HTTPError, MapsError, KeyError, ValueError) as e:
            errors.append(f"{name}: {e}")
    raise MapsError("rute tidak bisa dihitung: " + "; ".join(errors))


async def stage_payload(origin: dict, dest: dict, mode: str = "driving") -> dict:
    found, source = await routes(origin, dest, mode)
    for i, r in enumerate(found):
        traffic = f", macet +{r['delay_min']} mnt" if r.get("delay_min") else ""
        r["label"] = f"Rute {i + 1} · {r['distance_km']} km · {r['duration_min']} mnt{traffic}"
    return {"title": f"{origin['label']} → {dest['label']}", "mode": mode, "source": source,
            "traffic_note": "" if any(r.get("traffic") for r in found) else "Perkiraan tanpa data kemacetan",
            "markers": [{"lat": origin["lat"], "lon": origin["lon"], "label": origin["label"]},
                        {"lat": dest["lat"], "lon": dest["lon"], "label": dest["label"]}],
            "routes": found, "selected": 0}
