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

    async def fake_worker(text, session_id, image=None):
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


async def test_main_agent_can_stay_silent(pool, monkeypatch):
    from app import chat, memory
    monkeypatch.setattr(memory, "search", _no_memory)
    _fake_llm(monkeypatch, [("", [("stay_silent", {"reason": "obrolan orang lain"})])])
    t = await chat.handle("bang sopin nanti bang? Bismillah dulu", "s7", actor="test",
                          stt={"confidence": 0.71, "speakers": 2})
    assert (t.route, t.reply) == ("silent", "")
    row = await pool.fetchrow("SELECT stt_confidence FROM messages WHERE role = 'user' AND session_id = 's7'")
    assert abs(row["stt_confidence"] - 0.71) < 1e-6
    from app.assistant import _history
    assert await _history("s7") == [{"role": "user", "content": "bang sopin nanti bang? Bismillah dulu"}]


async def test_self_description_reflects_real_config(pool, monkeypatch):
    from app import config, self_model, status

    async def no_health():
        return []

    monkeypatch.setattr(status, "check_all", no_health)
    monkeypatch.setattr(config.settings, "deepgram_model", "nova-2")
    text = await self_model.describe(full=True)
    assert "Deepgram (model nova-2, bahasa id" in text and "BELUM bisa mengenali identitas suara" in text


async def test_selfcheck_applies_low_risk_and_queues_settings(pool, monkeypatch):
    from app import deepgram, selfimprove, self_model
    result = """Analisis selesai. {"summary_for_owner": "Aku sering salah dengar Deepgram dan tidak tahu kemampuanku sendiri.",
      "improvements": [
        {"kind": "stt_keyword", "term": "Deepgram", "reason": "terdengar Deep Drum"},
        {"kind": "lesson", "text": "Jangan menyangkal punya Deepgram; cek self_info dulu.", "reason": "menyangkal kemampuan"},
        {"kind": "setting", "key": "endpointing_ms", "value": "1200", "reason": "kalimat terpotong"},
        {"kind": "setting", "key": "openrouter_api_key", "value": "x", "reason": "tidak boleh"},
        {"kind": "code", "summary": "Tambah voiceprint untuk mengenali suara pemilik", "reason": "permintaan pemilik"}]}"""
    said = await selfimprove.on_selfcheck(None, result)
    assert "2 perbaikan langsung kuterapkan" in said and "1 butuh persetujuanmu" in said and "1 usulan" in said
    assert "Deepgram" in (await deepgram.stt_config())["keywords"]
    assert any("self_info" in l for l in await self_model.lessons())
    pending = await pool.fetchrow("SELECT kind, status FROM approvals WHERE kind = 'setting_change'")
    assert pending["status"] == "awaiting_approval"
    # approving applies the override; reverting the lesson removes it from the prompt
    from app import approvals, config
    a = await pool.fetchval("SELECT id FROM approvals WHERE kind = 'setting_change'")
    done = await approvals.decide(a, True, "owner")
    assert done["status"] == "completed" and config.settings.endpointing_ms == 1200
    lesson_id = await pool.fetchval("SELECT id FROM improvements WHERE kind = 'lesson'")
    assert await selfimprove.revert(lesson_id, "owner")
    assert await self_model.lessons() == []
    config.settings.endpointing_ms = 1000


async def test_situation_result_can_speak_first_but_rate_limited(pool, monkeypatch):
    from datetime import datetime, timezone, timedelta
    from app import awareness, hub, notifications
    hub.reset()
    pushed = []

    async def phone(ev):
        pushed.append(ev)

    hub.register(phone)
    monkeypatch.setattr(notifications, "quiet_now", lambda now=None: False)
    awareness._state["last_proactive"] = None
    now = datetime(2026, 10, 17, 0, 30, tzinfo=timezone.utc)
    res = """{"where": "rumah, Pondok Aren", "doing": "bersiap berangkat kerja", "likely_need": "info macet",
              "prepared": "Tol JORR padat, 40 menit", "confidence": 0.8, "speak": true,
              "line": "Pagi! Kalau mau berangkat, tol JORR lagi padat, sekitar 40 menit ke kantor."}"""
    r = await awareness.on_situation(1, res, now)
    assert r["spoke"] and pushed[-1]["type"] == "proactive" and "JORR" in pushed[-1]["text"]
    r = await awareness.on_situation(2, res, now + timedelta(minutes=10))
    assert not r["spoke"]  # max one proactive line per 45 minutes
    assert "bersiap berangkat kerja" in awareness.situation_block()
    hub.reset()


