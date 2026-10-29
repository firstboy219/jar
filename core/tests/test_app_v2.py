"""ADR-087: the app v2 foundation — the master flow (router → Hermes → skill/ringan/berat/Hermes), the front page, the owner's places,
the feature settings, and the app API every screen calls."""
import os
from datetime import datetime, timedelta

import httpx
import pytest

from tests.test_integration import pool  # noqa: F401  (fixture)

needs_db = pytest.mark.skipif(not os.getenv("TEST_DATABASE_URL"), reason="needs TEST_DATABASE_URL")


# ---------- pure ----------

def test_hermes_picks_the_way_a_job_is_done():
    from app import master
    base = dict(has_skill=False, skill_streak=0, tools=False, phone=False, routine=False, heavy=False, has_prompt=True, light_on=True, stats={})
    assert master.choose(**{**base, "has_skill": True})[0] == "skill"                       # a fixed procedure: no AI
    lane, why = master.choose(**{**base, "has_skill": True, "skill_streak": 3})               # … that keeps failing: AI takes over
    assert lane == "ringan" and "gagal" in why
    assert master.choose(**{**base, "heavy": True})[0] == "berat"
    assert master.choose(**base)[0] == "ringan"
    assert master.choose(**{**base, "light_on": False})[0] == "berat"
    assert master.choose(**{**base, "stats": {"ringan": (10, 4)}})[0] == "berat"             # learned: the light brain fails here
    assert master.choose(**{**base, "stats": {"ringan": (10, 9)}})[0] == "ringan"
    assert master.choose(**{**base, "tools": True})[0] == "hermes"
    assert master.choose(**{**base, "phone": True, "routine": True})[0] == "skill"            # a learned phone routine replays without AI
    assert master.choose(**{**base, "phone": True})[0] == "hermes"
    with pytest.raises(master.FlowError):
        master.choose(**{**base, "has_prompt": False})


def test_json_is_found_in_a_model_answer():
    from app import master
    assert master.parse_json('Berikut:\n```json\n{"a": 1}\n```') == {"a": 1}
    assert master.parse_json('ok [1, 2] selesai') == [1, 2]
    with pytest.raises(ValueError):
        master.parse_json("tidak ada json")


def test_the_moment_and_its_shortcuts():
    from app import home
    from app.location import WIB
    t = datetime(2026, 10, 29, 6, 30, tzinfo=WIB)     # a Thursday
    assert home.slot_of(t) == "pagi" and home.slot_of(t.replace(hour=4)) == "subuh" and home.slot_of(t.replace(hour=23)) == "larut"
    assert home.slot_of(t.replace(hour=14, minute=30)) == "siang" and home.slot_of(t.replace(hour=20)) == "malam"
    assert "gajian" in home.tags_of(t.replace(day=25), "malam") and "gajian" in home.tags_of(t.replace(day=30), "malam")
    assert "akhir-pekan" in home.tags_of(datetime(2026, 10, 31, 10, tzinfo=WIB), "kerja")
    m = home.Moment(now=t, slot="pagi", tags={"pagi"})
    first = home.rank_shortcuts([], m)
    assert first[0] in ("musik", "berangkat", "brief") and len(first) == 7            # what fits the morning comes first
    learned = home.rank_shortcuts([("bisnis", t - timedelta(days=d)) for d in range(1, 8)], m)
    assert learned[0] == "bisnis"                                                     # what he opens at this hour every day wins
    assert all(home.FEATURES[[f["id"] for f in home.FEATURES].index(i)]["route"].startswith("#/") for i in learned)


def test_the_hero_is_the_best_card_that_asks_for_something():
    from app import home
    cards = [{"id": "a", "kind": "tasks", "score": 90}, {"id": "b", "kind": "needs", "score": 80, "cta": "Tinjau"},
             {"id": "c", "kind": "needs", "score": 70, "cta": "Tinjau"}, {"id": "d", "kind": "player", "score": 10}]
    hero, side = home.pick(cards)
    assert hero["id"] == "b" and [c["id"] for c in side] == ["a", "d"]               # one card per kind beside the hero


