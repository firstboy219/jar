"""ADR-087 wave 9 gap batch G: the brain workshop proposes its own fixes and tests them all (only better ones go to 10%), a job's numbers
week on week; the flow's inputs, router speed, tools, memory and queue, a day replayed, every step's model/cost or "no AI"; the
investment being carried out with its checks; a meeting paused (nothing kept) or made confidential mid-way, with its room; a chat turn's
time and cost; a mission paused; memory's routine steps and what skills saved; a result's confidence; a failed ride to finish in Gojek;
"do it for me" only in approved apps (never Pluang); one answer to email + WhatsApp; a room change put on the calendar."""
import json
import os
from datetime import date, datetime, timedelta, timezone

import httpx
import pytest

from tests.test_integration import pool  # noqa: F401  (fixture)

needs_db = pytest.mark.skipif(not os.getenv("TEST_DATABASE_URL"), reason="needs TEST_DATABASE_URL")


def reply(content, usage=None):
    out = {"choices": [{"message": {"content": content if isinstance(content, str) else json.dumps(content)}}]}
    if usage:
        out["usage"] = usage
    return out


# ---------- pure ----------

def test_room_change_approved_app_ride_status_and_confidence():
    from app import attention, bimbing, commute, results
    assert attention.room_change("Info: ruang rapat pindah ke Lt 5 Melati ya, jam tetap") == "Lt 5 Melati"
    assert attention.room_change("Meeting room changed to Orchid 2.") == "Orchid 2"
    assert attention.room_change("Rapat jam 10 di ruang biasa") == ""
    assert bimbing.approved_app("com.gojek.app") == "gojek" and bimbing.approved_app("Pluang") == "pluang" and bimbing.approved_app("com.bca") is None
    assert bimbing.clean_step({"instruksi": "Ketuk", "sisa": "3"})["sisa"] == 3 and bimbing.clean_step({"sisa": "x"})["sisa"] == 0
    ev = [{"kind": "ride", "text": "x"}, {"kind": "ride_failed", "text": "GoRide belum terpesan: saldo", "at": "t", "data": {"error": "saldo"}}]
    assert commute.ride_status(ev)["ok"] is False and commute.ride_status(ev)["error"] == "saldo"
    assert commute.ride_status(ev + [{"kind": "ride_dismissed"}]) is None and commute.ride_status([]) is None
    data, _ = results.split('Ok.\n```hasil\n{"ringkasan": "Harga turun", "keyakinan": "Sedang", "tautan": [{"teks": "a", "url": "https://a.id"}]}\n```')
    assert data["keyakinan"] == "sedang" and len(data["tautan"]) == 1


# ---------- brain workshop & flow ----------

