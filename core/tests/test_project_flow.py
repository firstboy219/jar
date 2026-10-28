"""ADR-079: the order a project's workers work in (parallel / one after the other), the owner's pick between stages (notification + popup),
a start N minutes before the picked time, and a project run that needs no admin password."""
import os
from datetime import datetime, timedelta, timezone

import pytest

from tests.test_integration import pool  # noqa: F401  (fixture)

needs_db = pytest.mark.skipif(not os.getenv("TEST_DATABASE_URL"), reason="needs TEST_DATABASE_URL")
WIB = timezone(timedelta(hours=7))


def test_roles_run_together_unless_they_wait_for_the_one_before():
    from app import project_flow
    assert project_flow.stages_of([{}, {}, {}]) == [0, 0, 0]
    assert project_flow.stages_of([{}, {"after_prev": True}, {}, {"after_prev": True}]) == [0, 1, 1, 2]
    assert project_flow.stages_of([{"after_prev": True}]) == [0]                      # the first role is always first


def test_the_first_clock_time_in_a_text_is_found():
    from app import project_flow
    assert project_flow.time_of("KRL 06:27 → kantor 07:05") == "06:27" and project_flow.time_of("berangkat 6.27") == "06:27"
    assert project_flow.time_of("Rp 25.000 tiba 1234") == "" and project_flow.time_of("") == ""


def test_the_options_come_from_the_workers_pick_list_or_their_first_table():
    from app import project_flow
    doc = {"pilihan": [{"label": "KRL 06:27 → 07:05", "waktu": "06:02", "detail": "dari rumah 06:02"}, {"label": "KRL 07:09 → 07:52", "waktu": ""}]}
    got = project_flow.options_from([(doc, "")])
    assert [o["waktu"] for o in got] == ["06:02", "07:09"] and got[0]["detail"] == "dari rumah 06:02"
    table = {"tabel": [{"judul": "Jadwal", "kolom": ["#", "Berangkat", "Tiba"], "baris": [["1", "06:27", "07:05"], ["2", "07:09", "07:52"], ["1", "06:27", "07:05"]]}]}
    rows = project_flow.options_from([(table, "")])
    assert [o["label"] for o in rows] == ["1 · 06:27 · 07:05", "2 · 07:09 · 07:52"] and rows[0]["waktu"] == "06:27"   # a duplicate row is one option
    assert project_flow.options_from([({}, "teks saja")]) == []


def test_the_next_stage_starts_n_minutes_before_the_picked_time():
    from app import project_flow
    now = datetime(2026, 10, 28, 5, 0, tzinfo=WIB)
    opt = {"label": "KRL", "waktu": "06:02"}
    assert project_flow.start_time(opt, 5, now) == datetime(2026, 10, 28, 5, 57, tzinfo=WIB)
    assert project_flow.start_time(opt, None, now) is None and project_flow.start_time({"label": "x", "waktu": ""}, 5, now) is None
    assert project_flow.start_time(opt, 5, datetime(2026, 10, 28, 5, 59, tzinfo=WIB)) is None       # already due: at once
    assert project_flow.start_time(opt, 5, datetime(2026, 10, 28, 6, 10, tzinfo=WIB)) is None        # 8 minutes late: still go
    with pytest.raises(project_flow.FlowError, match="sudah lewat"):
        project_flow.start_time(opt, 5, datetime(2026, 10, 28, 6, 30, tzinfo=WIB))                  # the train left half an hour ago


def test_the_next_stage_is_told_what_the_last_found_and_what_the_owner_picked():
    from app import project_flow
    text = project_flow.context_text([{"role": "Asisten", "doc": {"ringkasan": "5 jadwal"}, "text": "tabel jadwal"}],
                                     {"label": "KRL 06:27", "detail": "dari rumah 06:02", "waktu": "06:02"})
    assert "HASIL TAHAP SEBELUMNYA" in text and "— Asisten:" in text and "5 jadwal" in text and "tabel jadwal" in text
    assert "PILIHAN PEMILIK" in text and "KRL 06:27 — dari rumah 06:02 · jam 06:02" in text
    assert project_flow.context_text([], None) == ""


