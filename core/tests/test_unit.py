import pytest
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



def test_direct_actions_and_model_question():
    from app.router import parse_action
    assert parse_action("tolong putarkan lagu ada band") == Intent("play_music", {"query": "ada band"})
    assert parse_action("jarvis, mainkan musik jazz santai") == Intent("play_music", {"query": "jazz santai"})
    assert parse_action("putar lagi") is None and parse_action("putar balik") is None
    assert parse_action("Coba cek berita hari ini.") == Intent("news", {"topic": ""})
    assert parse_action("berita tentang harga emas") == Intent("news", {"topic": "harga emas"})
    assert parse_action("rute ke bandara soekarno hatta") == Intent("show_route", {"destination": "bandara soekarno hatta"})
    assert parse_action("apakah kamu berhasil cek ke web terkait berita?") is None
    assert parse("Kamu sekarang pakai model apa untuk ngobrol?") == Intent("model")


def test_fast_worker_only_takes_lookups():
    from app import quick
    assert quick.suitable("Cari harga emas Antam hari ini")
    assert quick.suitable("Cari berita crypto yang melonjak hari ini" + quick.CONTEXT_MARK + "Pemilik: buatkan dokumen")
    assert not quick.suitable("Buatkan dokumen ringkasan rapat dan kirim ke email")
    assert not quick.suitable("Bandingkan tiga laptop untuk desain")
    assert quick.news_topic("Cari berita crypto yang melonjak hari ini, khususnya ICNT") == "crypto melonjak ICNT"
    assert quick.news_topic("Cek berita terbaru hari ini") == ""


def test_promise_detection():
    from app.assistant import _PROMISE
    assert _PROMISE.search("Oke, aku cek dulu ya, nanti aku kabari.")
    assert _PROMISE.search("Oke, saya akan cari lagu band dan tampilkan di layar HP.")
    assert not _PROMISE.search("Kopi, biar melek.")



def test_flow_checks_find_unkept_promises_and_repeats():
    from datetime import datetime, timedelta, timezone
    from app import auditor
    t = datetime(2026, 10, 21, 9, tzinfo=timezone.utc)

    def m(i, role, text, route="assistant", sec=0, trace=None):
        return {"id": i, "session_id": "s", "role": role, "content": text, "route": route,
                "created_at": t + timedelta(seconds=sec), "trace": trace}
    turns = [m(1, "user", "apa berita terkini hari ini"), m(2, "assistant", "Oke, aku cek dulu ya.", sec=20),
             m(3, "user", "kamu siapa sebenarnya"), m(4, "assistant", "Oke, aku cek dulu ya.", sec=40),
             m(5, "user", "tolong carikan harga emas"), m(6, "assistant", "Siap, aku carikan.", sec=60,
                                                         trace={"total_ms": 90_000, "route": {"model": "qwen-lokal"}})]
    issues = auditor.turn_checks(turns, [("s", t + timedelta(seconds=61))])
    kinds = [(i["message_id"], i["kind"]) for i in issues]
    assert (2, "promise_unkept") in kinds and (4, "repeated") in kinds and (6, "slow_reply") in kinds
    assert (6, "promise_unkept") not in kinds  # a task did start for that one
    assert auditor.parse_verdicts('ok: [{"i": 1, "ok": true}, {"i": 2, "ok": false, "masalah": "tidak nyambung"}]') == [
        {"i": 2, "ok": False, "masalah": "tidak nyambung"}]
    assert auditor.parse_verdicts("bukan json") == []


