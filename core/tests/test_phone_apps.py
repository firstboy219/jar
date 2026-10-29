"""ADR-077: JARVIS operates an app on the owner's phone (Gojek) — approval in the app with the admin password unless scheduled,
never a PIN/OTP, never another app, never a top-up or transfer."""
import asyncio
import os

import pytest

from tests.test_integration import pool  # noqa: F401  (fixture)

needs_db = pytest.mark.skipif(not os.getenv("TEST_DATABASE_URL"), reason="needs TEST_DATABASE_URL")

HOME = {"package": "com.gojek.app", "nodes": [
    {"i": 0, "c": "TextView", "t": "Mau ke mana?", "k": 1},
    {"i": 1, "c": "Button", "t": "GoRide", "k": 1},
    {"i": 2, "c": "Button", "t": "Top Up", "k": 1},
    {"i": 3, "c": "EditText", "h": "Cari tujuan", "e": 1}]}
PIN = {"package": "com.gojek.app", "keyboard": True, "nodes": [{"i": 0, "c": "TextView", "t": "Masukkan PIN GoPay kamu"},
                                                              {"i": 1, "c": "EditText", "e": 1, "p": 1}]}


def test_requests_for_gojek_are_recognised():
    from app import phone_agent, router
    assert phone_agent.detect_app("pesankan GoFood nasi padang") == "gojek" and phone_agent.detect_app("naik go-car ke bandara") == "gojek"
    assert phone_agent.detect_app("pesan tiket pesawat") is None
    assert router.phone_intent("Tolong pesankan goride ke kantor").args == {"app": "gojek", "text": "Tolong pesankan goride ke kantor"}
    assert router.parse_action("order gofood martabak manis").name == "phone_app"
    assert router.phone_intent("gojeknya sudah sampai mana?") is None and router.phone_intent("pesankan pizza") is None


def test_the_screen_is_read_as_numbered_elements():
    from app import phone_agent
    text = phone_agent.screen_text(HOME)
    assert text.splitlines()[0] == "Aplikasi di depan: com.gojek.app"
    assert '[1] Tombol "GoRide" ‹klik›' in text and '[3] Kolom isian "petunjuk: Cari tujuan" ‹isi›' in text
    assert "‹isi, RAHASIA›" in phone_agent.screen_text(PIN)
    assert phone_agent.screen_text({"nodes": [{"i": i, "t": "x" * 100} for i in range(200)]}, limit=500).endswith("gulir untuk melihat sisanya)")


def test_a_pin_or_otp_screen_is_for_the_owner():
    from app import phone_agent
    assert phone_agent.is_secret_screen(PIN) and not phone_agent.is_secret_screen(HOME)
    otp = {"package": "com.gojek.app", "nodes": [{"i": 0, "t": "Masukkan kode OTP"}, {"i": 1, "c": "EditText", "e": 1}]}
    keypad = {"package": "com.gojek.app", "nodes": [{"i": 0, "t": "Ketik PIN"}] + [{"i": i + 1, "t": str(i)} for i in range(10)]}
    assert phone_agent.is_secret_screen(otp) and phone_agent.is_secret_screen(keypad)
    assert not phone_agent.is_secret_screen({"nodes": [{"i": 0, "t": "Bayar pakai PIN di kasir"}]})     # just words, nothing to type


def test_actions_are_checked_before_the_phone_does_them():
    from app import phone_agent
    chk = phone_agent.check_action
    assert chk("ketuk", {"nomor": 1}, HOME, "gojek") is None
    assert "Top Up" in chk("ketuk", {"nomor": 2}, HOME, "gojek")                                   # no top-ups
    assert "tidak ada elemen" in chk("ketuk", {"nomor": 9}, HOME, "gojek")
    assert "bukan Gojek" in chk("ketuk", {"nomor": 1}, {**HOME, "package": "com.whatsapp"}, "gojek")   # only the approved app
    assert "PIN" in chk("ketik", {"nomor": 1, "teks": "123456"}, PIN, "gojek")                        # never a PIN
    assert chk("ketik", {"nomor": 3, "teks": "Kantor"}, HOME, "gojek") is None
    assert chk("kembali", {}, {**HOME, "package": "com.whatsapp"}, "gojek") is None                  # back / open are always fine


def _scripted(monkeypatch, calls):
    """The model, as a list of tool calls it makes in order."""
    from app import llm, phone_agent
    queue = list(calls)

    async def fake(messages, tools=None, **k):
        name, args = queue.pop(0)
        yield {"type": "done", "completion": llm.Completion(tool_calls=[llm.ToolCall("c", name, args)])}
    monkeypatch.setattr(phone_agent.llm, "stream_chat", fake)
    return queue


def _phone(monkeypatch, screens):
    """The phone: answers every instruction with the next screen; records what it was told."""
    from app import phone_agent
    told = []

    async def op(name, **args):
        told.append((name, args))
        if name in ("end", "begin"):
            return {"ok": True}
        return screens.pop(0) if len(screens) > 1 else screens[0]
    monkeypatch.setattr(phone_agent, "op", op)
    monkeypatch.setattr(phone_agent, "phone_online", lambda: True)   # the fake phone is connected
    return told