@needs_db
async def test_workshop_proposes_and_tests_itself_and_the_flow_tells_more(pool, monkeypatch):
    from app import alur, bengkel, gateway, master
    await pool.execute("TRUNCATE flow_runs, flow_samples, brain_versions, settings_kv, llm_usage RESTART IDENTITY CASCADE")
    bengkel.invalidate()
    for i in range(4):
        await pool.execute("INSERT INTO flow_runs (feature, action, goal, lane, status, trigger, started_at, finished_at) VALUES ('kopi', 'pesan', 'x', 'hermes', $1, 'owner', now() - interval '1 day', now() - interval '1 day' + interval '20 seconds')",
                           "failed" if i else "done")

    async def fake(lane, body, **kw):
        sysmsg = body["messages"][0]["content"]
        if "insinyur" in sysmsg:
            return reply({"lane": "auto", "instruction": "Periksa harga dulu sebelum bayar.", "alasan": "sering gagal di pembayaran"})
        if "juri" in sysmsg:
            c = body["messages"][1]["content"]
            return reply({"pemenang": "1" if "JAWABAN 1:\nBARU" in c else "2", "alasan": "lebih patuh aturan"})
        rule = any("SELALU sebut tenggat" in str(m.get("content")) for m in body["messages"])
        return reply("BARU" if rule else "LAMA", {"total_tokens": 120, "cost": 0.0004})
    monkeypatch.setattr(gateway, "complete", fake)

    out = await bengkel.self_propose()
    assert [o["job"] for o in out] == ["kopi:pesan"]
    v = await pool.fetchrow("SELECT created_by, status, config FROM brain_versions WHERE job = 'kopi:pesan'")
    assert v["created_by"] == "jarvis" and v["status"] == "draft" and "harga" in v["config"]["instruction"]
    assert await bengkel.self_propose() == []                                                        # once a fortnight per job

    r = await master.run(master.Job("brief", "compose", "tulis brief", messages=[{"role": "system", "content": "Tulis brief."}, {"role": "user", "content": "x"}]))
    steps = await pool.fetchval("SELECT steps FROM flow_runs WHERE id = $1", r["run_id"])
    jawab = next(s for s in steps if s["stage"] == "jawab")
    assert jawab["tokens"] == 120 and jawab["cost"] == 0.0004 and jawab["lane"] == "ringan"

    async def skill():
        return {"n": 1}
    r2 = await master.run(master.Job("bisnis", "sinkron", "ambil angka", skill=skill))
    assert any(s.get("no_ai") for s in await pool.fetchval("SELECT steps FROM flow_runs WHERE id = $1", r2["run_id"]))

    good = await pool.fetchval("INSERT INTO brain_versions (job, config, created_by) VALUES ('brief:compose', $1, 'owner') RETURNING id",
                               {"lane": "auto", "instruction": "SELALU sebut tenggat."})
    t = await bengkel.test_all("owner")
    res = {x["job"]: x["result"] for x in t["tested"]}
    assert res["brief:compose"] == "dipasang 10%" and res["kopi:pesan"].startswith("belum ada contoh")
    assert await pool.fetchval("SELECT status FROM brain_versions WHERE id = $1", good) == "canary"
    m = await bengkel.metrics("kopi:pesan")
    assert m["runs"] == 4 and m["fail_pct"] == 75 and m["p50_s"] == 20.0
    jv = await bengkel.job_view("kopi:pesan")
    assert jv["metrics"]["ok_pct"] == 25 and jv["metrics_prev"]["runs"] == 0
    assert any(d["created_by"] == "jarvis" for d in await bengkel.drafts())

    v = await alur.view(48)
    assert v["triggers"]["owner"] >= 5 and v["router"]["avg_s"] >= 0 and "hp" in v["tools"] and v["memory"]["used"] >= 1 and "workers" in v["queue"]
    live = await pool.fetchval("INSERT INTO flow_runs (feature, action, goal, lane, status) VALUES ('kopi', 'pesan', 'x', 'hermes', 'waiting') RETURNING id")
    assert next(x for x in (await alur.view(24))["live"] if x["id"] == live)["path"] == ["router", "hermes", "hermes"]
    day = (datetime.now(timezone(timedelta(hours=7))) - timedelta(days=1)).date().isoformat()
    rp = await alur.replay(day)
    assert len(rp["runs"]) >= 4 and {"t", "lane", "status", "trigger"} <= set(rp["runs"][0])


# ---------- execution, meeting, chat, missions, memory ----------

