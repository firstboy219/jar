"""ADR-087 wave 3: Perlu perhatian — Outlook (device-code sign-in, mail, calendar), Gmail and WhatsApp in one list, triaged by one master-flow
job (never a free endpoint), errands taken out of messages, drafts in the owner's style sent only on his Kirim (an approval he decided),
WhatsApp quick replies through the phone — and the meeting while it is recorded (live transcript, decisions and tasks, questions)."""
import json
import os
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from tests.test_integration import pool  # noqa: F401  (fixture)

needs_db = pytest.mark.skipif(not os.getenv("TEST_DATABASE_URL"), reason="needs TEST_DATABASE_URL")


def reply(content):
    return {"choices": [{"message": {"content": content if isinstance(content, str) else json.dumps(content)}}]}


# ---------- pure ----------

def test_whatsapp_rows_groups_triage_and_errands():
    from app import attention
    now = datetime.now(timezone.utc)
    rows = attention.wa_rows([
        {"id": 1, "title": "Sari (3 pesan)", "text": "Pak, laporan Q3 sudah saya kirim ke email", "posted_at": now, "package": "com.whatsapp"},
        {"id": 2, "title": "Bank", "text": "OTP 123456", "posted_at": now, "sensitive": True},
        {"id": 3, "title": "Istri", "text": "", "posted_at": now}])
    assert len(rows) == 1 and rows[0]["sender"] == "Sari" and rows[0]["thread"] == "wa:sari" and rows[0]["ext_id"] == "n1"   # OTP & empty never kept
    items = [{"id": 1, "source": "outlook", "topic": "Sari · laporan Q3", "triage": "fyi", "received_at": "2026-10-29T08:00", "thread": "t1"},
             {"id": 2, "source": "whatsapp", "topic": "sari · laporan q3", "triage": "needs", "received_at": "2026-10-29T09:00", "thread": "wa:sari"},
             {"id": 3, "source": "gmail", "topic": "", "triage": "fyi", "received_at": "2026-10-29T07:00", "thread": "g9"}]
    cards = attention.group(items)
    assert len(cards) == 2 and cards[0]["sources"] == ["whatsapp", "outlook"] and cards[0]["triage"] == "needs"   # one matter, two sources
    v = attention.parse_triage({"items": [{"id": 1, "kelas": "perlu", "alasan": "minta keputusan", "balasan": ["Oke", "Nanti saya cek", "x", "y"]},
                                          {"id": 99, "kelas": "perlu"}, {"id": "dua", "kelas": "tahu"}, {"id": 3, "kelas": "aneh"}]}, {1, 3})
    assert [(x["id"], x["triage"]) for x in v] == [(1, "needs"), (3, "fyi")] and len(v[0]["replies"]) == 3
    assert attention.is_errand("beli susu si Kecil") and attention.is_errand("Mampir apotek") and not attention.is_errand("kirim laporan")


def test_outlook_mail_row_and_live_transcript_text():
    from app import meeting_live, outlook
    r = outlook.mail_row({"id": "AAM1", "conversationId": "C1", "subject": "", "from": {"emailAddress": {"name": "Dimas", "address": "dimas@kantor.co.id"}},
                          "bodyPreview": "x" * 900, "receivedDateTime": "2026-10-29T01:00:00Z", "flag": {"flagStatus": "flagged"}, "isRead": False})
    assert r["sender"] == "Dimas" and r["subject"] == "(tanpa judul)" and len(r["snippet"]) == 500 and r["flagged"] and r["thread"] == "C1"
    t = meeting_live.transcript_text({"transcript": [{"n": 1, "text": "dua"}, {"n": 0, "text": "satu"}]})
    assert t == "[menit 1] satu\n[menit 2] dua"


# ---------- Outlook sign-in ----------

