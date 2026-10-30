"""Perjalanan (ADR-087): the trip to work and back, door to door — GoRide to the station, KRL (with the change at Manggarai when needed),
the walk — as options with times and costs; the one the owner takes becomes a live trip: reminders before each leg, the GoRide ordered on
his phone at the right moment (to the station when he leaves; from the station while the train is still two stops away), and a new plan
when his phone shows he is not where the plan says (a missed or late train). Everything runs through the master flow: planning and
watching are fixed procedures (no AI), the ride is a phone job (a learned routine replays it without AI).

Needs: the owner's places (rumah, kantor — learned from the phone or set) and his two stations (Berangkat screen)."""

import logging
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from . import appclock, appsettings, db, habits, home, hub, krl, master, setup_status
from .appauth import owner
from .location import WIB

log = logging.getLogger("jarvis-core")
router = APIRouter()
API = "/api/v1/app/commute"
WAIT_MIN = 5            # at the station before the train
PICKUP_LEAD_MIN = 8     # the ride home is ordered this long before the train arrives
MISSED_RADIUS_M = 500   # still this close to the origin station well after the train left → the plan changes
RIDE_BASE, RIDE_PER_KM, CAR_BASE, CAR_PER_KM = 10000, 2500, 15000, 4000


# ---------- pure ----------

def ride_cost(km: float, car: bool = False) -> int:
    base, per = (CAR_BASE, CAR_PER_KM) if car else (RIDE_BASE, RIDE_PER_KM)
    return int(round((base + per * max(0.0, km - 2)) / 500) * 500)


def options_out(trains: list[dict], ride_min: int, walk_min: int, arrive_by: int, ride_km: float, ride_to_station: bool) -> list[dict]:
    """Trip options to work from the next trains: when to leave, when he arrives, what it costs. Pure."""
    out = []
    for t in trains:
        leave = t["dep"] - WAIT_MIN - (ride_min if ride_to_station else 10)
        arrive = t["arr"] + walk_min
        out.append({"kind": "krl", "train": t["train"], "dep": krl.hhmm(t["dep"]), "arr": krl.hhmm(t["arr"]), "leave": krl.hhmm(leave),
                    "arrive": krl.hhmm(arrive), "late": arrive > arrive_by, "legs": t["legs"], "route": t["route"], "change": t.get("change"),
                    "ride": {"to": "stasiun", "min": ride_min, "cost": ride_cost(ride_km)} if ride_to_station else None,
                    "cost": (ride_cost(ride_km) if ride_to_station else 0) + 5000,
                    "minutes": arrive - leave})
    return out


def options_back(trains: list[dict], walk_min: int, ride_min: int, ride_km: float, ride_from_station: bool) -> list[dict]:
    out = []
    for t in trains:
        leave = t["dep"] - WAIT_MIN - walk_min
        home_at = t["arr"] + (ride_min + 3 if ride_from_station else 15)
        out.append({"kind": "krl", "train": t["train"], "dep": krl.hhmm(t["dep"]), "arr": krl.hhmm(t["arr"]), "leave": krl.hhmm(leave),
                    "arrive": krl.hhmm(home_at), "legs": t["legs"], "route": t["route"], "change": t.get("change"),
                    "ride": {"from": "stasiun", "min": ride_min, "cost": ride_cost(ride_km), "order_at": krl.hhmm(t["arr"] - PICKUP_LEAD_MIN)} if ride_from_station else None,
                    "cost": (ride_cost(ride_km) if ride_from_station else 0) + 5000, "minutes": home_at - leave})
    return out


def hhmm_to(s: str) -> int:
    return int(s[:2]) * 60 + int(s[3:5])


def after_ref(s: str, ref: int) -> int:
    """'00:10' read after a reference minute (with 23:40 as the reference → 1450), so a trip across midnight keeps its order. Pure."""
    v = hhmm_to(s)
    return v + 1440 if v < ref - 720 else v


