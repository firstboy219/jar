from app import approvals, hermes, sensitive
from app.mcp_server import _extract_json, validate_workflow
from datetime import datetime, timezone

from app.location import Location, context_prefix
from app.router import Intent, parse


# ---- router (tier 1, no LLM) ----

def test_parse_commands():
    assert parse("status") == Intent("status")
    assert parse("  Cek   Status ") == Intent("status")
    assert parse("persetujuan") == Intent("approvals")
    assert parse("setujui #12") == Intent("approve", {"id": 12})
    assert parse("TOLAK 7") == Intent("reject", {"id": 7})
    assert parse("workflow") == Intent("workflows")
    assert parse("bantuan") == Intent("help")


def test_parse_remember_keeps_case():
    assert parse("ingat: Rapat UAT tiap Senin jam 9") == Intent("remember", {"text": "Rapat UAT tiap Senin jam 9"})


def test_parse_recall_and_forget():
    assert parse("memori proyek Autotoko") == Intent("recall", {"query": "proyek autotoko"})
    mid = "0b6f3c1e-8f7a-4f5e-9a51-2a9b3c4d5e6f"
    assert parse(f"lupakan {mid}") == Intent("forget", {"id": mid})


def test_free_text_goes_to_hermes():
    for text in ("status proyek autotoko gimana?", "tolong setujui proposal klien", "halo", "apa kabar"):
        assert parse(text) is None, text


# ---- privacy gate ----

def test_sensitive_detection():
    assert "API key" in sensitive.scan("pakai key sk-or-v1-abcdefghijklmnopqrstuvwxyz123456")
    assert "password" in sensitive.scan("password: hunter2")
    assert "password" in sensitive.scan("kata sandi=rahasia123")
    assert "private key" in sensitive.scan("-----BEGIN OPENSSH PRIVATE KEY-----")
    assert "nomor kartu" in sensitive.scan("kartu 4111 1111 1111 1111")


def test_sensitive_no_false_positive():
    assert sensitive.scan("meeting jam 10, budget 15000000 rupiah") == []
    assert sensitive.scan("nomor order 1234567890123") == []  # fails Luhn
    assert sensitive.scan("password-nya sudah saya ganti kemarin") == []


def test_private_prefix():
    assert sensitive.is_private("/privat gaji saya berapa")
    assert sensitive.is_private("  #privat catatan")
    assert not sensitive.is_private("tolong buat /privat folder")


# ---- approval state machine ----

def test_transitions():
    assert approvals.can_transition("awaiting_approval", "approved")
    assert approvals.can_transition("approved", "executing")
    assert approvals.can_transition("executing", "completed")
    assert not approvals.can_transition("awaiting_approval", "executing")
    assert not approvals.can_transition("rejected", "approved")
    assert not approvals.can_transition("completed", "executing")


# ---- n8n workflow validation ----

def _wf(**over):
    wf = {"name": "Cek harga", "nodes": [
        {"id": "1", "name": "Jadwal", "type": "n8n-nodes-base.scheduleTrigger", "typeVersion": 1.2,
         "position": [0, 0], "parameters": {}},
        {"id": "2", "name": "Ambil", "type": "n8n-nodes-base.httpRequest", "typeVersion": 4.2,
         "position": [200, 0], "parameters": {"url": "https://example.com"}}],
        "connections": {"Jadwal": {"main": [[{"node": "Ambil", "type": "main", "index": 0}]]}}}
    wf.update(over)
    return wf


def test_validate_workflow_ok():
    assert validate_workflow(_wf()) == []


def test_validate_workflow_problems():
    assert "nodes kosong" in validate_workflow(_wf(nodes=[]))
    bad = _wf(connections={"Jadwal": {"main": [[{"node": "Hantu", "type": "main", "index": 0}]]}})
    assert any("Hantu" in p for p in validate_workflow(bad))


def test_extract_json_from_fenced_reply():
    assert _extract_json('Berikut:\n```json\n{"name": "x", "nodes": []}\n```') == {"name": "x", "nodes": []}


def test_parse_sse_frames():
    assert hermes.parse_sse(['event: hermes.tool.progress', 'data: {"tool": "x"}']) == ("hermes.tool.progress", {"tool": "x"})
    assert hermes.parse_sse(['data: [DONE]']) == (None, None)
    assert hermes.parse_sse(['data: {"choices": []}']) == (None, {"choices": []})


def test_tool_event_friendly_name():
    ev = hermes.tool_event({"tool": "mcp__jarvis__memory_search", "label": "proyek", "toolCallId": "c", "status": "running"})
    assert ev["name"] == "memory_search" and ev["title"] == "Mencari di memori" and ev["label"] == "proyek"