def test_stage_shows_anything():
    from app import stage
    assert stage.guess({"url": "https://x.id/lagu.mp3"})[0] == "audio"
    assert stage.guess({"url": "https://youtu.be/abcdefghijk"})[0] == "video"
    assert stage.guess({"url": "https://x.id/foto.JPG"})[0] == "image"
    assert stage.guess({"url": "https://x.id/laporan.pdf"}) == ("doc", {"url": "https://x.id/laporan.pdf", "title": "", "format": "pdf"})
    assert stage.guess({"url": "https://kompas.com/berita"})[0] == "web"
    assert stage.guess({"text": "1. beli kopi"})[0] == "text"
    assert stage.guess({"lat": -6.2, "lon": 106.8, "label": "Monas"})[0] == "map"
    board = stage.validate("board", {"blocks": [{"kind": "text", "text": "hai"}, {"kind": "image", "url": "https://x.id/a.png"}]})
    assert [b["kind"] for b in board["blocks"]] == ["text", "image"]
    for bad in ({"blocks": [{"kind": "draft", "variants": [{"text": "x"}]}]},
                {"blocks": [{"kind": "web", "url": "https://bank.id", "mode": "login"}]},
                {"blocks": [{"kind": "image", "url": "http://x.id/a.png"}]}):
        with pytest.raises(stage.StageError):
            stage.validate("board", bad)


def test_videos_named_songs_and_misheard_news():
    from app.media_tools import matches, wants_specific_song
    from app.router import parse_action
    assert parse_action("putarkan video berita") == Intent("play_video", {"query": "berita"})
    assert parse_action("nonton film agak laen") == Intent("play_video", {"query": "agak laen"})
    assert parse_action("Tolong cek baritah hari ini") == Intent("news", {"topic": ""})
    assert parse_action("Teruancet Brita Hari Ini") == Intent("news", {"topic": ""})
    assert wants_specific_song("bunga citra lestari sunny") and wants_specific_song("idgitaf sedia aku sebelum hujan")
    assert not wants_specific_song("lagu santai buat tidur")
    assert not matches({"title": "Takan Ada Yang Abadi", "artist": "chatoer"}, "peterpan")  # a stranger's cover
    assert matches({"title": "Peterpan - Takan Ada Yang Abadi", "artist": "x"}, "peterpan")


def test_server_usage_parsing():
    from app import hostinfo
    a = hostinfo.cpu_times("cpu  100 0 50 800 50 0 0 0 0 0")
    b = hostinfo.cpu_times("cpu  160 0 70 880 70 0 0 0 0 0")
    assert hostinfo.busy_pct(a, b) == 44.4  # 80 busy of 180 ticks
    m = hostinfo.meminfo("MemTotal: 16384000 kB\nMemAvailable: 8192000 kB\nSwapTotal: 4194304 kB\nSwapFree: 4194304 kB\n")
    assert m == {"total": 15.62, "used": 7.81, "swap_total": 4.0, "swap_used": 0.0}


def test_bugs_found_in_the_live_session():
    from datetime import datetime, timezone
    from app import auditor
    from app.assistant import without_tool_talk
    from app.media_tools import song_query
    t = datetime(2026, 10, 21, 9, tzinfo=timezone.utc)

    def m(i, role, text, model=None):
        return {"id": i, "session_id": "s", "role": role, "content": text, "route": "assistant", "created_at": t,
                "trace": {"route": {"model": model}} if model else None}
    turns = [m(1, "user", "tolong putarkan lagu Peterpan"), m(2, "assistant", "Oke, kuputar Peterpan - Mungkin Nanti.", "aksi-langsung"),
             m(3, "user", "tolong putarkan lagu peterpan"), m(4, "assistant", "Oke, kuputar Peterpan - Mungkin Nanti.", "aksi-langsung"),
             m(5, "user", "putar lagu idgitaf"), m(6, "assistant", "Maaf, idgitaf belum bisa kuputar: gagal.")]
    assert auditor.turn_checks(turns, []) == []  # done actions, failures and same answers to the same ask are fine
    assert without_tool_talk("Oke, saya akan cek kenapa video tidak bisa diputar. Saya akan panggil spawn_task untuk mengecek.") == \
        "Oke, saya akan cek kenapa video tidak bisa diputar."
    assert song_query("bunga cintail estari tapi pakai cover aja") == ("bunga cintail estari cover", True)
    assert song_query("peterpan") == ("peterpan", False)