def pick_usual(options: list[dict], usual: list[str]) -> int:
    """The option the owner usually takes (the departure time he chose most), else the first that arrives on time. Pure."""
    for u in usual:
        for i, o in enumerate(options):
            if abs(hhmm_to(o["dep"]) - hhmm_to(u)) <= 6:
                return i
    return next((i for i, o in enumerate(options) if not o.get("late")), 0)


# ---------- the world ----------

async def _stations() -> tuple[dict | None, dict | None, dict]:
    s = await appsettings.get("commute")
    all_ = await krl.stations()
    return krl.find_station(s["home_station"], all_), krl.find_station(s["office_station"], all_), s


async def _station_pos(name: str) -> dict | None:
    cache = await db.pool().fetchval("SELECT value FROM settings_kv WHERE key = 'commute:stationpos'") or {}
    if name in cache:
        return cache[name]
    from . import maps
    try:
        g = await maps.geocode(f"Stasiun {name}")
    except Exception:
        return None
    cache[name] = {"lat": g["lat"], "lon": g["lon"]}
    await db.pool().execute("""INSERT INTO settings_kv (key, value) VALUES ('commute:stationpos', $1) ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value""", cache)
    return cache[name]


async def _leg(a: dict | None, b: dict | None, mode: str = "driving") -> tuple[int, float]:
    """(minutes, km) between two points by road; a cautious guess when either point or the router is missing."""
    if not a or not b:
        return 15, 5.0
    from . import maps, places
    try:
        rs, source = await maps.routes(a, b, mode)
        r = rs[0]
        slow = 1.3 if mode == "driving" and not r.get("traffic") else 1.0   # no live traffic in the estimate: allow for it
        return max(3, int(round(r["duration_min"] * slow))), float(r["distance_km"])
    except Exception:
        d = places.distance_m(a["lat"], a["lon"], b["lat"], b["lon"]) / 1000
        return max(5, int(d / 20 * 60) + 5), round(d * 1.3, 1)


async def _usual(direction: str) -> list[str]:
    rows = await db.pool().fetch(
        "SELECT chosen->>'dep' AS dep, count(*) AS n FROM commute_trips WHERE direction = $1 AND chosen IS NOT NULL AND created_at > now() - interval '30 days' "
        "GROUP BY 1 ORDER BY n DESC LIMIT 3", direction)
    return [r["dep"] for r in rows if r["dep"]]


async def plan(direction: str, now: datetime | None = None) -> dict:
    """Options for the trip ('out' to work, 'back' home) from now. A fixed procedure — no AI."""
    from . import places, weather
    now = (now or datetime.now(WIB)).astimezone(WIB)
    home_st, office_st, s = await _stations()
    if not home_st or not office_st:
        raise ValueError("pilih stasiun dekat rumah dan dekat kantor dulu")
    pl = {p["name"]: p for p in await places.listing()}
    if direction == "out":
        st_pos = await _station_pos(home_st["name"])
        ride_min, ride_km = await _leg(pl.get("rumah"), st_pos)
        after = max(krl.now_minutes(now) + (ride_min if s["ride_to_station"] else 10) + WAIT_MIN, 0)
        trains = await krl.trips(home_st["id"], office_st["id"], after, limit=6)
        opts = options_out(trains, ride_min, int(s["walk_min"]), hhmm_to(s["arrive_before"]), ride_km, s["ride_to_station"])
        car_min, car_km = await _leg(pl.get("rumah"), pl.get("kantor"))
        car = {"kind": "car", "leave": krl.hhmm(krl.now_minutes(now) + 5), "arrive": krl.hhmm(krl.now_minutes(now) + 5 + int(car_min * 1.4)),
               "minutes": int(car_min * 1.4), "cost": ride_cost(car_km, car=True), "note": "tol & jalan padat, tidak pasti"}
    else:
        st_pos = await _station_pos(home_st["name"])
        ride_min, ride_km = await _leg(st_pos, pl.get("rumah"))
        after = max(krl.now_minutes(now) + int(s["walk_min"]) + WAIT_MIN, hhmm_to(s["leave_after"]) + int(s["walk_min"]) + WAIT_MIN if now.hour < 17 else 0)
        trains = await krl.trips(office_st["id"], home_st["id"], after, limit=6)
        opts = options_back(trains, int(s["walk_min"]), ride_min, ride_km, s["ride_from_station"])
        car_min, car_km = await _leg(pl.get("kantor"), pl.get("rumah"))
        car = {"kind": "car", "leave": krl.hhmm(krl.now_minutes(now) + 5), "arrive": krl.hhmm(krl.now_minutes(now) + 5 + int(car_min * 1.5)),
               "minutes": int(car_min * 1.5), "cost": ride_cost(car_km, car=True), "note": "jam pulang, tol padat"}
    best = pick_usual(opts, await _usual(direction)) if opts else None
    w = await weather.here()
    rain = (w or {}).get("rain")
    return {"direction": direction, "from": home_st if direction == "out" else office_st, "to": office_st if direction == "out" else home_st,
            "options": opts, "car": car, "best": best, "weather": w, "rain_note": f"Kemungkinan hujan {rain['pct']}% sekitar jam {int(rain['hour'])}." if rain else "",
            "made_at": now.isoformat(), "no_places": [n for n in ("rumah", "kantor") if n not in pl]}


