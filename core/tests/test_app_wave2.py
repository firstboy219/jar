"""ADR-087 wave 2: KRL trips (direct, with a change, to a terminus), trip options and the live trip (reminders, the ride at the right
moment, a missed train → a new plan), habits (time, arrival, learning, modes), and the evening recap as tasks in Catatan."""
import os
from datetime import date, datetime, timedelta

import httpx
import pytest

from tests.test_integration import pool  # noqa: F401  (fixture)

needs_db = pytest.mark.skipif(not os.getenv("TEST_DATABASE_URL"), reason="needs TEST_DATABASE_URL")


def dep(train, mins, dest, end=None):
    return {"train": train, "dep": mins, "dest": dest, "route": "BOGOR-X", "line": "L", "color": "", "end": end}


# ---------- pure ----------

def test_krl_trips_direct_with_a_change_and_to_a_terminus():
    from app import krl
    assert krl.wib_minutes("2024-11-12 00:19:00.277+00") == 7 * 60 + 19 and krl.wib_minutes("2024-11-12 17:30:00+00") == 30
    boo = [dep("A1", 420, "JAKK"), dep("A2", 430, "MRI"), dep("A3", 300, "JAKK")]
    mri = [dep("A1", 480, "JAKK"), dep("A2", 485, "MRI"), dep("C9", 492, "KPB")]
    sud = [dep("C9", 500, "KPB")]
    d = krl.direct(boo, mri, 400)
    assert [x["train"] for x in d] == ["A1", "A2"] and d[0]["arr"] == 480                    # 07:00 → 08:00 at Manggarai
    ch = krl.with_change(boo, mri, sud, "MRI", 400, b_id="SUD")
    assert ch[0]["train"] == "A1 → C9" and ch[0]["arr"] == 500 and ch[0]["change"]["dep"] == 492   # ≥5 minutes to change
    term = krl.direct([dep("B1", 1050, "BOO", end=1115)], [], 1000, b_id="BOO")
    assert term[0]["arr"] == 1115                                                               # a terminus: the train's end time
    st = [{"id": "BOO", "name": "Bogor"}, {"id": "SUD", "name": "Sudirman"}, {"id": "BOI", "name": "Bojonggede"}]
    assert krl.find_station("bogor", st)["id"] == "BOO" and krl.find_station("sudir", st)["id"] == "SUD" and krl.find_station("", st) is None


def test_trip_times_across_midnight_keep_their_order():
    from app import commute
    assert commute.after_ref("00:10", 23 * 60 + 40) == 1450 and commute.after_ref("23:55", 23 * 60 + 40) == 1435
    assert commute.after_ref("06:10", 5 * 60 + 50) == 370                                          # an ordinary morning is untouched


def test_trip_options_and_the_usual_train():
    from app import commute
    trains = [{"train": "A", "dep": 452, "arr": 518, "legs": 2, "route": "R · ganti di MRI", "change": {"hub": "MRI", "arr": 505, "dep": 510}},
              {"train": "B", "dep": 472, "arr": 540, "legs": 1, "route": "R"}]
    out = commute.options_out(trains, ride_min=17, walk_min=6, arrive_by=540, ride_km=6.0, ride_to_station=True)
    assert out[0]["leave"] == "07:10" and out[0]["arrive"] == "08:44" and out[0]["ride"]["cost"] == 20000 and not out[0]["late"]
    assert out[1]["late"] and out[1]["arrive"] == "09:06"
    back = commute.options_back(trains, walk_min=6, ride_min=17, ride_km=6.0, ride_from_station=True)
    assert back[0]["ride"]["order_at"] == "08:30" and back[0]["leave"] == "07:21"
    assert commute.pick_usual(out, ["07:52"]) == 1 and commute.pick_usual(out, []) == 0
    steps = commute.steps("out", {"from": {"name": "Bogor"}, "to": {"name": "Sudirman"}}, out[0])
    assert [s["kind"] for s in steps] == ["ride", "krl", "walk", "end"] and "ganti di MRI" in steps[1]["text"]
    assert commute.ride_cost(1) == 10000 and commute.ride_cost(10, car=True) == 47000


