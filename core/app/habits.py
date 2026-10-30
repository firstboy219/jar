"""Habits (ADR-087): what JARVIS does without being asked — at a time ("06.30 hari kerja"), when the owner arrives somewhere ("sampai
kantor") or leaves — and how: automatically, asking first (an offer on the front page and a notification), or not at all.

Some habits come built in (the trip plans, the evening recap, the coffee offer …) and start as "ask"; others are LEARNED: when the owner
opened the same feature around the same hour on most workdays of the last three weeks, JARVIS suggests making it a habit ("Usulan
baru") and only adds it when he agrees. Each habit shows how often it really happened ("14 dari 15 hari").

Firing a habit runs its action — a function a feature registered with @action — and every action does its work through the master flow.
Money and the phone keep their own guards whatever the mode."""

import logging
import statistics
from datetime import datetime, timedelta
from typing import Awaitable, Callable

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from . import appclock, db, home, hub, master
from .appauth import owner
from .location import WIB

log = logging.getLogger("jarvis-core")
router = APIRouter()
API = "/api/v1/app/habits"

ACTIONS: dict[str, tuple[str, Callable[[dict], Awaitable[dict | None]]]] = {}   # name → (label, fn(habit) -> offer/result)
WORKDAYS = [0, 1, 2, 3, 4]
WINDOW_MIN = 20          # a time habit fires within this many minutes after its time (a late start of the server still catches it)

BUILTIN = [
    {"key": "pagi.plan", "title": "Rencana berangkat (KRL + GoRide)", "trigger": {"type": "time", "at": "06:30", "days": WORKDAYS}, "action": "commute.plan_out", "mode": "auto"},
    {"key": "kantor.inbox", "title": "Sampai kantor: pilah email & WhatsApp", "trigger": {"type": "arrive", "place": "kantor", "after": "06:00", "before": "12:00"},
     "action": "inbox.triage", "mode": "auto"},
    {"key": "siang.kopi", "title": "Tawarkan kopi (cek promo)", "trigger": {"type": "time", "at": "14:30", "days": WORKDAYS, "place": "kantor"}, "action": "coffee.offer", "mode": "auto"},   # the offer itself is the question ("Mau kopi? Lagi diskon …")
    {"key": "pagi.musik", "title": "Musik pagi (mood yang biasa)", "trigger": {"type": "time", "at": "06:15", "days": WORKDAYS}, "action": "music.mood", "mode": "ask"},
    {"key": "sore.plan", "title": "Rencana pulang (KRL + GoRide)", "trigger": {"type": "time", "at": "16:45", "days": WORKDAYS}, "action": "commute.plan_back", "mode": "auto"},
    {"key": "rumah.recap", "title": "Sampai rumah: rekap hari ini + action plan", "trigger": {"type": "arrive", "place": "rumah", "after": "16:00", "before": "23:30"},
     "action": "recap.compose", "mode": "auto"},
    {"key": "malam.recap", "title": "Rekap hari ini (kalau belum sampai rumah)", "trigger": {"type": "time", "at": "21:00", "days": [0, 1, 2, 3, 4, 5, 6]},
     "action": "recap.compose", "mode": "auto"},
    {"key": "rapat.rekam", "title": "Rapat di kalender: tawarkan rekam", "trigger": {"type": "calendar", "before": 5, "place": "kantor"}, "action": "meeting.offer", "mode": "auto"},   # the action itself only offers
    {"key": "malam.dongeng", "title": "Dongeng untuk si kecil", "trigger": {"type": "time", "at": "20:00", "days": [0, 1, 2, 3, 4, 5, 6], "place": "rumah"},
     "action": "story.offer", "mode": "ask"},
]


def action(name: str, label: str):
    def wrap(fn):
        ACTIONS[name] = (label, fn)
        return fn
    return wrap


# ---------- pure ----------

def hm(at: str) -> int:
    return int(at[:2]) * 60 + int(at[3:5])


def time_due(trigger: dict, now: datetime, last_fired: datetime | None) -> bool:
    """Is a time habit due now (its day, within WINDOW_MIN after its time, not yet today)? Pure."""
    if trigger.get("type") != "time" or now.weekday() not in (trigger.get("days") or []):
        return False
    m = now.hour * 60 + now.minute
    t = hm(trigger["at"])
    if not 0 <= m - t <= WINDOW_MIN:
        return False
    return not (last_fired and last_fired.astimezone(WIB).date() == now.date())


def calendar_due(trigger: dict, event_start: datetime, event_id: int, now: datetime, fired_for: int | None) -> bool:
    """A calendar habit: an event starts within `before` minutes (and has not been offered yet). Pure."""
    if trigger.get("type") != "calendar" or fired_for == event_id:
        return False
    mins = (event_start - now).total_seconds() / 60
    return -2 <= mins <= int(trigger.get("before") or 5)


