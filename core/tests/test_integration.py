"""Integration tests against a real (throwaway) Postgres and Qdrant.

Run via infra/scripts/test-core.sh, which starts both and sets TEST_DATABASE_URL / TEST_QDRANT_URL.
"""

import os

import pytest
import pytest_asyncio

pytestmark = pytest.mark.skipif(not os.getenv("TEST_DATABASE_URL"), reason="needs TEST_DATABASE_URL")


@pytest_asyncio.fixture
async def pool(monkeypatch):
    from app import config, db
    monkeypatch.setattr(config.settings, "qdrant_url", os.getenv("TEST_QDRANT_URL", ""))
    p = await db.connect(os.environ["TEST_DATABASE_URL"])
    await p.execute("TRUNCATE devices, messages, approvals, memories, audit_events RESTART IDENTITY CASCADE")
    yield p
    await db.close()


async def test_migrations_idempotent(pool):
    from app import db
    assert await db.migrate(pool) == []


async def test_device_lifecycle(pool):
    from app import devices
    dev, token = await devices.create("HP Ilham", "test")
    assert (await devices.authenticate(token))["name"] == "HP Ilham"
    assert await devices.authenticate("jdv_wrong") is None
    stored = await pool.fetchval("SELECT token_hash FROM devices")
    assert token not in stored
    assert await devices.revoke(str(dev["id"]), "test")
    assert await devices.authenticate(token) is None


async def test_approval_reject_and_idempotency(pool):
    from app import approvals
    a = await approvals.create("manual", "Hapus log lama", {"detail": "x"}, "hermes", idempotency_key="k1")
    again = await approvals.create("manual", "Hapus log lama", {"detail": "x"}, "hermes", idempotency_key="k1")
    assert again["id"] == a["id"]
    assert await pool.fetchval("SELECT count(*) FROM approvals") == 1
    r = await approvals.decide(a["id"], False, "owner")
    assert r["status"] == "rejected" and r["decided_by"] == "owner"
    with pytest.raises(approvals.ApprovalError):
        await approvals.decide(a["id"], True, "owner")  # no second decision


async def test_approval_approve_runs_executor_once(pool, monkeypatch):
    from app import approvals
    calls = []

    async def fake_activate(detail):
        calls.append(detail["workflow_id"])
        return {"id": detail["workflow_id"], "active": True}

    monkeypatch.setitem(approvals.EXECUTORS, "n8n_activate_workflow", fake_activate)
    a = await approvals.create("n8n_activate_workflow", "Aktifkan X", {"workflow_id": "wf1"}, "hermes")
    done = await approvals.decide(a["id"], True, "owner")
    assert done["status"] == "completed" and done["result"]["active"] is True
    assert calls == ["wf1"]
    audit = [r["action"] for r in await pool.fetch("SELECT action FROM audit_events ORDER BY id")]
    assert audit == ["approval.requested", "approval.approved", "approval.completed"]


async def test_approval_executor_failure_is_recorded(pool, monkeypatch):
    from app import approvals

    async def boom(detail):
        raise RuntimeError("n8n down")

    monkeypatch.setitem(approvals.EXECUTORS, "n8n_activate_workflow", boom)
    a = await approvals.create("n8n_activate_workflow", "Aktifkan Y", {"workflow_id": "wf2"}, "hermes")
    done = await approvals.decide(a["id"], True, "owner")
    assert done["status"] == "failed" and "n8n down" in done["error"]


async def test_expired_approval_cannot_be_approved(pool):
    from app import approvals
    a = await approvals.create("manual", "Lama", {}, "hermes")
    await pool.execute("UPDATE approvals SET expires_at = now() - interval '1 minute' WHERE id = $1", a["id"])
    with pytest.raises(approvals.ApprovalError, match="expired"):
        await approvals.decide(a["id"], True, "owner")