@needs_db
async def test_execution_meeting_chat_mission_and_memory(pool, monkeypatch, tmp_path):
    from app import appsettings, devices, invest, main, meetings
    await pool.execute("TRUNCATE invest_snapshots, invest_proposals, meetings, calendar_events, flow_runs, llm_usage, routines, settings_kv RESTART IDENTITY CASCADE")
    monkeypatch.setattr(meetings, "ROOT", tmp_path / "meet")
    sid = await pool.fetchval("INSERT INTO invest_snapshots (data) VALUES ($1) RETURNING id", {"total": 1, "kas": 0, "aset": [{"nama": "Emas", "kode": "", "jenis": "emas", "nilai": 1, "harga": 1650000}]})
    await pool.execute("""INSERT INTO invest_proposals (snapshot_id, data, status, chosen, decided_by, decided_at) VALUES ($1, $2, 'running', 'A', 'device:HP', now())""", sid,
                       {"opsi": [{"id": "A", "judul": "Tambah emas", "aksi": [{"jenis": "beli", "aset": "Emas", "nominal": 500000}]}]})
    x = await invest.exec_view()
    checks = {c["label"].split(" ")[0]: c["ok"] for c in x["checks"]}
    assert x["status"] == "running" and checks["Password"] and checks["Batas"] and checks["Pengaman"] and checks["Anggaran"] is None

    await pool.execute("INSERT INTO calendar_events (source, ext_id, title, start_at, end_at, location) VALUES ('outlook', 'e1', 'Weekly', now(), now() + interval '1 hour', 'Lt 5 Melati')")
    m = await meetings.create("Weekly", False, True, participants=["Sari", "Budi"])
    mid = str(m["id"])
    await meetings.set_paused(mid, True, "owner")
    r = await meetings.add_chunk(mid, 0, b"audio", "ogg")
    assert r.get("paused") and not meetings.chunk_files(mid)                                          # paused: nothing kept
    await meetings.set_paused(mid, False, "owner")
    card = await meetings.desk_card()
    assert card["room"] == "Lt 5 Melati" and card["participants"] == ["Sari", "Budi"] and card["paused"] is False
    assert await meetings.set_confidential(mid, True, "owner") is True
    assert await pool.fetchval("SELECT confidential FROM meetings WHERE id = $1::uuid", mid)

    since = datetime.now(timezone.utc) - timedelta(seconds=1)
    await pool.execute("INSERT INTO llm_usage (category, caller, provider, model, cost_usd, ok, session_id) VALUES ('ngobrol', 'chat', 'openrouter', 'deepseek/v4', 0.0021, true, 'app-1')")
    meta = await main._turn_meta("app-1", since, 3.24)
    assert meta == {"seconds": 3.2, "calls": 1, "cost": 0.0021, "model": "deepseek/v4"}

    await pool.execute("INSERT INTO flow_runs (feature, action, goal, lane, status, cost_usd, started_at) VALUES ('brief', 'compose', 'x', 'ringan', 'done', 0.002, now() - interval '40 days'), "
                       "('brief', 'compose', 'x', 'skill', 'done', 0, now()), ('brief', 'compose', 'x', 'skill', 'done', 0, now())")
    from app import appapi
    assert await appapi.saved_this_month() == 0.004
    rid = await pool.fetchval("""INSERT INTO routines (app, name, intent, keys, params, steps) VALUES ('gojek', 'pesan goride', 'pesan goride', '{}', '{"tujuan": "alamat tujuan"}',
        '[{"op": "open", "app": "gojek"}, {"op": "tap", "target": "GoRide"}, {"op": "type", "target": "{tujuan}"}]') RETURNING id""")
    _, token = await devices.create("HP", "test", scope="owner")
    h = {"Authorization": f"Bearer {token}"}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url="http://t") as c:
        st = (await c.get(f"/api/v1/app/memory/routine/{rid}", headers=h)).json()
        assert [s["text"] for s in st["steps"]] == ["Buka gojek", "Ketuk GoRide", "Ketik {tujuan}"]
        assert (await c.post("/api/v1/app/missions/999999/pause", headers=h)).status_code == 409
        assert (await c.get("/api/v1/app/invest/exec", headers=h)).json()["exec"]["option"]["judul"] == "Tambah emas"
        assert (await c.post(f"/api/v1/app/meeting/{mid}/pause", json={"on": True}, headers=h)).json() == {"paused": True}
        mem = (await c.get("/api/v1/app/memory", headers=h)).json()
        assert mem["saved_usd"] == 0.004
    assert appsettings


# ---------- rides, guide, inbox ----------