def place_due(trigger: dict, kind: str, place: str, now: datetime, last_fired: datetime | None) -> bool:
    """Does an arrive/leave habit match this event (place, time window, once a day)? Pure."""
    if trigger.get("type") != kind or trigger.get("place") != place:
        return False
    m = now.hour * 60 + now.minute
    if trigger.get("after") and m < hm(trigger["after"]):
        return False
    if trigger.get("before") and m > hm(trigger["before"]):
        return False
    if trigger.get("days") and now.weekday() not in trigger["days"]:
        return False
    return not (last_fired and last_fired.astimezone(WIB).date() == now.date())


def learn(opens: list[tuple[str, datetime]], today: datetime, days: int = 21, min_share: float = 0.6, min_days: int = 4) -> list[dict]:
    """Repeated openings at about the same hour on workdays → suggested habits {feature, at, seen, of_days}. Pure.
    For each feature and hour bucket: on how many distinct workdays of the window it was opened; enough → suggest the median time minus
    five minutes (ready before he looks)."""
    start = (today - timedelta(days=days)).date()
    workdays = [start + timedelta(days=i) for i in range(days) if (start + timedelta(days=i)).weekday() < 5]
    by: dict[tuple[str, int], dict] = {}
    for feature, at in opens:
        t = at.astimezone(WIB)
        if t.date() < start or t.date() >= today.date() or t.weekday() >= 5:
            continue
        b = by.setdefault((feature, t.hour), {"days": set(), "mins": []})
        b["days"].add(t.date())
        b["mins"].append(t.hour * 60 + t.minute)
    out = []
    for (feature, hour), b in by.items():
        n = len(b["days"])
        if n >= min_days and workdays and n / len(workdays) >= min_share:
            m = max(0, int(statistics.median(b["mins"])) - 5)
            out.append({"feature": feature, "at": f"{m // 60:02d}:{m % 60:02d}", "seen": n, "of_days": len(workdays)})
    return sorted(out, key=lambda x: -x["seen"])


# ---------- the store ----------

async def ensure_builtin() -> None:
    for h in BUILTIN:
        await db.pool().execute(
            """INSERT INTO habits (key, title, trigger, action, mode, source) VALUES ($1, $2, $3, $4, $5, 'builtin') ON CONFLICT (key) DO NOTHING""",
            h["key"], h["title"], h["trigger"], h["action"], h["mode"])


async def listing() -> list[dict]:
    await ensure_builtin()
    return [dict(r) for r in await db.pool().fetch("SELECT * FROM habits WHERE status <> 'rejected' ORDER BY status DESC, (trigger->>'at') NULLS LAST, id")]


async def set_mode(habit_id: int, mode: str) -> dict:
    row = await db.pool().fetchrow("UPDATE habits SET mode = $2, updated_at = now() WHERE id = $1 RETURNING *", habit_id, mode)
    if not row:
        raise ValueError("kebiasaan tidak ada")
    return dict(row)


async def decide_suggestion(habit_id: int, accept: bool) -> dict:
    row = await db.pool().fetchrow("UPDATE habits SET status = $2, updated_at = now() WHERE id = $1 AND status = 'suggested' RETURNING *",
                                   habit_id, "active" if accept else "rejected")
    if not row:
        raise ValueError("usulan tidak ada")
    return dict(row)


async def fire(h: dict, why: str, at: datetime | None = None) -> dict:
    """Run one habit now: 'auto' runs its action; 'ask' makes an offer (the action decides what the offer is). `at` = the moment it was due."""
    await db.pool().execute("UPDATE habits SET last_fired = $2 WHERE id = $1", h["id"], at or datetime.now(WIB))
    label, fn = ACTIONS.get(h["action"], (h["action"], None))
    if fn is None:
        log.warning("habit %s: no action %s", h["key"], h["action"])
        return {"skipped": "aksi belum tersedia"}
    if h["mode"] == "ask":
        await hub.broadcast({"type": "notify", "title": h["title"], "text": "Mau aku kerjakan? Ketuk untuk melihat.", "kind": "habit",
                             "route": offer_route(h["action"])})
        await db.pool().execute("""INSERT INTO settings_kv (key, value) VALUES ($1, $2) ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value""",
                                f"habit:offer:{h['action']}", {"habit": h["id"], "at": datetime.now(WIB).isoformat(), "why": why})
        return {"offered": h["title"]}
    try:
        return (await fn(h)) or {"done": h["title"]}
    except Exception as e:
        log.exception("habit %s failed", h["key"])
        return {"error": str(e)[:200]}


