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
                    "settings_kv, owner_questions, documents, vault_entries, error_log, dev_changes, repair_attempts "
                    "RESTART IDENTITY CASCADE")
    # factory composition: everything local, no category budgets
    await p.execute("""UPDATE llm_categories SET budget_usd = NULL, routes = CASE
        WHEN name IN ('ngobrol', 'cepat', 'penglihatan', 'balas-pesan') THEN '[{"provider": "lokal", "model": "qwen-lokal"}]'::jsonb
        ELSE '[{"provider": "lokal-kerja", "model": "qwen-lokal"}]'::jsonb END""")
    from app import budget, gateway
    gateway.invalidate()
    budget.forget()
    budget._notified.clear()
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
    """Quick commands never reach a model; private/sensitive turns only ever reach the LOCAL model and
    are never replayed into a later (possibly cloud) prompt."""
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
    t = await chat.handle("/privat gaji saya 20jt", "s1", actor="test")
    assert calls[-1][0] is True
    t = await chat.handle("cuaca hari ini gimana?", "s1", actor="test")
    assert calls[-1][0] is False
    replayed = " ".join(str(m.get("content")) for m in calls[-1][1])
    assert "20jt" not in replayed and "hunter2" not in replayed  # private turns stay out of cloud prompts
    logged = [r["content"] for r in await pool.fetch("SELECT content FROM messages WHERE role='user' ORDER BY id")]
    assert "hunter2" not in " ".join(logged)
    assert await pool.fetchval("SELECT count(*) FROM messages WHERE route = 'private'") == 4


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
    assert "Inti permanen: Hermes" in text and "Anggaran AI bulan ini" in text
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


async def test_gateway_without_keys_or_for_private_content_uses_the_local_model(pool, monkeypatch):
    import httpx
    from app import composition
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    await composition.apply_preset("seimbang", "test")
    hosts = []

    def handler(req: httpx.Request) -> httpx.Response:
        import json as _j
        hosts.append(req.url.host)
        assert _j.loads(req.content)["cache_prompt"] is True  # local: reuse the prompt cache
        return httpx.Response(200, content=_sse("Dari lokal."), headers={"content-type": "text/event-stream"})

    _fake_providers(monkeypatch, handler)
    assert await _collect("ngobrol", caller="chat") == "Dari lokal."
    assert hosts == ["llama-chat"]  # no key: cloud routes skipped
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")
    hosts.clear()
    assert await _collect("ngobrol", caller="chat", private=True) == "Dari lokal."
    assert hosts == ["llama-chat"]  # private content never goes to the cloud, key or not
    hosts.clear()
    await _collect("web", caller="hermes", private=True, worker=True)
    assert hosts == ["llama-worker"]


async def test_budget_cap_stops_paid_models_but_keeps_free_and_local(pool, monkeypatch):
    import httpx
    from app import budget, gateway
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")
    await pool.execute("""UPDATE llm_categories SET routes = '[{"provider":"openrouter","model":"x/paid"},
                          {"provider":"openrouter","model":"y/gratis:free"}]' WHERE name = 'ngobrol'""")
    await pool.execute("INSERT INTO llm_usage (category, caller, provider, model, ok, cost_usd) VALUES ('web', 'hermes', 'openrouter', 'z', true, 25)")
    budget.forget()
    routes = await gateway.plan("ngobrol", caller="chat")
    assert [r.model for r in routes] == ["y/gratis:free", "qwen-lokal"]
    st = await budget.state(force=True)
    assert st["level"] == 100
    assert await pool.fetchval("SELECT count(*) FROM reports WHERE text LIKE 'Anggaran AI bulan ini%'") == 1


async def test_composition_only_changes_models_never_the_core(pool):
    from app import composition
    with pytest.raises(composition.CompositionError, match="inti JARVIS"):
        await composition.update({"hermes": "off"}, "test")
    with pytest.raises(composition.CompositionError, match="privat"):
        await composition.update({"categories": {"privat": {"routes": [{"provider": "openrouter", "model": "a/b"}]}}}, "test")
    with pytest.raises(composition.CompositionError, match="penyedia"):
        await composition.update({"categories": {"coding": {"routes": [{"provider": "nope", "model": "a/b"}]}}}, "test")
    c = await composition.update({"categories": {"coding": {"routes": [{"provider": "openrouter", "model": "anthropic/claude-sonnet-5.5"}],
                                                            "budget_usd": 8}}, "stt": "groq"}, "test")
    coding = next(x for x in c["categories"] if x["name"] == "coding")
    assert coding["budget_usd"] == 8 and c["stt"]["engine"] == "groq" and c["preset"] == "kustom"
    assert c["core"] == ["Hermes Agent", "Qdrant", "n8n"]


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
    A confidential meeting never touches a cloud engine or model."""
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
    assert done["summary"]["action_items"][0]["siapa"] == "Opik"
    assert set(private_flags) == {True}
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
    assert req == {"id": c["id"], "action": "test", "branch": "jarvis/cache-ringkasan"}
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
    done = await approvals.decide(a["id"], True, "owner")
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
