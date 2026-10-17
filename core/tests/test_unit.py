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
    assert parts[0] == {"type": "text", "text": "ini kenapa?"}
    assert parts[1]["image_url"]["url"] == "data:image/jpeg;base64,QUJD"