ROUTES = {"commute.plan_out": "#/berangkat", "commute.plan_back": "#/pulang", "inbox.triage": "#/inbox", "coffee.offer": "#/kopi",
          "recap.compose": "#/rekap", "story.offer": "#/dongeng", "music.mood": "#/musik", "meeting.offer": "#/rapat"}


def offer_route(action_name: str) -> str:
    if action_name.startswith("open:"):
        f = action_name[5:]
        return next((x["route"] for x in home.FEATURES if x["id"] == f and x["route"].startswith("#/")), "#/")
    return ROUTES.get(action_name, "#/")


async def offered(action_name: str) -> dict | None:
    """An offer still standing today for this action (the front page shows it, the feature screen answers it)."""
    v = await db.pool().fetchval("SELECT value FROM settings_kv WHERE key = $1", f"habit:offer:{action_name}")
    if v and datetime.fromisoformat(v["at"]).date() == datetime.now(WIB).date():
        return v
    return None


async def clear_offer(action_name: str) -> None:
    await db.pool().execute("DELETE FROM settings_kv WHERE key = $1", f"habit:offer:{action_name}")


# ---------- the engine ----------

@appclock.every(30, "habits.time")
async def tick(now: datetime | None = None) -> list[str]:
    now = (now or datetime.now(WIB)).astimezone(WIB)
    from . import places
    here = (await places.current()).get("place")
    fired = []
    for h in await listing():
        if h["status"] != "active" or h["mode"] == "off":
            continue
        t = h["trigger"]
        if not time_due(t, now, h["last_fired"]):
            continue
        if t.get("place") and here and here != t["place"]:   # "at kantor" habits wait for kantor (unknown place: they go ahead)
            continue
        r = await master.run(master.Job("kebiasaan", h["action"], f"kebiasaan: {h['title']}", trigger="habit",
                                        skill=lambda h=h, t=t: fire(h, f"jam {t['at']}", now)))
        fired.append(h["key"])
        log.info("habit %s fired: %s", h["key"], r.get("result"))
    fired += await _calendar(now, here)
    return fired


async def _calendar(now: datetime, here: str | None) -> list[str]:
    """Calendar habits: an event about to start (the record-the-meeting offer)."""
    hs = [h for h in await listing() if h["status"] == "active" and h["mode"] != "off" and (h["trigger"] or {}).get("type") == "calendar"]
    if not hs:
        return []
    ev = await db.pool().fetchrow("SELECT id, title, start_at FROM calendar_events WHERE start_at BETWEEN $1::timestamptz - interval '2 minutes' AND $1::timestamptz + interval '30 minutes' ORDER BY start_at LIMIT 1", now)
    if not ev:
        return []
    out = []
    for h in hs:
        t = h["trigger"]
        last = await db.pool().fetchval("SELECT value FROM settings_kv WHERE key = $1", f"habit:cal:{h['key']}") or {}
        if t.get("place") and here and here != t["place"]:
            continue
        if not calendar_due(t, ev["start_at"], ev["id"], now, last.get("event")):
            continue
        await db.pool().execute("INSERT INTO settings_kv (key, value) VALUES ($1, $2) ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value", f"habit:cal:{h['key']}", {"event": ev["id"]})
        await master.run(master.Job("kebiasaan", h["action"], f"kebiasaan: {h['title']}", trigger="habit",
                                    skill=lambda h=h, ev=ev: fire({**h, "title": f"{ev['title']} mulai {ev['start_at'].astimezone(WIB):%H.%M} — rekam?"}, f"kalender {ev['title']}", now)))
        out.append(h["key"])
    return out


@action("meeting.offer", "Tawarkan rekam rapat")
async def _meeting_offer(h: dict) -> dict:
    from . import meetings
    meetings.want_to_record(title=h.get("title", "").split(" mulai ")[0])
    await hub.broadcast({"type": "notify", "title": h.get("title") or "Rapat mulai", "text": "Ketuk untuk mulai merekam (semua peserta setuju).", "kind": "info", "route": "#/rapat"})
    return {"offered": True}


async def on_event(ev: dict) -> None:
    """Arrivals and departures (places.py broadcasts them) fire the arrive/leave habits."""
    if ev.get("type") != "place":
        return
    now = datetime.now(WIB)
    for h in await listing():
        if h["status"] == "active" and h["mode"] != "off" and place_due(h["trigger"], ev["kind"], ev["place"], now, h["last_fired"]):
            await master.run(master.Job("kebiasaan", h["action"], f"kebiasaan: {h['title']}", trigger="event",
                                        skill=lambda h=h: fire(h, f"{'sampai' if ev['kind'] == 'arrive' else 'keluar'} {ev['place']}")))


hub.tap(on_event)