def test_hermes_session_header_sanitized():
    assert hermes.session_header("abc/../../etc") == "jarvis-abc....etc"
    assert len(hermes.session_header("x" * 500)) == len("jarvis-") + 64


# ---- location ----

def test_whereami_command():
    for t in ("di mana saya?", "dimana aku sekarang", "lokasi saya", "Where am I?"):
        assert parse(t) == Intent("whereami"), t
    assert parse("di mana saya bisa beli sparepart?") is None  # a real question → Hermes


def test_location_describe_and_prefix():
    loc = Location(lat=-6.158, lon=106.905, accuracy_m=18.4, age_s=300, address="Kelapa Gading, Jakarta Utara")
    assert loc.describe() == "Kelapa Gading, Jakarta Utara (-6.15800, 106.90500 ±18 m, diambil 5 menit lalu)"
    p = context_prefix(loc, datetime(2026, 10, 17, 5, 30, tzinfo=timezone.utc))
    assert p.startswith("[Konteks perangkat — waktu Sabtu 17 Oktober 2026 12:30 WIB; lokasi HP pemilik: Kelapa Gading")
    assert context_prefix(None, datetime(2026, 10, 17, 5, 30, tzinfo=timezone.utc)).count("lokasi") == 0


def test_location_rejects_out_of_range():
    import pydantic, pytest
    with pytest.raises(pydantic.ValidationError):
        Location(lat=123, lon=0)


def test_tasks_command():
    assert parse("tugas") == Intent("tasks")
    assert parse("daftar tugas aktif") == Intent("tasks")


def test_tool_call_fragments_are_merged():
    from app import llm
    acc = {}
    llm._merge_tool_deltas(acc, [{"index": 0, "id": "c1", "function": {"name": "spawn_", "arguments": '{"title": "Cek'}}])
    llm._merge_tool_deltas(acc, [{"index": 0, "function": {"name": "task", "arguments": ' emas"}'}}])
    [call] = llm._finish_tools(acc)
    assert (call.id, call.name, call.arguments) == ("c1", "spawn_task", {"title": "Cek emas"})


def test_youtube_thumbnail():
    from app.media import youtube_thumbnail
    assert youtube_thumbnail("https://www.youtube.com/watch?v=dFjkFepm1Bc") == "https://i.ytimg.com/vi/dFjkFepm1Bc/hqdefault.jpg"
    assert youtube_thumbnail("https://youtu.be/dFjkFepm1Bc") == "https://i.ytimg.com/vi/dFjkFepm1Bc/hqdefault.jpg"
    assert youtube_thumbnail("https://evil.example/watch?v=dFjkFepm1Bc") is None


def test_screen_is_sent_as_image_part():
    from app.assistant import _user_content
    assert _user_content("halo", None) == "halo"
    parts = _user_content("ini kenapa?", "QUJD")
    assert parts[0] == {"type": "text", "text": "[terlampir gambar dari layar HP] ini kenapa?"}
    assert parts[1]["image_url"]["url"] == "data:image/jpeg;base64,QUJD"
    cam = _user_content("ini apa?", "QUJD", "camera", {"confidence": 0.62, "speakers": 2})
    assert cam[0]["text"] == "[diucapkan lewat suara, keyakinan transkrip 0.62, 2 pembicara terdeteksi; terlampir gambar dari kamera] ini apa?"
    assert _user_content("halo", None, None, {"confidence": 0.97, "speakers": 1}) == "[diucapkan lewat suara, keyakinan transkrip 0.97] halo"


def test_situation_due_reasons():
    from datetime import timedelta
    from app import awareness
    from app.location import Location
    now = datetime(2026, 10, 17, 1, 0, tzinfo=timezone.utc)
    home = Location(lat=-6.27, lon=106.70)
    ctx = awareness.DeviceContext(location=home, activity="still")
    awareness._state.update(checked_at=None, checked_at_place=None, checked_activity=None, announced_events=set())
    assert awareness.due_reason(ctx, now) == "pertama kali hari ini"
    awareness._state.update(checked_at=now, checked_at_place=home, checked_activity="still")
    assert awareness.due_reason(ctx, now + timedelta(minutes=10)) is None
    moved = awareness.DeviceContext(location=Location(lat=-6.20, lon=106.82), activity="still")
    assert awareness.due_reason(moved, now + timedelta(minutes=10)) == "pemilik berpindah tempat"
    driving = awareness.DeviceContext(location=home, activity="driving")
    assert awareness.due_reason(driving, now + timedelta(minutes=10)) == "pemilik mulai berkendara"
    soon = int((now + timedelta(minutes=20)).timestamp() * 1000)
    meeting = awareness.DeviceContext(location=home, activity="still",
                                      calendar=[awareness.CalendarEvent(title="UAT", start_ms=soon)])
    assert awareness.due_reason(meeting, now) == "agenda 'UAT' sebentar lagi"
    assert awareness.due_reason(meeting, now) is None  # announced once
    # No periodic re-check any more (the expensive "heartbeat" pattern): only events count.
    assert awareness.due_reason(ctx, now + timedelta(hours=5)) is None
    awareness._state["checked_unmuted"] = False
    unmuted = awareness.DeviceContext(location=home, activity="still", unmuted=True)
    assert awareness.due_reason(unmuted, now + timedelta(minutes=30)) == "pemilik menyalakan mic JARVIS"
    assert awareness.due_reason(ctx, now + timedelta(days=1)) == "pertama kali hari ini"