async def test_camera_image_reaches_the_worker(pool, monkeypatch):
    import asyncio
    from app import chat, hermes, hub, memory
    hub.reset()
    monkeypatch.setattr(memory, "search", _no_memory)
    seen = {}

    async def fake_worker(text, session_id, image=None):
        seen["image"], seen["text"] = image, text
        yield {"type": "done", "reply": hermes.HermesReply("Kampas rem Honda Beat ±Rp45.000", 1, 1, 1)}

    monkeypatch.setattr(hermes, "stream", fake_worker)
    _fake_llm(monkeypatch, [("", [("spawn_task", {"title": "Cek harga barang", "instruction": "Cari harga barang di gambar",
                                                  "attach_image": True})]),
                            ("Oke, aku cek harganya ya.", [])])
    t = await chat.handle("berapa harga barang ini?", "s8", actor="test", screen="QUJD", image_source="camera")
    assert t.reply == "Oke, aku cek harganya ya."
    for _ in range(50):
        if "image" in seen:
            break
        await asyncio.sleep(0.05)
    assert seen["image"] == "QUJD" and "Gambar terlampir" in seen["text"]
    hub.reset()


async def test_empty_balance_is_told_plainly_once(pool, monkeypatch):
    import asyncio
    from app import billing, chat, hermes, hub, llm, memory, workers
    hub.reset()
    monkeypatch.setattr(memory, "search", _no_memory)
    monkeypatch.setattr(billing, "_last_notified", 0.0)

    async def broke(*a, **k):
        raise llm.LLMError("OpenRouter HTTP 402: requires more credits")
        yield  # pragma: no cover

    monkeypatch.setattr(llm, "stream_chat", broke)
    t = await chat.handle("hi", "s10", actor="test")
    assert t.route == "error" and t.reply == billing.MESSAGE  # no raw "HTTP 402" text for the owner
    t = await chat.handle("halo?", "s10", actor="test")
    assert await pool.fetchval("SELECT count(*) FROM reports WHERE text = $1", billing.MESSAGE) == 1  # once per 12 h

    async def worker_402(text, session_id, image=None):
        yield {"type": "done", "reply": hermes.HermesReply("Billing or credits exhausted: HTTP 402: can only afford 81", 1, 1, 1)}

    monkeypatch.setattr(hermes, "stream", worker_402)
    task = await workers.spawn("Cek diri", "instruksi uji coba", "s10", "test", kind="selfcheck")
    for _ in range(50):
        if await pool.fetchval("SELECT status FROM tasks WHERE id = $1", task["id"]) == "failed":
            break
        await asyncio.sleep(0.05)
    assert await pool.fetchval("SELECT status FROM tasks WHERE id = $1", task["id"]) == "failed"
    # no misleading "Aku sudah mengecek diriku." and no second balance report
    assert await pool.fetchval("SELECT count(*) FROM reports") == 1
    hub.reset()


async def test_spawn_without_instruction_is_refused(pool, monkeypatch):
    from app import chat, memory
    monkeypatch.setattr(memory, "search", _no_memory)
    _fake_llm(monkeypatch, [("", [("spawn_task", {"title": "Tugas"})]), ("Mau aku kerjakan apa persisnya?", [])])
    t = await chat.handle("kerjain itu dong", "s11", actor="test")
    assert t.reply == "Mau aku kerjakan apa persisnya?"
    assert await pool.fetchval("SELECT count(*) FROM tasks") == 0


async def test_unreadable_selfcheck_is_not_reported_as_success(pool):
    from app import selfimprove
    said = await selfimprove.on_selfcheck(None, "Billing or credits exhausted")
    assert "tidak menghasilkan temuan" in said and "Aku sudah mengecek diriku." != said