async def make_plan(direction: str, trigger: str = "owner") -> dict:
    r = await master.run(master.Job("berangkat" if direction == "out" else "pulang", "rencana", f"susun rencana {'berangkat' if direction == 'out' else 'pulang'} KRL + GoRide",
                                    trigger=trigger, skill=lambda: plan(direction)))
    if r["status"] != "done":
        raise ValueError(r.get("error") or "rencana gagal")
    p = r["result"]
    tid = await db.pool().fetchval("INSERT INTO commute_trips (direction, plan) VALUES ($1, $2) RETURNING id", direction, p)
    return {"trip_id": tid, **p}


async def latest(direction: str) -> dict | None:
    row = await db.pool().fetchrow(
        "SELECT * FROM commute_trips WHERE direction = $1 AND created_at > now() - interval '14 hours' ORDER BY id DESC LIMIT 1", direction)
    return dict(row) if row else None


async def active() -> dict | None:
    row = await db.pool().fetchrow("SELECT * FROM commute_trips WHERE status = 'active' ORDER BY id DESC LIMIT 1")
    return dict(row) if row else None


async def _event(trip_id: int, kind: str, text: str) -> None:
    await db.pool().execute("UPDATE commute_trips SET events = events || $2::jsonb WHERE id = $1", trip_id,
                            [{"at": datetime.now(WIB).isoformat(), "kind": kind, "text": text}])


async def choose(trip_id: int, index: int, actor: str) -> dict:
    """The owner takes an option ('car' = index -1): the trip becomes active; the reminders and rides are the clock's job now."""
    row = await db.pool().fetchrow("SELECT * FROM commute_trips WHERE id = $1", trip_id)
    if not row:
        raise ValueError("rencana tidak ada")
    p = row["plan"]
    opt = p["car"] if index == -1 else (p["options"][index] if 0 <= index < len(p["options"]) else None)
    if not opt:
        raise ValueError("opsi tidak ada")
    await db.pool().execute("UPDATE commute_trips SET status = 'cancelled' WHERE status = 'active' AND id <> $1", trip_id)
    await db.pool().execute("UPDATE commute_trips SET chosen = $2, status = 'active', started_at = now() WHERE id = $1", trip_id, opt)
    await db.pool().execute("""INSERT INTO settings_kv (key, value) VALUES ('commute:active', $1) ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value""",
                            {"trip": trip_id, "mode": opt["kind"], "direction": row["direction"]})
    await _event(trip_id, "chosen", f"dipilih: {opt.get('dep') or 'mobil'} oleh {actor}")
    await habits.clear_offer("commute.plan_out" if row["direction"] == "out" else "commute.plan_back")
    await _broadcast_trip(trip_id)
    if opt["kind"] == "car":
        await order_ride(trip_id, car=True)
    return await trip_view(trip_id)


