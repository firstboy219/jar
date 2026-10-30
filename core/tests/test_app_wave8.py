"""ADR-087 wave 8: the job hunt on JobStreet — postings from JobStreet's own search (no AI), scored against the CV (never a free endpoint),
applied for through the JobStreet app on the phone (by JARVIS within his rules, at most N a day, or by his tap), emails matched to the
applications (invitation / rejection / offer), and replies to invitations — the free slot or the proposed time — sent after the undo window
(or kept as a draft), with the interview in the calendar."""
import json
import os
from datetime import date, datetime, timedelta
from pathlib import Path

import httpx
import pytest

from tests.test_integration import pool  # noqa: F401  (fixture)

needs_db = pytest.mark.skipif(not os.getenv("TEST_DATABASE_URL"), reason="needs TEST_DATABASE_URL")
FIX = Path(__file__).parent / "fixtures"


def reply(content):
    return {"choices": [{"message": {"content": content if isinstance(content, str) else json.dumps(content)}}]}


# ---------- pure ----------

def test_jobstreet_pages_salaries_mail_kinds_and_free_slots():
    from app import karier
    from app.location import WIB
    posts = karier.parse_search(json.loads((FIX / "jobstreet_search.json").read_text()), "data analyst · Jakarta Raya")
    assert [p["title"] for p in posts] == ["DATA ANALYST", "JUNIOR DATA ANALYST", "Business Analyst"]
    assert posts[0]["id"] == "95225815" and posts[0]["url"] == "https://id.jobstreet.com/id/job/95225815" and "Jakarta" in posts[0]["location"]
    d = karier.parse_detail((FIX / "jobstreet_detail.html").read_text())
    assert "DATA ANALYST" in d["description"] and "Tugas & Tanggung Jawab" in d["description"] and "<p>" not in d["description"]
    assert d["questions"][0].startswith("Kualifikasi mana") and d["link_out"] is False and d["expired"] is False and d["expires_at"].startswith("2026-11-28")
    assert karier.salary_max("Rp 8.000.000 – Rp 10.000.000 per month") == 10_000_000 and karier.salary_max("Rp 8 jt - 12 jt") == 12_000_000
    assert karier.salary_max("") is None and karier.salary_max("Kompetitif") is None
    assert karier.excluded({"title": "Sales Lapangan", "company": "PT X"}, ["sales lapangan"]) == "sales lapangan"
    assert karier.company_match("PT Maju Digital Indonesia", "Undangan interview dari HR Maju Digital") and not karier.company_match("PT Indonesia Jaya", "Indonesia hebat")
    assert karier.kind_of_mail("Undangan Interview User — Data Analyst") == "interview" and karier.kind_of_mail("Mohon maaf, Anda belum dapat melanjutkan") == "rejected"
    assert karier.kind_of_mail("Offering Letter – Data Analyst") == "offer" and karier.kind_of_mail("Promo akhir tahun") is None
    busy = [(datetime(2026, 11, 2, 9, 0, tzinfo=WIB), datetime(2026, 11, 2, 12, 0, tzinfo=WIB))]
    slots = karier.free_slots(busy, date(2026, 10, 31))          # Saturday: the next working days, the busy morning skipped
    assert [s.strftime("%a %H:%M") for s in slots] == ["Mon 13:00", "Mon 15:00", "Tue 09:00"]


# ---------- the round: search, score, apply ----------

def _fake_jobstreet(monkeypatch, hits):
    from app import karier
    search = (FIX / "jobstreet_search.json").read_text()
    detail = (FIX / "jobstreet_detail.html").read_text()

    def handler(req):
        hits.append(req.url.path)
        if req.url.path.endswith("/search"):
            return httpx.Response(200, text=search)
        return httpx.Response(200, text=detail)
    monkeypatch.setattr(karier, "_client", lambda timeout=25: httpx.AsyncClient(transport=httpx.MockTransport(handler)))


def _fake_phone(monkeypatch, pool, jobs):
    from app import phone_agent

    async def request(goal, app, actor, session_id=None, scheduled=False, project=None, by="jadwal"):
        tid = await pool.fetchval("INSERT INTO tasks (session_id, title, instruction, kind, status) VALUES ('phone', $1, $2, 'owner', 'running') RETURNING id", app, goal)
        jobs.append({"app": app, "goal": goal, "task_id": tid})
        return {"id": len(jobs), "task_id": tid, "status": "approved"}
    monkeypatch.setattr(phone_agent, "request", request)