@needs_db
async def test_outlook_device_code_sign_in_keeps_an_encrypted_refresh_token(pool, monkeypatch):
    from app import outlook
    monkeypatch.setenv("VAULT_KEY", "22" * 32)
    await pool.execute("TRUNCATE settings_kv")
    outlook._access.update(token="", until=0.0)
    seen = []

    def handler(req: httpx.Request):
        seen.append((req.method, str(req.url)))
        body = req.content.decode()
        if req.url.path.endswith("/devicecode"):
            return httpx.Response(200, json={"device_code": "DC", "user_code": "ABCD-1234", "verification_uri": "https://microsoft.com/devicelogin", "expires_in": 900, "interval": 5})
        if req.url.path.endswith("/token") and "device_code" in body:
            if len([s for s in seen if s[1].endswith("/token")]) == 1:
                return httpx.Response(400, json={"error": "authorization_pending"})
            return httpx.Response(200, json={"access_token": "AT1", "refresh_token": "RT-secret", "expires_in": 3600})
        if req.url.path.endswith("/token") and "refresh_token" in body:
            assert "RT-secret" in body
            return httpx.Response(200, json={"access_token": "AT2", "refresh_token": "RT-2", "expires_in": 3600})
        if req.url.path.endswith("/me"):
            assert req.headers["Authorization"] in ("Bearer AT1", "Bearer AT2")
            return httpx.Response(200, json={"mail": "owner@kantor.co.id"})
        return httpx.Response(404)
    monkeypatch.setattr(outlook, "_client", lambda timeout=20: httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    with pytest.raises(outlook.OutlookError):
        await outlook.start_login()                                                          # no client id yet: says so
    with pytest.raises(outlook.OutlookError):
        await outlook.set_client("bukan-guid", "common", "test")
    await outlook.set_client("11111111-2222-3333-4444-555555555555", "", "test")
    got = await outlook.start_login()
    assert got["user_code"] == "ABCD-1234" and (await outlook.status())["pending"]["user_code"] == "ABCD-1234"
    assert await outlook.poll_login() == "waiting"
    assert await outlook.poll_login() == "done"
    st = await outlook.status()
    assert st["connected"] and st["account"] == "owner@kantor.co.id" and st["pending"] is None
    stored = await pool.fetchval("SELECT value FROM settings_kv WHERE key = 'outlook:token'")
    assert "RT-secret" not in json.dumps(stored)                                            # the refresh token is kept encrypted
    outlook._access.update(token="", until=0.0)                                              # the access token expired → refreshed
    assert (await outlook.graph("GET", "/me"))["mail"] == "owner@kantor.co.id"
    assert outlook._access["token"] == "AT2"
    await outlook.logout("test")
    assert not (await outlook.status())["connected"]


# ---------- one list, one triage, errands ----------

def _fake_outlook(monkeypatch, sent):
    from app import outlook

    async def status():
        return {"connected": True, "account": "owner@kantor.co.id", "client_id": "x", "tenant": "common", "pending": None, "last_sync": None}

    async def recent_mail(since, top=50):
        return [outlook.mail_row({"id": "O1", "conversationId": "C1", "subject": "Laporan Q3", "from": {"emailAddress": {"name": "Sari", "address": "sari@kantor.co.id"}},
                                  "bodyPreview": "Mohon persetujuan laporan Q3 sebelum jam 3", "receivedDateTime": (datetime.now(timezone.utc) - timedelta(minutes=30)).isoformat()}),
                outlook.mail_row({"id": "O2", "conversationId": "C2", "subject": "Newsletter", "from": {"emailAddress": {"name": "Promo", "address": "promo@x.id"}},
                                  "bodyPreview": "Diskon", "receivedDateTime": (datetime.now(timezone.utc) - timedelta(minutes=40)).isoformat()})]

    async def calendar(start, end):
        s = datetime.now(timezone.utc) + timedelta(minutes=8)
        return [{"ext_id": "E1", "title": "Weekly Tim Produk", "start": s.isoformat(), "end": (s + timedelta(hours=1)).isoformat(), "location": "R. Rapat 3", "attendees": ["Sari", "Dimas"], "online": False}]

    async def nothing(*a, **k):
        return None

    async def body(ext_id):
        return "Pak, mohon persetujuan laporan Q3 sebelum jam 3 sore. Terima kasih, Sari"

    async def samples(n=8):
        return ["Siap, terima kasih Mbak. Saya cek dulu ya."]

    async def mk_draft(ext_id, text):
        sent.append(("draft", ext_id, text))
        return "D-1"

    async def send_draft(draft_id):
        sent.append(("send", draft_id))
    for k, v in {"status": status, "recent_mail": recent_mail, "calendar": calendar, "mark_synced": nothing, "message_body": body,
                 "sent_samples": samples, "create_reply_draft": mk_draft, "send_draft": send_draft}.items():
        monkeypatch.setattr(outlook, k, v)


@needs_db
async def test_email_and_whatsapp_become_one_triaged_list_with_errands(pool, monkeypatch):
    from app import attention, gateway, home, modelrouter, notes
    await pool.execute("TRUNCATE inbox_items, calendar_events, notifications, mail_items, flow_runs, settings_kv, note_pages RESTART IDENTITY CASCADE")
    _fake_outlook(monkeypatch, [])
    now = datetime.now(timezone.utc)
    await pool.execute("INSERT INTO notifications (app, package, title, text, posted_at) VALUES ('WhatsApp', 'com.whatsapp', 'Sari', 'Pak, sudah lihat email laporan Q3?', $1), "
                       "('WhatsApp', 'com.whatsapp', 'Istri', 'Nanti pulang beli susu si Kecil ya', $1), ('WhatsApp', 'com.whatsapp', 'Bank', 'OTP 99', $1)", now)
    await pool.execute("UPDATE notifications SET sensitive = true WHERE title = 'Bank'")
    await pool.execute("INSERT INTO mail_items (ext_id, sender, sender_addr, subject, snippet, received_at) VALUES ('G1', 'Toko', 'promo@toko.id', 'Flash sale', 'Diskon', $1)", now)
    calls = []

    async def fake(lane, body, **kw):
        calls.append((lane, modelrouter.NO_FREE.get(), kw.get("caller")))
        ids = {int(x.split("]")[0][1:]): x for x in body["messages"][1]["content"].split("ITEM:\n")[1].splitlines()}
        items = []
        for i, line in ids.items():
            if "Sari" in line:
                items.append({"id": i, "kelas": "perlu", "alasan": "Sari menunggu persetujuan laporan Q3 sebelum 15.00", "topik": "Sari · laporan Q3", "tenggat": "15.00",
                              "balasan": ["Sudah, saya setujui siang ini", "Saya cek dulu ya"]})
            elif "susu" in line:
                items.append({"id": i, "kelas": "perlu", "alasan": "titipan istri", "topik": "Istri · titipan", "tugas": "beli susu si Kecil"})
            else:
                items.append({"id": i, "kelas": "abaikan", "alasan": "promosi"})
        return reply({"items": items})
    monkeypatch.setattr(gateway, "complete", fake)

    r = await attention.tick()                                                                  # the 5-minute clock tick
    assert r["triaged"] == 5 and r["needs"] == 3
    assert calls and all(c[1] for c in calls)                                                    # personal content: never a free endpoint
    runs = [(x["feature"], x["action"], x["lane"]) for x in await pool.fetch("SELECT feature, action, lane FROM flow_runs ORDER BY id")]
    assert runs[0] == ("inbox", "sync", "skill") and runs[1][:2] == ("inbox", "triage") and runs[1][2] in ("ringan", "berat")   # router → Hermes → lane
    assert await pool.fetchval("SELECT count(*) FROM inbox_items WHERE sender = 'Bank'") == 0     # the OTP never entered the list
    lst = await attention.listing()
    sari = next(c for c in lst["needs"] if c["topic"] == "Sari · laporan Q3")
    assert sorted(sari["sources"]) == ["outlook", "whatsapp"]                                   # one matter across email and WhatsApp
    assert lst["counts"]["needs"] == 3 and lst["errands"] == ["beli susu si Kecil"]
    assert any(t["text"].startswith("beli susu si Kecil — dari WA Istri") for t in await notes.tasks("all"))
    assert await pool.fetchval("SELECT title FROM calendar_events") == "Weekly Tim Produk"
    assert (await attention.tick())["synced"]["outlook"] == 0                                    # the same mail is not taken twice
    f = await home.feed("kerja")
    shown = {c["id"]: c for c in f["all"]}
    assert shown["inbox"]["title"] == "Perlu perhatian · 3" and shown["inbox"]["route"] == "#/inbox"     # the front page, at work
    cal = next(c for c in f["all"] if c["kind"] == "calendar")
    assert cal["title"] == "Weekly Tim Produk" and cal["cta"] == "Rekam rapat"                           # a meeting in 8 minutes: record it


@needs_db
async def test_a_draft_in_his_style_is_sent_only_by_his_kirim_and_whatsapp_replies_via_the_phone(pool, monkeypatch):
    from app import attention, gateway, phone_agent
    await pool.execute("TRUNCATE inbox_items, approvals, flow_runs, settings_kv RESTART IDENTITY CASCADE")
    sent = []
    _fake_outlook(monkeypatch, sent)
    iid = await pool.fetchval("""INSERT INTO inbox_items (source, ext_id, thread, sender, sender_addr, subject, snippet, received_at, triage)
                                 VALUES ('outlook', 'O1', 'C1', 'Sari', 'sari@kantor.co.id', 'Laporan Q3', 'Mohon persetujuan', now(), 'needs') RETURNING id""")
    prompts = []

    async def fake(lane, body, **kw):
        prompts.append(body["messages"])
        return reply("Halo Mbak Sari,\n\nSiap, laporan Q3 saya setujui. Terima kasih.\n\nSalam")
    monkeypatch.setattr(gateway, "complete", fake)
    d = await attention.draft(iid, "kamu", "setujui")
    assert "setujui" in d["body"] and d["lane"] in ("ringan", "berat")
    assert "Saya cek dulu ya" in prompts[0][1]["content"] and "MAU PEMILIK: setujui" in prompts[0][1]["content"]   # his own sent mails as the style
    assert sent == []                                                                            # a draft is not sent
    s = await attention.save_draft(iid, d["body"] + " ")
    assert s["draft_id"] == "D-1" and sent[0][0] == "draft"                                      # in his Outlook Drafts too
    r = await attention.send(iid, d["body"], "device:HP")
    assert r["sent"] and ("send", "D-1") in sent
    a = await pool.fetchrow("SELECT kind, status, decided_by FROM approvals WHERE id = $1", r["approval"])
    assert a["kind"] == "outlook_send" and a["status"] == "completed" and a["decided_by"] == "device:HP"   # recorded as his decision
    assert await pool.fetchval("SELECT status FROM inbox_items WHERE id = $1", iid) == "done"

    wid = await pool.fetchval("""INSERT INTO inbox_items (source, ext_id, thread, sender, snippet, received_at, triage, data)
                                 VALUES ('whatsapp', 'n5', 'wa:istri', 'Istri', 'Jadi pulang jam berapa?', now(), 'needs', '{"conversation": "Istri"}') RETURNING id""")
    ops = []

    async def op(name, **args):
        ops.append((name, args))
        return {"ok": True, "title": args["title"]}
    monkeypatch.setattr(phone_agent, "op", op)
    assert (await attention.wa_reply(wid, "Jam 6 sampai rumah"))["to"] == "Istri"
    assert ops == [("notif_reply", {"title": "Istri", "text": "Jam 6 sampai rumah"})]
    assert await pool.fetchval("SELECT status FROM inbox_items WHERE id = $1", wid) == "done"
    with pytest.raises(ValueError):
        await attention.draft(wid)                                                               # WhatsApp: quick replies, not email drafts


@needs_db
async def test_phone_notifications_and_gmail_are_triaged_through_the_master_flow(pool, monkeypatch):
    from app import gateway, notifications
    await pool.execute("TRUNCATE notifications, flow_runs RESTART IDENTITY CASCADE")

    async def fake(lane, body, **kw):
        return reply({"decisions": [{"id": 1, "decision": "skip"}], "say": ""})
    monkeypatch.setattr(gateway, "complete", fake)
    await notifications.triage([{"id": 1, "app": "Shopee", "title": "Promo", "text": "Diskon"}])
    assert await pool.fetchval("SELECT feature || ':' || action FROM flow_runs") == "perhatian:notif-triase"


# ---------- the meeting while it is recorded ----------

@needs_db
async def test_the_live_meeting_transcript_decisions_tasks_and_questions(pool, monkeypatch, tmp_path):
    from app import gateway, hub, meeting_live, meetings, stt
    monkeypatch.setattr(meetings, "ROOT", tmp_path / "meetings")
    await pool.execute("TRUNCATE meetings, flow_runs RESTART IDENTITY CASCADE")
    hub.reset()
    events = []

    async def listen(ev):
        events.append(ev)
    hub.register(listen)
    texts = iter(["Oke kita mulai weekly.", "Rilis versi 2 diputuskan Jumat.", "Mas tolong kirim timeline ke Dimas besok.", "Rahasia gaji."])
    engines = []

    async def pcm(path):
        return b"\0" * 3200

    async def transcribe(data, engine=None):
        engines.append(engine)
        return {"text": next(texts)}
    monkeypatch.setattr(meeting_live, "_pcm", pcm)
    monkeypatch.setattr(stt, "transcribe", transcribe)
    calls = []

    async def fake(lane, body, **kw):
        calls.append(body["messages"][1]["content"])
        if "Pertanyaan" in body["messages"][1]["content"]:
            return reply("Rilisnya Jumat (menit 2).")
        return reply({"keputusan": ["Rilis versi 2 hari Jumat"], "tugas": [{"siapa": "pemilik", "apa": "kirim timeline ke Dimas", "kapan": "besok", "pemilik": True}, {"siapa": "x"}],
                      "topik": "rilis v2"})
    monkeypatch.setattr(gateway, "complete", fake)
    m = await meetings.create("Weekly Tim Produk", False, True)
    mid = str(m["id"])
    for n in range(3):
        await meeting_live.on_chunk(mid, n, str(tmp_path / f"c{n}.aac"), False)
    lv = await meeting_live.live(mid)
    assert [x["n"] for x in lv["transcript"]] == [0, 1, 2] and lv["keputusan"] == ["Rilis versi 2 hari Jumat"]
    assert lv["tugas"] == [{"siapa": "pemilik", "apa": "kirim timeline ke Dimas", "kapan": "besok", "pemilik": True}] and lv["topik"] == "rilis v2"
    assert len(calls) == 1 and "[menit 3] Mas tolong kirim timeline" in calls[0]                  # one extraction per 3 minutes
    assert any(e.get("type") == "meeting_live" and e.get("notes") for e in events)
    assert await pool.fetchval("SELECT count(*) FROM flow_runs WHERE feature = 'rapat' AND action = 'catat-langsung' AND status = 'done'") == 1

    c = await meetings.create("Gaji", True, True)                                               # confidential: the local Whisper, never a model
    await meeting_live.on_chunk(str(c["id"]), 0, str(tmp_path / "x.aac"), True)
    assert engines[-1] == "whisper" and len(calls) == 1

    from app import devices, main
    _, token = await devices.create("HP", "test", scope="owner")
    h = {"Authorization": f"Bearer {token}"}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url="http://t") as cl:
        st = (await cl.get("/api/v1/app/meeting", headers=h)).json()
        assert st["card"]["state"] == "recording" and st["live"]["transcript"]
        got = (await cl.get(f"/api/v1/app/meeting/{mid}/live", headers=h)).json()
        assert got["title"] == "Weekly Tim Produk" and got["live"]["keputusan"]
        a = (await cl.post(f"/api/v1/app/meeting/{mid}/ask", json={"question": "kapan rilisnya?"}, headers=h)).json()
        assert a["answer"].startswith("Rilisnya Jumat")
        assert (await cl.post(f"/api/v1/app/meeting/{c['id']}/ask", json={"question": "berapa gajinya?"}, headers=h)).status_code == 409
        assert (await cl.get("/api/v1/app/meeting/not-a-uuid/live", headers=h)).status_code == 404
    hub.reset()