def test_who_uses_the_server():
    from app import ops
    raw = {"containers": [{"Name": "jarvis-llm-worker", "CPUPerc": "363.04%", "MemUsage": "2.719GiB / 6GiB"},
                          {"Name": "jarvis-core", "CPUPerc": "0.15%", "MemUsage": "650.3MiB / 15.41GiB"},
                          {"Name": "jarvis-brain", "CPUPerc": "12.0%", "MemUsage": "339.9MiB / 4GiB"}]}
    rows = ops.parse_stats(raw, cores=4)
    assert [r["name"] for r in rows] == ["jarvis-llm-worker", "jarvis-brain", "jarvis-core"]
    assert rows[0] == {"name": "jarvis-llm-worker", "label": "AI kerja lokal", "cpu_pct": 90.8, "mem_gb": 2.72}
    assert rows[2]["mem_gb"] == 0.64
    assert parse("netralkan server") == Intent("relieve") and parse("tolong reset cpu dan memori") == Intent("relieve")


def test_ai_calls_in_words():
    from app import ops
    assert ops.ai_calls([{"caller": "flowwatch"}, {"caller": "chat"}, {"caller": "chat"}]) == ["pengawas alur", "ngobrol denganmu ×2"]


def test_background_rules_and_orphan_watchdog():
    from app import ops
    assert ops.worker_policy("1 tugasmu berjalan")[0] == 4.0
    assert ops.worker_policy("") == (4.0, "semua inti, prioritas paling rendah")  # no 50% limit (owner, 2026-10-21)
    assert ops.orphaned(71.0, [])  # computing while nobody waits: the 286% bug
    assert ops.orphaned(71.0, [{"caller": "flowwatch", "provider": "lokal"}])  # the chat model is another server
    assert not ops.orphaned(71.0, [{"caller": "hermes", "provider": "lokal-kerja"}])
    assert not ops.orphaned(10.0, [])


def test_hermes_profile_follows_where_it_runs():
    from app.composition import hermes_profile_for
    assert hermes_profile_for(False) == "lean" and hermes_profile_for(True) == "full"



def test_hermes_session_lines_move_after_the_shared_prefix():
    from app.gateway import hoist_volatile
    body = {"messages": [
        {"role": "system", "content": "You are JARVIS.\n\n## Skills\n<available_skills>a</available_skills>"
                                      "\n\nActive Hermes profile: default.\n\nConversation started: Wednesday\nModel: jarvis-web"},
        {"role": "user", "content": "Cari harga emas"}], "tools": [{"type": "function"}]}
    out = hoist_volatile(body)
    assert out["messages"][0]["content"] == "You are JARVIS.\n\n## Skills\n<available_skills>a</available_skills>"
    assert out["messages"][1]["content"].startswith("[Konteks sesi]\nActive Hermes profile: default.")
    assert out["messages"][1]["content"].endswith("Model: jarvis-web\n\nCari harga emas")
    assert out["tools"] == body["tools"] and body["messages"][0]["content"].endswith("jarvis-web")  # input untouched
    other = {"messages": [{"role": "system", "content": "no marker"}, {"role": "user", "content": "x"}]}
    assert hoist_volatile(other) == other


def _office_files():
    import io
    from docx import Document
    from openpyxl import Workbook
    from pptx import Presentation
    from reportlab.pdfgen import canvas
    d = Document()
    d.add_paragraph("Kontrak sewa kantor BSD berlaku 12 bulan.")
    t = d.add_table(rows=1, cols=2)
    t.rows[0].cells[0].text, t.rows[0].cells[1].text = "Biaya", "Rp 120 juta"
    b = io.BytesIO(); d.save(b); docx = b.getvalue()
    wb = Workbook(); ws = wb.active; ws.title = "Penjualan"
    ws.append(["Bulan", "Omzet"]); ws.append(["Oktober", 1500000])
    b = io.BytesIO(); wb.save(b); xlsx = b.getvalue()
    p = Presentation(); s = p.slides.add_slide(p.slide_layouts[1]); s.shapes.title.text = "Rencana Q4"
    s.placeholders[1].text = "Target naik 20 persen"
    b = io.BytesIO(); p.save(b); pptx = b.getvalue()
    b = io.BytesIO(); c = canvas.Canvas(b); c.drawString(72, 750, "Laporan keuangan Oktober"); c.save(); pdf = b.getvalue()
    return {"a.docx": docx, "a.xlsx": xlsx, "a.pptx": pptx, "a.pdf": pdf}