def test_places_are_learned_from_the_trail():
    from app import places
    from app.location import WIB
    home_pt, office_pt = (-6.595, 106.79), (-6.21, 106.82)
    trail = []
    for d in range(10):
        day = datetime(2026, 10, 12, tzinfo=WIB) + timedelta(days=d)
        trail.append({"lat": home_pt[0] + 0.0001 * (d % 3), "lon": home_pt[1], "at": day.replace(hour=23)})
        if day.weekday() < 5:
            trail.append({"lat": office_pt[0], "lon": office_pt[1] + 0.0001 * (d % 2), "at": day.replace(hour=11)})
    found = places.learn(trail)
    assert places.distance_m(found["rumah"][0], found["rumah"][1], *home_pt) < 100
    assert places.distance_m(found["kantor"][0], found["kantor"][1], *office_pt) < 100
    plist = [{"name": "rumah", "lat": home_pt[0], "lon": home_pt[1], "radius_m": 200}]
    assert places.at_place(home_pt[0] + 0.0005, home_pt[1], plist) == "rumah"
    assert places.at_place(office_pt[0], office_pt[1], plist) is None


def test_settings_keep_only_known_fields_of_the_right_type():
    from app import appsettings
    out = appsettings.merge(appsettings.DEFAULTS["coffee"], {"max_price": 60000, "evil": 1, "apps": ["kopikenangan"]})
    assert out["max_price"] == 60000 and "evil" not in out and out["apps"] == ["kopikenangan"] and out["enabled"] is True
    with pytest.raises(appsettings.SettingError):
        appsettings.merge(appsettings.DEFAULTS["coffee"], {"max_price": "mahal"})


# ---------- with the database ----------

async def _fresh(pool):
    await pool.execute("TRUNCATE flow_runs, app_usage, location_history, places, place_events RESTART IDENTITY")


@needs_db
async def test_a_skill_job_runs_without_ai_and_is_recorded(pool, monkeypatch):
    from app import hub, master
    await _fresh(pool)
    seen = []

    async def tap(ev):
        seen.append(ev)
    hub.tap(tap)

    async def poll():
        return {"sales": 12}
    r = await master.run(master.Job("bisnis", "poll", "ambil angka penjualan hari ini", trigger="schedule", skill=poll))
    assert r["status"] == "done" and r["lane"] == "skill" and r["result"] == {"sales": 12}
    row = await pool.fetchrow("SELECT * FROM flow_runs WHERE id = $1", r["run_id"])
    assert row["status"] == "done" and row["lane"] == "skill" and [s["stage"] for s in row["steps"]][:2] == ["router", "hermes"]
    assert any(e.get("type") == "flow" and e.get("stage") == "router" for e in seen)


@needs_db
async def test_a_light_answer_that_is_not_json_goes_to_the_heavy_brain(pool, monkeypatch):
    from app import gateway, master
    await _fresh(pool)
    asked = []

    async def fake(category, body, **kw):
        asked.append(category)
        content = "maaf" if category == "ringan" else '{"ok": true}'
        return {"choices": [{"message": {"content": content}}], "jarvis_route": {"model": f"m-{category}"}}
    monkeypatch.setattr(gateway, "complete", fake)
    r = await master.run(master.Job("brief", "compose", "tulis ringkasan berita", messages=[{"role": "user", "content": "x"}], json_out=True))
    assert asked == ["ringan", "berat"] and r["status"] == "done" and r["lane"] == "berat" and r["result"] == {"ok": True}


@needs_db
async def test_a_skill_that_cannot_do_it_hands_the_job_to_ai(pool, monkeypatch):
    from app import gateway, master
    await _fresh(pool)

    async def fake(category, body, **kw):
        return {"choices": [{"message": {"content": "jawaban AI"}}]}
    monkeypatch.setattr(gateway, "complete", fake)

    async def miss():
        raise master.SkillMiss("data tidak lengkap")
    r = await master.run(master.Job("kopi", "promo", "cek promo kopi", skill=miss, messages=[{"role": "user", "content": "x"}]))
    assert r["status"] == "done" and r["lane"] == "ringan" and r["result"] == "jawaban AI"
    assert "AI mengambil alih" in await pool.fetchval("SELECT why FROM flow_runs WHERE id = $1", r["run_id"])