@needs_db
async def test_failed_ride_guide_for_me_reply_both_and_room(pool, monkeypatch):
    from app import attention, bimbing, commute, devices, main, outlook, phone_agent
    await pool.execute("TRUNCATE commute_trips, guide_sessions, inbox_items, calendar_events, flow_runs, tasks, settings_kv RESTART IDENTITY CASCADE")
    tid = await pool.fetchval("INSERT INTO commute_trips (direction, status, plan, chosen) VALUES ('out', 'active', $1, $2) RETURNING id",
                              {"from": {"name": "Bogor"}, "to": {"name": "Sudirman"}, "car": {"cost": 90000}, "options": []},
                              {"leave": "07:00", "dep": "07:15", "arr": "08:10", "arrive": "08:30", "ride": {"cost": 17000}, "walk_min": 6})
    await commute._ride_done(0, {"ok": False, "text": "Saldo GoPay kurang", "data": {"trip": tid, "goal": "Pesan GoRide"}, "task_id": 5})
    v = await commute.trip_view(tid)
    assert v["ride"]["ok"] is False and "Saldo" in v["ride"]["error"]

    jobs = []

    async def request(goal, app, actor, session_id=None, scheduled=False, project=None, by="jadwal"):
        t = await pool.fetchval("INSERT INTO tasks (session_id, title, instruction, kind, status) VALUES ('phone', $1, $2, 'owner', 'running') RETURNING id", app, goal)
        jobs.append((app, goal))
        return {"id": len(jobs), "task_id": t, "status": "approved"}
    monkeypatch.setattr(phone_agent, "request", request)
    g = await bimbing.start("pesan GoRide ke stasiun")
    await pool.execute("UPDATE guide_sessions SET steps = $2 WHERE id = $1", g["id"], [{"n": 1, "instruksi": "Ketuk GoRide", "app": "com.gojek.app"}])
    r = await bimbing.do_for_me(g["id"])
    assert r["app"] == "gojek" and jobs[-1] == ("gojek", "pesan GoRide ke stasiun")
    g2 = await bimbing.start("jual emas")
    await pool.execute("UPDATE guide_sessions SET steps = $2 WHERE id = $1", g2["id"], [{"n": 1, "instruksi": "Ketuk Jual", "app": "com.EmasDigi"}])
    with pytest.raises(bimbing.GuideError):
        await bimbing.do_for_me(g2["id"])                                                         # trades only through Investasi
    g3 = await bimbing.start("aktifkan notifikasi BCA")
    await pool.execute("UPDATE guide_sessions SET steps = $2 WHERE id = $1", g3["id"], [{"n": 1, "instruksi": "Ketuk Akun", "app": "com.bca"}])
    with pytest.raises(bimbing.GuideError):
        await bimbing.do_for_me(g3["id"])

    await pool.execute("""INSERT INTO inbox_items (source, ext_id, sender, sender_addr, subject, snippet, received_at, triage, topic, thread, data) VALUES
        ('outlook', 'M1', 'Sari', 'sari@x.id', 'Rapat Weekly', 'Ruang rapat pindah ke Lt 5 Melati ya', now(), 'needs', 'weekly', 'm1', '{}'),
        ('whatsapp', 'W1', 'Sari', '', '', 'Mas, rapat weekly pindah ruang ya', now(), 'needs', 'weekly', 'wa-sari', '{"conversation": "Sari"}')""")
    await pool.execute("INSERT INTO calendar_events (source, ext_id, title, start_at, end_at, location) VALUES ('outlook', 'EV1', 'Weekly Tim Produk', now() + interval '2 hours', now() + interval '3 hours', 'Lt 3')")
    lst = await attention.listing()
    head = lst["needs"][0]
    assert {i["source"] for i in head["items"]} == {"outlook", "whatsapp"}
    room = next(i["room"] for i in head["items"] if i.get("room"))
    assert room["room"] == "Lt 5 Melati" and room["title"] == "Weekly Tim Produk" and room["old"] == "Lt 3"

    sent, patched = [], []

    async def op(name, **kw):
        sent.append(kw)
        return {"title": kw.get("title")}
    monkeypatch.setattr(phone_agent, "op", op)

    async def mk(ext, text):
        return "D9"

    async def upd(event_id, location):
        patched.append((event_id, location))
        return {}
    monkeypatch.setattr(outlook, "create_reply_draft", mk)
    monkeypatch.setattr(outlook, "update_event_location", upd)

    async def body(ext):
        return "Ruang rapat pindah ke Lt 5 Melati ya"
    monkeypatch.setattr(outlook, "message_body", body)
    email = await pool.fetchval("SELECT id FROM inbox_items WHERE ext_id = 'M1'")
    wa = await pool.fetchval("SELECT id FROM inbox_items WHERE ext_id = 'W1'")
    _, token = await devices.create("HP", "test", scope="owner")
    h = {"Authorization": f"Bearer {token}"}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url="http://t") as c:
        r = (await c.post("/api/v1/app/inbox/both", json={"email_id": email, "wa_id": wa, "text": "Siap, terima kasih infonya."}, headers=h)).json()
        assert r["wa"]["sent"] and sent[-1]["text"] == "Siap, terima kasih infonya." and r["draft"]["body"] == "Siap, terima kasih infonya."
        assert await pool.fetchval("SELECT draft->>'draft_id' FROM inbox_items WHERE id = $1", email) == "D9"             # sending email stays his Kirim
        r = (await c.post("/api/v1/app/inbox/room", json={"event_id": room["event_id"], "room": "Lt 5 Melati"}, headers=h)).json()
        assert r == {"title": "Weekly Tim Produk", "room": "Lt 5 Melati"} and patched == [("EV1", "Lt 5 Melati")]
        assert await pool.fetchval("SELECT location FROM calendar_events WHERE ext_id = 'EV1'") == "Lt 5 Melati"
        assert (await c.post(f"/api/v1/app/commute/trip/{tid}/ride/dismiss", headers=h)).json() == {"ok": True}
        assert (await commute.trip_view(tid))["ride"] is None
    assert date.today()