@needs_db
async def test_a_round_finds_scores_and_applies_within_his_rules(pool, monkeypatch):
    from app import gateway, karier, master, modelrouter
    await pool.execute("TRUNCATE job_posts, job_applications, job_replies, flow_runs, tasks, settings_kv RESTART IDENTITY CASCADE")
    await pool.execute("""INSERT INTO settings_kv (key, value) VALUES ('app:jobs', '{"roles": ["data analyst"], "locations": ["Jakarta Raya"], "profile": "5 tahun analis data FMCG, SQL, Power BI",
        "auto_apply": true, "max_per_day": 1, "min_match": 75, "exclude": ["junior"]}')""")
    hits, jobs, calls = [], [], []
    _fake_jobstreet(monkeypatch, hits)
    _fake_phone(monkeypatch, pool, jobs)

    async def fake(lane, body, **kw):
        sysmsg = body["messages"][0]["content"]
        calls.append((sysmsg[:30], modelrouter.NO_FREE.get()))
        if "Nilai kecocokan" in sysmsg:
            ids = [line[1:line.index("]")] for line in body["messages"][1]["content"].split("LOWONGAN:\n")[1].split("\n") if line.startswith("[")]
            return reply({"items": [{"id": i, "skor": 90 if n == 0 else 60, "cocok": ["SQL", "FMCG"], "kurang": ["Python"], "alasan": "pengalaman FMCG pas"} for n, i in enumerate(ids)]})
        return reply({"surat": "Dengan hormat, saya tertarik dengan posisi Data Analyst…", "jawaban": [{"tanya": "Berapa tahun pengalaman?", "jawab": "5 tahun"}]})
    monkeypatch.setattr(gateway, "complete", fake)
    r = await karier.round_("schedule")
    assert r["search"]["new"] == 3 and r["score"] == {"scored": 2, "skipped": 1}                       # the junior posting is left out by his rule
    assert all(c[1] for c in calls)                                                                     # CV and postings: never a free endpoint
    best = await pool.fetchval("SELECT id FROM job_posts WHERE score = 90")
    assert r["applied"] == [best] and len(jobs) == 1 and jobs[0]["app"] == "jobstreet"                 # the best one; his limit: one a day
    assert "Dengan hormat" in jobs[0]["goal"] and "5 tahun" in jobs[0]["goal"] and "Jangan mengubah profil" in jobs[0]["goal"]
    flows = [(x["action"], x["lane"]) for x in await pool.fetch("SELECT action, lane FROM flow_runs ORDER BY id")]
    assert flows[0] == ("cari", "skill") and ("nilai", "ringan") in flows and ("lamar", "hermes") in flows
    await pool.execute("UPDATE tasks SET status = 'completed', result = '{\"terkirim\": true, \"catatan\": \"Lamaran terkirim\"}' WHERE id = $1", jobs[0]["task_id"])
    await master.on_task_finished(jobs[0]["task_id"])
    a = await pool.fetchrow("SELECT status, via, applied_at, cover_letter FROM job_applications")
    assert a["status"] == "applied" and a["via"] == "jarvis" and a["applied_at"] and a["cover_letter"].startswith("Dengan hormat")
    assert (await karier.round_("schedule"))["applied"] == []                                           # today's limit already used
    with pytest.raises(karier.JobError):
        await karier.apply(best, "owner", "test")                                                       # not twice