def test_distance():
    from app.awareness import distance_m
    from app.location import Location
    d = distance_m(Location(lat=-6.2700, lon=106.7000), Location(lat=-6.2700, lon=106.7100))
    assert 1000 < d < 1200



def test_quiet_hours_wrap_midnight(monkeypatch):
    from app import config, notifications
    monkeypatch.setattr(config.settings, "quiet_hours", "22:00-06:00")
    at = lambda h, m=0: datetime(2026, 10, 17, h - 7 if h >= 7 else h + 17, m, tzinfo=timezone.utc)  # WIB → UTC
    assert notifications.quiet_now(at(23)) and notifications.quiet_now(at(5, 59))
    assert not notifications.quiet_now(at(6)) and not notifications.quiet_now(at(14))
    monkeypatch.setattr(config.settings, "quiet_hours", "")
    assert not notifications.quiet_now(at(23))


def test_otp_and_secrets_are_withheld():
    from app.notifications import Notification, redact
    otp = Notification(app="BCA", package="com.bca", title="Kode OTP", text="Kode OTP Anda 482913, jangan berikan", posted_at=0)
    title, text, sens = redact(otp)
    assert sens and "482913" not in title + text
    ok = Notification(app="WhatsApp", package="com.whatsapp", title="Budi", text="Rapat jadi jam 3", posted_at=0)
    assert redact(ok) == ("Budi", "Rapat jadi jam 3", False)


def test_announced_silence_is_treated_as_silence():
    from app.assistant import announces_silence
    assert announces_silence("Ucapan ini tampaknya bukan untukku, jadi aku diam saja.")
    assert announces_silence("Kalimatnya belum selesai, aku tunggu lanjutannya ya.")
    assert not announces_silence("Iya, aku pakai Deepgram nova-2.")
    assert not announces_silence("Saya diam-diam sudah menyiapkan laporannya. " * 5)  # long real answer


def test_exhausted_credit_errors_are_recognised():
    from app.billing import is_exhausted
    assert is_exhausted("Billing or credits exhausted: HTTP 402: This request requires more credits")
    assert is_exhausted("OpenRouter HTTP 402: b'{...}'")
    assert not is_exhausted("Harga emas Antam Rp2,5 juta") and not is_exhausted(None)


def test_stage_payloads_are_https_only():
    import pytest
    from app import stage
    ok = stage.validate("web", {"url": "https://kompas.com/berita/1", "mode": "read"})
    assert ok["domain"] == "kompas.com"
    for bad in ({"url": "http://kompas.com", "mode": "read"}, {"url": "javascript:alert(1)", "mode": "read"},
                {"url": "file:///etc/passwd", "mode": "login"}):
        with pytest.raises(stage.StageError):
            stage.validate("web", bad)
    with pytest.raises(stage.StageError):
        stage.validate("music", {"title": "x", "cover_url": "intent://evil"})
    assert stage.validate("music", {"title": "Lagu", "url": "/api/v1/media/abc"})
    with pytest.raises(stage.StageError):
        stage.validate("draft", {"variants": []})
    with pytest.raises(stage.StageError):
        stage.validate("unknown", {})


def test_document_markdown_blocks():
    from app import documents
    blocks = documents.parse("# Notulen\nRapat **UAT** dimulai.\n\n- satu\n- dua\n1. a\n2. b\n| Nama | Tugas |\n|---|---|\n| Opik | Tes |")
    kinds = [b[0] for b in blocks]
    assert kinds == ["h", "p", "ul", "ol", "table"]
    assert blocks[4][1] == [["Nama", "Tugas"], ["Opik", "Tes"]]


def test_document_files_are_made(tmp_path, monkeypatch):
    import asyncio
    from app import documents
    content = "# Ringkasan\nIsi **penting**.\n\n- poin\n| A | B |\n|---|---|\n| 1.250 | x |"
    for fmt, maker in (("docx", documents._docx), ("pdf", documents._pdf)):
        path = tmp_path / f"t.{fmt}"
        maker("Uji", documents.parse(content), path)
        assert path.stat().st_size > 500
    path = tmp_path / "t.xlsx"
    documents._xlsx("Uji", documents.parse(content), None, path)
    from openpyxl import load_workbook
    ws = load_workbook(path).active
    assert ws["A2"].value == 1250  # Indonesian thousands separator becomes a number


