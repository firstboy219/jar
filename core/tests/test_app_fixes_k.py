"""The owner's first run of APK 0.26 (2026-10-30): AI answers that came back empty (the models' thinking ate max_tokens), open-licence music
when Openverse is unreachable, a mission's question with its mission and its whole text, missions handing strict sites to the phone's
web agent, invisible reCAPTCHA no longer taken for a robot check, and phone web steps given the time a heavy page needs."""
import json
import os

import httpx
import pytest

from tests.test_integration import pool  # noqa: F401  (fixture)

needs_db = pytest.mark.skipif(not os.getenv("TEST_DATABASE_URL"), reason="needs TEST_DATABASE_URL")


def reply(content):
    return {"choices": [{"message": {"content": content}}], "jarvis_route": {"model": "m/x"}, "usage": {"total_tokens": 5}}


def test_a_mood_is_asked_in_the_catalogue_s_words_and_licences_read_plainly():
    from app import musiclib
    assert musiclib.mood_query("putar musik santai buat kerja") == ("santai kerja", "chill")
    assert musiclib.mood_query("lagu semangat") == ("semangat", "upbeat")
    assert musiclib.mood_query("Tulus") == ("Tulus", "")
    assert musiclib.licence_name("http://creativecommons.org/licenses/by-nc-sa/3.0/") == "CC BY-NC-SA 3.0"
    assert musiclib.licence_name("https://creativecommons.org/publicdomain/zero/1.0/") == "CC0 / domain publik"
    assert musiclib.licence_name("") == "" and musiclib.licence_name("https://example.com/terms") == ""


def test_a_question_card_shows_the_whole_question_and_who_asked():
    from app import needs
    long = "JobStreet menampilkan halaman verifikasi Cloudflare. " * 6
    it = needs.question_item({"id": 3, "question": long, "task_id": 462, "title": "Apply job di jobstreet"})
    assert it["text"] == long and it["title"].endswith("…") and len(it["title"]) <= 160
    assert it["sub"] == "Ditanya oleh misi: Apply job di jobstreet" and it["task_id"] == 462
    assert needs.question_item({"id": 4, "question": "Lanjut?", "task_id": None})["sub"] == "Ditanya oleh pekerja JARVIS"   # never "#None"


def test_only_a_captcha_on_screen_counts_as_a_robot_check():
    from app import webagent
    assert "size=invisible" in webagent.STATE_JS and "r.width>=60" in webagent.STATE_JS


async def test_phone_web_steps_get_the_time_a_heavy_page_needs(monkeypatch):
    from app import phone_agent, webagent
    seen = []

    async def op(name, **kw):
        seen.append((name, kw.get("wait")))
        return {"result": "{}"}
    monkeypatch.setattr(phone_agent, "op", op)
    s = webagent._PhoneSession("wt1")
    await s.open("https://www.agoda.com/")
    await s.run("1", settle_ms=8000)
    assert seen == [("web_open", 18 + webagent.PHONE_SLACK_S), ("web_eval", 8 + webagent.PHONE_SLACK_S)]


async def test_a_busy_page_is_read_again_before_the_task_gives_up(monkeypatch):
    from app import webagent

    async def no_wait(s):
        return None
    monkeypatch.setattr(webagent.asyncio, "sleep", no_wait)

    class Busy:
        n = 0

        async def run(self, js, settle_ms=0):
            self.n += 1
            if self.n == 1:
                raise webagent.WebError("HP: HP tidak menjawab")
            return "" if self.n == 2 else json.dumps({"url": "https://x.test", "els": []})
    b = Busy()
    assert (await webagent._state(b))["url"] == "https://x.test" and b.n == 3


