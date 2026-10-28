"""ADR-074: the main agent oversees every task — the pattern of how each finished task went (owner, project, dev team) is kept and shown
to it when similar work comes up again, and the owner's projects are known and driven from the chat."""
import os
from datetime import datetime, timedelta, timezone

import pytest

from tests.test_integration import _no_memory, pool  # noqa: F401  (fixture)

needs_db = pytest.mark.skipif(not os.getenv("TEST_DATABASE_URL"), reason="needs TEST_DATABASE_URL")


def test_the_pattern_of_a_task_says_how_long_which_steps_which_model_and_who_helped():
    from app import episodes
    steps = ["- alat browser_navigate: jobstreet", "- pikir: cari lowongan", "- alat browser_click: lamar", "- alat browser_navigate: x",
             "- alat terminal: ls"]
    line = episodes.pattern(7.4, steps, "deepseek/deepseek-v4.1-flash", 1, True)
    assert line.startswith("berhasil dalam 7 menit, 4 langkah (browser_navigate×2, ")
    assert "model deepseek-v4.1-flash" in line and "pemilik membantu 1x" in line
    assert episodes.pattern(None, [], None, 0, False) == "gagal"


def test_the_main_agent_sees_similar_past_work_in_one_line_each():
    from app import episodes
    now = datetime(2026, 10, 27, tzinfo=timezone.utc)
    text = episodes.situation_lines([{"created_at": now - timedelta(days=3), "goal": "Bantu lamar kerja IT Manager", "success": True,
                                      "lesson": "berhasil dalam 12 menit; pemilik membantu 1x"},
                                     {"created_at": now, "goal": "Cek harga emas", "success": False, "lesson": None}], now)
    assert text.startswith("POLA SERUPA") and '3 hari lalu: "Bantu lamar kerja IT Manager" — berhasil dalam 12 menit' in text
    assert 'hari ini: "Cek harga emas" — gagal' in text and episodes.situation_lines([]) == ""


def test_a_project_is_found_by_part_of_its_name():
    from app import projects
    rows = [{"name": "Bantu lamar kerja"}, {"name": "Laporan harga emas"}]
    assert projects.find(rows, "lamar kerja")["name"] == "Bantu lamar kerja"
    assert projects.find(rows, "Laporan Harga Emas")["name"] == "Laporan harga emas"
    assert projects.find(rows, "harga emas")["name"] == "Laporan harga emas"
    assert projects.find(rows, "resep rendang") is None and projects.find(rows, "") is None
    assert projects.find(rows[:1], "")["name"] == "Bantu lamar kerja"        # the only one


def test_a_projects_status_names_its_latest_run():
    from app import projects
    p = {"name": "Cari kerja", "status": "active", "schedule": "daily", "schedule_text": "Tiap hari 08:00", "runs": 2,
         "next_run": datetime(2026, 10, 28, 1, 0, tzinfo=timezone.utc),
         "workers": [{"id": 9, "title": "x", "role": "Pencari", "status": "running", "project_run": 2},
                     {"id": 8, "title": "x", "role": "Penulis", "status": "failed", "error": "captcha", "project_run": 2},
                     {"id": 5, "title": "x", "role": "Pencari", "status": "completed", "result": "lama", "project_run": 1}]}
    text = projects.status_text(p)
    assert text.startswith('Proyek "Cari kerja" (aktif, Tiap hari 08:00), berikutnya Rabu 28/10 08:00 WIB — run #2: 1 bekerja, 1 gagal.')
    assert "#8 Penulis: gagal — captcha" in text and "lama" not in text
    assert projects.status_text(p | {"runs": 0, "workers": [], "status": "paused"}).endswith("— belum pernah dijalankan.")


def test_project_commands_said_plainly_are_understood():
    from app import router
    it = router.project_intent
    assert (it("jalankan proyek lamar kerja").args) == {"op": "run", "name": "lamar kerja"}
    assert it("Tolong jeda proyek Laporan emas dong").args == {"op": "pause", "name": "Laporan emas"}
    assert it("lanjutkan proyek laporan emas").args["op"] == "resume"
    assert it("status proyek cari kerja").args == {"op": "status", "name": "cari kerja"}
    assert it("status proyek").args["op"] == "list" and it("proyek saya apa saja?").args["op"] == "list"
    assert it("jalankan proyek") is None and it("mulai proyek baru untuk cari kos") is None
    assert it("jalankan musik") is None and it("proyek ini bagus") is None
    assert router.parse_action("jalankan proyek lamar kerja").name == "project"