def test_habits_fire_on_time_and_place_and_are_learned():
    from app import habits
    from app.location import WIB
    t = {"type": "time", "at": "06:30", "days": [0, 1, 2, 3, 4]}
    thu = datetime(2026, 10, 29, 6, 31, tzinfo=WIB)
    assert habits.time_due(t, thu, None) and not habits.time_due(t, thu.replace(hour=7), None)
    assert not habits.time_due(t, thu, thu - timedelta(minutes=1))                        # once a day
    assert not habits.time_due(t, datetime(2026, 10, 31, 6, 31, tzinfo=WIB), None)        # Saturday
    a = {"type": "arrive", "place": "rumah", "after": "16:00", "before": "23:30"}
    assert habits.place_due(a, "arrive", "rumah", thu.replace(hour=19), None)
    assert not habits.place_due(a, "arrive", "rumah", thu.replace(hour=12), None) and not habits.place_due(a, "leave", "rumah", thu.replace(hour=19), None)
    opens = [("bisnis", datetime(2026, 10, d, 8, 10 + d % 5, tzinfo=WIB)) for d in range(8, 29) if datetime(2026, 10, d).weekday() < 5]
    found = habits.learn(opens + [("video", datetime(2026, 10, 20, 21, 0, tzinfo=WIB))], datetime(2026, 10, 29, 3, 0, tzinfo=WIB))
    assert found[0]["feature"] == "bisnis" and found[0]["at"].startswith("08:0") and found[0]["seen"] >= 10
    assert all(f["feature"] != "video" for f in found)


def test_recap_page_blocks_and_due_dates():
    from app import recap
    thu = date(2026, 10, 29)
    assert recap.due_of("besok", thu) == "2026-10-30" and recap.due_of("Jumat", thu) == "2026-10-30" and recap.due_of("Senin", thu) == "2026-11-02"
    assert recap.due_of("2026-11-05", thu) == "2026-11-05" and recap.due_of("kapan-kapan", thu) is None
    b = recap.blocks_for({"ringkasan": "Hari padat.", "selesai": ["PO disetujui"], "action_plan": [{"tugas": "Kirim timeline ke Dimas", "tenggat": "Jumat",
                          "dari": "rapat Tim Produk", "penting": True}, {"tugas": ""}], "besok": "KRL 07.32."}, thu)
    todos = [x for x in b if x["type"] == "todo"]
    assert len(todos) == 1 and todos[0]["text"] == "Kirim timeline ke Dimas — dari rapat Tim Produk" and todos[0]["due"] == "2026-10-30" and todos[0]["priority"] == 3
    assert b[0]["type"] == "callout" and b[-1]["text"] == "KRL 07.32."


# ---------- with the database ----------

@needs_db
async def test_a_time_habit_runs_through_the_master_flow_once(pool, monkeypatch):
    from app import habits
    from app.location import WIB
    await pool.execute("TRUNCATE habits, flow_runs, place_events RESTART IDENTITY")
    ran = []

    async def act(h):
        ran.append(h["key"])
        return {"ok": 1}
    monkeypatch.setitem(habits.ACTIONS, "commute.plan_out", ("Rencana", act))
    t = datetime(2026, 10, 29, 6, 32, tzinfo=WIB)
    fired = await habits.tick(t)
    assert "pagi.plan" in fired and ran == ["pagi.plan"]
    assert await habits.tick(t.replace(minute=40)) == []
    run = await pool.fetchrow("SELECT lane, trigger, status FROM flow_runs WHERE feature = 'kebiasaan' AND action = 'commute.plan_out'")
    assert dict(run) == {"lane": "skill", "trigger": "habit", "status": "done"}
    hid = await pool.fetchval("SELECT id FROM habits WHERE key = 'sore.plan'")
    await habits.set_mode(hid, "off")
    assert "sore.plan" not in await habits.tick(t.replace(hour=16, minute=46))