@needs_db
async def test_light_answers_straight_away_and_heavy_thinks_a_little_with_room_left(pool, monkeypatch):
    from app import gateway, master
    bodies = []
    answers = iter([reply("halo"), reply(""), reply('{"ok": true}')])

    async def fake(category, body, **kw):
        bodies.append((category, body))
        return next(answers)
    monkeypatch.setattr(gateway, "complete", fake)
    rid = await pool.fetchval("INSERT INTO flow_runs (feature, action) VALUES ('uji', 'x') RETURNING id")
    job = master.Job("uji", "x", "uji", messages=[{"role": "user", "content": "hai"}], max_tokens=500)
    assert (await master._think(job, "ringan", rid))[0] == "halo"
    assert bodies[0][1]["reasoning"] == {"enabled": False} and bodies[0][1]["max_tokens"] == 500
    job = master.Job("uji", "x", "uji", messages=[{"role": "user", "content": "hai"}], max_tokens=500, json_out=True)
    assert (await master._think(job, "berat", rid))[0] == {"ok": True}
    assert bodies[1][1]["reasoning"] == {"effort": "low"} and bodies[1][1]["max_tokens"] == 500 + master.THINK_ROOM
    assert bodies[2][1]["reasoning"] == {"enabled": False} and bodies[2][1]["max_tokens"] == 500    # it thought itself out of budget: once more, directly
    steps = await pool.fetchval("SELECT steps FROM flow_runs WHERE id = $1", rid)
    assert any("kehabisan token" in s["text"] for s in steps)


@needs_db
async def test_a_mission_s_question_and_its_web_work_on_the_phone(pool, monkeypatch):
    from app import config, main, questions, reports, webagent
    await pool.execute("TRUNCATE owner_questions, web_tasks, tasks RESTART IDENTITY CASCADE")

    async def quiet(*a, **k):
        return {"id": 1}
    monkeypatch.setattr(reports, "_create", quiet)
    tid = await pool.fetchval("INSERT INTO tasks (session_id, title, instruction, status, kind, runtime) VALUES ('s', 'Apply job di jobstreet', 'x', 'running', 'owner', 'hermes') RETURNING id")
    q = await questions.ask("Butuh bantuanmu di JobStreet: verifikasi Cloudflare.", None)
    assert q["task_id"] == tid                                                                    # the one running mission is the one asking
    await pool.execute("INSERT INTO tasks (session_id, title, instruction, status, kind, runtime) VALUES ('s', 'Lain', 'x', 'running', 'owner', 'hermes')")
    assert (await questions.ask("Yang mana?", None))["task_id"] is None                           # two running: no guessing

    asked = []

    async def request(goal, start_url="", who="owner", origin="app", feature="web", title=""):
        asked.append((goal, origin, who, title))
        wid = await pool.fetchval("INSERT INTO web_tasks (goal, start_url, site, origin, created_by) VALUES ($1, 'https://www.jobstreet.co.id/', 'jobstreet.co.id', $2, $3) RETURNING id",
                                  goal, origin, who)
        return {"id": wid, "task_id": tid}
    monkeypatch.setattr(webagent, "request", request)
    monkeypatch.setattr(config.settings, "mcp_token", "tok")
    pid = await pool.fetchval("INSERT INTO projects (name) VALUES ('Lamar kerja') RETURNING id")
    await pool.execute("UPDATE tasks SET project_id = $2 WHERE id = $1", tid, pid)
    h = {"X-Internal-Token": "tok"}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url="http://t") as c:
        assert (await c.post("/internal/web_task", json={"goal": "Lamar IT Manager di JobStreet", "task_id": tid})).status_code == 404   # tool server only
        r = (await c.post("/internal/web_task", json={"goal": "Lamar IT Manager di JobStreet", "task_id": tid}, headers=h)).json()
        assert asked[-1][1] == "feature" and asked[-1][2] == "hermes" and f"misi #{tid}" in asked[-1][3]   # a project's mission: no admin password at review
        await pool.execute("INSERT INTO web_waits (web_task_id, kind, title) VALUES ($1, 'verifikasi', 'jobstreet: verifikasi')", r["web_task_id"])
        st = (await c.get(f"/internal/web_task/{r['web_task_id']}", headers=h)).json()
        assert st["status"] == "queued" and st["waiting_for_owner"] == [{"kind": "verifikasi", "title": "jobstreet: verifikasi"}]
        await c.post("/internal/web_task", json={"goal": "Pesan hotel di Agoda"}, headers=h)
        assert asked[-1][1] == "chat"                                                             # not a project's: reviewed with the password
        assert (await c.get("/internal/web_task/99999", headers=h)).status_code == 404


async def test_the_phone_can_play_a_video_silently_to_read_its_subtitles():
    from app import main
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url="http://t") as c:
        page = (await c.get("/embed/youtube/dQw4w9WgXcQ?play=1&mute=1&cc=id")).text
        assert "MUTE=1" in page and "if(MUTE)e.target.mute()" in page and 'CC="id"' in page
        assert "MUTE=0" in (await c.get("/embed/youtube/dQw4w9WgXcQ")).text                 # the owner's own player keeps its sound