def test_a_role_cannot_ask_the_owner_unless_it_waits_for_the_one_before():
    from app import projects
    base = {"name": "P", "roles": [{"role": "A"}, {"role": "B", "after_prev": True, "ask_owner": True, "start_offset_min": 5}]}
    c = projects.clean(base)
    assert [r["stage"] for r in c["roles"]] == [0, 1] and c["roles"][1]["ask_owner"] and c["roles"][1]["start_offset_min"] == 5
    with pytest.raises(projects.ProjectError, match="setelah peran sebelumnya"):
        projects.clean({"name": "P", "roles": [{"role": "A"}, {"role": "B", "ask_owner": True}]})
    with pytest.raises(projects.ProjectError, match="0–180"):
        projects.clean({"name": "P", "roles": [{"role": "A"}, {"role": "B", "after_prev": True, "ask_owner": True, "start_offset_min": 500}]})
    first = projects.clean({"name": "P", "roles": [{"role": "A", "after_prev": True}]})["roles"][0]
    assert not first["after_prev"] and first["stage"] == 0


def _hub(monkeypatch):
    from app import hub
    sent = []

    async def broadcast(ev):
        sent.append(ev)
        return 1
    monkeypatch.setattr(hub, "broadcast", broadcast)
    return sent


async def _project(pool, main, monkeypatch, offset=5):
    from app import workers
    started = []
    monkeypatch.setattr(workers, "_start", lambda task_id, context="": started.append(task_id))
    await pool.execute("TRUNCATE projects, phone_runs, owner_choices CASCADE")
    dev = {"name": "HP pemilik", "scope": "owner"}
    p = await main.projects_create(main.ProjectIn(name="Berangkat kerja", goal="ke kantor naik KRL", roles=[
        {"role": "Asisten", "brief": "cek jadwal KRL"},
        {"role": "Pesan gojek", "brief": "pesan GoRide ke stasiun", "app": "gojek", "after_prev": True, "ask_owner": True, "start_offset_min": offset}]), device=dev)
    return p, dev, started