@needs_db
async def test_every_finished_task_leaves_its_pattern_and_the_main_agent_recognises_it(pool, monkeypatch):
    from app import assistant, config, episodes, memory
    monkeypatch.setattr(config.settings, "memory_collection", "test_memory_v2")
    monkeypatch.setattr(memory, "search", _no_memory)
    await pool.execute("TRUNCATE episodes")
    tid = await pool.fetchval(
        """INSERT INTO tasks (session_id, title, instruction, kind, category, status, model_used, started_at, finished_at, result)
           VALUES ('project-1', 'Cari kerja · Pencari', 'x', 'owner', 'web', 'completed', 'deepseek/deepseek-v4.1-flash',
                   now() - interval '9 minutes', now(), '3 lowongan IT Manager dilamar') RETURNING id""")
    await pool.execute("INSERT INTO owner_questions (task_id, question) VALUES ($1, 'Boleh kirim lamarannya?')", tid)
    await pool.execute("INSERT INTO audit_events (actor, action, target) VALUES ('owner', 'live.takeover', $1)", f"task:{tid}")
    assert await episodes.record(tid, ["- alat browser_navigate: jobstreet", "- alat browser_click: lamar"]) == {"task": tid, "success": True}
    ep = await pool.fetchrow("SELECT goal, approach, lesson FROM episodes WHERE task_id = $1", tid)
    assert ep["goal"] == "Cari kerja · Pencari" and "browser_navigate" in ep["approach"]               # no plan: the steps are the approach
    assert ep["lesson"].startswith("berhasil dalam 9 menit, 2 langkah") and "pemilik membantu 2x" in ep["lesson"]
    job = await pool.fetchval("INSERT INTO dev_jobs (request) VALUES ('hapus kartu riwayat chat dari meja') RETURNING id")
    dev = await pool.fetchval(
        """INSERT INTO tasks (session_id, title, instruction, kind, status, dev_job, dev_role, error)
           VALUES ('devteam-1', 'bisan · spesifikasi: hapus kartu', 'x', 'devteam', 'failed', $1, 'bisan', 'ReadTimeout') RETURNING id""", job)
    assert await episodes.record(dev) == {"task": dev, "success": False}                               # the dev team learns too
    assert await pool.fetchval("SELECT goal FROM episodes WHERE task_id = $1", dev) == "bisan (tim dev): hapus kartu riwayat chat dari meja"
    assert await pool.fetchval(
        "INSERT INTO tasks (session_id, title, instruction, kind, status) VALUES ('s', 'x', 'y', 'situation', 'completed') RETURNING id") \
        and await episodes.record(await pool.fetchval("SELECT max(id) FROM tasks")) is None             # background chores are not lessons
    text = await assistant._situation("tolong cari kerja lagi, pencari lowongan", None)
    assert "POLA SERUPA" in text and "pemilik membantu 2x" in text
    assert "POLA SERUPA" not in await assistant._situation("tolong cari kerja lagi, pencari lowongan", None, compact=True)


@needs_db
async def test_the_owners_projects_are_driven_from_the_chat(pool, monkeypatch):
    from app import assistant, memory, workers
    monkeypatch.setattr(workers, "_start", lambda task_id, context="": None)
    monkeypatch.setattr(memory, "search", _no_memory)
    await pool.execute("TRUNCATE projects CASCADE")
    made = await assistant._project_tool({"action": "create", "nama": "Laporan emas", "tujuan": "harga emas Antam tiap pagi",
                                          "jadwal": "daily", "jam": "07:00", "peran": [{"role": "Peneliti", "workers": 1}]}, "owner")
    assert made["created"] and "Laporan emas" in made["say"]
    assert "proyek tidak ditemukan" in (await assistant._project_tool({"action": "run", "nama": "resep rendang"}, "owner"))["error"]
    said = await assistant._act(assistant.router.parse_action("jalankan proyek laporan emas"), "s", "owner", None, None, False)
    assert said.startswith('Proyek "Laporan emas" run #1 jalan dengan 1 pekerja')
    assert await pool.fetchval("SELECT count(*) FROM tasks WHERE project_id = $1", made["created"]) == 1
    said = await assistant._act(assistant.router.parse_action("jeda proyek laporan emas"), "s", "owner", None, None, False)
    assert "dijeda" in said
    assert "tidak ketemu" in await assistant._act(assistant.router.parse_action("jalankan proyek resep rendang"), "s", "owner", None, None, False)
    text = await assistant._situation("halo", None)
    assert 'PROYEK PEMILIK' in text and 'Proyek "Laporan emas" (dijeda' in text and "1 antre" in text
