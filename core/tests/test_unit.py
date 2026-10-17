from app import approvals, hermes, sensitive
from app.mcp_server import _extract_json, validate_workflow
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


def test_hermes_session_header_sanitized():
    assert hermes.session_header("abc/../../etc") == "jarvis-abc....etc"
    assert len(hermes.session_header("x" * 500)) == len("jarvis-") + 64