@needs_db
async def test_the_owner_picks_between_the_stages_and_the_ride_is_ordered_before_the_picked_time(pool, monkeypatch):
    from app import main, project_flow
    sent = _hub(monkeypatch)
    p, dev, started = await _project(pool, main, monkeypatch)
    r = await main.projects_run(p["id"], device=dev)
    assert len(r["tasks"]) == 1 and len(started) == 1                                           # only the first stage
    assert "pilihan" in await pool.fetchval("SELECT instruction FROM tasks WHERE id = $1", r["tasks"][0])   # told to hand over options
    assert (await project_flow.advance(p["id"])) == "running"                                    # still working
    soon = (datetime.now(WIB) + timedelta(minutes=40)).strftime("%H:%M")
    block = ('Hasil.\n```hasil\n{"ringkasan": "2 opsi", "pilihan": [{"label": "KRL pertama", "waktu": "%s", "detail": "dari rumah"},'
             '{"label": "KRL kedua", "waktu": "23:59"}]}\n```' % soon)
    await pool.execute("UPDATE tasks SET status = 'completed', result = $2 WHERE id = $1", r["tasks"][0], block)
    assert await project_flow.advance(p["id"]) == "choice" and len(started) == 1                 # waits for the owner
    pushed = [e for e in sent if e.get("type") == "owner_choice"][-1]
    assert pushed["status"] == "open" and [o["label"] for o in pushed["options"]] == ["KRL pertama", "KRL kedua"]
    note = [e for e in sent if e.get("type") == "notify" and e["kind"] == "choice"][-1]
    assert "pilih dulu" in note["title"] and "2 opsi" in note["text"]
    listed = await main.choices_open(device=dev)
    assert [c["id"] for c in listed] == [pushed["id"]]
    shown = (await main.projects_list(device=dev))["projects"][0]["chain"]
    assert shown["state"] == "choice" and shown["waiting"] == ["Pesan gojek"] and shown["choice"]["options"][0]["label"] == "KRL pertama"
    with pytest.raises(main.HTTPException):
        await main.projects_run(p["id"], device=dev)                                             # the run is not over
    with pytest.raises(main.HTTPException):
        await main.choice_answer(pushed["id"], main.ChoiceIn(option=9), device=dev)

    got = await main.choice_answer(pushed["id"], main.ChoiceIn(option=0), device=dev)
    assert got["state"] == "timer" and len(started) == 1                                         # 5 minutes before: not yet
    start_at = got["start_at"] if isinstance(got["start_at"], datetime) else datetime.fromisoformat(got["start_at"])
    assert 30 <= (start_at - datetime.now(timezone.utc)).total_seconds() / 60 <= 36
    assert any("dijadwalkan" in e["title"] for e in sent if e.get("type") == "notify")
    with pytest.raises(main.HTTPException):
        await main.choice_answer(pushed["id"], main.ChoiceIn(option=0), device=dev)              # once only
    assert await project_flow.advance(p["id"]) == "timer"
    await pool.execute("UPDATE project_chain SET start_at = now() - interval '1 minute' WHERE project_id = $1", p["id"])
    assert await project_flow.advance(p["id"]) == "started" and len(started) == 2
    phone = await pool.fetchrow("SELECT status, approved_by, goal FROM phone_runs ORDER BY id DESC LIMIT 1")
    assert phone["status"] == "approved" and phone["approved_by"] == "proyek"                    # no admin password for a project
    assert "KRL pertama" in phone["goal"] and "PILIHAN PEMILIK" in phone["goal"] and "cek jadwal" not in phone["goal"].split("PILIHAN")[0][:30]
    assert await pool.fetchval("SELECT count(*) FROM project_chain") == 0                         # the last stage is out
    await pool.execute("DELETE FROM projects")