def test_attachments_are_read_whatever_the_format():
    from app import attachments
    f = _office_files()
    kind, text, _ = attachments.extract("kontrak.docx", "", f["a.docx"])
    assert kind == "docx" and "sewa kantor BSD" in text and "Biaya | Rp 120 juta" in text
    kind, text, _ = attachments.extract("omzet.xlsx", "", f["a.xlsx"])
    assert kind == "xlsx" and "[lembar Penjualan]" in text and "Oktober | 1500000" in text
    kind, text, _ = attachments.extract("rencana.pptx", "", f["a.pptx"])
    assert kind == "pptx" and "Rencana Q4" in text and "Target naik 20 persen" in text
    kind, text, _ = attachments.extract("laporan.pdf", "", f["a.pdf"])
    assert kind == "pdf" and "Laporan keuangan Oktober" in text
    import io
    from reportlab.pdfgen import canvas
    blank = io.BytesIO(); c = canvas.Canvas(blank); c.showPage(); c.save()  # a page without any text = a scan
    kind, text, note = attachments.extract("scan.pdf", "", blank.getvalue())
    assert kind == "pdf" and text == "" and "pindai" in note  # a scanned PDF is said to be a scan, not "empty"
    assert attachments.extract("a.csv", "text/csv", "nama,umur\nBudi,30\n".encode())[1].startswith("nama,umur")
    assert attachments.extract("foto.jpg", "image/jpeg", b"x", "Struk Indomaret Rp 25.000")[:2] == ("image", "Struk Indomaret Rp 25.000")
    assert attachments.extract("foto.jpg", "image/jpeg", b"x")[2]  # no OCR text → a note, not silence
    import pytest
    with pytest.raises(attachments.AttachmentError):
        attachments.extract("program.exe", "application/octet-stream", b"MZ")
    with pytest.raises(attachments.AttachmentError):
        attachments.extract("rusak.docx", "", b"bukan zip")


def test_meeting_terms_and_misheard_names_are_corrected():
    from app import meetings
    meeting = {"title": "UAT Autotoko minggu 3", "context": {"participants": ["Bu Rina", "Opik"], "agenda": "Bahas workflow n8n dan Shopee API"}}
    t = meetings.meeting_terms(meeting, ["Deepgram"])
    assert "Bu Rina" in t["prompt"] and "Autotoko" in t["prompt"] and "Shopee" in t["hotwords"]
    assert "Deepgram" in t["glossary"] and "Opik" not in t["glossary"]  # too short to fuzzy-match safely
    g = ["Autotoko", "Deepgram", "Shopee", "Bu Rina"]
    assert meetings.correct_terms("Kita pakai Deep gram untuk suara", g) == "Kita pakai Deepgram untuk suara"
    assert meetings.correct_terms("Toko Auto toko minggu ini", g) == "Toko Autotoko minggu ini"
    assert meetings.correct_terms("kata Bu Rinah tadi, Shopee, ya.", g) == "kata Bu Rina tadi, Shopee, ya."
    assert meetings.correct_terms("rapat hari ini membahas toko dan sopir", g) == "rapat hari ini membahas toko dan sopir"  # everyday words stay
    assert meetings.correct_terms("apa saja", []) == "apa saja"
    segs = meetings.flag_unclear([{"text": "a", "confidence": 0.9}, {"text": "b", "confidence": 0.2}, {"text": "c"}])
    assert [s.get("low") for s in segs] == [None, True, None]
    lines = meetings.blocks([{"start": 0, "end": 3, "speaker": "Pemilik", "text": "setuju", "low": True}])
    assert lines == ["00:00 Pemilik: setuju [?]"]


