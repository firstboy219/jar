"""Owner 2026-10-31: every request for songs becomes a list he ticks, the ticked ones made MP3 (played lewat YouTube until the converter
runs); a mission's question that asks him to act on a page gets buttons, not a text box, and questions nobody waits for go away; the
phone agent that goes back and forth between the same screens hands over to the heavy brain."""
import asyncio
import os

import httpx
import pytest

from tests.test_integration import pool  # noqa: F401  (fixture)

needs_db = pytest.mark.skipif(not os.getenv("TEST_DATABASE_URL"), reason="needs TEST_DATABASE_URL")


def test_youtube_results_become_songs_to_tick():
    from app import musik
    opts = musik.song_options([
        {"url": "https://www.youtube.com/watch?v=9II3OGZETo4", "title": "TULUS - Hati-Hati di Jalan (Official Music Video)", "channel": "Tulus", "duration_s": 262},
        {"url": "https://www.youtube.com/watch?v=9II3OGZETo4", "title": "dup", "channel": "x", "duration_s": 262},
        {"url": "https://www.youtube.com/watch?v=ZPBYO3J_xWw", "title": "PLAYLIST 11 LAGU", "channel": "y", "duration_s": 3699},
        {"url": "https://example.com/x", "title": "bukan youtube"}])
    assert opts == [{"url": "https://www.youtube.com/watch?v=9II3OGZETo4", "title": "TULUS - Hati-Hati di Jalan (Official Music Video)", "channel": "Tulus",
                     "duration_s": 262, "cover": "https://i.ytimg.com/vi/9II3OGZETo4/mqdefault.jpg"}]


def test_a_question_asking_him_to_act_on_a_page_gets_buttons():
    from app import needs
    assert needs.question_item({"id": 1, "question": "JobStreet menampilkan verifikasi Cloudflare. Selesaikan lalu tekan Selesai.", "task_id": 9})["takeover"]
    assert not needs.question_item({"id": 2, "question": "Prioritas lowongan mana yang dilamar dulu?", "task_id": 9})["takeover"]


@needs_db
async def test_questions_nobody_waits_for_are_closed(pool, monkeypatch):
    from app import questions
    await pool.execute("TRUNCATE owner_questions, tasks RESTART IDENTITY CASCADE")
    done = await pool.fetchval("INSERT INTO tasks (session_id, title, instruction, status) VALUES ('s', 'Apply', 'x', 'completed') RETURNING id")
    live = await pool.fetchval("INSERT INTO tasks (session_id, title, instruction, status) VALUES ('s', 'Cari', 'x', 'running') RETURNING id")
    await pool.execute("INSERT INTO owner_questions (task_id, question) VALUES ($1, 'lama'), ($2, 'masih ditunggu'), (NULL, 'yatim')", done, live)
    await pool.execute("UPDATE owner_questions SET created_at = now() - interval '3 hours' WHERE question = 'yatim'")
    assert [q["question"] for q in await questions.open_questions()] == ["masih ditunggu"]


async def test_going_back_and_forth_hands_over_to_the_heavy_brain(monkeypatch):
    from app import llm, phone_agent
    home = {"package": "com.EmasDigi", "nodes": [{"i": i, "c": "Button", "t": f"Beranda {i}", "k": 1} for i in range(8)]}
    aset = {"package": "com.EmasDigi", "nodes": [{"i": i, "c": "Button", "t": f"Aset {i}", "k": 1} for i in range(8)]}
    screens = [aset, home] * 10

    async def op(name, **args):
        return screens.pop(0)
    monkeypatch.setattr(phone_agent, "op", op)
    cats = []

    async def model(messages, tools=None, category="hp", **k):
        cats.append(category)
        call = ("selesai", {"hasil": "{\"total\": 1}"}) if len(cats) >= 8 else ("ketuk", {"nomor": 1})
        yield {"type": "done", "completion": llm.Completion(tool_calls=[llm.ToolCall("c", *call)])}
    monkeypatch.setattr(phone_agent.llm, "stream_chat", model)

    async def quiet(*a, **k):
        return None
    out, _ = await phone_agent._loop(1, "pluang", phone_agent.APPS["pluang"], "BACA saja portofolio", quiet, quiet, home)
    assert out == "{\"total\": 1}" and cats[0] == "hp" and "berat" in cats                     # light first, heavy once it loops


@needs_db
async def test_reading_pluang_end_to_end_through_the_worker_branch(pool, monkeypatch):
    from app import hub, llm, phone_agent, workers
    monkeypatch.setattr(workers, "_start", lambda task_id, context="": None)

    async def quiet(ev):
        return 1
    monkeypatch.setattr(hub, "broadcast", quiet)
    real_sleep = asyncio.sleep
    monkeypatch.setattr(phone_agent.asyncio, "sleep", lambda s: real_sleep(0))
    await pool.execute("TRUNCATE phone_runs, routines RESTART IDENTITY CASCADE")
    run = await phone_agent.request("Buka Pluang dan BACA saja portofolio", "pluang", "owner")
    run = await phone_agent.approve(run["id"], "owner")
    row = await pool.fetchrow("SELECT id, instruction FROM tasks WHERE id = $1", run["task_id"])
    home = {"package": "com.EmasDigi", "nodes": [{"i": 0, "c": "TextView", "t": "Total portofolio Rp 12.500.000"}, {"i": 1, "c": "Button", "t": "Aset", "k": 1}]
            + [{"i": i, "c": "View"} for i in range(2, 9)]}

    async def op(name, **args):
        return {"ok": True} if name in ("begin", "end") else home
    monkeypatch.setattr(phone_agent, "op", op)
    monkeypatch.setattr(phone_agent, "phone_online", lambda: True)

    calls = []

    async def model(messages, tools=None, **k):
        calls.append(1)
        call = (("selesai", {"hasil": "{\"total\": 12500000}"}) if len(calls) > 4 else ("lihat_gambar", {}) if len(calls) == 2
                else ("ketuk", {"nomor": 1}))   # looking at the picture, then carrying on (it once broke the next step)
        yield {"type": "done", "completion": llm.Completion(tool_calls=[llm.ToolCall("c", *call)])}
    monkeypatch.setattr(phone_agent.llm, "stream_chat", model)

    async def progress(*a, **k):
        return None
    out = await phone_agent.produce(row["id"], dict(row), progress, progress)
    assert out == "{\"total\": 12500000}"