@appclock.daily(lambda: "03:10", "habits.learn")
async def nightly_learn() -> list[dict]:
    rows = await db.pool().fetch("SELECT feature, opened_at FROM app_usage WHERE opened_at > now() - interval '22 days'")
    found = learn([(r["feature"], r["opened_at"]) for r in rows], datetime.now(WIB))
    made = []
    for f in found:
        label = next((x["label"] for x in home.FEATURES if x["id"] == f["feature"]), f["feature"])
        key = f"learned:{f['feature']}:{f['at'][:2]}"
        r = await db.pool().fetchrow(
            """INSERT INTO habits (key, title, trigger, action, mode, status, source, seen, of_days) VALUES ($1, $2, $3, $4, 'ask', 'suggested', 'learned', $5, $6)
               ON CONFLICT (key) DO UPDATE SET seen = EXCLUDED.seen, of_days = EXCLUDED.of_days, updated_at = now() RETURNING status""",
            key, f"Buka {label} sekitar {f['at']}", {"type": "time", "at": f["at"], "days": WORKDAYS}, f"open:{f['feature']}", f["seen"], f["of_days"])
        made.append({**f, "status": r["status"]})
    await _count_builtin()
    return made


async def _count_builtin() -> None:
    """How often each built-in habit really fired on the days it could (the "14 dari 15 hari")."""
    rows = await db.pool().fetch(
        """SELECT action, count(DISTINCT (started_at AT TIME ZONE 'Asia/Jakarta')::date) AS n FROM flow_runs
           WHERE feature = 'kebiasaan' AND status = 'done' AND started_at > now() - interval '21 days' GROUP BY action""")
    for r in rows:
        await db.pool().execute("UPDATE habits SET seen = $2, of_days = 15 WHERE action = $1 AND source = 'builtin'", r["action"], r["n"])


@action("open", "Buka fitur")
async def _open(h: dict) -> dict:
    return {"offered": h["title"]}


for _f in home.FEATURES:   # a learned habit "open <feature>" is an offer that opens it
    ACTIONS.setdefault(f"open:{_f['id']}", (f"Buka {_f['label']}", _open))


# ---------- the front page: standing offers and suggestions ----------

@home.provider("habits")
async def _home(m: home.Moment) -> list[dict]:
    out = []
    for h in await listing():
        if h["status"] == "suggested":
            out.append({"id": f"habit:{h['id']}", "title": "Usulan kebiasaan baru", "sub": f"{h['title']} ({h['seen']} dari {h['of_days']} hari kerja)",
                        "route": "#/kebiasaan", "icon": "repeat", "tone": "cyan", "score": 22})
        elif h["status"] == "active" and h["mode"] == "ask" and h["action"].startswith("open:") and await offered(h["action"]):
            out.append({"id": f"habit:{h['id']}", "title": h["title"].replace("Buka ", ""), "sub": "kebiasaanmu jam segini", "route": offer_route(h["action"]),
                        "icon": "repeat", "tone": "cyan", "score": 48, "cta": "Buka"})
    return out


# ---------- API ----------

class ModeIn(BaseModel):
    mode: str = Field(pattern="^(auto|ask|off)$")


class HabitIn(BaseModel):
    title: str = Field(min_length=3, max_length=120)
    at: str = Field(pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    days: list[int] = Field(default_factory=lambda: WORKDAYS)
    action: str = Field(max_length=60)
    mode: str = Field(default="ask", pattern="^(auto|ask|off)$")


@router.get(API)
async def api_list(device: dict = Depends(owner)):
    from . import places
    return {"habits": await listing(), "places": await places.listing(), "actions": {k: v[0] for k, v in ACTIONS.items() if not k.startswith("open:")}}


@router.put(API + "/{habit_id}/mode")
async def api_mode(habit_id: int, body: ModeIn, device: dict = Depends(owner)):
    try:
        return await set_mode(habit_id, body.mode)
    except ValueError as e:
        raise HTTPException(404, str(e))


@router.post(API + "/{habit_id}/{decision}")
async def api_decide(habit_id: int, decision: str, device: dict = Depends(owner)):
    if decision not in ("accept", "reject"):
        raise HTTPException(404)
    try:
        return await decide_suggestion(habit_id, decision == "accept")
    except ValueError as e:
        raise HTTPException(409, str(e))


@router.post(API)
async def api_add(body: HabitIn, device: dict = Depends(owner)):
    if body.action not in ACTIONS:
        raise HTTPException(422, "aksi tidak dikenal")
    days = sorted({d for d in body.days if 0 <= d <= 6})
    row = await db.pool().fetchrow(
        """INSERT INTO habits (key, title, trigger, action, mode, source) VALUES ($1, $2, $3, $4, $5, 'owner') RETURNING *""",
        f"owner:{datetime.now(WIB).timestamp():.0f}", body.title, {"type": "time", "at": body.at, "days": days}, body.action, body.mode)
    return dict(row)