def test_a_real_answer_is_not_followed_by_a_promise_or_a_needless_worker():
    from app.assistant import answer_without_promises
    full = "Oke, aku lihat dokumen itu. Biaya sewa Rp 120 juta per tahun, mulai 1 November 2026. Oke, aku cek dokumen itu ya, nanti aku kabari."
    assert answer_without_promises(full) == "Biaya sewa Rp 120 juta per tahun, mulai 1 November 2026."
    assert len(answer_without_promises("Oke, aku cek dulu ya, nanti aku kabari.")) < 30  # a bare promise still starts a worker


def test_charts_and_playlist_requests_are_understood():
    from app import charts
    from app.router import parse_action
    assert charts.resolve("tlg carikan beberapa lagu rnb yg top10") == (15, "R&B/Soul", "us")
    assert charts.resolve("lagu k-pop terpopuler")[1] == "K-Pop"
    assert charts.resolve("lagu indonesia paling populer") == (None, "semua genre", "id")
    a = parse_action("tlg Carikan beberapa lagu RnB yg top10 dan masukkan di playlist saya")
    assert a == Intent("chart", {"text": "tlg carikan beberapa lagu rnb yg top10 dan masukkan di playlist saya", "limit": 10, "to_playlist": True})
    assert parse_action("lagu pop top 5 apa aja?").args["limit"] == 5
    assert parse_action("putar playlist saya") == Intent("play_playlist", {"name": ""})
    assert parse_action("tolong putarkan lagu peterpan").name == "play_music"  # an ordinary song is still a song


def test_draft_requests_and_writer_output():
    from app import writer
    from app.router import parse_action
    for ask in ("bantu saya bikin reply draft atas email ini (btw nama saya Ilham)", "tolong draftkan email ke pak Budi",
                "buatkan balasan email ini", "tlg bikin draf surat izin", "tolong bales email ini dong"):
        assert parse_action(ask).name == "write_draft", ask
    for not_ask in ("tolong cek balasan email dari pak X", "putar lagu RnB", "baca email terakhir"):
        a = parse_action(not_ask)
        assert a is None or a.name != "write_draft", not_ask
    d = writer.parse('ok {"jenis": "email", "kepada": "Henry", "subjek": "Re: Publikasi", "email": "h@x.id", '
                     '"ringkas": "konfirmasi", "isi": "Halo Pak Henry,\\n\\nTerima kasih.\\n\\nSalam,\\nIlham"}')
    assert d["kepada"] == "Henry" and d["email"] == "h@x.id" and d["isi"].endswith("Ilham")
    assert writer.parse("Halo, ini drafnya saja")["isi"] == "Halo, ini drafnya saja"  # plain text still becomes the body
    assert writer.parse('{"email": "bukan-email", "isi": "x"}')["email"] == ""
    md = writer.markdown(d)
    assert md.startswith("# Draf email") and "**Subjek:** Re: Publikasi" in md


def test_board_holds_a_draft_only_for_the_writer():
    from app import stage
    board = {"blocks": [{"kind": "draft", "variants": [{"label": "Draf", "text": "Halo"}]},
                        {"kind": "doc", "title": "Draf", "url": "/api/v1/documents/1", "format": "docx"}]}
    with pytest.raises(stage.StageError):
        stage.validate("board", board)
    assert [b["kind"] for b in stage.validate("board", board, drafts=True)["blocks"]] == ["draft", "doc"]


def test_simpanan_names_what_was_shown():
    from app import library
    assert library.kind_of_panel("image", {}) == "gambar" and library.kind_of_panel("map", {}) == "peta"
    assert library.kind_of_panel("board", {"blocks": [{"kind": "draft"}, {"kind": "doc"}]}) == "draf"
    assert library.kind_of_panel("board", {"blocks": [{"kind": "text"}, {"kind": "video"}]}) == "video"
    assert library.title_of("web", {"url": "https://a.id/x", "domain": "a.id"}) == "a.id"
    assert library.title_of("text", {}) == "Catatan"
    assert library.parse_key("shown:42") == ("shown", "42")
    for bad in ("shown:", "x:1", "music:../../etc", "doc:1;drop"):
        with pytest.raises(library.LibraryError):
            library.parse_key(bad)


