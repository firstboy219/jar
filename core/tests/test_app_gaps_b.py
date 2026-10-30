"""ADR-087 wave 9 gap batch B: the trip home carries his errands; Gojek's own notifications (driver, plate, minutes away) reach the trip and
the lock screen; a train held between stations moves the arrival and the ride home; other options from now; telling home where he is."""
import os
from datetime import datetime, timedelta

import pytest

from tests.test_integration import pool  # noqa: F401  (fixture)

needs_db = pytest.mark.skipif(not os.getenv("TEST_DATABASE_URL"), reason="needs TEST_DATABASE_URL")


def test_driver_notifications_held_trains_errands_and_the_message_home():
    from app import commute
    from app.location import WIB
    d = commute.driver_of("Driver ditemukan! Pak Budi Santoso (B 1234 XYZ) menuju lokasimu, 4 menit lagi")
    assert d == {"driver": "Budi Santoso", "plate": "B 1234 XYZ", "eta_min": 4, "state": "coming"}
    assert commute.driver_of("Driver sudah sampai di lokasi jemput. F 4321 AB")["state"] == "arrived"
    assert commute.driver_of("Promo GoFood diskon 50%") is None
    t0 = datetime(2026, 10, 30, 18, 0, tzinfo=WIB)
    fixes = [(t0 + timedelta(minutes=m), -6.45, 106.80 + (0.01 * m if m < 4 else 0.04)) for m in range(0, 15, 2)]   # moving, then still
    st = [{"lat": -6.2025, "lon": 106.8234}, {"lat": -6.5957, "lon": 106.7907}]
    assert commute.stalled_min(fixes, st) == 10
    assert commute.stalled_min([(t0, -6.5958, 106.7908), (t0 + timedelta(minutes=12), -6.5958, 106.7908)], st) == 0   # waiting at a station is not "held"
    p = {"from": {"name": "Sudirman"}, "to": {"name": "Bogor"}}
    o = {"leave": "17:20", "dep": "17:30", "arr": "18:40", "arrive": "19:00", "ride": {"order_at": "18:32", "min": 15}}
    s = commute.steps("back", p, o, ["beli susu si Kecil"])
    assert [x["kind"] for x in s] == ["walk", "krl", "ride", "walk", "errand", "end"] and s[4]["text"] == "Titipan: beli susu si Kecil"
    msg = commute.home_message({"plan": p, "chosen": {**o, "delay_min": 9}})
    assert msg.startswith("Aku naik KRL 17.30 dari Sudirman, tiba di Bogor 18.40, sampai rumah sekitar 19.00") and "tertahan ±9 menit" in msg


@needs_db
async def test_the_live_trip_hears_gojek_moves_when_held_offers_options_and_tells_home(pool, monkeypatch):
    from app import commute, hub, krl, phone_agent
    from app.location import WIB
    await pool.execute("TRUNCATE commute_trips, notifications, location_history, settings_kv RESTART IDENTITY CASCADE")
    now = datetime.now(WIB)
    await pool.execute("""INSERT INTO settings_kv (key, value) VALUES ('app:commute', '{"home_station": "Bogor", "office_station": "Sudirman", "home_contact": "Istri"}'),
        ('commute:stationpos', '{"Bogor": {"lat": -6.5957, "lon": 106.7907}, "Sudirman": {"lat": -6.2025, "lon": 106.8234}}'),
        ('commute:errands', $1)""", {"day": now.date().isoformat(), "items": ["beli susu si Kecil"]})
    dep = (now - timedelta(minutes=20)).strftime("%H:%M")
    arr = (now + timedelta(minutes=40)).strftime("%H:%M")
    chosen = {"leave": (now - timedelta(minutes=30)).strftime("%H:%M"), "dep": dep, "arr": arr, "arrive": (now + timedelta(minutes=60)).strftime("%H:%M"),
              "ride": {"order_at": (now + timedelta(minutes=32)).strftime("%H:%M"), "min": 15, "cost": 18000}}
    plan = {"from": {"id": "SUD", "name": "Sudirman"}, "to": {"id": "BOO", "name": "Bogor"}, "options": [], "car": {}}
    tid = await pool.fetchval("INSERT INTO commute_trips (direction, plan, chosen, status, started_at) VALUES ('back', $1, $2, 'active', now() - interval '30 minutes') RETURNING id", plan, chosen)
    v = await commute.trip_view(tid)
    assert v["errands"] == ["beli susu si Kecil"] and v["steps"][-2]["kind"] == "errand"
    for m in range(14, -1, -2):   # moving until 10 minutes ago, then still between stations
        await pool.execute("INSERT INTO location_history (lat, lon, at) VALUES ($1, $2, now() - make_interval(mins => $3))", -6.40, 106.80 + (0.01 * (14 - m) if m > 10 else 0.04), m)
    await pool.execute("INSERT INTO notifications (app, package, title, text, posted_at) VALUES ('Gojek', 'com.gojek.app', 'Driver ditemukan', 'Pak Budi (B 1234 XYZ) menuju lokasimu, 4 menit lagi', now())")
    hub.reset()
    sent = []

    async def listen(e):
        sent.append(e)
    hub.register(listen)
    did = await commute.watch(now)
    assert "driver" in did and "held" in did
    t = await commute.trip_view(tid)
    assert t["driver"]["plate"] == "B 1234 XYZ" and t["chosen"]["delay_min"] == 10
    assert t["chosen"]["ride"]["order_at"] == (now + timedelta(minutes=42)).strftime("%H:%M")      # the ride home moves with the delay
    trip_ev = [e for e in sent if e.get("type") == "trip"][-1]
    assert "Budi" in trip_ev["driver"] and trip_ev["leg"].count("/") == 1 and "tertahan" in trip_ev["text"]
    assert "driver" not in await commute.watch(now)                                                 # the same notification once

    async def trips(a, b, after, limit=6):
        return [{"train": "T9", "dep": after + 3, "arr": after + 70, "legs": 1, "route": "SUD-BOO"}]

    async def leg(a, b, mode="driving"):
        return 15, 5.0
    monkeypatch.setattr(krl, "trips", trips)
    monkeypatch.setattr(commute, "_leg", leg)
    alt = await commute.alternatives(tid)
    assert alt["options"][0]["dep"] and alt["car"]["cost"] > 0
    sw = await commute.switch(tid, 0, "test")
    assert sw["chosen"]["dep"] == alt["options"][0]["dep"] and sw["chosen"]["replanned_from"] == dep
    ops = []

    async def op(name, **a):
        ops.append((name, a))
        return {"ok": True, "title": a["title"]}
    monkeypatch.setattr(phone_agent, "op", op)
    r = await commute.tell_home(tid)
    assert r["sent"] and ops[0][0] == "notif_reply" and ops[0][1]["title"] == "Istri" and "sampai rumah" in ops[0][1]["text"]
    hub.reset()
