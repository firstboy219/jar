"""ADR-080: the local Qwen models are gone — every model is a cloud model; /privat is refused, sensitive content and mail use paid
models only, a confidential meeting is transcript-only, and nothing falls back to a local server."""
import os

import pytest

from tests.test_integration import pool  # noqa: F401  (fixture)

needs_db = pytest.mark.skipif(not os.getenv("TEST_DATABASE_URL"), reason="needs TEST_DATABASE_URL")


def test_the_gateway_knows_no_local_server():
    from app import gateway, ops
    for gone in ("LOCAL", "LOCAL_WORKER", "LOCAL_MODEL", "restore_worker_slot", "save_worker_slot", "_local_route"):
        assert not hasattr(gateway, gone), gone
    for gone in ("worker_policy", "orphaned"):
        assert not hasattr(ops, gone), gone
    assert set(gateway.FIRST_BYTE_S) == {"cloud"}


@needs_db
async def test_the_migration_leaves_no_local_route_provider_or_preset(pool):
    from app import composition, db
    assert await pool.fetchval("SELECT count(*) FROM llm_providers WHERE name LIKE 'lokal%'") == 0
    assert "lokal" not in composition.PRESETS
    # run the migration's route cleanup on a category that still has the old shape
    await pool.execute("""UPDATE llm_categories SET routes = '[{"provider":"openrouter","model":"a/b"},{"provider":"lokal-kerja","model":"qwen-lokal"}]'::jsonb
                          WHERE name = 'web'""")
    sql = (db.MIGRATIONS / "035_no_local_model.sql").read_text()
    await pool.execute(sql)
    assert await pool.fetchval("SELECT routes FROM llm_categories WHERE name = 'web'") == [{"provider": "openrouter", "model": "a/b"}]
    privat = await pool.fetchrow("SELECT routes, allow_free FROM llm_categories WHERE name = 'privat'")
    assert privat["allow_free"] is False and all(r["provider"] == "openrouter" and not r["model"].endswith(":free") for r in privat["routes"])
    assert await pool.fetchval("SELECT count(*) FROM llm_categories WHERE routes::text LIKE '%lokal%'") == 0


@needs_db
async def test_a_privat_message_is_refused_and_goes_nowhere(pool, monkeypatch):
    from app import assistant, chat, llm

    async def boom(*a, **k):
        raise AssertionError("no model may see a /privat message")
    monkeypatch.setattr(llm, "stream_chat", boom)
    monkeypatch.setattr(assistant, "respond", boom)
    t = await chat.handle("/privat berapa saldo rekeningku", "s-privat", actor="test")
    assert t.route == "blocked" and "dimatikan" in t.reply and "model lokal" in t.reply
    rows = await pool.fetch("SELECT role, content, route FROM messages WHERE session_id = 's-privat' ORDER BY id")
    assert [r["role"] for r in rows] == ["user", "assistant"] and "saldo rekeningku" not in rows[0]["content"]   # the text is not even kept


@needs_db
async def test_sensitive_text_still_gets_an_answer_but_only_from_paid_models(pool, monkeypatch):
    from app import chat, gateway, llm
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")
    await pool.execute("""UPDATE llm_categories SET allow_free = true, routes = '[{"provider":"openrouter","model":"x/free:free"},
                          {"provider":"openrouter","model":"x/paid"}]' WHERE name = 'ngobrol'""")
    gateway.invalidate()
    assert [r.model for r in await gateway.plan("ngobrol", private=True)] == ["x/paid"]
    assert [r.model for r in await gateway.plan("ngobrol")][0] == "x/free:free"             # an ordinary turn may still use it


@needs_db
async def test_a_confidential_meeting_is_transcript_only(pool, monkeypatch):
    from app import llm, meetings

    async def boom(*a, **k):
        raise AssertionError("a confidential meeting is never summarised by a model")
    monkeypatch.setattr(llm, "complete", boom)
    summary = await meetings._summarize({"confidential": True, "title": "Gaji", "marks": []}, [{"text": "rahasia", "start": 0, "end": 1, "speaker": "A"}])
    assert "tidak ada model lokal" in summary["ringkasan"] and summary["action_items"] == []
    mid = (await pool.fetchrow("""INSERT INTO meetings (title, confidential, consent, status) VALUES ('Gaji', true, true, 'done') RETURNING id"""))["id"]
    with pytest.raises(meetings.MeetingError, match="rapat rahasia"):
        await meetings.ask(str(mid), "siapa yang bicara?")
    await pool.execute("DELETE FROM meetings WHERE id = $1", mid)


@needs_db
async def test_an_ordinary_meeting_is_still_summarised(pool, monkeypatch):
    from app import llm, meetings
    seen = []

    async def complete(messages, **k):
        seen.append(k.get("private"))
        return '{"ringkasan": "ok", "keputusan": ["a"], "action_items": [{"siapa": "Opik", "apa": "x", "tenggat": ""}], "pertanyaan": [], "topik": []}'
    monkeypatch.setattr(llm, "complete", complete)
    summary = await meetings._summarize({"confidential": False, "title": "UAT", "marks": [], "context": {}},
                                        [{"text": "halo", "start": 0, "end": 1, "speaker": "A"}])
    assert summary["action_items"][0]["siapa"] == "Opik" and set(seen) == {False}


def test_the_owner_is_not_told_a_local_model_will_catch_him():
    from app import billing, budget, router
    assert "lokal" not in billing.MESSAGE and "Qwen" not in billing.MESSAGE
    assert "/privat" not in router.HELP and "model lokal" not in router.HELP
