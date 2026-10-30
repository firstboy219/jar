"""ADR-087 wave 9 gap batch C: a snoozed message comes back at its time, family filter and the ignored list, a draft that tells its context
and carries attachments into Outlook, tasks that open their source, the recap's mail and transport numbers, JobStreet's "viewed" from the
phone and interview preparation the evening before."""
import base64
import os
from datetime import datetime, timedelta

import pytest

from tests.test_integration import pool  # noqa: F401  (fixture)

needs_db = pytest.mark.skipif(not os.getenv("TEST_DATABASE_URL"), reason="needs TEST_DATABASE_URL")


def reply(content):
    import json
    return {"choices": [{"message": {"content": content if isinstance(content, str) else json.dumps(content)}}]}


def test_snooze_presets():
    from app import attention
    from app.location import WIB
    now = datetime(2026, 10, 30, 10, 15, tzinfo=WIB)   # a Friday
    assert attention.snooze_until("1j", now) == now + timedelta(hours=1)
    assert attention.snooze_until("14:00", now).hour == 14 and attention.snooze_until("09:00", now).day == 31
    assert attention.snooze_until("besok", now) == datetime(2026, 10, 31, 8, 0, tzinfo=WIB)
    assert attention.snooze_until("senin", now) == datetime(2026, 11, 2, 8, 0, tzinfo=WIB)
    with pytest.raises(ValueError):
        attention.snooze_until("kapan-kapan", now)


@needs_db
async def test_snooze_family_draft_context_attachments_and_task_links(pool, monkeypatch, tmp_path):
    from app import attachments, attention, gateway, hub, notes, outlook
    monkeypatch.setattr(attachments, "ROOT", tmp_path / "att")
    await pool.execute("TRUNCATE inbox_items, flow_runs, settings_kv, note_pages RESTART IDENTITY CASCADE")
    await pool.execute("INSERT INTO settings_kv (key, value) VALUES ('app:inbox', '{\"family\": [\"Istri\"]}')")
    a = await pool.fetchval("""INSERT INTO inbox_items (source, ext_id, sender, sender_addr, subject, snippet, received_at, triage) VALUES
        ('outlook', 'O1', 'Sari', 'sari@x.id', 'Laporan', 'mohon cek', now(), 'needs') RETURNING id""")
    await pool.execute("""INSERT INTO inbox_items (source, ext_id, sender, snippet, received_at, triage) VALUES ('whatsapp', 'n1', 'Istri', 'pulang jam berapa?', now(), 'needs'),
        ('gmail', 'G1', 'Promo', 'diskon', now(), 'ignore')""")
    hub.reset()
    told = []

    async def listen(e):
        told.append(e)
    hub.register(listen)
    await attention.snooze(a, "1j")
    assert await pool.fetchval("SELECT status FROM inbox_items WHERE id = $1", a) == "snoozed"
    assert await attention._snooze_tick() is None                                               # not yet
    await pool.execute("UPDATE inbox_items SET snoozed_until = now() - interval '1 minute' WHERE id = $1", a)
    assert await attention._snooze_tick() == [a] and any(e.get("title") == "Pengingat: Sari" for e in told)
    assert await pool.fetchval("SELECT status FROM inbox_items WHERE id = $1", a) == "open"
    lst = await attention.listing("keluarga")
    assert [c["items"][0]["sender"] for c in lst["needs"]] == ["Istri"] and lst["family"] == ["istri"]
    assert [x["sender"] for x in (await attention.listing())["ignored"]] == ["Promo"]

    calls = []

    async def body(ext):
        return "Mohon cek laporan Q3."

    async def samples(n=8):
        return ["Siap, saya cek."]

    async def mk(ext, text):
        calls.append(("draft", text))
        return "D1"

    async def add(draft_id, name, data, ctype=""):
        calls.append(("attach", draft_id, name, len(data)))
    for k, v in {"message_body": body, "sent_samples": samples, "create_reply_draft": mk, "add_attachment": add}.items():
        monkeypatch.setattr(outlook, k, v)

    async def fake(lane, b, **kw):
        return reply("Halo Sari, sudah saya cek.")
    monkeypatch.setattr(gateway, "complete", fake)
    d = await attention.draft(a, "kamu", "setujui")
    assert d["context"] == {"samples": 1, "facts": 0, "instruction": True, "chars": len("Mohon cek laporan Q3.")}
    f = await attachments.save("struk.txt", "text/plain", base64.b64encode(b"Struk GoFood Rp45.000").decode())
    s = await attention.save_draft(a, d["body"], [f["id"], "0" * 32])
    assert s["attachments"] == [f["id"]] and ("attach", "D1", "struk.txt", len(b"Struk GoFood Rp45.000")) in calls
    await attention._take_task({"id": a, "task": "kirim struk ke Sari"})
    t = next(x for x in await notes.tasks("all") if x["text"].startswith("kirim struk"))
    assert t["link"] == f"#/draf/{a}"
    hub.reset()