@needs_db
async def test_an_invitation_is_matched_and_answered_after_the_undo_window(pool, monkeypatch):
    from app import approvals, attention, gateway, karier, outlook
    await pool.execute("TRUNCATE job_posts, job_applications, job_replies, inbox_items, calendar_events, approvals, flow_runs, settings_kv RESTART IDENTITY CASCADE")
    await pool.execute("""INSERT INTO settings_kv (key, value) VALUES ('app:jobs', '{"roles": ["data analyst"], "auto_reply_invites": true, "undo_min": 5}')""")
    await pool.execute("INSERT INTO job_posts (id, title, company, status) VALUES ('1', 'Data Analyst', 'PT Maju Digital Indonesia', 'applied')")
    app_id = await pool.fetchval("INSERT INTO job_applications (post_id, status, applied_at) VALUES ('1', 'applied', now()) RETURNING id")
    iid = await pool.fetchval("""INSERT INTO inbox_items (source, ext_id, thread, sender, sender_addr, subject, snippet, received_at)
        VALUES ('outlook', 'M1', 'T1', 'HR Maju Digital', 'hr@majudigital.co.id', 'Undangan Interview Data Analyst', 'Kami mengundang Bapak interview Selasa 3 Nov pukul 10.00', now()) RETURNING id""")
    await pool.execute("""INSERT INTO inbox_items (source, ext_id, sender, subject, snippet, received_at) VALUES ('outlook', 'M2', 'Toko', 'Promo', 'diskon', now())""")
    sent = []

    async def status():
        return {"connected": True}

    async def body(ext):
        return "Kami mengundang Bapak interview Selasa 3 Nov pukul 10.00 di kantor kami."

    async def mk(ext, text):
        sent.append(("draft", text))
        return "D1"

    async def send(d):
        sent.append(("send", d))

    async def event(title, start, end, location="", body=""):
        sent.append(("event", title, start))
        return {"id": "EV1"}
    for k, v in {"status": status, "message_body": body, "create_reply_draft": mk, "send_draft": send, "create_event": event}.items():
        monkeypatch.setattr(outlook, k, v)

    async def fake(lane, b, **kw):
        return reply({"terima": "2026-11-03T10:00", "slot": [], "lokasi": "Kantor Maju Digital", "online": False,
                      "balasan": "Terima kasih atas undangannya. Saya bersedia hadir Selasa, 3 November pukul 10.00.", "ringkas": "Menerima Selasa 10.00"})
    monkeypatch.setattr(gateway, "complete", fake)
    r = await karier.watch_mail()
    assert r == {"checked": 2, "matched": 1}
    a = await pool.fetchrow("SELECT status, events FROM job_applications WHERE id = $1", app_id)
    assert a["status"] == "interview" and a["events"][-1]["kind"] == "undangan"
    rep = await pool.fetchrow("SELECT * FROM job_replies")
    assert rep["status"] == "pending" and rep["proposal"]["accept"] == "2026-11-03T10:00"
    assert await karier.send_due() == []                                                                 # still inside the undo window
    assert (await karier.watch_mail())["checked"] == 0                                                   # each email looked at once
    await pool.execute("UPDATE job_replies SET send_at = now() - interval '1 second'")
    assert await karier.send_due() == [rep["id"]]
    assert ("send", "D1") in sent and any(s[0] == "event" and s[1].startswith("Interview PT Maju Digital") for s in sent)
    ap = await pool.fetchrow("SELECT kind, decided_by, status FROM approvals")
    assert ap["kind"] == "outlook_send" and ap["decided_by"] == "aturan pemilik: balas undangan otomatis" and ap["status"] == "completed"   # on record as his rule
    assert await pool.fetchval("SELECT title FROM calendar_events WHERE source = 'jarvis'") == "Interview PT Maju Digital Indonesia — Data Analyst"
    assert (await pool.fetchrow("SELECT interview FROM job_applications WHERE id = $1", app_id))["interview"]["at"].startswith("2026-11-03T10:00")


@needs_db
async def test_without_auto_reply_it_is_a_draft_he_can_cancel_or_send_and_the_screen(pool, monkeypatch):
    from app import devices, gateway, karier, main
    await pool.execute("TRUNCATE job_posts, job_applications, job_replies, inbox_items, flow_runs, settings_kv RESTART IDENTITY CASCADE")
    await pool.execute("""INSERT INTO settings_kv (key, value) VALUES ('app:jobs', '{"roles": [], "auto_reply_invites": true}')""")   # no criteria: never automatic
    await pool.execute("INSERT INTO job_posts (id, title, company, status, score, score_data) VALUES ('1', 'BA', 'Kopi Senja Group', 'applied', 88, '{\"alasan\": \"pas\"}'), ('2', 'PM', 'Toko Abadi', 'scored', 81, '{}')")
    await pool.execute("INSERT INTO job_applications (post_id, status) VALUES ('1', 'applied')")
    await pool.execute("INSERT INTO inbox_items (source, ext_id, sender, subject, snippet, received_at) VALUES ('gmail', 'G1', 'HR Kopi Senja', 'Jadwal interview', 'Mohon pilih jadwal interview', now())")

    async def fake(lane, b, **kw):
        return reply({"terima": None, "slot": ["2026-11-02T13:00", "2026-11-02T15:00"], "balasan": "Terima kasih. Saya bisa Senin 13.00 atau 15.00.", "ringkas": "Menawarkan 2 slot"})
    monkeypatch.setattr(gateway, "complete", fake)
    await karier.watch_mail()
    rep = await pool.fetchrow("SELECT * FROM job_replies")
    assert rep["status"] == "draft" and rep["send_at"] is None
    _, token = await devices.create("HP", "test", scope="owner")
    h = {"Authorization": f"Bearer {token}"}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url="http://t") as c:
        st = (await c.get("/api/v1/app/jobs", headers=h)).json()
        assert [p["id"] for p in st["good"]] == ["2"] and st["counts"]["interview"] == 1 and st["ready"] == {"roles": False, "cv": False}
        assert st["replies"][0]["proposal"]["slots"] == ["2026-11-02T13:00", "2026-11-02T15:00"]
        assert (await c.post(f"/api/v1/app/jobs/reply/{rep['id']}/cancel", headers=h)).status_code == 409     # a draft is not pending
        assert (await c.post("/api/v1/app/jobs/post/2/skip", headers=h)).json() == {"ok": True}
        assert (await c.get("/api/v1/app/jobs", headers=h)).json()["good"] == []
        assert (await c.put("/api/v1/app/jobs/cv", json={"attachment_id": "0" * 32}, headers=h)).status_code == 422
        assert (await c.get("/api/v1/app/jobs")).status_code in (401, 403)