async def cancel(trip_id: int) -> None:
    await db.pool().execute("UPDATE commute_trips SET status = 'cancelled', finished_at = now() WHERE id = $1", trip_id)
    await db.pool().execute("DELETE FROM settings_kv WHERE key = 'commute:active'")
    await hub.broadcast({"type": "trip", "id": trip_id, "status": "cancelled"})


async def order_ride(trip_id: int, car: bool = False) -> dict:
    """GoRide/GoCar on the owner's phone (Gojek): to his station when he leaves home, from the station when the train nears it, or straight
    to the destination by car. A phone job of the master flow — a learned routine replays it without AI; JARVIS stops at any PIN."""
    row = await db.pool().fetchrow("SELECT * FROM commute_trips WHERE id = $1", trip_id)
    p, opt = row["plan"], row["chosen"] or {}
    if row["direction"] == "out":
        goal = (f"Pesan GoCar dari lokasi sekarang ke kantor" if car else f"Pesan GoRide dari lokasi sekarang ke Stasiun {p['from']['name']}")
    else:
        goal = (f"Pesan GoCar dari lokasi sekarang ke rumah" if car else f"Pesan GoRide dari Stasiun {p['to']['name']} ke rumah")
    r = await master.run(master.Job("perjalanan", "pesan-ojek", goal, trigger="habit", phone={"app": "gojek", "goal": goal}, title=goal))
    await _event(trip_id, "ride", f"{goal} — {r.get('status')}")
    return r


async def trip_view(trip_id: int) -> dict:
    row = await db.pool().fetchrow("SELECT * FROM commute_trips WHERE id = $1", trip_id)
    t = dict(row)
    return {"id": t["id"], "direction": t["direction"], "status": t["status"], "plan": t["plan"], "chosen": t["chosen"], "events": t["events"],
            "steps": steps(t["direction"], t["plan"], t["chosen"]) if t["chosen"] else []}


def steps(direction: str, p: dict, o: dict) -> list[dict]:
    """The legs of a chosen option, in order, for the live trip screen and the lock screen. Pure."""
    if o.get("kind") == "car":
        return [{"at": o["leave"], "text": "GoCar langsung", "kind": "car"}, {"at": o["arrive"], "text": "Tiba", "kind": "end"}]
    out = []
    if direction == "out":
        if o.get("ride"):
            out.append({"at": o["leave"], "text": f"GoRide ke Stasiun {p['from']['name']}", "kind": "ride"})
        else:
            out.append({"at": o["leave"], "text": f"Berangkat ke Stasiun {p['from']['name']}", "kind": "walk"})
        out.append({"at": o["dep"], "text": f"KRL {p['from']['name']} → {p['to']['name']}" + (f" (ganti di {o['change']['hub']} {o['change']['dep'] if o.get('change') else ''})" if o.get("change") else ""), "kind": "krl"})
        out.append({"at": o["arr"], "text": f"Turun di {p['to']['name']}, jalan ke kantor", "kind": "walk"})
    else:
        out.append({"at": o["leave"], "text": f"Jalan ke Stasiun {p['from']['name']}", "kind": "walk"})
        out.append({"at": o["dep"], "text": f"KRL {p['from']['name']} → {p['to']['name']}" + (f" (ganti di {o['change']['hub']})" if o.get("change") else ""), "kind": "krl"})
        if o.get("ride"):
            out.append({"at": o["ride"]["order_at"], "text": "GoRide dipesan otomatis, menunggu di stasiun", "kind": "ride"})
        out.append({"at": o["arr"], "text": f"Tiba di {p['to']['name']}" + (", naik GoRide ke rumah" if o.get("ride") else ""), "kind": "walk"})
    out.append({"at": o["arrive"], "text": "Sampai kantor" if direction == "out" else "Sampai rumah", "kind": "end"})
    return out