@needs_db
async def test_a_run_needs_the_admin_password_then_operates_the_app(pool, monkeypatch):
    from app import hub, main, phone_agent, workers
    sent, started = [], []

    async def broadcast(ev):
        sent.append(ev)
        return 1
    monkeypatch.setattr(hub, "broadcast", broadcast)
    monkeypatch.setattr(workers, "_start", lambda task_id, context="": started.append(task_id))
    await pool.execute("TRUNCATE phone_runs")
    dev = {"id": "00000000-0000-0000-0000-000000000001", "name": "HP pemilik", "scope": "owner"}
    run = await phone_agent.request("Pesan GoRide ke Kantor Sudirman", "gojek", "device:HP pemilik", "s-hp")
    assert run["status"] == "awaiting" and not started
    assert sent[-1]["type"] == "phone_approval" and sent[-1]["goal"] == "Pesan GoRide ke Kantor Sudirman" and sent[-1]["label"] == "Gojek"
    assert [c["id"] for c in (await main.phone_runs(device=dev))["pending"]] == [run["id"]]

    class R:
        def __init__(self, code):
            self.status_code = code
    monkeypatch.setattr(main, "_admin_internal", lambda m, p, json=None: _resp(R(200 if json["password"] == "rahasia" else 401)))
    main._approve_failures.clear()
    with pytest.raises(main.HTTPException) as e:
        await main.phone_run_approve(run["id"], main.PhoneApproveIn(password="salah"), None, device=dev)
    assert e.value.status_code == 401 and not started                                          # a wrong password starts nothing
    got = await main.phone_run_approve(run["id"], main.PhoneApproveIn(password="rahasia"), None, device=dev)
    assert got["status"] == "approved" and started == [got["task_id"]]
    task = await pool.fetchrow("SELECT title, instruction, category FROM tasks WHERE id = $1", got["task_id"])
    assert task["title"].startswith("Gojek: Pesan GoRide") and task["instruction"].startswith(phone_agent.MARK) and task["category"] == "hp"
    with pytest.raises(main.HTTPException):
        await main.phone_run_approve(run["id"], main.PhoneApproveIn(password="rahasia"), None, device=dev)   # once only

    for _ in range(5):   # five wrong passwords lock approving for a while
        with pytest.raises(main.HTTPException):
            await main.phone_run_approve(run["id"], main.PhoneApproveIn(password="salah"), None, device=dev)
    with pytest.raises(main.HTTPException) as e:
        await main.phone_run_approve(run["id"], main.PhoneApproveIn(password="rahasia"), None, device=dev)
    assert e.value.status_code == 429

    late = await phone_agent.request("Pesan GoFood", "gojek", "owner")
    await pool.execute("UPDATE phone_runs SET created_at = now() - interval '20 minutes' WHERE id = $1", late["id"])
    with pytest.raises(phone_agent.PhoneError, match="kedaluwarsa"):
        await phone_agent.approve(late["id"], "owner")
    other = await phone_agent.request("Kirim GoSend", "gojek", "owner")
    assert await phone_agent.reject(other["id"], "owner") and not await phone_agent.reject(other["id"], "owner")
    with pytest.raises(phone_agent.PhoneError, match="belum didukung"):
        await phone_agent.request("x y z w", "grab", "owner")


async def _resp(r):
    return r