@needs_db
async def test_an_ask_habit_makes_an_offer_and_arrival_fires_place_habits(pool, monkeypatch):
    from app import habits, hub
    from app.location import WIB
    await pool.execute("TRUNCATE habits, flow_runs RESTART IDENTITY")
    sent, ran = [], []

    async def tap(ev):
        if ev.get("type") == "notify":
            sent.append(ev)
    hub.tap(tap)

    async def act(h):
        ran.append(h["key"])
        return {"ok": 1}
    monkeypatch.setitem(habits.ACTIONS, "recap.compose", ("Rekap", act))
    monkeypatch.setitem(habits.ACTIONS, "inbox.triage", ("Pilah", act))
    await habits.ensure_builtin()
    await habits.on_event({"type": "place", "place": "rumah", "kind": "arrive"})
    now = datetime.now(WIB)
    if 16 <= now.hour < 23:
        assert ran == ["rumah.recap"]
    story = await pool.fetchrow("SELECT * FROM habits WHERE key = 'malam.dongeng'")   # an 'ask' habit (the coffee offer asks by itself: auto)
    assert story["mode"] == "ask" and await pool.fetchval("SELECT mode FROM habits WHERE key = 'siang.kopi'") == "auto"
    monkeypatch.setitem(habits.ACTIONS, "story.offer", ("Dongeng", act))
    r = await habits.fire(dict(story), "jam 20:00")
    assert r == {"offered": story["title"]} and sent[-1]["route"] == "#/dongeng" and await habits.offered("story.offer")


@needs_db
async def test_the_trip_plans_then_runs_rides_and_replans(pool, monkeypatch):
    from app import commute, krl, location, master, places
    from app.location import WIB
    await pool.execute("TRUNCATE commute_trips, flow_runs, places, settings_kv RESTART IDENTITY")
    await places.set_place("rumah", -6.56, 106.80)
    await places.set_place("kantor", -6.21, 106.82)
    await pool.execute("""INSERT INTO settings_kv (key, value) VALUES ('app:commute', '{"home_station": "Bogor", "office_station": "Sudirman", "walk_min": 6}'),
        ('commute:stationpos', '{"Bogor": {"lat": -6.5957, "lon": 106.7907}, "Sudirman": {"lat": -6.2025, "lon": 106.8234}}')""")

    async def stations():
        return [{"id": "BOO", "name": "Bogor"}, {"id": "SUD", "name": "Sudirman"}]

    async def trips(a, b, after, limit=6):
        base = max(after, 450)
        return [{"train": f"T{i}", "dep": base + 10 * i, "arr": base + 10 * i + 70, "legs": 1, "route": "BOGOR-SUD"} for i in range(3)]

    async def leg(a, b, mode="driving"):
        return 17, 6.0
    monkeypatch.setattr(krl, "stations", stations)
    monkeypatch.setattr(krl, "trips", trips)
    monkeypatch.setattr(commute, "_leg", leg)
    rides = []

    async def phone_run(job):
        if job.phone:
            rides.append(job.phone["goal"])
            return {"status": "waiting", "run_id": 0}
        return await real_run(job)
    real_run = master.run
    monkeypatch.setattr(commute.master, "run", phone_run)
    p = await commute.make_plan("out")
    assert p["options"] and p["from"]["name"] == "Bogor" and p["options"][0]["ride"]["min"] == 17
    v = await commute.choose(p["trip_id"], 0, "test")
    assert v["status"] == "active" and v["steps"][0]["kind"] == "ride"
    o = v["chosen"]
    leave = datetime.now(WIB).replace(hour=int(o["leave"][:2]), minute=int(o["leave"][3:5]), second=0, microsecond=0)
    did = await commute.watch(leave - timedelta(minutes=2))
    assert "remind_leave" in did and "ride_out" in did and rides == ["Pesan GoRide dari lokasi sekarang ke Stasiun Bogor"]
    assert await commute.watch(leave) == []                                             # once
    # the train left 8 minutes ago and the phone is still at Bogor station → the next train
    await location.remember_last(location.Location(lat=-6.5958, lon=106.7908, accuracy_m=10, age_s=0))
    dep_t = leave.replace(hour=int(o["dep"][:2]), minute=int(o["dep"][3:5])) + timedelta(minutes=8)
    did = await commute.watch(dep_t)
    assert "replan" in did
    t = await commute.active()
    assert t["chosen"]["replanned_from"] == o["dep"] and any(e["kind"] == "replan" for e in t["events"])
    await commute.on_place({"type": "place", "place": "kantor", "kind": "arrive"})
    assert await commute.active() is None


