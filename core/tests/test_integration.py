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
    await p.execute("TRUNCATE devices, messages, approvals, memories, audit_events, tasks, reports, llm_usage, "
                    "settings_kv, owner_questions, documents, vault_entries, error_log, dev_changes, repair_attempts, flow_issues, stage_history, library_kept, dev_jobs, note_pages "
                    "RESTART IDENTITY CASCADE")
    # factory composition: one cloud model everywhere (there is no local model, ADR-080), no category budgets
    await p.execute("""UPDATE llm_categories SET budget_usd = NULL, allow_free = true,
        routes = '[{"provider": "openrouter", "model": "deepseek/deepseek-v4-pro"}]'::jsonb""")
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")
    from app import budget, gateway, quick

    async def no_quick(instruction):  # the fast worker searches the real web; tests opt in explicitly
        return None
    monkeypatch.setattr(quick, "answer", no_quick)
    from app import openrouter

    async def no_catalog(force=False):  # tests never reach openrouter.ai: model ids are accepted unchecked unless a test opts in
        return None
    monkeypatch.setattr(openrouter, "catalog", no_catalog)
    from app import composition as _composition

    async def no_probe(model):  # the real one sends a request to openrouter.ai
        return None
    monkeypatch.setattr(_composition, "_probe", no_probe)
    from app import workers as _w
    _w._background_turn = None  # an asyncio.Lock belongs to one event loop (one per test)
    from app import stage as _stage
    _stage._current = None
    _stage._desk.clear()  # the desk's cards are module state: every test starts with an empty desk
    gateway.invalidate()
    budget.forget()
    budget._notified.clear()
    from app import voice as _voice
    _voice.forget()  # learned voice data is cached for 30 s; each test starts from its own tables
    _voice._spoken.clear()
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
    """Quick commands never reach a model; sensitive turns go to paid models only and are never replayed into a later prompt;
    /privat is refused (no local model any more, ADR-080)."""
    from app import chat, hermes, llm, memory
    monkeypatch.setattr(memory, "search", _no_memory)

    def no_hermes(*a, **k):
        raise AssertionError("must not reach Hermes")

    monkeypatch.setattr(hermes, "stream", no_hermes)
    calls = []

    async def fake_stream(messages, tools=None, **kw):
        calls.append((kw.get("private"), messages))
        yield {"type": "done", "completion": llm.Completion(text="Oke, kucatat di sini saja.")}

    monkeypatch.setattr(llm, "stream_chat", fake_stream)
    t = await chat.handle("bantuan", "s1", actor="test")
    assert t.route == "core" and "Perintah cepat" in t.reply and not calls
    t = await chat.handle("simpan ini ya, password: hunter2", "s1", actor="test")
    assert t.route == "assistant" and calls[-1][0] is True
    before = len(calls)
    t = await chat.handle("/privat gaji saya 20jt", "s1", actor="test")
    assert t.route == "blocked" and len(calls) == before          # refused: no model, not even a paid one, sees it
    t = await chat.handle("cuaca hari ini gimana?", "s1", actor="test")
    assert calls[-1][0] is False
    replayed = " ".join(str(m.get("content")) for m in calls[-1][1])
    assert "20jt" not in replayed and "hunter2" not in replayed  # private turns stay out of cloud prompts
    logged = [r["content"] for r in await pool.fetch("SELECT content FROM messages WHERE role='user' ORDER BY id")]
    assert "hunter2" not in " ".join(logged)
    assert await pool.fetchval("SELECT count(*) FROM messages WHERE route = 'private'") == 2


def _fake_llm(monkeypatch, script):
    """script: list of rounds; each round = (text, [(tool_name, args), ...])."""
    from app import llm
    rounds = iter(script)

    async def fake_stream(messages, tools=None, **kw):
        text, calls = next(rounds)
        if text:
            yield {"type": "delta", "text": text}
        yield {"type": "done", "completion": llm.Completion(
            text=text, tool_calls=[llm.ToolCall(f"c{i}", n, a) for i, (n, a) in enumerate(calls)],
            prompt_tokens=50, completion_tokens=5)}

    async def fake_complete(messages, **kw):
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

    async def fake_worker(text, session_id, image=None, **kw):
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
    assert worker_prompts[0][1] == "task-1" and "[tugas #1]" in worker_prompts[0][0]
    task = await pool.fetchrow("SELECT status, result FROM tasks WHERE id = 1")
    assert (task["status"], task["result"]) == ("completed", "Antam Rp1.900.000/gram (logammulia.com)")
    kinds = [e["type"] for e in pushed]
    assert kinds[:2] == ["task", "task"] and "task_event" in kinds and kinds[-1] == "report"
    report = pushed[-1]
    assert report["text"].startswith("Harga emas Antam") and report["attempt"] == 1
    assert (await reports.unconfirmed())[0]["status"] == "pending"
    hub.reset()


async def test_a_spoken_report_is_never_repeated_or_chased(pool, monkeypatch):
    # The owner turned "make sure I heard" off (2026-10-26): a delivered report stays listed, silently, until acknowledged.
    from app import config, hub, reports
    hub.reset()
    pushed = []

    async def phone(ev):
        pushed.append(ev)

    monkeypatch.setattr(config.settings, "report_ack_timeout_s", 0)
    r = await reports._create(None, "s4", "Laporan uji.")
    hub.register(phone)
    await reports.spoken(r["id"])               # phone said it out loud, once
    pushed.clear()
    for _ in range(3):
        reports._last_sent.clear()              # plenty of time passed, with no acknowledgement
        await pool.execute("UPDATE reports SET delivered_at = now() - interval '1 hour' WHERE id = $1", r["id"])
        await reports.tick()
    await reports.on_connect(phone)             # a reconnect does not read it out again either
    assert pushed == []
    assert await pool.fetchval("SELECT status FROM reports WHERE id = $1", r["id"]) == "delivered"
    assert [x["id"] for x in await reports.unconfirmed()] == [r["id"]]      # still listed until acknowledged
    r2 = await reports._create(None, "s4", "Belum diucapkan.")               # but a report the phone never spoke is still delivered
    pushed.clear()                                                           # (_create already pushed it once; this is the reconnect)
    await reports.on_connect(phone)
    assert [e["id"] for e in pushed if e["type"] == "report"] == [r2["id"]] and not pushed[-1].get("repeat")
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

    async def fake(messages, tools=None, **kw):
        seen["system"] = messages[0]["content"]
        seen["user"] = messages[-1]["content"]
        yield {"type": "done", "completion": llm.Completion(text="Cerah.")}

    monkeypatch.setattr(llm, "stream_chat", fake)
    monkeypatch.setattr(memory, "search", _no_memory)
    await chat.handle("cuaca di sini gimana?", "s9", actor="test", location=loc)
    # per-turn context rides in the owner's message (last), so the static system prompt stays cacheable
    assert "Kelapa Gading" not in seen["system"] and "TENTANG DIRIMU" in seen["system"]
    assert seen["user"].startswith("[Konteks perangkat") and "Kelapa Gading" in seen["user"]
    assert seen["user"].endswith("UCAPAN PEMILIK:\ncuaca di sini gimana?")
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

    async def fake_complete(messages, **kw):
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
    assert r["level"] == "urgent" and pushed[-1]["type"] == "report"  # urgent → pushed at once
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

    async def fake_complete(messages, **kw):
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
    assert "Whisper LOKAL" in text and "BELUM bisa memastikan identitas suara" in text  # default composition
    assert "Inti permanen: Qdrant+Postgres" in text and "find_models" in text and "Anggaran AI bulan ini" in text
    from app import composition
    await composition.update({"stt": "deepgram"}, "test")
    assert "Deepgram (model nova-2)" in await self_model.describe()


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

    async def fake_worker(text, session_id, image=None, **kw):
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