async def _broadcast_trip(trip_id: int) -> None:
    v = await trip_view(trip_id)
    o = v["chosen"] or {}
    nxt = next((s for s in v["steps"] if hhmm_to(s["at"]) >= krl.now_minutes()), v["steps"][-1] if v["steps"] else None)
    await hub.broadcast({"type": "trip", "id": trip_id, "status": v["status"], "title": nxt["text"] if nxt else "Perjalanan",
                         "text": f"{nxt['at'] if nxt else ''} · tiba {o.get('arrive', '')}", "route": "#/perjalanan"})


# ---------- the clock: reminders, rides at the right moment, a missed train ----------

async def _done_today(trip_id: int, kind: str) -> bool:
    return bool(await db.pool().fetchval("SELECT 1 FROM commute_trips WHERE id = $1 AND events @> $2::jsonb", trip_id, [{"kind": kind}]))


@appclock.every(30, "commute.watch")
async def watch(now: datetime | None = None) -> list[str]:
    now = (now or datetime.now(WIB)).astimezone(WIB)
    t = await active()
    if not t or not t["chosen"]:
        return []
    o, p, m = t["chosen"], t["plan"], krl.now_minutes(now)
    did = []
    ref = hhmm_to(o.get("leave") or o.get("dep") or o["arrive"])   # every time of the trip is read after its start (a trip may cross midnight)
    if m < ref - 720:
        m += 1440
    if o.get("kind") == "car":
        if m > after_ref(o["arrive"], ref) + 60:
            await _finish(t["id"], "selesai (waktu)")
        return did
    leave = ref
    if leave - 10 <= m < leave and not await _done_today(t["id"], "remind_leave"):
        await _event(t["id"], "remind_leave", "pengingat berangkat")
        await hub.broadcast({"type": "notify", "title": f"Berangkat {o['leave'].replace(':', '.')}", "text": steps(t["direction"], p, o)[0]["text"],
                             "kind": "info", "route": "#/perjalanan"})
        did.append("remind_leave")
    if t["direction"] == "out" and o.get("ride") and leave - 3 <= m <= leave + 10 and not await _done_today(t["id"], "ride"):
        await order_ride(t["id"])
        did.append("ride_out")
    if t["direction"] == "back" and o.get("ride") and after_ref(o["ride"]["order_at"], ref) <= m <= after_ref(o["arr"], ref) + 5 and not await _done_today(t["id"], "ride"):
        await order_ride(t["id"])
        did.append("ride_home")
    dep = after_ref(o["dep"], ref)
    if dep + 6 <= m <= dep + 30 and not await _done_today(t["id"], "replan"):
        if await _still_near(p["from"]["name"]):
            await _replan(t, now)
            did.append("replan")
    if m > after_ref(o["arrive"], ref) + 90:
        await _finish(t["id"], "selesai (waktu)")
    if did:
        await _broadcast_trip(t["id"])
    return did


async def _still_near(station: str) -> bool:
    from . import location, places
    last = await location.last() or {}
    pos = await _station_pos(station)
    if not pos or last.get("lat") is None:
        return False
    received = last.get("received_at")
    if received and (datetime.now(WIB) - datetime.fromisoformat(received)).total_seconds() > 900:
        return False   # no fresh fix: do not guess
    return places.distance_m(last["lat"], last["lon"], pos["lat"], pos["lon"]) <= MISSED_RADIUS_M