@needs_db
async def test_wave3_screens_get_real_answers(pool, monkeypatch):
    from app import devices, main
    await pool.execute("TRUNCATE inbox_items, calendar_events, settings_kv RESTART IDENTITY")
    _, token = await devices.create("HP", "test", scope="owner")
    h = {"Authorization": f"Bearer {token}"}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url="http://t") as c:
        lst = (await c.get("/api/v1/app/inbox", headers=h)).json()
        assert lst["needs"] == [] and lst["outlook"]["connected"] is False and lst["counts"]["needs"] == 0
        assert (await c.get("/api/v1/app/inbox?source=email", headers=h)).status_code == 200
        assert (await c.put("/api/v1/app/outlook/client", json={"client_id": "x" * 36}, headers=h)).status_code == 409   # not a GUID: says so
        assert (await c.post("/api/v1/app/outlook/login", headers=h)).status_code == 409                               # no client id yet
        assert (await c.get("/api/v1/app/calendar", headers=h)).json() == {"events": []}
        assert (await c.get("/api/v1/app/inbox/item/999", headers=h)).status_code == 404
        assert (await c.post("/api/v1/app/inbox/item/1/zzz", headers=h)).status_code == 404
        assert (await c.get("/api/v1/app/meeting", headers=h)).status_code == 200
        assert (await c.get("/api/v1/app/inbox")).status_code in (401, 403)                                           # the owner only
        assert (await c.get("/api/v1/app/home", headers=h)).status_code == 200
    from app import setup_status
    st = await setup_status.all_status()
    assert st["inbox"]["ready"] is False and st["inbox"]["setup_route"] == "#/inbox"                # the front page says what to connect