async def test_chat_core_route_and_privacy_gate(pool, monkeypatch):
    from app import chat, hermes

    def no_hermes(*a, **k):
        raise AssertionError("must not reach Hermes / cloud")

    monkeypatch.setattr(hermes, "stream", no_hermes)
    t = await chat.handle("bantuan", "s1", actor="test")
    assert t.route == "core" and "Perintah cepat" in t.reply
    t = await chat.handle("simpan ini ya, password: hunter2", "s1", actor="test")
    assert t.route == "blocked"
    t = await chat.handle("/privat gaji saya 20jt", "s1", actor="test")
    assert t.route == "blocked"
    logged = [r["content"] for r in await pool.fetch("SELECT content FROM messages WHERE role='user' ORDER BY id")]
    assert "hunter2" not in " ".join(logged)


async def test_chat_free_text_goes_to_hermes(pool, monkeypatch):
    from app import chat, hermes

    async def fake(text, session_id):
        yield {"type": "thought", "text": "User menyapa."}
        yield {"type": "tool", "id": "c1", "name": "memory_search", "title": "Mencari di memori",
               "label": "sapaan", "emoji": "", "status": "running"}
        yield {"type": "delta", "text": "Halo, saya JARVIS."}
        yield {"type": "done", "reply": hermes.HermesReply("Halo, saya JARVIS.", 100, 5, 42)}

    async def no_context(query):
        return {"type": "context", "source": "memory", "query": query, "items": []}

    monkeypatch.setattr(hermes, "stream", fake)
    monkeypatch.setattr(chat, "_memory_context", no_context)
    events = []

    async def emit(e):
        events.append(e)

    t = await chat.handle("halo", "s2", actor="test", emit=emit)
    assert (t.route, t.reply) == ("hermes", "Halo, saya JARVIS.")
    assert [e["type"] for e in events] == ["status", "thought", "tool", "context", "delta", "status"]
    assert events[0]["state"] == "thinking" and events[-1]["state"] == "completed"
    row = await pool.fetchrow("SELECT prompt_tokens, latency_ms FROM messages WHERE role='assistant'")
    assert (row["prompt_tokens"], row["latency_ms"]) == (100, 42)


@pytest.mark.skipif(not os.getenv("TEST_QDRANT_URL"), reason="needs TEST_QDRANT_URL")
async def test_memory_roundtrip(pool, monkeypatch):
    from app import config, memory
    monkeypatch.setattr(config.settings, "memory_collection", "test_memory")
    await memory.ensure_collection()
    m = await memory.save("Proyek Autotoko memakai Shopee dan Tokopedia", "project", "test")
    await memory.save("Saya suka kopi tanpa gula", "personal", "test", kind="preference")
    hits = await memory.search("marketplace apa yang dipakai autotoko?")
    assert hits[0]["id"] == m["id"]
    with pytest.raises(memory.MemoryError_):
        await memory.save("token: abcdefghijklmnop1234", "personal", "test")
    await memory.update(str(m["id"]), "test", stale=True)
    assert all(h["id"] != m["id"] for h in await memory.search("autotoko marketplace"))
    assert await memory.delete(str(m["id"]), "test")
    assert await memory.get(str(m["id"])) is None


async def test_n8n_draft_is_idempotent_while_pending(pool, monkeypatch):
    from app import mcp_server, n8n
    created = []

    async def fake_generate(description):
        return {"name": "Tes", "nodes": [{"id": "1", "name": "A", "type": "n8n-nodes-base.manualTrigger",
                                          "typeVersion": 1, "position": [0, 0], "parameters": {}}],
                "connections": {}}

    async def fake_create(wf):
        created.append(wf["name"])
        return {"id": f"wf{len(created)}", "name": wf["name"], "active": False}

    monkeypatch.setattr(mcp_server, "_generate_workflow", fake_generate)
    monkeypatch.setattr(n8n, "create_inactive", fake_create)
    first = await mcp_server.n8n_draft_workflow("tiap pagi cek kurs")
    second = await mcp_server.n8n_draft_workflow("tiap pagi cek kurs")
    assert first["created"] and not second["created"] and second["already_pending"]
    assert second["approval_id"] == first["approval_id"] and created == ["Tes"]