@needs_db
async def test_a_tools_job_becomes_a_hermes_mission_and_its_result_comes_back(pool, monkeypatch):
    from app import master, workers
    await _fresh(pool)
    got = {}

    async def spawn(title, instruction, session_id, actor, **kw):
        assert kw["kind"] == "feature"
        return {"id": await pool.fetchval("INSERT INTO tasks (session_id, title, instruction, kind, status) VALUES ($1, $2, $3, 'feature', 'running') RETURNING id",
                                          session_id, title, instruction)}
    monkeypatch.setattr(workers, "spawn", spawn)
    import app.master as mod

    async def done(run_id, result):
        got.update(result)
    monkeypatch.setattr(mod, "_test_done", done, raising=False)
    r = await master.run(master.Job("bioskop", "jadwal", "cari jadwal film hari ini", tools=True, instruction="buka situs bioskop", on_done="master:_test_done"))
    assert r["status"] == "waiting" and r["lane"] == "hermes"
    await pool.execute("UPDATE tasks SET status = 'completed', result = 'Film A 19.15' WHERE id = $1", r["task_id"])
    await master.on_task_finished(r["task_id"])
    assert got["ok"] and got["text"] == "Film A 19.15"
    assert await pool.fetchval("SELECT status FROM flow_runs WHERE id = $1", r["run_id"]) == "done"


@needs_db
async def test_arriving_and_leaving_a_place_are_events(pool):
    from app import places
    await _fresh(pool)
    await places.set_place("kantor", -6.21, 106.82, radius_m=200)
    assert await places.observe(-6.30, 106.90, 20) is None
    assert await places.observe(-6.2101, 106.8201, 20) == "kantor"
    assert await places.observe(-6.30, 106.90, 20) is None
    kinds = [r["kind"] for r in await pool.fetch("SELECT kind FROM place_events ORDER BY id")]
    assert kinds == ["arrive", "leave"]


@needs_db
async def test_the_app_api_answers_every_wave0_screen(pool, monkeypatch):
    from app import devices, main, status
    await _fresh(pool)

    async def no_probe():
        return [{"name": "Hermes Agent", "ok": True, "detail": ""}]
    monkeypatch.setattr(status, "check_all", no_probe)
    _, token = await devices.create("HP", "test", scope="owner")
    h = {"Authorization": f"Bearer {token}"}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url="http://t") as c:
        for path in ("/api/v1/app/home", "/api/v1/app/home?slot=subuh", "/api/v1/app/features", "/api/v1/app/needs", "/api/v1/app/missions",
                     "/api/v1/app/pages", "/api/v1/app/places", "/api/v1/app/memory", "/api/v1/app/control",
                     "/api/v1/app/settings/coffee", "/api/v1/app/chat/history?session_id=x"):
            r = await c.get(path, headers=h)
            assert r.status_code == 200, (path, r.text)
        home = (await c.get("/api/v1/app/home?slot=subuh", headers=h)).json()
        assert home["slot"] == "subuh" and len(home["shortcuts"]) == 7 and home["greeting"]
        assert (await c.post("/api/v1/app/opened", json={"feature": "kopi"}, headers=h)).json()["ok"] is True
        assert (await c.post("/api/v1/app/opened", json={"feature": "bukan-fitur"}, headers=h)).json()["ok"] is False
        put = await c.put("/api/v1/app/settings/coffee", json={"max_price": 50000}, headers=h)
        assert put.json()["max_price"] == 50000
        assert (await c.put("/api/v1/app/settings/nope", json={}, headers=h)).status_code == 404
        loc = await c.post("/api/v1/app/location", json={"lat": -6.2, "lon": 106.8, "accuracy_m": 10}, headers=h)
        assert loc.status_code == 200
        assert (await c.get("/app/", headers=h)).status_code == 200 and "JARVIS" in (await c.get("/app/index.html")).text
        assert (await c.get("/app/../main.py")).status_code == 404
        assert (await c.get("/api/v1/app/home")).status_code == 401
        basic = (await devices.create("tamu", "test", scope="basic"))[1]
        assert (await c.get("/api/v1/app/home", headers={"Authorization": f"Bearer {basic}"})).status_code == 403