CATALOG = [
    {"id": "deepseek/deepseek-v4-flash", "name": "DeepSeek: V4 Flash", "context": 1048576, "price_in": 0.091, "price_out": 0.182,
     "free": False, "tools": True, "vision": False, "audio": False, "created": 3, "description": ""},
    {"id": "deepseek/deepseek-v4-pro", "name": "DeepSeek: V4 Pro", "context": 1048576, "price_in": 0.44, "price_out": 0.89,
     "free": False, "tools": True, "vision": False, "audio": False, "created": 2, "description": ""},
    {"id": "google/gemma-4-31b-it:free", "name": "Gemma 4 31B (free)", "context": 131072, "price_in": 0, "price_out": 0,
     "free": True, "tools": False, "vision": True, "audio": False, "created": 1, "description": ""},
]


def test_openrouter_catalog_normalize_search_and_hints():
    from app import openrouter as o
    m = o.normalize({"id": "a/b", "name": "B", "context_length": 1000, "pricing": {"prompt": "0.0000003", "completion": "0.0000012"},
                     "architecture": {"input_modalities": ["text", "image"]}, "supported_parameters": ["tools", "temperature"]})
    assert m["price_in"] == 0.3 and m["price_out"] == 1.2 and m["vision"] and m["tools"] and not m["free"]
    assert o.normalize({"id": "x/y:free", "pricing": {"prompt": "0", "completion": "0"}})["free"]
    assert [x["id"] for x in o.search(CATALOG, "deepseek flash")] == ["deepseek/deepseek-v4-flash"]  # every word must match
    assert [x["id"] for x in o.search(CATALOG, free=True)] == ["google/gemma-4-31b-it:free"]
    assert [x["id"] for x in o.search(CATALOG, vision=True)] == ["google/gemma-4-31b-it:free"]
    assert [x["id"] for x in o.search(CATALOG, tools=True, sort="termurah")][0] == "deepseek/deepseek-v4-flash"
    assert [x["id"] for x in o.search(CATALOG, sort="terbaru")][0] == "deepseek/deepseek-v4-flash"
    assert o.search(CATALOG, max_price_out=0.5)[0]["id"] != "deepseek/deepseek-v4-pro"
    assert "deepseek/deepseek-v4-flash" in o.closest(CATALOG, "deepseek/deepseek-v4-flsh")
    assert o.short(CATALOG[2])["harga_per_juta_token"] == "gratis"


def test_openrouter_health_a_402_is_final_until_a_real_call_works():
    from datetime import datetime, timedelta
    from app.billing import judge
    now = datetime(2026, 10, 22, 22, 0)
    stale_zero = {"credits": 0, "usage": 0.2, "remaining": -0.2}
    assert judge(now, now - timedelta(hours=1), stale_zero)["working"] is True   # a real paid call worked after the last 402
    assert judge(now - timedelta(hours=1), now, stale_zero)["working"] is False  # last paid call was a 402
    assert judge(None, None, stale_zero)["working"] is False and "HABIS" in judge(None, None, stale_zero)["text"]  # tiny probes prove nothing
    assert judge(None, None, {"credits": 10, "usage": 1, "remaining": 9})["working"] is True
    assert judge(None, None, None)["working"] is None


def test_gateway_skips_models_the_provider_refuses_outright():
    from app.gateway import refused_outright
    assert refused_outright("openrouter/thinkingmachines/inkling:free: HTTP 403: {\"error\": …}")
    assert refused_outright("openrouter/x/y: HTTP 404: Provider returned error")
    assert not refused_outright("openrouter/x/y: HTTP 402: requires more credits")  # credit: not the model's fault
    assert not refused_outright("openrouter/x/y: HTTP 429: rate limited") and not refused_outright("lokal/qwen: RemoteProtocolError")