async def _replan(t: dict, now: datetime) -> None:
    """The phone is still at the origin station after the train left: the next train, and the ride at the other end moved with it."""
    p = t["plan"]
    trains = await krl.trips(p["from"]["id"], p["to"]["id"], krl.now_minutes(now) + 2, limit=3)
    if not trains:
        return
    s = await appsettings.get("commute")
    o = t["chosen"]
    if t["direction"] == "out":
        new = options_out(trains[:1], (o.get("ride") or {}).get("min", 0), int(s["walk_min"]), hhmm_to(s["arrive_before"]), 0, False)[0]
    else:
        new = options_back(trains[:1], int(s["walk_min"]), (o.get("ride") or {}).get("min", 15), 0, bool(o.get("ride")))[0]
        if o.get("ride"):
            new["ride"]["cost"] = o["ride"]["cost"]
    new["replanned_from"] = o["dep"]
    await db.pool().execute("UPDATE commute_trips SET chosen = $2 WHERE id = $1", t["id"], new)
    await _event(t["id"], "replan", f"KRL {o['dep']} terlewat/terlambat → {new['dep']}, tiba {new['arrive']}")
    await hub.broadcast({"type": "notify", "title": "Rencana berubah", "text": f"Kamu belum berangkat dari {p['from']['name']}. Kereta berikutnya {new['dep']}, tiba {new['arrive']}.",
                         "kind": "urgent", "route": "#/berubah"})


async def _finish(trip_id: int, why: str) -> None:
    await db.pool().execute("UPDATE commute_trips SET status = 'done', finished_at = now() WHERE id = $1 AND status = 'active'", trip_id)
    await db.pool().execute("DELETE FROM settings_kv WHERE key = 'commute:active'")
    await _event(trip_id, "end", why)
    await hub.broadcast({"type": "trip", "id": trip_id, "status": "done"})


async def on_place(ev: dict) -> None:
    """Arriving at the destination ends the trip."""
    if ev.get("type") != "place" or ev.get("kind") != "arrive":
        return
    t = await active()
    if t and ((t["direction"] == "out" and ev["place"] == "kantor") or (t["direction"] == "back" and ev["place"] == "rumah")):
        await _finish(t["id"], f"sampai {ev['place']}")


hub.tap(on_place)


@habits.action("commute.plan_out", "Rencana berangkat")
async def _plan_out(h: dict) -> dict:
    p = await make_plan("out", "habit")
    best = p["options"][p["best"]] if p.get("best") is not None and p["options"] else None
    await hub.broadcast({"type": "notify", "title": "Rencana berangkat siap",
                         "text": f"KRL {best['dep']} → tiba {best['arrive']}. {p['rain_note']}" if best else "Lihat pilihan berangkat.", "kind": "info", "route": "#/berangkat"})
    return {"planned": p["trip_id"]}


@habits.action("commute.plan_back", "Rencana pulang")
async def _plan_back(h: dict) -> dict:
    p = await make_plan("back", "habit")
    best = p["options"][p["best"]] if p.get("best") is not None and p["options"] else None
    await hub.broadcast({"type": "notify", "title": "Rencana pulang siap",
                         "text": f"KRL {best['dep']} → rumah {best['arrive']}" if best else "Lihat pilihan pulang.", "kind": "info", "route": "#/pulang"})
    return {"planned": p["trip_id"]}


# ---------- front page, catalog ----------