def test_brain_layout_is_stable_and_two_hemispheres():
    import numpy as np
    from app import brain
    rng = np.random.default_rng(1)
    v = rng.normal(size=(40, 384)).astype("float32")
    a, b = brain.layout(v), brain.layout(v.copy())
    assert np.allclose(a, b) and a.shape == (40, 3)
    assert (np.abs(a[:, 0]) >= 0.149).all()  # gap between hemispheres
    assert (a[:, 0] < 0).any() and (a[:, 0] > 0).any()
    e = brain.edges(np.vstack([v[:1], v[:1] + 0.01, v[1:3]]))
    assert [0, 1] in e


def test_stt_drops_whisper_hallucinations():
    from app import stt
    for t in ("Terima kasih.", "terima kasih sudah menonton", "Thank you for watching!", "..."):
        assert stt.HALLUCINATIONS.match(t)
    assert not stt.HALLUCINATIONS.match("terima kasih, tolong cek server")


def test_sentences_are_spoken_as_they_stream():
    from app.assistant import _SENTENCE_END
    buf = "Oke, aku cek dulu ya. Nanti aku kabari"
    m = _SENTENCE_END.search(buf)
    assert buf[:m.end()].strip() == "Oke, aku cek dulu ya."


def test_voiceprint_names_the_owner_in_meetings():
    from app import voice_id
    owner = [1.0, 0.0, 0.0]
    names = voice_id.name_speakers({"0": [0.1, 0.99, 0.0], "1": [0.95, 0.31, 0.0]}, owner)
    assert names == {"0": "Pembicara 2", "1": "Pemilik"}
    assert voice_id.name_speakers({"0": [0.0, 1.0, 0.0]}, owner, ["0", "1"]) == {"0": "Pembicara 1", "1": "Pembicara 2"}


def test_meeting_speakers_and_blocks():
    from app import meetings
    segs = [{"start": 0, "end": 4, "text": "Selamat pagi semua."}, {"start": 5, "end": 9, "text": "Kita mulai dari UAT."},
            {"start": 700, "end": 705, "text": "Jadi kita sepakat Kamis."}]
    turns = [{"start": 0, "end": 4.5, "speaker": 1}, {"start": 4.6, "end": 10, "speaker": 0}, {"start": 699, "end": 706, "speaker": 1}]
    out = meetings.assign_speakers(segs, turns, {"0": "Pemilik", "1": "Pembicara 2"})
    assert [s["speaker"] for s in out] == ["Pembicara 2", "Pemilik", "Pembicara 2"]
    b = meetings.blocks(out, seconds=600)
    assert len(b) == 2 and b[0].startswith("00:00 Pembicara 2: Selamat pagi") and b[1].startswith("11:40")


def test_route_polyline_is_thinned_keeping_ends():
    from app import maps
    pts = [[-6.0 - i * 0.001, 106.0 + i * 0.001] for i in range(1000)]
    t = maps.thin(pts, 300)
    assert len(t) == 300 and t[0] == [-6.0, 106.0] and t[-1] == [round(pts[-1][0], 5), round(pts[-1][1], 5)]


def test_vault_origin_and_encryption(monkeypatch):
    import pytest
    from app import vault
    monkeypatch.setenv("VAULT_KEY", "11" * 32)
    assert vault.normalize_origin("Login.KlikBCA.com/x?y") == "https://login.klikbca.com"
    assert vault.normalize_origin("https://a.b.co.id:8443/") == "https://a.b.co.id:8443"
    with pytest.raises(vault.VaultError):
        vault.normalize_origin("http://example.com")
    blob = vault.encrypt("rahasia-123")
    assert b"rahasia" not in blob and vault.decrypt(blob) == "rahasia-123"
    assert vault.base_domain("ibank.klikbca.co.id") == "klikbca.co.id"
    monkeypatch.setenv("VAULT_KEY", "short")
    with pytest.raises(vault.VaultError):
        vault.encrypt("x")


def test_error_signature_ignores_values():
    from app import errors
    tb1 = 'Traceback\n  File "/srv/app/x.py", line 10, in f\nValueError: bad id 12'
    tb2 = 'Traceback\n  File "/srv/app/x.py", line 10, in f\nValueError: bad id 99'
    assert errors.signature("jarvis-core.x", "m", tb1) == errors.signature("jarvis-core.x", "m", tb2)
    cleaned = errors._clean("key sk-or-abcdefghijklmnopqrstu leaked")
    assert "abcdefghijklmnopqrstu" not in cleaned and "…" in cleaned