@needs_db
async def test_a_pick_at_once_a_failed_stage_a_late_pick_and_stopping(pool, monkeypatch):
    from app import main, project_flow
    sent = _hub(monkeypatch)
    p, dev, started = await _project(pool, main, monkeypatch, offset=None)
    r = await main.projects_run(p["id"], device=dev)
    await pool.execute("UPDATE tasks SET status = 'failed', error = 'timeout' WHERE id = $1", r["tasks"][0])
    assert await project_flow.advance(p["id"]) == "failed" and len(started) == 1                  # the ride is never ordered after a failure
    assert any("berhenti" in e["title"] and "gagal" in e["text"] for e in sent if e.get("type") == "notify")
    assert await pool.fetchval("SELECT count(*) FROM project_chain") == 0

    await pool.execute("UPDATE projects SET runs = runs, notified_run = runs")
    r = await main.projects_run(p["id"], device=dev)
    await pool.execute("UPDATE tasks SET status = 'completed', result = 'jadwal tanpa opsi' WHERE id = $1", r["tasks"][0])
    assert await project_flow.advance(p["id"]) == "failed" and any("tidak ada opsi" in e["title"] for e in sent if e.get("type") == "notify")

    r = await main.projects_run(p["id"], device=dev)
    old = (datetime.now(WIB) - timedelta(hours=2)).strftime("%H:%M")
    await pool.execute("UPDATE tasks SET status = 'completed', result = $2 WHERE id = $1", r["tasks"][0],
                       '```hasil\n{"pilihan": [{"label": "KRL tadi", "waktu": "%s"}, {"label": "KRL lagi"}]}\n```' % old)
    await project_flow.advance(p["id"])
    cid = await pool.fetchval("SELECT id FROM owner_choices WHERE status = 'open'")
    p2 = await pool.fetchrow("SELECT start_offset_min FROM project_roles WHERE ask_owner")
    assert p2["start_offset_min"] is None
    got = await main.choice_answer(cid, main.ChoiceIn(option=0), device=dev)                     # no offset: at once, whatever the time
    assert got["state"] == "started" and len(started) == 4                                       # runs 1 and 2 stopped after their first stage

    await pool.execute("UPDATE project_roles SET start_offset_min = 5 WHERE ask_owner")
    await pool.execute("UPDATE tasks SET status = 'completed' WHERE project_id = $1", p["id"])
    r = await main.projects_run(p["id"], device=dev)
    await pool.execute("UPDATE tasks SET status = 'completed', result = $2 WHERE id = $1", r["tasks"][0],
                       '```hasil\n{"pilihan": [{"label": "KRL tadi", "waktu": "%s"}]}\n```' % old)
    await project_flow.advance(p["id"])
    cid = await pool.fetchval("SELECT id FROM owner_choices WHERE status = 'open'")
    with pytest.raises(main.HTTPException) as e:
        await main.choice_answer(cid, main.ChoiceIn(option=0), device=dev)                       # 2 hours late: refused
    assert e.value.status_code == 409 and "sudah lewat" in e.value.detail
    assert (await main.projects_stop(p["id"], device=dev))["chain"]
    assert await pool.fetchval("SELECT status FROM owner_choices WHERE id = $1", cid) == "cancelled"
    assert await pool.fetchval("SELECT count(*) FROM project_chain") == 0

    r = await main.projects_run(p["id"], device=dev)
    await pool.execute("UPDATE tasks SET status = 'completed', result = $2 WHERE id = $1", r["tasks"][0], '```hasil\n{"pilihan": [{"label": "a"}]}\n```')
    await project_flow.advance(p["id"])
    await pool.execute("UPDATE owner_choices SET expires_at = now() - interval '1 minute' WHERE status = 'open'")
    assert await project_flow.advance(p["id"]) == "expired" and await main.choices_open(device=dev) == []
    await pool.execute("DELETE FROM projects")


@needs_db
async def test_parallel_roles_start_together_and_the_end_is_told_once(pool, monkeypatch):
    from app import main, project_flow, workers
    sent = _hub(monkeypatch)
    started = []
    monkeypatch.setattr(workers, "_start", lambda task_id, context="": started.append(task_id))
    await pool.execute("TRUNCATE projects, owner_choices CASCADE")
    dev = {"name": "HP pemilik", "scope": "owner"}
    p = await main.projects_create(main.ProjectIn(name="Riset", roles=[{"role": "A"}, {"role": "B"}, {"role": "C", "after_prev": True}]), device=dev)
    assert [r["stage"] for r in p["roles"]] == [0, 0, 1]
    r = await main.projects_run(p["id"], device=dev)
    assert len(r["tasks"]) == 2 == len(started)                                                  # A and B together, C waits
    await pool.execute("UPDATE tasks SET status = 'completed', result = 'temuan A' WHERE id = $1", r["tasks"][0])
    assert await project_flow.advance(p["id"]) == "running" and len(started) == 2                # B is still busy
    await pool.execute("UPDATE tasks SET status = 'completed', result = 'temuan B' WHERE id = $1", r["tasks"][1])
    assert await project_flow.advance(p["id"]) == "started" and len(started) == 3                # both done: C goes
    brief = await pool.fetchval("SELECT instruction FROM tasks WHERE id = $1", started[2])
    assert "HASIL TAHAP SEBELUMNYA" in brief and "temuan A" in brief and "temuan B" in brief            # C is handed A's and B's results
    await pool.execute("UPDATE tasks SET status = 'completed' WHERE project_id = $1", p["id"])
    assert await project_flow.advance(p["id"]) == "done"
    assert await project_flow.advance(p["id"]) == "none"                                         # told once
    ends = [e for e in sent if e.get("type") == "notify" and "selesai" in e["title"]]
    assert len(ends) == 1 and "3/3" in ends[0]["text"]
    await pool.execute("DELETE FROM projects")