@needs_db
async def test_recap_numbers_viewed_applications_and_interview_prep(pool, monkeypatch):
    from app import gateway, karier, recap
    from app.location import WIB
    await pool.execute("TRUNCATE job_posts, job_applications, notifications, money_tx, inbox_items, flow_runs, settings_kv, note_pages RESTART IDENTITY CASCADE")
    await pool.execute("INSERT INTO money_tx (amount, direction, merchant, category, source) VALUES (17000, 'out', 'GoRide', 'transport', 'notif'), (5000, 'out', 'KRL', 'transport', 'notif')")
    await pool.execute("INSERT INTO inbox_items (source, ext_id, sender, snippet, received_at, status) VALUES ('outlook', 'X', 'A', 'b', now(), 'done')")

    async def fake(lane, b, **kw):
        sysmsg = b["messages"][0]["content"]
        if "REKAP" in sysmsg:
            return reply({"ringkasan": "ok", "action_plan": []})
        return reply({"pertanyaan": [{"tanya": "Ceritakan pengalaman produk Anda", "jawab_singkat": "8 tahun e-commerce"}], "tentang": "marketplace", "bawa": ["KTP"], "tanya_balik": []})
    monkeypatch.setattr(gateway, "complete", fake)
    r = await recap.compose()
    assert r["stats"]["mail_done"] == 1 and r["stats"]["transport"] == 22000
    await pool.execute("INSERT INTO job_posts (id, title, company, status) VALUES ('1', 'Product Manager', 'PT Toko Nusantara', 'applied')")
    aid = await pool.fetchval("INSERT INTO job_applications (post_id, status, applied_at) VALUES ('1', 'applied', now()) RETURNING id")
    await pool.execute("INSERT INTO notifications (app, package, title, text, posted_at) VALUES ('JobStreet', 'com.jobstreet.jobstreet', 'Kabar baik!', 'Lamaranmu untuk Product Manager di PT Toko Nusantara telah dilihat', now())")
    assert await karier.watch_phone() == 1
    assert await pool.fetchval("SELECT status FROM job_applications WHERE id = $1", aid) == "viewed"
    assert await karier.watch_phone() == 0                                                      # each notification once
    tomorrow = (datetime.now(WIB) + timedelta(days=1)).replace(hour=10, minute=0, second=0, microsecond=0)
    await pool.execute("UPDATE job_applications SET status = 'interview', interview = $2 WHERE id = $1", aid, {"at": tomorrow.isoformat()})
    assert await karier.prep_interviews() == [aid]
    prep = (await pool.fetchrow("SELECT interview FROM job_applications WHERE id = $1", aid))["interview"]["prep"]
    assert prep["pertanyaan"][0]["tanya"].startswith("Ceritakan") and prep["bawa"] == ["KTP"]
    assert await karier.prep_interviews() == []                                                 # prepared once