@needs_db
async def test_the_loop_waits_for_the_pin_refuses_what_is_not_allowed_and_reports(pool, monkeypatch):
    from app import hub, phone_agent, workers
    monkeypatch.setattr(workers, "_start", lambda task_id, context="": None)

    async def quiet(ev):
        return 1
    monkeypatch.setattr(hub, "broadcast", quiet)
    real_sleep = asyncio.sleep
    monkeypatch.setattr(phone_agent.asyncio, "sleep", lambda s: real_sleep(0))
    await pool.execute("TRUNCATE phone_runs")
    run = await phone_agent.request("Pesan GoRide ke Kantor", "gojek", "owner")
    run = await phone_agent.approve(run["id"], "owner")
    row = await pool.fetchrow("SELECT id, instruction FROM tasks WHERE id = $1", run["task_id"])
    after = {**HOME, "nodes": HOME["nodes"] + [{"i": 4, "c": "Button", "t": "Pesan GoRide · Rp18.000", "k": 1}]}
    told = _phone(monkeypatch, [HOME, after, PIN, PIN, after])
    _scripted(monkeypatch, [("ketuk", {"nomor": 2}),                      # Top Up → refused, the phone is not told
                            ("ketik", {"nomor": 3, "teks": "Kantor", "kirim": True}),
                            ("ketuk", {"nomor": 4}),                      # → the PIN screen: waits for the owner
                            ("selesai", {"hasil": "GoRide dipesan, Rp18.000, driver 4 menit lagi"})])
    steps, events = [], []

    async def progress(pct, text, extra=None):
        steps.append((pct, text))

    async def emit(e):
        events.append(e)
    out = await phone_agent.produce(row["id"], dict(row), progress, emit)
    assert out == "GoRide dipesan, Rp18.000, driver 4 menit lagi"
    names = [n for n, _ in told]
    assert names[:2] == ["begin", "open"] and names[-1] == "end"
    assert ("type", {"index": 3, "text": "Kantor", "submit": True, "direction": "bawah", "package": "com.gojek.app"}) in told
    assert not any(n == "tap" and a.get("index") == 2 for n, a in told)                       # Top Up was never tapped
    assert any("ditolak" in (e.get("text") or "") for e in events)
    assert any("PIN/OTP sendiri" in (e.get("text") or "") for e in events) and names.count("observe") >= 1
    assert not any(n == "type" and a.get("index") == 1 for n, a in told)                      # the PIN field was never typed into
    assert (await pool.fetchrow("SELECT status, result FROM phone_runs WHERE id = $1", run["id"]))["status"] == "done"

    _phone(monkeypatch, [HOME])
    _scripted(monkeypatch, [("gagal", {"alasan": "alamat tidak ditemukan"})])
    with pytest.raises(phone_agent.PhoneError, match="alamat tidak ditemukan"):
        await phone_agent.produce(row["id"], dict(row), progress, emit)
    assert (await pool.fetchval("SELECT status FROM phone_runs WHERE id = $1", run["id"])) == "failed"


@needs_db
async def test_a_project_run_starts_the_app_without_the_admin_password(pool, monkeypatch):
    from app import hub, main, projects, workers
    started = []
    monkeypatch.setattr(workers, "_start", lambda task_id, context="": started.append(task_id))
    sent = []

    async def broadcast(ev):
        sent.append(ev)
        return 1
    monkeypatch.setattr(hub, "broadcast", broadcast)
    await pool.execute("TRUNCATE projects, phone_runs CASCADE")
    dev = {"name": "HP pemilik", "scope": "owner"}
    p = await main.projects_create(main.ProjectIn(name="Makan siang", goal="pesan makan siang kantor", schedule="weekdays", at_time="11:30",
                                                  roles=[{"role": "Pemesan", "brief": "GoFood nasi padang ke kantor, maks Rp50.000",
                                                          "workers": 3, "app": "gojek", "web": True}]), device=dev)
    assert p["roles"][0]["app"] == "gojek" and p["roles"][0]["workers"] == 1 and not p["roles"][0]["web"]
    r = await main.projects_run(p["id"], device=dev)                                           # ▶ Jalankan: no password (ADR-079)
    assert len(r["tasks"]) == 1 and r["approvals"] == [] and len(started) == 1
    first = await pool.fetchrow("SELECT status, scheduled, approved_by FROM phone_runs ORDER BY id LIMIT 1")
    assert first["status"] == "approved" and first["scheduled"] and first["approved_by"] == "proyek"
    assert not any(e.get("type") == "phone_approval" and e.get("status") == "awaiting" for e in sent)
    assert any(e.get("type") == "notify" and "mengoperasikan Gojek" in e["title"] for e in sent)   # the owner is told it began
    await pool.execute("UPDATE tasks SET status = 'completed' WHERE project_id = $1", p["id"])
    await pool.execute("UPDATE projects SET next_run = now() - interval '1 minute' WHERE id = $1", p["id"])
    assert await projects.tick() == 1 and len(started) == 2                                    # the schedule too
    run = await pool.fetchrow("SELECT * FROM phone_runs ORDER BY id DESC LIMIT 1")
    assert run["approved_by"] == "jadwal" and run["project_id"] == p["id"]
    assert await pool.fetchval("SELECT project_id FROM tasks WHERE id = $1", run["task_id"]) == p["id"]
    with pytest.raises(main.HTTPException):
        await main.projects_create(main.ProjectIn(name="x", roles=[{"role": "a", "app": "grab"}]), device=dev)
    await pool.execute("DELETE FROM projects")   # the other project tests expect a clean list


@needs_db
async def test_a_run_waits_for_the_phone_and_asks_for_the_app_to_be_opened(pool, monkeypatch):
    from app import hub, phone_agent
    sent = []

    async def broadcast(ev):
        sent.append(ev)
        return 1
    monkeypatch.setattr(hub, "broadcast", broadcast)
    monkeypatch.setattr(phone_agent, "OFFLINE_WAIT_S", 0)
    monkeypatch.setattr(phone_agent, "phone_online", lambda: False)

    async def progress(*a, **k):
        return None
    with pytest.raises(phone_agent.PhoneError, match="5 menit"):
        await phone_agent._start_app(1, "gojek", phone_agent.APPS["gojek"], progress)
    assert any(e.get("type") == "notify" and "Buka aplikasi JARVIS" in e["title"] for e in sent)
    assert any(e.get("type") == "announce" for e in sent)