@home.provider("commute")
async def _home(m: home.Moment) -> list[dict]:
    t = await active()
    if t and t["chosen"]:
        v = await trip_view(t["id"])
        nxt = next((s for s in v["steps"] if hhmm_to(s["at"]) >= krl.now_minutes(m.now)), None)
        return [{"id": "trip", "title": nxt["text"] if nxt else "Dalam perjalanan", "sub": f"{nxt['at'] if nxt else ''} · tiba {t['chosen'].get('arrive', '')}",
                 "route": "#/perjalanan", "icon": "train", "tone": "cyan", "score": 92, "cta": "Lihat perjalanan"}]
    direction = "out" if m.slot in ("subuh", "pagi") else ("back" if m.slot in ("sore",) else None)
    if not direction or m.now.weekday() >= 5:
        return []
    last = await latest(direction)
    if not last or last["chosen"]:
        return [{"id": f"plan-{direction}", "title": "Rencana berangkat" if direction == "out" else "Rencana pulang", "sub": "KRL + GoRide, dari pintu ke pintu",
                 "route": "#/berangkat" if direction == "out" else "#/pulang", "icon": "train", "tone": "cyan", "score": 60, "cta": "Susun rencana"}] if not last else []
    p = last["plan"]
    best = p["options"][p["best"]] if p.get("best") is not None and p["options"] else None
    if not best:
        return []
    return [{"id": f"plan-{direction}", "title": f"KRL {best['dep'].replace(':', '.')} · tiba {best['arrive'].replace(':', '.')}",
             "sub": (f"GoRide {best['leave'].replace(':', '.')}" if best.get("ride") and direction == "out" else f"berangkat {best['leave'].replace(':', '.')}") + (f" · {p['rain_note']}" if p.get("rain_note") else ""),
             "route": "#/berangkat" if direction == "out" else "#/pulang", "icon": "train", "tone": "cyan", "score": 88,
             "cta": "Pesankan GoRide" if best.get("ride") and direction == "out" else "Pakai rencana ini"}]


@setup_status.check("berangkat")
async def _ready() -> dict:
    from . import places
    s = await appsettings.get("commute")
    have = {p["name"] for p in await places.listing()}
    if not s["home_station"] or not s["office_station"]:
        return setup_status.needs("Pilih stasiun dekat rumah & kantor", "#/berangkat")
    if not {"rumah", "kantor"} <= have:
        return setup_status.needs("Izinkan lokasi di HP (rumah & kantor dipelajari), atau tandai di Kontrol", "#/kontrol")
    return setup_status.ready()


setup_status.CHECKS["pulang"] = _ready


# ---------- API ----------

class ChooseIn(BaseModel):
    index: int = Field(ge=-1, le=10)


@router.get(API + "/stations")
async def api_stations(q: str = "", device: dict = Depends(owner)):
    try:
        all_ = await krl.stations()
    except Exception as e:
        raise HTTPException(503, f"daftar stasiun KRL (Comuline) belum terjangkau — coba lagi ({type(e).__name__})")
    qn = q.lower().strip()
    return {"stations": [s for s in all_ if not qn or qn in s["name"].lower()][:30]}


@router.get(API + "/active")
async def api_active(device: dict = Depends(owner)):
    t = await active()
    return {"trip": await trip_view(t["id"]) if t else None}


@router.get(API + "/{direction}")
async def api_latest(direction: str, device: dict = Depends(owner)):
    if direction not in ("out", "back"):
        raise HTTPException(404)
    t = await active()
    last = await latest(direction)
    return {"active": await trip_view(t["id"]) if t else None, "latest": await trip_view(last["id"]) if last else None,
            "settings": await appsettings.get("commute"), "offer": await habits.offered("commute.plan_out" if direction == "out" else "commute.plan_back")}


@router.post(API + "/{direction}/plan")
async def api_plan(direction: str, device: dict = Depends(owner)):
    if direction not in ("out", "back"):
        raise HTTPException(404)
    try:
        return await make_plan(direction)
    except (ValueError, krl.KrlError) as e:
        raise HTTPException(409, str(e))


@router.post(API + "/trip/{trip_id}/choose")
async def api_choose(trip_id: int, body: ChooseIn, device: dict = Depends(owner)):
    try:
        return await choose(trip_id, body.index, f"device:{device['name']}")
    except ValueError as e:
        raise HTTPException(409, str(e))


@router.post(API + "/trip/{trip_id}/cancel")
async def api_cancel(trip_id: int, device: dict = Depends(owner)):
    await cancel(trip_id)
    return {"ok": True}