@needs_db
async def test_the_recap_becomes_a_page_with_tasks(pool, monkeypatch):
    from app import gateway, notes, recap
    await pool.execute("TRUNCATE note_pages, flow_runs, settings_kv RESTART IDENTITY CASCADE")

    async def fake(category, body, **kw):
        return {"choices": [{"message": {"content": '{"ringkasan": "Hari yang padat.", "selesai": ["Riset laptop"], "belum": [], '
                                                    '"action_plan": [{"tugas": "Kirim timeline ke Dimas", "tenggat": "besok", "dari": "rapat"}], "besok": "KRL 07.32."}'}}]}
    monkeypatch.setattr(gateway, "complete", fake)
    r = await recap.compose()
    assert r["stats"]["plan"] == 1 and r["title"].startswith("Rekap ")
    tasks = await notes.tasks("all")
    assert any(t["text"].startswith("Kirim timeline ke Dimas") and t["page_kind"] == "recap" for t in tasks)
    page = await notes.get(r["page_id"])
    blocks = page["blocks"]
    todo = next(b for b in blocks if b["type"] == "todo")
    await notes.set_block(r["page_id"], todo["id"], "test", checked=True)
    r2 = await recap.compose()                                                           # again the same day: same page, the tick kept
    assert r2["page_id"] == r["page_id"]
    page = await notes.get(r["page_id"])
    assert next(b for b in page["blocks"] if b["type"] == "todo")["checked"] is True


@needs_db
async def test_wave2_screens_get_real_answers(pool, monkeypatch):
    from app import devices, krl, main
    await pool.execute("TRUNCATE habits, commute_trips, settings_kv RESTART IDENTITY")

    async def stations():
        return [{"id": "BOO", "name": "Bogor"}, {"id": "SUD", "name": "Sudirman"}]
    monkeypatch.setattr(krl, "stations", stations)
    _, token = await devices.create("HP", "test", scope="owner")
    h = {"Authorization": f"Bearer {token}"}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url="http://t") as c:
        hb = (await c.get("/api/v1/app/habits", headers=h)).json()
        assert any(x["key"] == "pagi.plan" for x in hb["habits"]) and "commute.plan_out" in hb["actions"]
        hid = next(x["id"] for x in hb["habits"] if x["key"] == "siang.kopi")
        assert (await c.put(f"/api/v1/app/habits/{hid}/mode", json={"mode": "off"}, headers=h)).json()["mode"] == "off"
        assert (await c.get("/api/v1/app/commute/stations?q=bog", headers=h)).json()["stations"][0]["id"] == "BOO"
        out = (await c.get("/api/v1/app/commute/out", headers=h)).json()
        assert out["active"] is None and out["settings"]["walk_min"] == 6
        assert (await c.post("/api/v1/app/commute/out/plan", headers=h)).status_code == 409         # stations not chosen yet: says so
        assert (await c.get("/api/v1/app/commute/active", headers=h)).json() == {"trip": None}
        assert (await c.get("/api/v1/app/recap", headers=h)).json()["recap"] is None
        new = await c.post("/api/v1/app/habits", json={"title": "Pulang awal Jumat", "at": "16:30", "days": [4], "action": "commute.plan_back"}, headers=h)
        assert new.json()["source"] == "owner"
