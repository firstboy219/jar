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


def _fake_llm(monkeypatch, script):
    """script: list of rounds; each round = (text, [(tool_name, args), ...])."""
    from app import llm
    rounds = iter(script)

    async def fake_stream(messages, tools=None, model=None, max_tokens=400, temperature=0.6):
        text, calls = next(rounds)
        if text:
            yield {"type": "delta", "text": text}
        yield {"type": "done", "completion": llm.Completion(
            text=text, tool_calls=[llm.ToolCall(f"c{i}", n, a) for i, (n, a) in enumerate(calls)],
            prompt_tokens=50, completion_tokens=5)}

    async def fake_complete(messages, model=None, max_tokens=300):
        return "Harga emas Antam hari ini Rp1,9 juta per gram. Sudah kedengaran?"

    monkeypatch.setattr(llm, "stream_chat", fake_stream)
    monkeypatch.setattr(llm, "complete", fake_complete)


async def _no_memory(*a, **k):
    return []


async def test_main_agent_answers_without_workers(pool, monkeypatch):
    from app import chat, hermes, memory
    monkeypatch.setattr(memory, "search", _no_memory)
    monkeypatch.setattr(hermes, "stream", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no worker")))
    _fake_llm(monkeypatch, [("Kopi, biar melek.", [])])
    events = []

    async def emit(e):
        events.append(e)

    t = await chat.handle("kopi atau teh?", "s2", actor="test", emit=emit)
    assert (t.route, t.reply) == ("assistant", "Kopi, biar melek.")
    assert [e["type"] for e in events] == ["status", "delta", "status"]


async def test_delegation_runs_worker_and_reports_back(pool, monkeypatch):
    import asyncio
    from app import chat, hermes, hub, memory, reports, workers
    hub.reset()
    monkeypatch.setattr(memory, "search", _no_memory)
    pushed = []

    async def phone(ev):
        pushed.append(ev)

    hub.register(phone)
    worker_prompts = []

    async def fake_worker(text, session_id):
        worker_prompts.append((text, session_id))
        yield {"type": "thought", "text": "Cari harga emas."}
        yield {"type": "done", "reply": hermes.HermesReply("Antam Rp1.900.000/gram (logammulia.com)", 900, 40, 5)}

    monkeypatch.setattr(hermes, "stream", fake_worker)
    # round 1: tool call without text -> round 2: the spoken sentence
    _fake_llm(monkeypatch, [("", [("spawn_task", {"title": "Cek harga emas", "instruction": "Cari harga emas Antam hari ini"})]),
                            ("Siap, lagi aku cek ya.", [])])

    t = await chat.handle("cek harga emas antam dong", "s3", actor="test")
    assert t.reply == "Siap, lagi aku cek ya."  # the owner gets an answer before the work is done
    for _ in range(50):
        if any(e["type"] == "report" for e in pushed):
            break
        await asyncio.sleep(0.05)
    assert worker_prompts[0][1] == "task-1" and "WORKER JARVIS" in worker_prompts[0][0]
    task = await pool.fetchrow("SELECT status, result FROM tasks WHERE id = 1")
    assert (task["status"], task["result"]) == ("completed", "Antam Rp1.900.000/gram (logammulia.com)")
    kinds = [e["type"] for e in pushed]
    assert kinds[:2] == ["task", "task"] and "task_event" in kinds and kinds[-1] == "report"
    report = pushed[-1]
    assert report["text"].startswith("Harga emas Antam") and report["attempt"] == 1
    assert (await reports.unconfirmed())[0]["status"] == "pending"
    hub.reset()


async def test_report_repeats_until_acknowledged_then_gives_up(pool, monkeypatch):
    from app import config, hub, reports
    hub.reset()
    pushed = []

    async def phone(ev):
        pushed.append(ev)

    monkeypatch.setattr(config.settings, "report_ack_timeout_s", 0)
    r = await reports._create(None, "s4", "Laporan uji.")
    hub.register(phone)
    for attempt in range(1, 4):
        await reports.spoken(r["id"])           # phone said it out loud
        reports._last_sent.clear()              # pretend enough time passed
        await pool.execute("UPDATE reports SET delivered_at = now() - interval '1 second' WHERE id = $1", r["id"])
        await reports.tick()
    row = await pool.fetchrow("SELECT status, attempts FROM reports WHERE id = $1", r["id"])
    assert (row["status"], row["attempts"]) == ("unheard", 3)
    assert [e.get("repeat") for e in pushed if e["type"] == "report"] == [True, True]
    assert pushed[-1] == {"type": "report_unheard", "id": r["id"]}
    hub.reset()


async def test_voice_acknowledgement_via_main_agent(pool, monkeypatch):
    from app import chat, memory, reports
    monkeypatch.setattr(memory, "search", _no_memory)
    r = await reports._create(None, "s5", "Server aman semua.")
    await reports.spoken(r["id"])
    _fake_llm(monkeypatch, [("Sip.", [("acknowledge_reports", {"report_ids": [r["id"]]})])])
    await chat.handle("oke makasih", "s5", actor="test")
    row = await pool.fetchrow("SELECT status, acked_by FROM reports WHERE id = $1", r["id"])
    assert (row["status"], row["acked_by"]) == ("acknowledged", "voice")


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


async def test_location_whereami_and_agent_context(pool, monkeypatch):
    from app import chat
    from app.location import Location, last

    t = await chat.handle("di mana saya", "s9", actor="test")
    assert t.route == "core" and "belum menerima lokasi" in t.reply

    loc = Location(lat=-6.158, lon=106.905, accuracy_m=20, address="Kelapa Gading, Jakarta Utara")
    t = await chat.handle("di mana saya", "s9", actor="test", location=loc)
    assert "Kelapa Gading" in t.reply and "maps.google.com" in t.reply
    assert (await last())["address"] == "Kelapa Gading, Jakarta Utara"

    from app import llm, memory
    seen = {}

    async def fake(messages, tools=None, model=None, max_tokens=400, temperature=0.6):
        seen["situation"] = messages[1]["content"]
        seen["user"] = messages[-1]["content"]
        yield {"type": "done", "completion": llm.Completion(text="Cerah.")}

    monkeypatch.setattr(llm, "stream_chat", fake)
    monkeypatch.setattr(memory, "search", _no_memory)
    await chat.handle("cuaca di sini gimana?", "s9", actor="test", location=loc)
    assert seen["situation"].startswith("[Konteks perangkat") and "Kelapa Gading" in seen["situation"]
    assert seen["user"] == "cuaca di sini gimana?"
    logged = await pool.fetchval("SELECT content FROM messages WHERE role='user' ORDER BY id DESC LIMIT 1")
    assert logged == "cuaca di sini gimana?"  # context is not written into the message log


async def test_media_is_validated_then_pushed(pool, monkeypatch):
    from app import hub, media
    hub.reset()
    pushed = []

    async def phone(ev):
        pushed.append(ev)

    async def image_ok(client, url):
        return "good" in url

    monkeypatch.setattr(media, "_image_ok", image_ok)
    hub.register(phone)
    r = await media.show([
        {"url": "https://img.example/good.jpg", "kind": "image", "title": "Kampas rem"},
        {"url": "http://img.example/good.jpg"},                       # not https
        {"url": "https://img.example/bad.html", "kind": "image"},      # not an image
        {"url": "https://www.youtube.com/watch?v=dFjkFepm1Bc", "kind": "video", "title": "Ganti kampas rem PCX"},
    ], "Contoh kampas rem", "test")
    assert r["shown"] == 2 and r["devices"] == 1
    ev = pushed[0]
    assert ev["type"] == "media" and ev["caption"] == "Contoh kampas rem"
    assert [i["kind"] for i in ev["items"]] == ["image", "video"]
    assert ev["items"][1]["thumbnail"] == "https://i.ytimg.com/vi/dFjkFepm1Bc/hqdefault.jpg"
    hub.reset()


async def test_notification_triage_levels(pool, monkeypatch):
    from app import config, hub, llm, notifications
    hub.reset()
    pushed = []

    async def phone(ev):
        pushed.append(ev)

    hub.register(phone)
    monkeypatch.setattr(config.settings, "quiet_hours", "")
    answers = iter([
        '{"decisions": [{"id": 1, "decision": "announce"}, {"id": 2, "decision": "skip"}], "say": "Ada WhatsApp dari Budi: rapat jadi jam 3."}',
        '{"decisions": [{"id": 3, "decision": "urgent"}], "say": "Ada transaksi Rp4,5 juta dari BCA yang tidak biasa."}',
    ])

    async def fake_complete(messages, model=None, max_tokens=300):
        assert "482913" not in messages[1]["content"]  # OTP never reaches the model
        return next(answers)

    monkeypatch.setattr(llm, "complete", fake_complete)
    N = notifications.Notification
    for n in (N(app="WhatsApp", package="com.whatsapp", title="Budi", text="Rapat jadi jam 3", posted_at=1),
              N(app="Shopee", package="com.shopee", title="Flash sale!", text="Diskon 90%", posted_at=1)):
        await notifications.receive(n, None)
    notifications._pending.clear()  # drive triage directly instead of waiting for the debounce
    r = await notifications.triage([{"id": 1, "app": "WhatsApp", "title": "Budi", "text": "Rapat jadi jam 3"},
                                    {"id": 2, "app": "Shopee", "title": "Flash sale!", "text": "Diskon 90%"}])
    assert r["level"] == "announce" and pushed[-1] == {"type": "announce", "text": "Ada WhatsApp dari Budi: rapat jadi jam 3."}

    await notifications.receive(N(app="BCA", package="com.bca", title="Kode OTP", text="OTP 482913", posted_at=1), None)
    notifications._pending.clear()
    stored = await pool.fetchrow("SELECT title, text, sensitive FROM notifications WHERE id = 3")
    assert stored["sensitive"] and "482913" not in stored["text"]
    r = await notifications.triage([{"id": 3, "app": "BCA", "title": stored["title"], "text": stored["text"]}])
    assert r["level"] == "urgent" and pushed[-1]["type"] == "report"  # urgent → repeated until acknowledged
    decisions = [r["decision"] for r in await pool.fetch("SELECT decision FROM notifications ORDER BY id")]
    assert decisions == ["announce", "skip", "urgent"]
    hub.reset()


async def test_quiet_hours_suppress_announcements(pool, monkeypatch):
    from app import hub, llm, notifications
    hub.reset()
    pushed = []

    async def phone(ev):
        pushed.append(ev)

    hub.register(phone)
    monkeypatch.setattr(notifications, "quiet_now", lambda now=None: True)

    async def fake_complete(messages, model=None, max_tokens=300):
        return '{"decisions": [{"id": 1, "decision": "announce"}], "say": "Ada pesan dari Ani."}'

    monkeypatch.setattr(llm, "complete", fake_complete)
    await notifications.receive(notifications.Notification(app="WA", package="wa", title="Ani", text="hai", posted_at=1), None)
    notifications._pending.clear()
    r = await notifications.triage([{"id": 1, "app": "WA", "title": "Ani", "text": "hai"}])
    assert r["level"] == "skip" and pushed == []
    hub.reset()