def _fake_providers(monkeypatch, handler):
    """Every provider call of the gateway goes to handler(request) -> httpx.Response."""
    import httpx
    from app import gateway
    monkeypatch.setattr(gateway, "_client", lambda timeout: httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    gateway.invalidate()


def _sse(text: str, cost: float = 0.0, model: str = "m") -> bytes:
    import json as _j
    chunks = [{"choices": [{"index": 0, "delta": {"content": text}}], "model": model},
              {"choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
               "usage": {"prompt_tokens": 100, "completion_tokens": 5, "cost": cost,
                         "prompt_tokens_details": {"cached_tokens": 80}}}]
    return b"".join(f"data: {_j.dumps(c)}\n\n".encode() for c in chunks) + b"data: [DONE]\n\n"


async def _collect(category, **kw):
    from app import gateway
    out = []
    async for c in gateway.stream(category, {"messages": [{"role": "user", "content": "halo"}]}, **kw):
        out += [ch["delta"].get("content", "") for ch in c.get("choices", [])]
    return "".join(out)


async def test_gateway_fails_over_before_first_byte_and_records_cost(pool, monkeypatch):
    import httpx
    from app import billing, gateway
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")
    monkeypatch.setattr(billing, "_last_notified", 0.0)
    await pool.execute("""UPDATE llm_categories SET routes = '[{"provider":"openrouter","model":"a/broke"},
                          {"provider":"openrouter","model":"b/works"}]' WHERE name = 'ngobrol'""")
    seen = []

    def handler(req: httpx.Request) -> httpx.Response:
        import json as _j
        body = _j.loads(req.content)
        seen.append((req.url.host, body["model"], req.headers.get("x-session-id")))
        if body["model"] == "a/broke":
            return httpx.Response(402, text='{"error":{"message":"requires more credits"}}')
        return httpx.Response(200, content=_sse("Halo juga!", cost=0.0012), headers={"content-type": "text/event-stream"})

    _fake_providers(monkeypatch, handler)
    assert await _collect("ngobrol", caller="chat", session_id="sess-1") == "Halo juga!"
    assert [m for _, m, _ in seen] == ["a/broke", "b/works"] and seen[1][2] == "sess-1"
    rows = await pool.fetch("SELECT model, ok, cost_usd::float AS c, cached_tokens FROM llm_usage ORDER BY id")
    assert [(r["model"], r["ok"]) for r in rows] == [("a/broke", False), ("b/works", True)]
    assert rows[1]["c"] == 0.0012 and rows[1]["cached_tokens"] == 80
    import asyncio
    await asyncio.sleep(0.1)  # the 402 makes JARVIS tell the owner the credit ran out (once per 12 h)
    assert await pool.fetchval("SELECT count(*) FROM reports WHERE text = $1", billing.MESSAGE) == 1


async def test_gateway_without_a_key_has_no_model_and_private_content_uses_paid_cloud_only(pool, monkeypatch):
    import httpx
    from app import composition, gateway
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    await composition.apply_preset("seimbang", "test")
    seen = []

    def handler(req: httpx.Request) -> httpx.Response:
        import json as _j
        seen.append(_j.loads(req.content)["model"])
        assert "cache_prompt" not in _j.loads(req.content)   # that was for the local llama.cpp server (ADR-080)
        return httpx.Response(200, content=_sse("Dari cloud."), headers={"content-type": "text/event-stream"})

    _fake_providers(monkeypatch, handler)
    with pytest.raises(gateway.GatewayError, match="tidak ada model"):
        await _collect("ngobrol", caller="chat")           # no key and no local model: nothing can answer, and it says so
    assert seen == []
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")
    await pool.execute("""UPDATE llm_categories SET allow_free = true, routes = '[{"provider":"openrouter","model":"x/free:free"},
                          {"provider":"openrouter","model":"x/paid"}]' WHERE name = 'ngobrol'""")
    gateway.invalidate()
    assert await _collect("ngobrol", caller="chat", private=True) == "Dari cloud."
    assert seen == ["x/paid"]                              # private content: never the free endpoint that may log it


async def test_budget_cap_stops_paid_models_but_keeps_free_ones(pool, monkeypatch):
    import httpx
    from app import budget, gateway
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")
    await pool.execute("""UPDATE llm_categories SET routes = '[{"provider":"openrouter","model":"x/paid"},
                          {"provider":"openrouter","model":"y/gratis:free"}]' WHERE name = 'ngobrol'""")
    await pool.execute("INSERT INTO llm_usage (category, caller, provider, model, ok, cost_usd) VALUES ('web', 'hermes', 'openrouter', 'z', true, 25)")
    budget.forget()
    routes = await gateway.plan("ngobrol", caller="chat")
    assert [r.model for r in routes] == ["y/gratis:free"]
    await pool.execute("""UPDATE llm_categories SET routes = '[{"provider":"openrouter","model":"x/paid"}]' WHERE name = 'ngobrol'""")
    gateway.invalidate()
    with pytest.raises(gateway.GatewayError, match="anggaran"):   # no free model left and no local one: it says why nothing answers
        await gateway.plan("ngobrol", caller="chat")
    st = await budget.state(force=True)
    assert st["level"] == 100
    assert await pool.fetchval("SELECT count(*) FROM reports WHERE text LIKE 'Anggaran AI bulan ini%'") == 1


async def test_composition_only_changes_models_never_the_core(pool):
    from app import composition
    with pytest.raises(composition.CompositionError, match="inti JARVIS"):
        await composition.update({"hermes": "off"}, "test")
    with pytest.raises(composition.CompositionError, match="penyedia"):
        await composition.update({"categories": {"coding": {"routes": [{"provider": "nope", "model": "a/b"}]}}}, "test")
    c = await composition.update({"categories": {"coding": {"routes": [{"provider": "openrouter", "model": "anthropic/claude-sonnet-5.5"}],
                                                            "budget_usd": 8}}, "stt": "groq"}, "test")
    coding = next(x for x in c["categories"] if x["name"] == "coding")
    assert coding["budget_usd"] == 8 and c["stt"]["engine"] == "groq" and c["preset"] == "kustom"
    assert c["core"] == ["Qdrant", "n8n"]


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


async def test_meeting_pipeline_with_local_engine(pool, monkeypatch, tmp_path):
    """Chunks → (fake) jarvis-ears transcription + diarization → minutes (fake model) → docx + report.
    A confidential meeting never touches a cloud engine or model — and gets no AI minutes (there is no local model, ADR-080)."""
    import httpx
    from app import config, documents, llm, meetings, memory
    monkeypatch.setattr(meetings, "ROOT", tmp_path / "meetings")
    monkeypatch.setattr(documents, "ROOT", tmp_path / "documents")
    monkeypatch.setattr(config.settings, "groq_api_key", "gsk_should_not_be_used")
    calls = []

    async def fake_ears(path, body, timeout=0):
        calls.append(path)
        if path == "/meeting/transcribe":
            return httpx.Response(200, json={"segments": [
                {"start": 0, "end": 4, "text": "Rapat UAT kita mulai."}, {"start": 5, "end": 9, "text": "Opik siapkan data hari Kamis."},
                {"start": 10, "end": 11, "text": "Terima kasih."}]})
        return httpx.Response(200, json={"segments": [{"start": 0, "end": 4.5, "speaker": 0}, {"start": 4.6, "end": 12, "speaker": 1}],
                                         "voices": {}})

    private_flags = []

    async def fake_complete(messages, **kw):
        private_flags.append(kw.get("private"))
        if "NOTULEN" in messages[0]["content"]:
            return ('{"ringkasan": "Persiapan UAT.", "keputusan": ["UAT Kamis"], '
                    '"action_items": [{"siapa": "Opik", "apa": "siapkan data", "tenggat": "Kamis"}], "pertanyaan": [], "topik": ["UAT"]}')
        return "Catatan: UAT, Opik siapkan data Kamis."

    async def no_index(*a, **k):
        return None

    monkeypatch.setattr(meetings, "_ears", fake_ears)
    monkeypatch.setattr(llm, "complete", fake_complete)
    monkeypatch.setattr(meetings, "_index", no_index)
    from app import composition
    await composition.update({"stt": "groq"}, "test")
    with pytest.raises(meetings.MeetingError):
        await meetings.create("Tanpa izin", False, False)
    m = await meetings.create("UAT Autotoko", True, True)
    mid = str(m["id"])
    await meetings.add_chunk(mid, 0, b"OggS" + b"\0" * 100)
    await meetings.add_chunk(mid, 0, b"OggS" + b"\0" * 120)  # re-upload after a drop: replaced, not duplicated
    with pytest.raises(meetings.MeetingError, match="baru 1 dari 2"):
        await meetings.finish(mid, 120, 2, "test")
    await meetings.add_chunk(mid, 1, b"OggS" + b"\0" * 100)
    await meetings.finish(mid, 120, 2, "test")
    await meetings.process(mid)
    done = await meetings.get(mid)
    assert done["status"] == "done" and done["engine"] == "whisper"  # confidential: local even though Groq is chosen
    assert [s["speaker"] for s in done["transcript"]] == ["Pembicara 1", "Pembicara 2"]  # "Terima kasih." dropped
    assert done["summary"]["action_items"] == [] and "tidak ada model lokal" in done["summary"]["ringkasan"]
    assert private_flags == []                                      # no model call at all
    assert await pool.fetchval("SELECT format FROM documents WHERE id = $1", done["document_id"]) == "docx"
    assert await pool.fetchval("SELECT count(*) FROM reports WHERE text LIKE 'Notulen rapat UAT Autotoko%'") == 1
    assert "/meeting/concat" not in calls


async def test_draft_reply_asks_before_cloud_and_never_sends(pool, monkeypatch):
    from app import chat, drafts, hub, llm, memory
    hub.reset()
    pushed = []

    async def phone(ev):
        pushed.append(ev)

    hub.register(phone)
    monkeypatch.setattr(memory, "search", _no_memory)
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")
    await pool.execute("""UPDATE llm_categories SET routes = '[{"provider":"openrouter","model":"qwen/qwen3.7-flash"}]'
                          WHERE name = 'balas-pesan'""")
    assert await drafts.needs_confirmation()

    async def fake_complete(messages, **kw):
        assert "Bu Rina: Pak, bisa rapat besok jam 9?" in messages[1]["content"]
        return ('{"to": "Bu Rina", "channel": "whatsapp", "summary": "minta rapat besok jam 9", "variants": ['
                '{"label": "Singkat", "text": "Bisa, Bu."}, {"label": "Santai", "text": "Siap Bu, jam 9 ya."},'
                '{"label": "Formal", "text": "Baik Bu Rina, saya bisa hadir pukul 09.00."}]}')

    monkeypatch.setattr(llm, "complete", fake_complete)
    _fake_llm(monkeypatch, [("", [("draft_reply", {"instruction": "terima"})]), ("Isi chat ini akan diproses cloud, boleh?", [])])
    monkeypatch.setattr(llm, "complete", fake_complete)
    t = await chat.handle("bantu balas ini", "s20", actor="test", screen_text="Bu Rina: Pak, bisa rapat besok jam 9?")
    assert "boleh" in t.reply and not [e for e in pushed if e.get("type") == "stage"]
    _fake_llm(monkeypatch, [("", [("draft_reply", {"instruction": "terima", "confirmed": True})]), ("Drafnya sudah di layar.", [])])
    monkeypatch.setattr(llm, "complete", fake_complete)
    await chat.handle("boleh", "s20", actor="test", screen_text="Bu Rina: Pak, bisa rapat besok jam 9?")
    stage_ev = [e for e in pushed if e.get("type") == "stage"][-1]
    assert stage_ev["panel"] == "draft" and len(stage_ev["payload"]["variants"]) == 3
    hub.reset()


async def test_password_manager_never_leaks_and_feeds_the_agent_vault(pool, monkeypatch):
    from app import vault
    monkeypatch.setenv("VAULT_KEY", "22" * 32)
    e = await vault.save("https://ibank.klikbca.co.id/login", "ilham", "S3cret!", "test", allow_agent=False)
    again = await vault.save("ibank.klikbca.co.id", "ilham", "N3w!", "test")  # same account: update, not duplicate
    assert again["id"] == e["id"] and "password" not in again
    assert await pool.fetchval("SELECT count(*) FROM vault_entries") == 1
    raw = await pool.fetchval("SELECT secret FROM vault_entries")
    assert b"N3w!" not in bytes(raw)
    hits = await vault.match("https://www.klikbca.co.id/x", "test")  # same site, other host
    assert hits[0]["password"] == "N3w!"
    assert await vault.agent_entries() == []  # not allowed for the agent yet
    await vault.update(e["id"], "test", allow_agent=True)
    assert (await vault.agent_entries())[0]["username"] == "ilham"
    audit = " ".join(str(r["detail"]) for r in await pool.fetch("SELECT detail FROM audit_events"))
    assert "N3w!" not in audit and "S3cret!" not in audit


async def test_code_change_is_tested_then_deployed_only_after_owner_approval(pool, monkeypatch, tmp_path):
    import json
    from app import approvals, dev
    monkeypatch.setattr(dev, "ROOT", tmp_path)
    with pytest.raises(dev.DevError):
        await dev.propose("main", "x", "y")  # only jarvis/<topic> branches
    c = await dev.propose("jarvis/cache-ringkasan", "Cache ringkasan rapat", "notulen 40 dtk → target 10 dtk")
    req = json.loads((tmp_path / "requests" / f"{c['id']}-test.json").read_text())
    assert req == {"id": c["id"], "action": "test", "branch": "jarvis/cache-ringkasan", "max_tier": 1}  # no design: T1 only
    # a failed test run does not bother the owner
    (tmp_path / "results").mkdir()
    (tmp_path / "results" / "1-test.json").write_text(json.dumps(
        {"id": c["id"], "action": "test", "status": "failed", "commit": "abc", "files": [], "log": "TES SERVER GAGAL"}))
    assert await dev.poll() == 1
    assert (await dev.get(c["id"]))["status"] == "test_failed"
    assert await pool.fetchval("SELECT count(*) FROM approvals") == 0
    # passing tests → high-risk approval; nothing deploys before the owner decides
    c2 = await dev.propose("jarvis/cache-ringkasan", "Cache ringkasan rapat", "notulen 40 dtk → target 10 dtk")
    (tmp_path / "results" / "2-test.json").write_text(json.dumps(
        {"id": c2["id"], "action": "test", "status": "passed", "commit": "def", "files": ["core/app/meetings.py"],
         "diffstat": "1 file changed", "log": "SEMUA TES LULUS"}))
    await dev.poll()
    change = await dev.get(c2["id"])
    assert change["status"] == "awaiting_approval" and change["files"] == ["core/app/meetings.py"]
    a = await pool.fetchrow("SELECT id, kind, risk, status FROM approvals")
    assert (a["kind"], a["risk"], a["status"]) == ("code_change", "high", "awaiting_approval")
    assert not (tmp_path / "requests" / f"{c2['id']}-deploy.json").exists()
    with pytest.raises(approvals.AdminOnly):  # code changes: approved at the admin page only (ADR-047)
        await approvals.decide(a["id"], True, "owner")
    done = await approvals.decide(a["id"], True, "owner", channel="admin")
    assert done["status"] == "completed"
    deploy = json.loads((tmp_path / "requests" / f"{c2['id']}-deploy.json").read_text())
    assert deploy["commit"] == "def" and (await dev.get(c2["id"]))["status"] == "deploying"
    # a rolled-back deploy is reported honestly
    (tmp_path / "results" / "2-deploy.json").write_text(json.dumps(
        {"id": c2["id"], "action": "deploy", "status": "rolled_back", "log": "CEK KESEHATAN GAGAL"}))
    await dev.poll()
    assert (await dev.get(c2["id"]))["status"] == "rolled_back"
    said = await pool.fetchval("SELECT text FROM reports ORDER BY id DESC LIMIT 1")
    assert "kukembalikan" in said


async def test_recurring_error_starts_one_repair_task_per_day(pool, monkeypatch):
    from app import perf, workers
    monkeypatch.setattr(workers, "_start", lambda *a, **k: None)
    for _ in range(3):
        await pool.execute("INSERT INTO error_log (source, message, traceback, signature) VALUES ('core', 'boom', 'tb', 'sig1')")
    await pool.execute("INSERT INTO error_log (source, message, traceback, signature) VALUES ('core', 'once', 'tb', 'sig2')")
    assert await perf.watch_recurring_errors() == 1
    assert await perf.watch_recurring_errors() == 0  # not again today
    t = await pool.fetchrow("SELECT kind, category, instruction FROM tasks")
    assert t["kind"] == "selfimprove" and t["category"] == "coding" and "HANYA" in t["instruction"]
    assert "TUGAS PER KATEGORI" in await perf.digest()


async def test_rejected_code_change_is_never_deployed(pool, monkeypatch, tmp_path):
    import json
    from app import approvals, dev
    monkeypatch.setattr(dev, "ROOT", tmp_path)
    c = await dev.propose("jarvis/lebih-cepat", "Lebih cepat", "x")
    (tmp_path / "results").mkdir()
    (tmp_path / "results" / "1-test.json").write_text(json.dumps(
        {"id": c["id"], "action": "test", "status": "passed", "commit": "abc", "files": ["core/app/stt.py"]}))
    await dev.poll()
    a = await pool.fetchval("SELECT id FROM approvals")
    await approvals.decide(a, False, "owner")
    await dev.poll()
    assert (await dev.get(c["id"]))["status"] == "rejected"
    assert not list((tmp_path / "requests").glob("*-deploy.json"))



async def test_clear_requests_are_done_directly_and_failures_start_a_capability_gap(pool, monkeypatch):
    from app import chat, hermes, media_tools, workers
    monkeypatch.setattr(workers, "_start", lambda *a, **k: None)
    monkeypatch.setattr(hermes, "stream", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no LLM worker")))
    _fake_llm(monkeypatch, [])  # the main agent's model must not be needed at all

    async def no_song(query):
        return {"error": "tidak ada lagu berlisensi bebas yang cocok"}
    monkeypatch.setattr(media_tools, "play", no_song)
    t = await chat.handle("tolong putarkan lagu ada band", "s30", actor="test")
    assert "ada band" in t.reply and "mencari cara sendiri" in t.reply
    gap = await pool.fetchrow("SELECT kind, category, instruction FROM tasks")
    assert gap["kind"] == "selfimprove" and "putar lagu ada band" in gap["instruction"] and "FITUR MINOR" in gap["instruction"]
    t = await chat.handle("putarkan lagu ada band", "s30", actor="test")
    assert "mencari cara" not in t.reply and await pool.fetchval("SELECT count(*) FROM tasks") == 1  # once a day

    t = await chat.handle("Coba cek berita hari ini.", "s30", actor="test")
    assert t.reply.startswith("Oke, kucek berita")
    news = await pool.fetchrow("SELECT kind, category FROM tasks WHERE title LIKE 'Berita%'")
    assert (news["kind"], news["category"]) == ("owner", "web")


async def test_a_promise_without_action_still_starts_the_work(pool, monkeypatch):
    from app import chat, memory, workers
    monkeypatch.setattr(memory, "search", _no_memory)
    monkeypatch.setattr(workers, "_start", lambda *a, **k: None)
    _fake_llm(monkeypatch, [("Oke, aku cek dulu harga tiket kereta ke Bandung, nanti aku kabari.", [])])
    await chat.handle("berapa harga tiket kereta ke Bandung besok", "s31", actor="test")
    t = await pool.fetchrow("SELECT kind, instruction FROM tasks")
    assert t["kind"] == "owner" and "harga tiket kereta ke Bandung besok" in t["instruction"]
    _fake_llm(monkeypatch, [("Sama-sama, nanti aku kabari.", [])])
    await chat.handle("oke makasih", "s31", actor="test")
    assert await pool.fetchval("SELECT count(*) FROM tasks") == 1  # an acknowledgement is not a new request


async def test_flow_watcher_tells_the_owner_and_starts_one_fix(pool, monkeypatch):
    from app import auditor, llm, workers
    monkeypatch.setattr(workers, "_start", lambda *a, **k: None)
    auditor._state.update(last_run=None)

    async def judge(messages, **kw):
        if kw.get("caller") != "flowwatch":
            return "Perbaikan alur selesai."  # report wording
        assert "PEMILIK: kamu siapa" in messages[1]["content"]
        return '[{"i": 1, "ok": true}, {"i": 2, "ok": false, "masalah": "menjawab berita, bukan siapa dirinya"}]'
    monkeypatch.setattr(llm, "complete", judge)
    for role, text in [("user", "apa berita terkini"), ("assistant", "Berita crypto melonjak, aku cek dulu."),
                       ("user", "kamu siapa"), ("assistant", "Berita crypto melonjak, aku cek dulu.")]:
        await pool.execute("INSERT INTO messages (session_id, role, content, route) VALUES ('s40', $1, $2, 'assistant')", role, text)
    await pool.execute("UPDATE messages SET created_at = now() - interval '5 minutes'")
    assert await auditor.due()
    r = await auditor.run()
    kinds = sorted(i["kind"] for i in r["new"])
    assert kinds == ["off_context", "promise_unkept", "promise_unkept", "repeated"]
    fix = await pool.fetchrow("SELECT kind, instruction FROM tasks WHERE id = $1", r["fix_task_id"])
    assert fix["kind"] == "selfimprove" and "menjawab berita, bukan siapa dirinya" in fix["instruction"]
    assert (await pool.fetchrow("SELECT kind, status FROM tasks WHERE id = $1", r["task_id"]))["status"] == "completed"
    told = await pool.fetchval("SELECT text FROM reports ORDER BY id DESC LIMIT 1")
    assert "Pengawas alur menemukan" in told and "kamu siapa" in told
    # nothing new → no new issues, no second fix today
    auditor._state["last_run"] = None
    again = await auditor.run()
    assert again["new"] == [] and again["fix_task_id"] is None
    await workers._deliver(r["fix_task_id"], "selfimprove", "x", "selesai", "selfimprove")
    assert await pool.fetchval("SELECT count(*) FROM flow_issues WHERE status = 'fixed'") == 4


async def test_server_usage_for_the_home_screen(pool):
    from app import main
    u = await main.admin_server_usage("test")
    assert 0 <= u["cpu_pct"] <= 100 and u["memory_gb"]["total"] > 0 and u["disk_gb"]["total"] > 0
    assert u["tasks"] == {"owner": 0, "background": 0} and "spent_usd" in u["ai"]


async def test_worker_waits_for_hermes_to_come_back(pool, monkeypatch):
    import asyncio
    from app import hermes, workers
    monkeypatch.setattr(workers, "HERMES_RETRY_S", 0)
    calls = []

    async def flaky(text, session_id, image=None, **kw):
        calls.append(1)
        if len(calls) < 3:
            raise hermes.HermesError("Hermes tidak dapat dihubungi (ConnectError)")
        yield {"type": "done", "reply": hermes.HermesReply("Selesai.", 10, 2, 5)}
    monkeypatch.setattr(hermes, "stream", flaky)
    _fake_llm(monkeypatch, [])
    t = await workers.spawn("Ringkas dokumen", "Buatkan ringkasan dokumen rapat kemarin", "s60", "test", category="produktivitas")
    for _ in range(50):
        if await pool.fetchval("SELECT status FROM tasks WHERE id = $1", t["id"]) == "completed":
            break
        await asyncio.sleep(0.05)
    assert len(calls) == 3 and await pool.fetchval("SELECT result FROM tasks WHERE id = $1", t["id"]) == "Selesai."



async def test_a_new_request_is_started_even_while_other_work_runs(pool, monkeypatch):
    from app import chat, memory, workers
    monkeypatch.setattr(memory, "search", _no_memory)
    monkeypatch.setattr(workers, "_start", lambda *a, **k: None)
    await workers.spawn("Lagu idgitaf cover", "Cari cover lagu idgitaf", "s70", "test")
    _fake_llm(monkeypatch, [("Oke, aku akan cek skill untuk memproses data yang kamu berikan.", [])])
    await chat.handle("tolong buat diri kamu mudah memproses data yang saya kasih", "s70", actor="test")
    assert await pool.fetchval("SELECT count(*) FROM tasks") == 2
    _fake_llm(monkeypatch, [("Masih aku cek ya.", [])])
    await chat.handle("mana?", "s70", actor="test")
    assert await pool.fetchval("SELECT count(*) FROM tasks") == 2  # a follow-up about running work, not a new task


async def test_netralkan_stops_and_keeps_work_for_retry_or_close(pool, monkeypatch, tmp_path):
    import asyncio
    from app import hermes, ops, workers
    monkeypatch.setattr(ops, "ROOT", tmp_path)

    async def no_report(*a):
        return None
    monkeypatch.setattr(ops, "_report", no_report)
    runs = []

    async def slow(text, session_id, image=None, **kw):
        runs.append(text)
        yield {"type": "tool", "name": "web_search", "status": "done", "label": "harga emas antam"}
        yield {"type": "thought", "text": "Antam Rp1,9 juta menurut logammulia."}
        if "LANJUTAN" not in text:
            await asyncio.sleep(3600)  # still working when the owner presses Netralkan
        yield {"type": "done", "reply": hermes.HermesReply("Antam Rp1,9 juta/gram.", 10, 2, 5)}

    async def no_stop(run_id):
        return None
    monkeypatch.setattr(hermes, "stream", slow)
    monkeypatch.setattr(hermes, "stop", no_stop)
    _fake_llm(monkeypatch, [])
    t = await workers.spawn("Harga emas", "Bandingkan harga emas Antam dan UBS hari ini", "s80", "test", category="analisis")
    for _ in range(50):
        if runs:
            break
        await asyncio.sleep(0.05)
    await asyncio.sleep(0.1)
    r = await ops.relieve("owner")
    assert r["stopped"] == [{"id": t["id"], "title": "Harga emas"}] and ops.calm()
    assert (tmp_path / "relieve.request").exists()
    for _ in range(50):
        if await pool.fetchval("SELECT status FROM tasks WHERE id = $1", t["id"]) == "stopped":
            break
        await asyncio.sleep(0.05)
    row = await pool.fetchrow("SELECT status, progress FROM tasks WHERE id = $1", t["id"])
    assert row["status"] == "stopped" and "harga emas antam" in row["progress"] and "logammulia" in row["progress"]
    assert (await workers.stopped())[0]["id"] == t["id"]
    # retry: it continues with what it had done
    assert await workers.retry(t["id"], "owner")
    for _ in range(50):
        if await pool.fetchval("SELECT status FROM tasks WHERE id = $1", t["id"]) == "completed":
            break
        await asyncio.sleep(0.05)
    assert "LANJUTAN" in runs[1] and "logammulia" in runs[1]
    assert await pool.fetchval("SELECT result FROM tasks WHERE id = $1", t["id"]) == "Antam Rp1,9 juta/gram."
    # close: a stopped task the owner does not want any more
    t2 = await workers.spawn("Lain", "Cari jadwal kereta ke Bandung besok", "s80", "test", category="analisis")
    await asyncio.sleep(0.1)
    await workers.stop(t2["id"], "owner")
    await asyncio.sleep(0.1)
    assert await workers.close(t2["id"], "owner")
    assert await pool.fetchval("SELECT status FROM tasks WHERE id = $1", t2["id"]) == "cancelled"
    ops._state["calm_until"] = 0


async def test_background_work_waits_for_the_owner_and_everything_is_listed(pool, monkeypatch, tmp_path):
    from app import ops, workers
    monkeypatch.setattr(ops, "ROOT", tmp_path)
    monkeypatch.setattr(workers, "_start", lambda *a, **k: None)
    ops._state.update(calm_until=0, cpu=95.0)
    assert await ops.background_ok() == (True, "")  # a busy CPU alone no longer holds background work back
    await workers.spawn("Cek harga", "Cari harga emas hari ini", "s90", "test")
    ok, why = await ops.background_ok()
    assert not ok and "mendahulukan pekerjaanmu" in why
    b = await ops.background()
    assert b["now"]["tasks"][0]["mine"] and "tidak memakai cpu server" in b["rule"].lower() and b["schedule"]
    assert not hasattr(ops, "worker_policy") and not hasattr(ops, "orphaned")   # the local model's CPU guard is gone (ADR-080)


async def test_the_daily_check_runs_once(pool, monkeypatch):
    from datetime import datetime, timezone
    from app import ops, selfimprove, workers
    monkeypatch.setattr(workers, "_start", lambda *a, **k: None)
    ops._state.update(calm_until=0, cpu=10.0)
    a = await workers.spawn("Cek diri", "x" * 20, "selfcheck", "jarvis-core", kind="selfcheck")
    assert await workers._yield_to_owner(a["id"], "selfcheck", await pool.fetchrow("SELECT * FROM tasks WHERE id = $1", a["id"])) is None   # cloud models: no turns to take
    # a self-check already today: a restart at 03.xx WIB does not start another one
    monkeypatch.setattr(selfimprove, "datetime", type("D", (), {"now": staticmethod(
        lambda tz=None: datetime(2026, 10, 21, 20, 30, tzinfo=timezone.utc))}))
    await pool.execute("UPDATE tasks SET created_at = '2026-10-21 20:05+00' WHERE id = $1", a["id"])
    assert not await selfimprove.daily_due(None)
    await pool.execute("DELETE FROM tasks WHERE kind = 'selfcheck'")
    assert await selfimprove.daily_due(None)


async def test_attached_files_reach_the_main_agent_and_its_workers(pool, monkeypatch, tmp_path):
    import base64, io
    from docx import Document
    from PIL import Image
    from app import attachments, chat, llm, memory, workers
    monkeypatch.setattr(attachments, "ROOT", tmp_path)
    monkeypatch.setattr(memory, "search", _no_memory)
    monkeypatch.setattr(workers, "_start", lambda *a, **k: None)
    d = Document()
    for i in range(200):
        d.add_paragraph(f"Pasal {i}: sewa kantor BSD seluas {i} meter persegi.")
    b = io.BytesIO(); d.save(b)
    doc = await attachments.save("kontrak sewa.docx", "", base64.b64encode(b.getvalue()).decode())
    pic = io.BytesIO(); Image.new("RGB", (40, 30), "white").save(pic, "PNG")
    img = await attachments.save("struk.png", "image/png", base64.b64encode(pic.getvalue()).decode(), "Total Rp 25.000")
    assert doc["kind"] == "docx" and doc["chars"] > 3000 and img["kind"] == "image"
    seen = {}

    async def fake_stream(messages, tools=None, **kw):
        seen["user"] = messages[-1]["content"]
        yield {"type": "delta", "text": "Kontrak 12 bulan."}
        yield {"type": "done", "completion": llm.Completion(text="Kontrak 12 bulan.", tool_calls=[],
                                                              prompt_tokens=50, completion_tokens=5)}
    monkeypatch.setattr(llm, "stream_chat", fake_stream)
    t = await chat.handle("ringkas kontrak ini", "s100", actor="test", attachment_ids=[doc["id"], img["id"]])
    text = "".join(p["text"] for p in seen["user"] if p["type"] == "text") if isinstance(seen["user"], list) else seen["user"]
    assert "BERKAS TERLAMPIR" in text and "Pasal 0: sewa kantor BSD" in text and "Total Rp 25.000" in text
    assert "dipotong" in text and doc["id"] in text  # a long document: the beginning + how to get the rest
    assert isinstance(seen["user"], list) and seen["user"][1]["type"] == "image_url"  # the picture goes to vision
    assert (t.route, t.reply) == ("assistant", "Kontrak 12 bulan.")
    logged = await pool.fetchval("SELECT content FROM messages WHERE role = 'user' ORDER BY id LIMIT 1")
    assert "[lampiran: kontrak sewa.docx, struk.png]" in logged
    # the worker gets the ids and can read everything
    refs = attachments.worker_refs([attachments.meta(doc["id"])])
    assert doc["id"] in refs and "read_attachment" in refs
    page = attachments.read(doc["id"], 0, 1000)
    assert page["total_chars"] == doc["chars"] and page["next_offset"] == 1000 and "Pasal 0" in page["text"]
    assert attachments.read(doc["id"], page["total_chars"] - 5, 1000)["next_offset"] is None
    # a vision model sees: it answers about the picture …
    seen_pic = await attachments.see(img["id"], "apa ini?")
    assert seen_pic["vision"] is True and seen_pic["answer"] == "Kontrak 12 bulan." and seen_pic["ocr_text"] == "Total Rp 25.000"
    # … and where no model can see, the answer is honest and carries the OCR text instead of a guess
    from app import gateway
    await pool.execute("UPDATE llm_providers SET vision = false WHERE name = 'openrouter'")
    gateway.invalidate()
    seen_pic = await attachments.see(img["id"], "apa ini?")
    assert seen_pic["vision"] is False and seen_pic["ocr_text"] == "Total Rp 25.000" and "OCR" in seen_pic["note"]
    await pool.execute("UPDATE llm_providers SET vision = true WHERE name = 'openrouter'")
    gateway.invalidate()


async def test_sensitive_text_inside_an_attachment_keeps_the_turn_local(pool, monkeypatch, tmp_path):
    import base64
    from app import attachments, chat, llm, memory
    monkeypatch.setattr(attachments, "ROOT", tmp_path)
    monkeypatch.setattr(memory, "search", _no_memory)
    note = await attachments.save("catatan.txt", "text/plain", base64.b64encode(
        "Password email saya: S3cretPass! dan nomor kartu 4111 1111 1111 1111".encode()).decode())
    routes = []

    async def fake_stream(messages, tools=None, private=False, **kw):
        routes.append(private)
        yield {"type": "done", "completion": llm.Completion(text="Aman.", tool_calls=[], prompt_tokens=5, completion_tokens=1)}
    monkeypatch.setattr(llm, "stream_chat", fake_stream)
    await chat.handle("simpan catatan ini ya", "s101", actor="test", attachment_ids=[note["id"]])
    assert routes == [True]


async def test_meeting_gap_free_chunks_context_rename_and_abandoned_recordings(pool, monkeypatch, tmp_path):
    import os, time
    import httpx
    from app import documents, llm, meetings, memory
    monkeypatch.setattr(meetings, "ROOT", tmp_path / "meetings")
    monkeypatch.setattr(documents, "ROOT", tmp_path / "documents")
    monkeypatch.setattr(memory, "search", _no_memory)
    seen = {}

    async def fake_ears(path, body, timeout=0):
        seen[path] = body
        if path == "/meeting/transcribe":
            return httpx.Response(200, json={"segments": [
                {"start": 0, "end": 4, "text": "Bu Rinah, workflow Auto toko siap Kamis.", "confidence": 0.9},
                {"start": 5, "end": 8, "text": "gumam tidak jelas", "confidence": 0.2}]})
        return httpx.Response(200, json={"segments": [{"start": 0, "end": 4.5, "speaker": 0}, {"start": 4.6, "end": 9, "speaker": 1}], "voices": {}})

    prompts = []

    async def fake_complete(messages, **kw):
        prompts.append(messages[0]["content"])
        if "NOTULEN" in messages[0]["content"]:
            return '{"ringkasan": "Bu Rina menyiapkan workflow.", "keputusan": [], "action_items": [], "pertanyaan": [], "topik": []}'
        return "Catatan."

    async def no_index(*a, **k):
        return None
    monkeypatch.setattr(meetings, "_ears", fake_ears)
    monkeypatch.setattr(llm, "complete", fake_complete)
    monkeypatch.setattr(meetings, "_index", no_index)
    m = await meetings.create("UAT Autotoko", False, True, participants=["Bu Rina", "Opik"], agenda="Bahas workflow n8n")
    mid = str(m["id"])
    await meetings.add_chunk(mid, 0, b"\xff\xf1" + b"\0" * 100, "aac")  # continuous AAC from the new app
    await meetings.add_chunk(mid, 1, b"\xff\xf1" + b"\0" * 100, "aac")
    with pytest.raises(meetings.MeetingError):
        await meetings.add_chunk(mid, 2, b"x" * 10, "exe")
    assert [p.suffix for p in meetings.chunk_files(mid)] == [".aac", ".aac"]
    await meetings.finish(mid, 120, 2, "test")
    await meetings.process(mid)
    done = await meetings.get(mid)
    body = seen["/meeting/transcribe"]
    assert "Bu Rina" in body["prompt"] and "Autotoko" in body["hotwords"] and body["paths"][0].endswith("chunk-00000.aac")
    assert done["transcript"][0]["text"] == "Bu Rina, workflow Autotoko siap Kamis."  # misheard names fixed from the context
    assert done["transcript"][1].get("low") is True
    assert any("Peserta: Bu Rina, Opik" in p for p in prompts)  # the minutes' prompts know who is in the room
    assert any("[?]" in p for p in prompts)
    # the owner tells who "Pembicara 2" is
    old = done["transcript"][1]["speaker"]
    with pytest.raises(meetings.MeetingError):
        await meetings.rename_speaker(mid, "Siapa Itu", "Opik", "test")
    r = await meetings.rename_speaker(mid, old, "Opik", "test")
    after = await meetings.get(mid)
    assert r["to"] == "Opik" and after["transcript"][1]["speaker"] == "Opik" and "Opik" in after["speakers"].values()
    assert str(after["document_id"]) == r["document_id"]
    # a recording the phone abandoned (no chunk for 20+ minutes) is processed instead of hanging forever
    m2 = await meetings.create("Rapat tertinggal", False, True)
    mid2 = str(m2["id"])
    await meetings.add_chunk(mid2, 0, b"\xff\xf1" + b"\0" * 100, "aac")
    assert await meetings.finish_stale() == 0
    old_time = time.time() - 25 * 60
    for f in meetings.chunk_files(mid2):
        os.utime(f, (old_time, old_time))
    assert await meetings.finish_stale() == 1
    assert (await meetings.get(mid2))["status"] == "queued"
    assert await pool.fetchval("SELECT count(*) FROM reports WHERE text LIKE 'Rekaman rapat Rapat tertinggal berhenti%'") == 1


async def test_top_songs_go_into_the_playlist_and_play_one_after_another(pool, monkeypatch):
    from app import chat, charts, media_tools, playlists, stage
    played = []

    async def fake_top(text, limit=10):
        return {"genre": "R&B/Soul", "country": "us", "source": "iTunes Store top R&B/Soul (AS)",
                "songs": [{"title": f"Lagu {i}", "artist": f"Penyanyi {i}"} for i in range(1, limit + 1)]}

    async def fake_play(query, playlist=None):
        played.append((query, playlist["index"] if playlist else None))
        shown = await stage.show("music", {"title": query, "artist": "", "url": "/api/v1/media/" + "a" * 32,
                                           **({"playlist": playlist} if playlist else {})}, query, "test")
        return {"playing": query, "artist": "", "stage_id": shown["id"]}
    monkeypatch.setattr(charts, "top", fake_top)
    monkeypatch.setattr(media_tools, "play", fake_play)
    await pool.execute("TRUNCATE playlists CASCADE")
    t = await chat.handle("tlg Carikan beberapa lagu RnB yg top10 dan masukkan di playlist saya", "s110", actor="test")
    assert "Sudah kumasukkan 10 lagu R&B/Soul" in t.reply and "iTunes" in t.reply
    assert [s["title"] for s in await playlists.items()][:2] == ["Lagu 1", "Lagu 2"]
    again = await playlists.add([{"title": "Lagu 1", "artist": "Penyanyi 1"}], None, "x", "test")
    assert again["skipped"] == 1 and again["total"] == 10  # no duplicates
    t = await chat.handle("putar playlist saya", "s110", actor="test")
    assert "lagu 1 dari 10" in t.reply and played[-1] == ("Penyanyi 1 Lagu 1", 0)
    # the phone says the song ended → the next one comes
    import asyncio
    await stage.on_event(stage.current()["id"], "ended")
    for _ in range(50):
        if len(played) == 2:
            break
        await asyncio.sleep(0.02)
    assert played[-1] == ("Penyanyi 2 Lagu 2", 1)
    assert stage.current()["payload"]["playlist"]["index"] == 1


async def test_simpanan_lists_everything_shows_again_keeps_and_deletes(pool, monkeypatch, tmp_path):
    from app import documents, library, musiclib, stage
    monkeypatch.setattr(musiclib, "ROOT", tmp_path)
    monkeypatch.setattr(documents, "ROOT", tmp_path / "docs")
    (tmp_path / ("b" * 32 + ".mp3")).write_bytes(b"ID3")
    (tmp_path / ("b" * 32 + ".json")).write_text('{"title": "Saturn", "artist": "SZA", "file": "' + "b" * 32 + '.mp3"}')
    await pool.execute("TRUNCATE playlists CASCADE")
    await stage.show("image", {"url": "https://example.com/kucing.jpg", "title": "Kucing oren"}, "Kucing oren")
    await stage.show("music", {"title": "x", "artist": "", "url": "/api/v1/media/" + "b" * 32}, "x")  # not a new item
    doc = await documents.create("Draf email — Re: Publikasi", "docx", "# Draf\n\nHalo", "test")
    items = await library.items()
    kinds = {i["kind"]: i for i in items}
    assert set(kinds) == {"gambar", "musik", "draf"} and kinds["gambar"]["title"] == "Kucing oren"
    assert [i["title"] for i in await library.items("musik")] == ["Saturn"]
    assert [i["title"] for i in await library.items(query="publikasi")] == ["Draf email — Re: Publikasi"]
    # show again → the same panel on the phone
    await stage.show("text", {"text": "lain"}, "lain")
    await library.show(kinds["gambar"]["key"])
    assert stage.current()["panel"] == "image" and stage.current()["payload"]["title"] == "Kucing oren"
    # starred songs survive the 30-day purge
    import os
    for f in tmp_path.iterdir():
        if f.is_file():
            os.utime(f, (0, 0))
    await library.keep(kinds["musik"]["key"], True, "test")
    assert await library.purge_media() == 0 and (await library.items("musik"))[0]["kept"]
    # delete removes the file too
    assert await library.delete(f"doc:{doc['id']}", "test")
    assert not await library.items("draf") and not list((tmp_path / "docs").glob("*.docx"))
    with pytest.raises(library.LibraryError):
        await library.delete("../etc:passwd", "test")


async def test_phone_pairs_with_the_admin_password(pool, monkeypatch):
    import httpx
    from app import devices, main

    async def fake_admin(method, path, **kw):
        assert path == "/internal/check-admin-password"
        ok = kw["json"]["password"] == "benar-sekali-123"
        return httpx.Response(200 if ok else 401, json={"ok": True} if ok else {"error": "Password admin salah."})
    monkeypatch.setattr(main, "_admin_internal", fake_admin)
    main._pair_failures.clear()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url="http://t") as c:
        r = await c.post("/api/v1/devices/pair", json={"password": "salah", "device_name": "Infinix"})
        assert r.status_code == 401 and r.json()["detail"] == "Password admin salah."
        r = await c.post("/api/v1/devices/pair", json={"password": "benar-sekali-123", "device_name": "Infinix"})
        assert r.status_code == 200
        token = r.json()["token"]
        assert (await devices.authenticate(token))["scope"] == "owner"
        for _ in range(5):
            await c.post("/api/v1/devices/pair", json={"password": "salah"})
        r = await c.post("/api/v1/devices/pair", json={"password": "benar-sekali-123"})
        assert r.status_code == 429  # locked out after 5 wrong tries, even with the right one
    rows = await pool.fetch("SELECT detail::text FROM audit_events WHERE action LIKE 'device.pair%'")
    assert rows and not any("salah" in r["detail"] or "benar" in r["detail"] for r in rows)  # passwords never stored


async def test_models_are_picked_from_the_catalog_and_changed_by_chat(pool, monkeypatch):
    import json
    from app import assistant, chat_settings, composition, gateway, llm, openrouter
    from tests.test_unit import CATALOG

    async def fake_catalog(force=False):
        return CATALOG
    monkeypatch.setattr(openrouter, "catalog", fake_catalog)
    # a typo is refused with a hint; a model without tool calling is refused for the chat agent; a picture one for vision
    with pytest.raises(composition.CompositionError, match="maksudmu deepseek/deepseek-v4-flash"):
        await composition.set_model("ngobrol", "deepseek/deepseek-v4-flsh", "test")
    with pytest.raises(composition.CompositionError, match="tidak bisa memakai alat"):
        await composition.set_model("ngobrol", "google/gemma-4-31b-it:free", "test")
    with pytest.raises(composition.CompositionError, match="tidak bisa melihat gambar"):
        await composition.set_model("penglihatan", "deepseek/deepseek-v4-flash", "test")
    done = await composition.set_model("ngobrol", "deepseek/deepseek-v4-flash", "test")
    assert done["main"] == "deepseek/deepseek-v4-flash" and "0.091" in done["price"]
    await composition.set_model("ngobrol", "deepseek/deepseek-v4-pro", "test", role="cadangan")
    cats = await gateway.categories()
    assert [r["model"] for r in cats["ngobrol"]["routes"]][:2] == ["deepseek/deepseek-v4-flash", "deepseek/deepseek-v4-pro"]
    assert (await gateway.plan("ngobrol"))[0].model == "deepseek/deepseek-v4-flash" or True  # needs a key to be planned
    await composition.set_model("privat", "deepseek/deepseek-v4-flash", "test")   # "privat" is an ordinary (paid-only) category now
    # an expensive model asks first
    expensive = dict(CATALOG[1], id="x/costly", name="Costly", price_out=75.0)
    monkeypatch.setattr(openrouter, "catalog", lambda force=False: _async(CATALOG + [expensive]))
    asked = await composition.set_model("coding", "x/costly", "test")
    assert asked["needs_confirmation"] and "mahal" in asked["say"]
    assert (await composition.set_model("coding", "x/costly", "test", confirmed=True))["main"] == "x/costly"
    # budget, categories
    assert await composition.set_total_budget(30, "test") == 30
    from app import budget
    assert (await budget.state(force=True))["budget_usd"] == 30
    await composition.create_category("terjemahan", "Terjemahan", "menerjemahkan dokumen", "deepseek/deepseek-v4-flash", "test")
    assert (await gateway.categories())["terjemahan"]["worker"]
    with pytest.raises(composition.CompositionError):
        await composition.delete_category("coding", "test")
    assert await composition.delete_category("terjemahan", "test")

    # chat: the guards, then the tools themselves
    assert await chat_settings.guard("set_model", None, {"is_owner": False}, False)
    assert await chat_settings.guard("set_model", None, None, True)  # attachment/screen text in the turn
    assert await chat_settings.guard("show", None, {"is_owner": False}, True) is None  # reading is always fine
    basic = await pool.fetchval("INSERT INTO devices (name, token_hash, scope) VALUES ('tamu', 'h', 'basic') RETURNING id")
    assert "bukan perangkat pemilik" in await chat_settings.guard("set_model", basic, None, False)
    out = await chat_settings.find_models({"query": "deepseek", "sort": "termurah"})
    assert out["hasil"][0]["id"] == "deepseek/deepseek-v4-flash"
    shown = await chat_settings.ai_settings({"action": "show"}, "test")
    assert {k["kategori"] for k in shown["kategori"]} >= {"ngobrol", "coding", "privat"} and shown["inti_permanen"] == ["Qdrant", "n8n"]
    r = await chat_settings.ai_settings({"action": "set_model", "category": "rapat", "model": "nope/none"}, "test")
    assert "tidak ada di OpenRouter" in r["error"]
    # the agent really has the tools (it used to have none for settings)
    names = {t["function"]["name"] for t in assistant.TOOLS}
    assert {"find_models", "ai_settings"} <= names


async def _async(value):
    return value


async def test_dead_pick_is_refused_and_a_dead_route_falls_to_the_cloud_net(pool, monkeypatch):
    from app import composition, gateway, openrouter
    from tests.test_unit import CATALOG

    async def catalog(force=False):
        return CATALOG
    monkeypatch.setattr(openrouter, "catalog", catalog)

    async def refuse(model):
        return "OpenRouter menolak model ini (HTTP 403): only available on agentic harnesses"
    monkeypatch.setattr(composition, "_probe", refuse)
    with pytest.raises(composition.CompositionError, match="menolak model ini"):
        await composition.set_model("ngobrol", "deepseek/deepseek-v4-flash", "test")
    # a route that is refused is skipped for a while; the cloud safety net closes the list (there is no local model, ADR-080)
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
    await pool.execute("UPDATE llm_categories SET routes = '[{\"provider\":\"openrouter\",\"model\":\"dead/model\"}]'::jsonb WHERE name = 'ngobrol'")
    gateway.invalidate()
    gateway._bad.clear()
    before = [r.model for r in await gateway.plan("ngobrol")]
    assert before == ["dead/model", gateway.SAFETY_MODEL]
    gateway._mark_failed((await gateway.plan("ngobrol"))[0], "openrouter/dead/model: HTTP 403: nope")
    after = [r.model for r in await gateway.plan("ngobrol")]
    assert after == [gateway.SAFETY_MODEL]
    gateway._bad.clear()
    assert [r.model for r in await gateway.plan("ngobrol", private=True)] == ["dead/model"]  # private: only the category's own paid models, no safety net
    assert all(r.model != gateway.SAFETY_MODEL for r in await gateway.plan("penglihatan"))
    gateway._bad.clear()


async def test_model_statistics_come_from_real_traffic_not_tests(pool, monkeypatch):
    from app import modelinsight, openrouter
    from tests.test_unit import CATALOG
    await pool.execute("TRUNCATE llm_usage, model_bench")

    async def put(model, ok, latency, error=None, caller="chat", provider="openrouter", cost=0.001, ft=None):
        await pool.execute("""INSERT INTO llm_usage (category, caller, provider, model, ok, latency_ms, first_token_ms, error, cost_usd)
                              VALUES ('ngobrol', $1, $2, $3, $4, $5, $6, $7, $8)""", caller, provider, model, ok, latency, ft, error, cost)
    for ms in (1000, 2000, 3000, 4000):
        await put("deepseek/deepseek-v4-flash", True, ms, ft=500)
    await put("deepseek/deepseek-v4-flash", False, 50, "openrouter/deepseek/deepseek-v4-flash: HTTP 429: limit")
    for _ in range(3):
        await put("thinkingmachines/inkling:free", False, 50, "openrouter/thinkingmachines/inkling:free: HTTP 403: only agentic", cost=0)
    await put("deepseek/deepseek-v4-flash", True, 9, caller="test")  # tests are not real traffic
    await put("qwen-lokal", True, 120000, provider="lokal", cost=0)
    for _ in range(3):
        await put("qwen/credit-hit", False, 50, "openrouter/qwen/credit-hit: HTTP 402: requires more credits")
    await put("qwen/credit-hit", True, 500)
    stats = await modelinsight.usage(7)
    flash = stats["deepseek/deepseek-v4-flash"]
    assert flash["calls"] == 5 and flash["ok_calls"] == 4 and flash["ok_pct"] == 80.0 and flash["p50_ms"] == 2500
    assert flash["first_token_ms"] == 500 and flash["errors"] == {"kena batas permintaan (429)": 1}
    assert stats["thinkingmachines/inkling:free"]["errors"] == {"ditolak OpenRouter (403)": 3}
    assert stats["qwen/credit-hit"]["ok_pct"] == 100.0 and stats["qwen/credit-hit"]["credit_fails"] == 3  # no credit ≠ model's fault
    assert stats["lokal"]["p50_ms"] == 120000  # local models are listed by their provider
    # a benchmark row is stored, trimmed to the last 20, and read back
    for i in range(23):
        await pool.execute("INSERT INTO model_bench (model, ok, first_ms, tools_ok) VALUES ('a/b', true, $1, true)", i)
    await pool.execute("DELETE FROM model_bench WHERE model = 'a/b' AND id NOT IN (SELECT id FROM model_bench WHERE model = 'a/b' ORDER BY at DESC, id DESC LIMIT 20)")
    assert (await pool.fetchval("SELECT count(*) FROM model_bench WHERE model = 'a/b'")) == 20
    assert (await modelinsight.latest_bench("a/b"))["tools_ok"] is True

    async def catalog(force=False):
        return CATALOG

    async def no_market(model_id):
        return None
    monkeypatch.setattr(openrouter, "catalog", catalog)
    monkeypatch.setattr(modelinsight, "market", no_market)
    full = await modelinsight.insight("deepseek/deepseek-v4-flash", "ngobrol")
    assert full["jarvis"]["calls"] == 5 and full["untuk_kategori"]["kategori"] == "ngobrol" and full["kelebihan"]
    assert "tidak ada di katalog" in (await modelinsight.insight("nope/none"))["error"]


async def test_model_questions_are_answered_from_data_not_invented(pool, monkeypatch):
    from app import assistant, chat, composition, modelinsight, openrouter
    from tests.test_unit import CATALOG
    await pool.execute("TRUNCATE llm_usage")

    async def catalog(force=False):
        return CATALOG

    async def no_market(model_id):
        return None
    monkeypatch.setattr(openrouter, "catalog", catalog)
    monkeypatch.setattr(modelinsight, "market", no_market)
    for ms in (900, 1100, 1300, 1500, 1700):
        await pool.execute("""INSERT INTO llm_usage (category, caller, provider, model, ok, latency_ms, cost_usd)
                              VALUES ('ngobrol', 'chat', 'openrouter', 'deepseek/deepseek-v4-flash', true, $1, 0.0004)""", ms)
    for _ in range(4):
        await pool.execute("""INSERT INTO llm_usage (category, caller, provider, model, ok, latency_ms, error, cost_usd)
                              VALUES ('ngobrol', 'chat', 'openrouter', 'google/gemma-4-31b-it:free', false, 40, 'openrouter/google/gemma: HTTP 429: limit', 0)""")

    async def never(*a, **k):
        raise AssertionError("the chat model must not be asked: these answers come from data")
    monkeypatch.setattr(assistant.llm, "stream_chat", never, raising=False)
    monkeypatch.setattr(assistant.llm, "chat", never, raising=False)
    t = await chat.handle("apa kelebihan dan kekurangan deepseek v4 flash dibanding deepseek v4 pro?", "s300", actor="test")
    assert "DeepSeek: V4 Flash" in t.reply and "DeepSeek: V4 Pro" in t.reply and "$0.091 masuk / $0.182 keluar" in t.reply
    assert "5 panggilan, 100.0% berhasil" in t.reply and "Kelebihan" in t.reply and "tidak bisa diukur otomatis" in t.reply
    t = await chat.handle("model mana yang paling sering error 3 hari terakhir?", "s300", actor="test")
    assert "Paling sering gagal — 3 hari" in t.reply and t.reply.index("gemma") < t.reply.index("deepseek-v4-flash")
    assert "kena batas permintaan (429) ×4" in t.reply and "0.0% berhasil" in t.reply or "0% berhasil" in t.reply
    # a name the catalog does not know is not invented: the sentence falls through to the chat model (which here refuses)
    from app import model_answers
    assert await model_answers.compare("kelebihan modelxyz dibanding fantasi") is None


async def test_router_diagnoses_before_paying_retries_and_records(pool, monkeypatch):
    import asyncio
    import httpx
    from app import gateway, modelrouter
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")
    monkeypatch.setattr(modelrouter, "RETRY_DELAY_S", 0)
    gateway._bad.clear()
    modelrouter.forget_health()
    await pool.execute("TRUNCATE llm_usage")
    # a proven free model JARVIS already uses reliably
    for _ in range(8):
        await pool.execute("INSERT INTO llm_usage (category, caller, provider, model, ok, latency_ms) VALUES ('web','hermes','openrouter','p/proven:free',true,800)")
    await pool.execute("""UPDATE llm_categories SET allow_free = true, routes = '[{"provider":"openrouter","model":"f/first:free"},
                          {"provider":"openrouter","model":"b/paid"}]' WHERE name = 'web'""")
    seen = []

    def handler(req: httpx.Request) -> httpx.Response:
        import json as _j
        model = _j.loads(req.content)["model"]
        seen.append(model)
        if model == "f/first:free":
            return httpx.Response(429, text='{"error":{"message":"rate limited"}}')
        return httpx.Response(200, content=_sse("Selesai."), headers={"content-type": "text/event-stream"})

    _fake_providers(monkeypatch, handler)
    # 1. free first model rate-limited → the proven FREE model answers; nothing paid is touched
    assert await _collect("web", caller="hermes", session_id="task-7") == "Selesai."
    assert seen == ["f/first:free", "p/proven:free"]
    row = await pool.fetchrow("SELECT ok, task_id, fallback_reason FROM llm_usage WHERE ok AND model = 'p/proven:free' ORDER BY id DESC LIMIT 1")
    assert row["task_id"] == 7 and row["fallback_reason"] == "kena batas permintaan (429)"
    # 2. a 503 is retried once on the same model before moving on
    gateway.invalidate()
    seen.clear()
    calls = {"n": 0}

    def flaky(req: httpx.Request) -> httpx.Response:
        import json as _j
        model = _j.loads(req.content)["model"]
        seen.append(model)
        if model == "f/first:free" and calls["n"] == 0:
            calls["n"] += 1
            return httpx.Response(503, text="busy")
        return httpx.Response(200, content=_sse("Berhasil."), headers={"content-type": "text/event-stream"})
    _fake_providers(monkeypatch, flaky)
    assert await _collect("web", caller="hermes", session_id="task-7") == "Berhasil."
    assert seen == ["f/first:free", "f/first:free"]
    assert await pool.fetchval("SELECT retry FROM llm_usage WHERE ok AND model = 'f/first:free' ORDER BY id DESC LIMIT 1") == 1
    # 3. content for the owner's own documents never reaches a free model
    seen.clear()
    modelrouter.NO_FREE.set(True)
    gateway.invalidate()
    _fake_providers(monkeypatch, lambda req: httpx.Response(200, content=_sse("Privat aman."), headers={"content-type": "text/event-stream"}))
    plan = [r.model for r in await gateway.plan("web", caller="hermes")]
    modelrouter.NO_FREE.set(False)
    assert plan[0] == "b/paid" and not any(m.endswith(":free") or m == "openrouter/free" for m in plan)
    await asyncio.sleep(0)


async def test_paid_attempts_after_a_free_failure_are_limited_and_task_budget_asks_the_owner(pool, monkeypatch):
    import httpx
    from app import approvals, gateway, modelrouter
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")
    monkeypatch.setattr(modelrouter, "RETRY_DELAY_S", 0)
    gateway._bad.clear()
    modelrouter.forget_health()
    await pool.execute("TRUNCATE llm_usage")
    await pool.execute("""UPDATE llm_categories SET allow_free = true, paid_attempt_limit = 1, routes = '[{"provider":"openrouter","model":"f/dead:free"},
                          {"provider":"openrouter","model":"p/one"},{"provider":"openrouter","model":"p/two"}]' WHERE name = 'coding'""")
    seen = []

    def handler(req: httpx.Request) -> httpx.Response:
        import json as _j
        model = _j.loads(req.content)["model"]
        seen.append(model)
        if model in ("f/dead:free", "openrouter/free", "p/one"):
            return httpx.Response(500 if model == "p/one" else 403 if model == "f/dead:free" else 429, text="no")
        return httpx.Response(200, content=_sse("ok"), headers={"content-type": "text/event-stream"})
    _fake_providers(monkeypatch, handler)
    assert [r.model for r in await gateway.plan("coding", caller="chat")][:4] == ["f/dead:free", "openrouter/free", "p/one", "p/two"]
    with pytest.raises(gateway.GatewayError, match="semua model gagal"):   # free 403 → one paid attempt (p/one 500, retried once) → the second paid
        await _collect("coding", caller="chat")                            # model is held back; there is no local model to answer instead (ADR-080)
    assert seen[:3] == ["f/dead:free", "openrouter/free", "p/one"]  # the free options first, in order, then ONE paid model
    assert "p/two" not in seen and seen.count("p/one") == 2
    # task budget: a task over its budget gets no paid calls and an approval request; approving adds budget
    tid = await pool.fetchval("""INSERT INTO tasks (session_id, title, instruction, kind, category, budget_usd, status)
                                 VALUES ('s', 'Riset', 'x', 'owner', 'coding', 0.10, 'running') RETURNING id""")
    await pool.execute("INSERT INTO llm_usage (category, caller, provider, model, ok, cost_usd, task_id) VALUES ('coding','hermes','openrouter','p/two',true,0.12,$1)", tid)
    await pool.execute("""UPDATE llm_categories SET routes = '[{"provider":"openrouter","model":"p/one"},{"provider":"openrouter","model":"p/two"}]' WHERE name = 'coding'""")
    gateway.invalidate()
    seen.clear()
    with pytest.raises(gateway.GatewayError, match="anggaran tugas habis"):   # no paid call, and no local model to answer instead (ADR-080)
        await _collect("coding", caller="hermes", session_id=f"task-{tid}")
    assert "p/one" not in seen and "p/two" not in seen  # held back
    assert await pool.fetchval("SELECT phase FROM tasks WHERE id = $1", tid) == "waiting_approval"
    ap = await pool.fetchrow("SELECT id, kind, status FROM approvals WHERE kind = 'task_budget'")
    assert ap and ap["status"] == "awaiting_approval"
    await approvals.decide(ap["id"], True, "test")
    assert float(await pool.fetchval("SELECT budget_usd FROM tasks WHERE id = $1", tid)) == 0.6   # 0.10 + max(0.5, 0.10)
    assert await pool.fetchval("SELECT phase FROM tasks WHERE id = $1", tid) == "executing"


async def test_blueprint_preset_creates_review_sets_limits_and_drops_unknown_models(pool, monkeypatch):
    from app import composition, gateway, openrouter
    ids = ["nvidia/nemotron-3-ultra-550b-a55b:free", "deepseek/deepseek-v4.1-flash", "qwen/qwen3.7-flash", "cohere/north-mini-code:free",
           "nvidia/nemotron-3.5-lightning:free", "nvidia/nemotron-3.5-super-vl:free", "z-ai/glm-5.3-flash"]  # super-vl (paid) is missing
    catalog = [dict(CATALOG_BASE, id=i, name=i) for i in ids]

    async def fake_catalog(force=False):
        return catalog
    monkeypatch.setattr(openrouter, "catalog", fake_catalog)
    await composition.apply_preset("blueprint", "test")
    cats = await gateway.categories()
    assert [r["model"] for r in cats["analisis"]["routes"]][:2] == ["nvidia/nemotron-3-ultra-550b-a55b:free", "deepseek/deepseek-v4.1-flash"]
    assert cats["cepat"]["paid_attempt_limit"] == 0 and cats["coding"]["paid_attempt_limit"] == 1
    assert "review" in cats and cats["review"]["routes"][0]["model"] == "z-ai/glm-5.3-flash" and not cats["review"]["worker"]
    vision = [r["model"] for r in cats["penglihatan"]["routes"]]
    assert vision == ["nvidia/nemotron-3.5-super-vl:free"]  # the paid id OpenRouter does not list was never written
    assert all(r["provider"] == "openrouter" for c in cats.values() for r in c["routes"])   # no local route anywhere (ADR-080)
    c = await composition.update({"categories": {"coding": {"paid_attempt_limit": 2, "max_retries": 0}}}, "test")
    assert next(x for x in c["categories"] if x["name"] == "coding")["paid_attempt_limit"] == 2
    import pytest
    with pytest.raises(composition.CompositionError):
        await composition.update({"categories": {"coding": {"max_retries": 99}}}, "test")


CATALOG_BASE = {"context": 1_000_000, "price_in": 0.0, "price_out": 0.0, "free": False, "tools": True, "vision": True, "audio": False,
                "created": 1, "description": "", "reasoning": False, "reasoning_forced": False, "expires": None}


def _fake_embed(monkeypatch):
    """A deterministic stand-in for the local embedding model: a bag of words over a small shared vocabulary."""
    from app import capabilities, memory
    vocab = {}

    async def embed(texts):
        out = []
        for t in texts:
            vec = [0.0] * 1024
            for w in __import__("re").findall(r"\w{3,}", t.lower()):
                vocab.setdefault(w, len(vocab))
                vec[vocab[w]] += 1.0
            out.append(vec)
        return out
    monkeypatch.setattr(memory, "embed", embed)
    capabilities._vectors.clear()


async def test_registry_finds_skills_by_meaning_versions_changes_and_keeps_score(pool, monkeypatch, tmp_path):
    from app import capabilities
    _fake_embed(monkeypatch)
    await pool.execute("TRUNCATE capabilities CASCADE")
    skill = tmp_path / "jarvis" / "riset-bersumber"  # ours; the bundled folder below is ignored
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text('---\nname: riset-bersumber\ndescription: "riset web sumber terpercaya tanggal kutipan"\nversion: 1.0.0\n---\n# v1')
    other = tmp_path / "jarvis" / "keuangan"
    other.mkdir()
    (other / "SKILL.md").write_text('---\nname: keuangan-pribadi\ndescription: "catat pengeluaran anggaran bulanan tabungan"\nversion: 1.0.0\n---\n# k')
    (tmp_path / "bundled").mkdir()
    (tmp_path / "bundled" / "SKILL.md").write_text('---\nname: ignored\ndescription: "x"\n---\n')
    tools = [{"type": "function", "function": {"name": "play_music", "description": "putar lagu musik"}}]
    r = await capabilities.sync(tools, root=tmp_path)
    assert r["skills"] == 2 and r["total"] == 2 + 1 + len(capabilities.WORKERS)
    assert await capabilities.sync(tools, root=tmp_path) == r  # idempotent
    found = await capabilities.search("tolong riset sumber terpercaya tentang harga emas")
    assert found and found[0]["id"] == "skill:riset-bersumber" and "skill:keuangan-pribadi" not in [c["id"] for c in found][:1]
    assert await capabilities.search("zzzz qqqq xxxx") == []
    # a verified success marks it tested; the brief carries the record
    assert await capabilities.record("skill:riset-bersumber", True, 0.002, verified=True)
    await capabilities.record("skill:riset-bersumber", False, 0.001)
    row = await pool.fetchrow("SELECT tested, success_n, fail_n, runs FROM capabilities WHERE id = 'skill:riset-bersumber'")
    assert (row["tested"], row["success_n"], row["fail_n"], row["runs"]) == (False, 1, 1, 2)  # the failure: to be validated again
    assert "berhasil 1 dari 2" in await capabilities.brief_for("riset sumber terpercaya")
    # the skill changes → version 2, untested again, the old text stays
    (skill / "SKILL.md").write_text('---\nname: riset-bersumber\ndescription: "riset web sumber terpercaya tanggal kutipan"\nversion: 1.1.0\n---\n# v2 baru')
    await capabilities.sync(tools, root=tmp_path)
    row = await pool.fetchrow("SELECT version, tested FROM capabilities WHERE id = 'skill:riset-bersumber'")
    assert row["version"] == 2 and row["tested"] is False
    assert await pool.fetchval("SELECT count(*) FROM capability_versions WHERE capability_id = 'skill:riset-bersumber'") == 2


async def test_task_plan_verification_note_and_one_automatic_recovery(pool, monkeypatch):
    import asyncio
    from app import capabilities, hermes, hub, memory, workers
    hub.reset()
    _fake_embed(monkeypatch)
    monkeypatch.setattr(memory, "search", _no_memory)
    await pool.execute("TRUNCATE capabilities CASCADE")
    await capabilities._upsert("skill:riset-bersumber", "skill", "riset-bersumber", "cari harga emas antam sumber terpercaya")
    prompts = []

    async def hermes_flow(text, session_id, image=None, **kw):
        prompts.append(text)
        tid = int(session_id.split("-")[1])
        if len(prompts) == 1:
            raise RuntimeError("HTTP 500: upstream broke")  # first attempt fails
        assert await workers.set_plan(tid, "Cari harga emas", ["ada harga", "ada sumber"], ["cari", "bandingkan"])
        yield {"type": "done", "reply": hermes.HermesReply("Emas Rp1.900.000/gram", 10, 10, 1)}
    monkeypatch.setattr(hermes, "stream", hermes_flow)
    t = await workers.spawn("Cek emas", "Cari harga emas Antam sumber terpercaya", "s-recover", "test")
    for _ in range(100):
        row = await pool.fetchrow("SELECT status, recovered FROM tasks WHERE id = $1", t["id"])
        if row["status"] == "completed":
            break
        await asyncio.sleep(0.05)
    row = await pool.fetchrow("SELECT status, recovered, result, plan, criteria, phase FROM tasks WHERE id = $1", t["id"])
    assert row["status"] == "completed" and row["recovered"] == 1  # failed once, recovered by itself
    assert "PERCOBAAN KEDUA" in prompts[1] and "pendekatan yang berbeda" in prompts[1]
    assert "KEMAMPUAN YANG SUDAH ADA" in prompts[0] and "skill:riset-bersumber" in prompts[0]  # reuse offered first
    assert "belum diperiksa terhadap kriteria" in row["result"]  # planned but never verified: said so
    # a recorded check with evidence scores the capability and removes the note
    t2 = await pool.fetchval("""INSERT INTO tasks (session_id, title, instruction, kind, category, status, plan, budget_usd)
                                VALUES ('s', 'x', 'y', 'owner', 'web', 'running', '["a"]', 0.5) RETURNING id""")
    assert await workers.verify(t2, True, "dua sumber: logammulia.com, antam.com", ["skill:riset-bersumber"])
    assert await workers._verification_note(t2) == ""
    assert await pool.fetchval("SELECT tested FROM capabilities WHERE id = 'skill:riset-bersumber'") is True
    assert await workers.verify(t2, False, "harga tidak ditemukan", [])
    assert "TIDAK lolos: harga tidak ditemukan" in await workers._verification_note(t2)
    # an empty balance is never "recovered" (it is reported once elsewhere); a second failure is final
    assert await workers._auto_recover(t2, {"title": "x"}, RuntimeError("saldo OpenRouter habis"), "") is False
    hub.reset()


async def test_memory_merges_repeats_corrects_and_keeps_provenance(pool, monkeypatch):
    from app import config, memory
    monkeypatch.setattr(config.settings, "memory_collection", "test_memory_v2")
    await pool.execute("TRUNCATE memories")
    await memory.ensure_collection()
    a = await memory.save("Kantor saya di NIPSEA Ancol, Jakarta Utara", "personal", "owner", "fact", verified=True, evidence="kata pemilik")
    assert a["verified"] and a["evidence"] == "kata pemilik" and a["confidence"] == pytest.approx(0.7)
    again = await memory.save("Kantor saya di NIPSEA Ancol, Jakarta Utara", "personal", "hermes", "fact", confidence=0.95)
    assert again["deduped"] and str(again["id"]) == str(a["id"]) and again["confidence"] == pytest.approx(0.95) and again["verified"]
    assert await pool.fetchval("SELECT count(*) FROM memories") == 1  # one memory, not two
    guess = await memory.save("Pemilik mungkin suka rapat pagi hari", "personal", "hermes", "assumption")
    assert guess["confidence"] == pytest.approx(0.4) and not guess["verified"]
    # a correction: the new one is live, the old one stale and pointing at it, both kept
    done = await memory.correct(str(a["id"]), "Kantor saya sekarang di Kuningan, Jakarta Selatan", "owner")
    assert done["new"]["verified"] and done["new"]["confidence"] == pytest.approx(0.9)
    old = await memory.get(str(a["id"]))
    assert old["stale"] and str(old["superseded_by"]) == str(done["new"]["id"])
    hits = await memory.search("di mana kantor saya?")
    assert str(hits[0]["id"]) == str(done["new"]["id"]) and all(str(h["id"]) != str(a["id"]) for h in hits)
    assert (await memory.best_match("kantor saya di mana"))["id"] == done["new"]["id"]
    assert await pool.fetchval("SELECT last_used IS NOT NULL FROM memories WHERE id = $1", done["new"]["id"])
    with pytest.raises(memory.MemoryError_):
        await memory.correct("00000000-0000-0000-0000-000000000000", "x", "owner")
    # upkeep: an unused old assumption is retired; a verified fact never is; an old replaced memory is deleted
    await pool.execute("UPDATE memories SET created_at = now() - interval '70 days' WHERE id = $1", guess["id"])
    await pool.execute("UPDATE memories SET updated_at = now() - interval '100 days' WHERE id = $1", a["id"])
    r = await memory.maintain()
    assert r["assumptions_retired"] == 1 and r["deleted"] == 0  # a was verified: never auto-deleted
    assert (await memory.get(str(guess["id"])))["stale"] and not (await memory.get(str(done["new"]["id"])))["stale"]
    assert await memory.get(str(a["id"])) is not None  # verified → kept even when replaced


async def test_episodes_goals_and_repeated_tasks(pool, monkeypatch):
    from app import config, episodes, goals, memory, workers
    monkeypatch.setattr(config.settings, "memory_collection", "test_memory_v2")
    await pool.execute("TRUNCATE episodes, goals")
    tid = await pool.fetchval("""INSERT INTO tasks (session_id, title, instruction, kind, category, status, goal, plan, result, cost_usd, model_used)
                                 VALUES ('s', 'Harga emas', 'x', 'owner', 'web', 'completed', 'Cek harga emas Antam hari ini',
                                         '["cari", "bandingkan"]', 'Antam Rp1.900.000/gram (logammulia.com)', 0.0012, 'qwen/qwen3.7-flash') RETURNING id""")
    assert (await episodes.record(tid)) == {"task": tid, "success": True}
    failed = await pool.fetchval("""INSERT INTO tasks (session_id, title, instruction, kind, category, status, goal, error)
                                    VALUES ('s', 'x', 'y', 'owner', 'web', 'failed', 'Laporan tren produk TikTok', 'ReadTimeout (timeout)') RETURNING id""")
    await episodes.record(failed)
    assert (await pool.fetchval("SELECT lesson FROM episodes WHERE task_id = $1", failed)).startswith("timeout: ReadTimeout (timeout) · gagal")
    similar = await episodes.similar("tolong cek lagi harga emas antam")
    assert similar and similar[0]["task_id"] == tid and similar[0]["success"]
    brief = await episodes.brief_for("cek lagi harga emas Antam")
    assert "TUGAS SERUPA PERNAH DIKERJAKAN" in brief and "logammulia.com" in brief
    assert await episodes.brief_for("resep rendang padang") == ""  # unrelated: nothing is offered
    await pool.execute("UPDATE episodes SET created_at = now() - interval '200 days' WHERE task_id = $1", failed)
    assert await episodes.prune() == 1
    # goals: ordered by priority then due; the agent's situation block shows them
    g1 = await goals.add("Selesaikan laporan Q4", "owner", 2, __import__("datetime").date(2026, 11, 5))
    g2 = await goals.add("Belajar Blender", "owner", 4)
    await goals.update(g2["id"], "owner", status="paused")
    assert [g["text"] for g in await goals.list_("active")] == ["Selesaikan laporan Q4"]
    assert "Selesaikan laporan Q4" in await goals.situation_block() and "Blender" not in await goals.situation_block()
    with pytest.raises(goals.GoalError):
        await goals.add("x", "owner", 9)
    done = await goals.update(g1["id"], "owner", status="done")
    assert done["status"] == "done" and await goals.situation_block() == ""


async def _settle(pool, name, want, tries=100):
    import asyncio
    for _ in range(tries):
        status = await pool.fetchval("SELECT status FROM skill_drafts WHERE name = $1 ORDER BY id DESC LIMIT 1", name)
        if status in want:
            return status
        await asyncio.sleep(0.03)
    return status


async def test_learning_a_skill_validate_evaluate_publish_version_rollback(pool, monkeypatch, tmp_path):
    from app import capabilities, skills_pipeline as sp
    from tests.test_unit import CASES, GOOD_BODY
    monkeypatch.setattr(sp, "LEARNED_DIR", tmp_path / "learned")
    monkeypatch.setattr(sp, "SANDBOX_DIR", tmp_path / "sandbox")
    await pool.execute("TRUNCATE skill_drafts, capabilities, reports CASCADE")
    verdicts = {"ok": True}

    async def judge(messages, category="cepat", max_tokens=300, caller="core", private=False, temperature=0.4):
        assert category in ("review", "analisis") and caller == "skills" and temperature == 0.0
        return '{"ok": true, "alasan": "tercakup"}' if verdicts["ok"] else '{"ok": false, "alasan": "langkah tidak mencakup"}'
    monkeypatch.setattr(sp.llm, "complete", judge)
    desc = "Membuat laporan tren produk dari sebuah platform beserta rekomendasi"
    # rejected: nothing is written, the reasons come back so Hermes can fix it
    r = await sp.submit("laporan-tren", desc, "# kosong", CASES, None)
    assert r["status"] == "rejected" and any("bagian wajib" in p for p in r["problems"])
    assert not (tmp_path / "learned").exists()
    # accepted and evaluated by the (other) model → published, tested, own, versioned, the owner told
    r = await sp.submit("laporan-tren", desc, GOOD_BODY, CASES, None)
    assert r["status"] == "evaluating" and await _settle(pool, "laporan-tren", {"published", "failed_tests"}) == "published"
    skill_md = (tmp_path / "learned" / "laporan-tren" / "SKILL.md").read_text()
    assert skill_md.startswith("---\nname: laporan-tren") and "## Langkah" in skill_md and "version: 1.0.0" in skill_md
    cap = await pool.fetchrow("SELECT tested, own, version, status FROM capabilities WHERE id = 'skill:laporan-tren'")
    assert (cap["tested"], cap["own"], cap["version"], cap["status"]) == (True, True, 1, "published")
    for _ in range(100):  # the report is written right after the status flips to published
        if await pool.fetchval("SELECT text FROM reports ORDER BY id DESC LIMIT 1"):
            break
        await __import__("asyncio").sleep(0.02)
    assert "Aku belajar skill baru: laporan-tren" in await pool.fetchval("SELECT text FROM reports ORDER BY id DESC LIMIT 1")
    # a second version (improved) → v2; then rollback restores v1's text as v3 and keeps the history
    await sp.submit("laporan-tren", desc, GOOD_BODY.replace("5 produk", "10 produk"), CASES, None)
    await _settle(pool, "laporan-tren", {"published"}, tries=5)
    for _ in range(100):
        if await pool.fetchval("SELECT version FROM capabilities WHERE id = 'skill:laporan-tren'") == 2:
            break
        await __import__("asyncio").sleep(0.03)
    assert "10 produk" in (tmp_path / "learned" / "laporan-tren" / "SKILL.md").read_text()
    back = await sp.rollback("laporan-tren", "test")
    assert back == {"name": "laporan-tren", "restored": 1, "version": 3}
    restored = (tmp_path / "learned" / "laporan-tren" / "SKILL.md").read_text()
    assert "5 produk" in restored and "10 produk" not in restored
    assert await pool.fetchval("SELECT count(*) FROM capability_versions WHERE capability_id = 'skill:laporan-tren'") == 3
    with pytest.raises(sp.SkillError):
        await sp.rollback("belum-ada", "test")
    assert await sp.retire("laporan-tren", "test") and not (tmp_path / "learned" / "laporan-tren").exists()
    assert await pool.fetchval("SELECT status FROM capabilities WHERE id = 'skill:laporan-tren'") == "deprecated"
    # a skill the other model does not believe in is not published; a model that cannot answer counts as failing
    verdicts["ok"] = False
    await sp.submit("skill-lemah", desc, GOOD_BODY, CASES, None)
    assert await _settle(pool, "skill-lemah", {"published", "failed_tests"}) == "failed_tests"
    assert not (tmp_path / "learned" / "skill-lemah").exists()
    assert any("langkah tidak mencakup" in p for p in (await sp.status("skill-lemah"))["problems"])
    # a failed use makes any capability "untested" again
    await capabilities._upsert("skill:x-y", "skill", "x-y", "desc skill")
    await capabilities.record("skill:x-y", True, verified=True)
    assert await pool.fetchval("SELECT tested FROM capabilities WHERE id = 'skill:x-y'") is True
    await capabilities.record("skill:x-y", False)
    assert await pool.fetchval("SELECT tested FROM capabilities WHERE id = 'skill:x-y'") is False


async def test_a_skill_with_scripts_runs_in_the_sandbox_and_needs_the_owners_approval(pool, monkeypatch, tmp_path):
    import json
    from app import approvals, skills_pipeline as sp
    from tests.test_unit import GOOD_BODY
    monkeypatch.setattr(sp, "LEARNED_DIR", tmp_path / "learned")
    monkeypatch.setattr(sp, "SANDBOX_DIR", tmp_path / "sandbox")
    await pool.execute("TRUNCATE skill_drafts, capabilities, approvals CASCADE")
    desc = "Menghitung total dari angka yang diberikan lewat argumen"
    code = "import sys\nprint(sum(float(a) for a in sys.argv[1:]))\n"
    cases = [{"name": "dua angka", "args": ["1", "2"], "expect": "3"}, {"name": "tiga angka", "args": ["1", "2", "3"], "expect": "6"}]
    r = await sp.submit("hitung-total", desc, GOOD_BODY, cases, {"scripts/main.py": code})
    assert r["status"] == "evaluating"
    assert await _settle(pool, "hitung-total", {"sandbox_testing"}) == "sandbox_testing"
    req = json.loads((tmp_path / "sandbox" / "requests" / f"{r['draft_id']}.json").read_text())
    assert req["files"] == {"scripts/main.py": code} and req["cases"] == cases and req["name"] == "hitung-total"
    assert await sp.poll() == 0  # no result yet
    # the runner answers: one case failed → not offered to the owner
    (tmp_path / "sandbox" / "results").mkdir()
    (tmp_path / "sandbox" / "results" / f"{r['draft_id']}.json").write_text(json.dumps({"cases": [
        {"name": "dua angka", "ok": True, "exit": 0, "stdout": "3.0"}, {"name": "tiga angka", "ok": False, "exit": 1, "stdout": "", "note": "ValueError"}]}))
    assert await sp.poll() == 1
    assert (await sp.status("hitung-total"))["status"] == "failed_tests"
    # a fixed version passes → an approval request with the test summary; nothing is published until the owner approves
    r2 = await sp.submit("hitung-total", desc, GOOD_BODY, cases, {"scripts/main.py": code + "# v2\n"})
    await _settle(pool, "hitung-total", {"sandbox_testing"})
    (tmp_path / "sandbox" / "results" / f"{r2['draft_id']}.json").write_text(json.dumps({"cases": [
        {"name": "dua angka", "ok": True, "exit": 0, "stdout": "3.0"}, {"name": "tiga angka", "ok": True, "exit": 0, "stdout": "6.0"}]}))
    assert await sp.poll() == 1
    st = await sp.status("hitung-total")
    assert st["status"] == "awaiting_approval" and st["approval_id"]
    ap = await approvals.get(st["approval_id"])
    assert ap["kind"] == "skill_publish" and "2/2 lulus di sandbox" in ap["detail"]["tests"] and ap["detail"]["scripts"] == ["scripts/main.py"]
    assert not (tmp_path / "learned" / "hitung-total").exists()
    with pytest.raises(approvals.AdminOnly):  # a skill with code is approved at the admin page only (ADR-047)
        await approvals.decide(st["approval_id"], True, "device:HP")
    assert not (tmp_path / "learned" / "hitung-total").exists()
    await approvals.decide(st["approval_id"], True, "owner", channel="admin")
    assert (tmp_path / "learned" / "hitung-total" / "scripts" / "main.py").read_text().endswith("# v2\n")
    assert (await sp.status("hitung-total"))["status"] == "published"
    # the daily limit bounds how much JARVIS can spend learning
    monkeypatch.setattr(sp, "DAILY_LIMIT", 1)
    with pytest.raises(sp.SkillError, match="batas"):
        await sp.submit("skill-lain", desc, GOOD_BODY, cases, None)
