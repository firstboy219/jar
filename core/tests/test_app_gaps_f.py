"""ADR-087 wave 9 gap batch F (second mockup audit): a source's API key only with the admin password and its expiry warned, HR views
counted, stock and payouts per channel, a shipping cutoff, strategy missions and channel shares, opportunities' effort and payback, the
camera's ask mode and paint minus doors and windows, a fare estimate on Gojek approvals, drafts that name what they used and notice a
requested attachment, habits on arriving/leaving/meetings with how often they ran, receipts from email as spending (never twice), the
bekam clinic search, the trip on Halaman, and file info and progress."""
import json
import os
from datetime import date, datetime, timedelta

import httpx
import pytest

from tests.test_integration import pool  # noqa: F401  (fixture)

needs_db = pytest.mark.skipif(not os.getenv("TEST_DATABASE_URL"), reason="needs TEST_DATABASE_URL")


def reply(content):
    return {"choices": [{"message": {"content": content if isinstance(content, str) else json.dumps(content)}}]}


# ---------- pure ----------

def test_expiry_stock_fare_attachment_trigger_receipt_and_estimate():
    from app import attention, bisnis, habits, money, needs, ukur
    from app.location import WIB
    today = date(2026, 10, 30)
    assert bisnis.key_days_left({"expires": "2026-11-04"}, today) == 5 and bisnis.key_days_left({}, today) is None
    assert bisnis.key_days_left({"expires": "bukan"}, today) is None

    s = {"unpacked_after": "23:59", "cutoff": ""}
    a = bisnis.judge("Renature", datetime(2026, 10, 30, 10, 0, tzinfo=WIB), {"stok_habis": 2, "stok_menipis": 5}, {}, None, s)
    assert a[0]["key"] == "stock:Renature:2026-10-30" and a[0]["tone"] == "red" and "2 produk stok habis" in a[0]["title"] and "5 lainnya" in a[0]["text"]
    assert bisnis.judge("Renature", datetime(2026, 10, 30, 10, 0, tzinfo=WIB), {"stok_menipis": 3}, {}, None, s)[0]["tone"] == "amber"

    trip = {"chosen": {"ride": {"cost": 18000}}, "plan": {"car": {"cost": 95000}}}
    assert needs.fare_of("Pesan GoRide ke Stasiun Bogor", trip) == 18000
    assert needs.fare_of("Pesan GoCar ke kantor", trip) == 95000
    assert needs.fare_of("Pesan GoRide, maksimal Rp25.000", trip) == 25000 and needs.fare_of("Cek promo", trip) is None and needs.fare_of("GoRide", None) is None

    assert attention.needs_attachment("Tolong invoice bulan Oktober ya") == "invoice" and attention.needs_attachment("Mohon kirimkan datanya") == "Mohon kirimkan"
    assert attention.needs_attachment("Terlampir laporan Q3") == "Terlampir" and attention.needs_attachment("Rapat jam 10") == ""

    T = habits.HabitIn
    assert habits.trigger_of(T(title="Pulang", type="leave", place="kantor", after="16:00", action="commute.plan_back")) == {
        "type": "leave", "place": "kantor", "days": [0, 1, 2, 3, 4], "after": "16:00"}
    assert habits.trigger_of(T(title="Rapat", type="calendar", before_min=10, action="meeting.offer")) == {"type": "calendar", "before": 10}
    with pytest.raises(ValueError):
        habits.trigger_of(T(title="Sampai", type="arrive", action="inbox.triage"))
    with pytest.raises(ValueError):
        habits.trigger_of(T(title="Jam", type="time", action="inbox.triage"))

    assert money.parse_receipt("Tokopedia <noreply@tokopedia.com>", "Pembayaran berhasil", "Terima kasih. Total Pembayaran: Rp 245.000") == {
        "amount": 245000, "merchant": "Tokopedia"}
    assert money.parse_receipt("Bank", "Top up berhasil", "Pembayaran berhasil Total Rp100.000") is None
    assert money.parse_receipt("Teman", "Halo", "Total Rp100.000") is None

    d = ukur.clean_estimate({"objek": "dinding", "lebar": 4, "tinggi": 3, "bukaan_m2": 2.5})
    assert d["luas_m2"] == 12.0 and d["bukaan_m2"] == 2.5


# ---------- DB ----------

@needs_db
async def test_source_key_password_expiry_alert_stock_payouts_and_strategy(pool, monkeypatch):
    from app import appauth, bisnis, devices, main, workers
    await pool.execute("TRUNCATE biz_sources, biz_daily, biz_insights, flow_runs, settings_kv RESTART IDENTITY CASCADE")
    monkeypatch.setenv("VAULT_KEY", "x" * 44)

    async def check(pw):
        return 200 if pw == "pw-admin" else 401
    monkeypatch.setattr(appauth, "_check", check)
    _, token = await devices.create("HP", "test", scope="owner")
    h = {"Authorization": f"Bearer {token}"}
    src = {"business": "Renature", "name": "Renature API", "base_url": "https://api.renature.id", "auth": {"type": "bearer", "expires": (date.today() + timedelta(days=3)).isoformat()},
           "key": "rahasia-123", "endpoints": [{"metric": "penjualan", "path": "/v1/orders", "agg": "count"}]}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url="http://t") as c:
        assert (await c.post("/api/v1/app/bisnis/sources", json=src, headers=h)).status_code == 422          # a key needs his password
        assert await pool.fetchval("SELECT count(*) FROM biz_sources") == 0
        r = await c.post("/api/v1/app/bisnis/sources", json={**src, "admin_password": "pw-admin"}, headers=h)
        if r.status_code == 409 and "brankas" in r.text:
            pytest.skip("vault key format")
        assert r.status_code == 200 and r.json()["key_days_left"] == 3
        sid = r.json()["id"]
        assert (await c.put(f"/api/v1/app/bisnis/sources/{sid}", json={**src, "key": "", "name": "Renature v2"}, headers=h)).status_code == 200   # no new key: no password
    new = await bisnis.alerts("Renature")
    assert any(x["key"].startswith("expiry:") and "habis 3 hari lagi" in x["title"] for x in new)

    today = date.today()
    for m, v in (("pesanan", 20), ("dikemas", 20), ("stok_habis", 1), ("pencairan@Shopee", 1_500_000), ("pencairan@Tokopedia", 700_000), ("penjualan@Shopee", 3_000_000),
                 ("penjualan@Tokopedia", 1_000_000)):
        await pool.execute("INSERT INTO biz_daily (business, metric, day, value, unit) VALUES ('Renature', $1, $2, $3, 'n')", m, today, v)
    v = (await bisnis.today_view())["businesses"][0]
    assert [p["name"] for p in v["payouts"]] == ["Shopee", "Tokopedia"] and all(c["name"] in ("Shopee", "Tokopedia") for c in v["channels"])
    share = await bisnis.channel_share("Renature", "penjualan")
    assert [(x["name"], x["pct"]) for x in share] == [("Shopee", 75.0), ("Tokopedia", 25.0)]

    await pool.execute("INSERT INTO biz_insights (kind, business, data) VALUES ('strategy', 'Renature', $1)",
                       {"ringkasan": "x", "strategi": [{"judul": "Bundling", "kenapa": "AOV", "langkah": ["paket 2+1"], "ukur": "AOV"}]})
    spawned = []

    async def spawn(title, instruction, **kw):
        spawned.append(instruction)
        return {"id": 501}
    monkeypatch.setattr(workers, "spawn", spawn)
    m = await bisnis.strategy_mission("Renature", 0)
    assert m["task_id"] == 501 and m["lane"] == "hermes" and "JANGAN mengubah" in spawned[-1] and "Bundling" in spawned[-1]
    with pytest.raises(bisnis.BisnisError):
        await bisnis.strategy_mission("Renature", 3)


@needs_db
async def test_habits_drafts_fare_receipts_bekam_pages_and_file_info(pool, monkeypatch, tmp_path):
    import base64
    from app import attachments, attention, berkas, commute, devices, gateway, habits, hub, ibadah, main, money, needs, outlook, phone_agent, workers
    monkeypatch.setattr(attachments, "ROOT", tmp_path / "att")
    await pool.execute("TRUNCATE habits, flow_runs, inbox_items, money_tx, commute_trips, settings_kv, places RESTART IDENTITY CASCADE")
    await habits.ensure_builtin()
    await pool.execute("INSERT INTO flow_runs (feature, action, goal, lane, status, trigger, started_at) VALUES ('kebiasaan', 'music.mood', 'x', 'skill', 'done', 'habit', now() - interval '1 day'), "
                       "('kebiasaan', 'music.mood', 'x', 'skill', 'done', 'habit', now() - interval '2 days'), ('kebiasaan', 'music.mood', 'x', 'skill', 'done', 'habit', now() - interval '2 days')")
    _, token = await devices.create("HP", "test", scope="owner")
    h = {"Authorization": f"Bearer {token}"}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url="http://t") as c:
        hs = (await c.get("/api/v1/app/habits", headers=h)).json()["habits"]
        assert next(x for x in hs if x["action"] == "music.mood")["fired_days"] == 2
        r = await c.post("/api/v1/app/habits", json={"title": "Sampai kantor: cek inbox", "type": "arrive", "place": "kantor", "action": "inbox.triage"}, headers=h)
        assert r.status_code == 200 and r.json()["trigger"]["type"] == "arrive"
        assert (await c.post("/api/v1/app/habits", json={"title": "Tanpa tempat", "type": "arrive", "action": "inbox.triage"}, headers=h)).status_code == 422

        # drafts name what they used and notice a requested file
        await pool.execute("""INSERT INTO inbox_items (source, ext_id, sender, sender_addr, subject, snippet, received_at, triage) VALUES
            ('outlook', 'A0', 'Sari', 'sari@x.id', 'Laporan September', 'sudah diterima', now() - interval '20 days', 'fyi'),
            ('outlook', 'A1', 'Sari', 'sari@x.id', 'Invoice Oktober', 'Mohon kirimkan invoice Oktober', now(), 'needs')""")

        async def body(ext):
            return "Mohon kirimkan invoice Oktober."

        async def samples(n=8):
            return []
        monkeypatch.setattr(outlook, "message_body", body)
        monkeypatch.setattr(outlook, "sent_samples", samples)
        asked = []

        async def fake(lane, b, **kw):
            asked.append(b["messages"][1]["content"])
            return reply("Halo Sari, terlampir invoice Oktober.")
        monkeypatch.setattr(gateway, "complete", fake)
        item = await pool.fetchval("SELECT id FROM inbox_items WHERE ext_id = 'A1'")
        d = await attention.draft(item)
        assert d["needs_attachment"] == "Mohon kirimkan" and d["context"]["earlier"] == ["Laporan September"] and "Laporan September" in asked[-1]

        # receipts in email become spending — not twice
        await pool.execute("""INSERT INTO inbox_items (source, ext_id, sender, subject, snippet, received_at, triage) VALUES
            ('gmail', 'R1', 'Tokopedia <noreply@tokopedia.com>', 'Pembayaran berhasil', 'Total Pembayaran: Rp 245.000', now(), 'ignore'),
            ('gmail', 'R2', 'Shopee <info@shopee.co.id>', 'Pesanan kamu telah dibayar', 'Total Pembayaran Rp 99.000', now(), 'ignore')""")
        await pool.execute("INSERT INTO money_tx (at, amount, direction, merchant, category, source) VALUES (now() - interval '2 hours', 99000, 'out', 'ShopeePay', 'belanja', 'notif')")
        assert await money.ingest_mail() == 1
        assert await pool.fetchval("SELECT merchant || ':' || source FROM money_tx WHERE source = 'email'") == "Tokopedia:email"
        assert await money.ingest_mail() == 0                                                         # remembered

        # a Gojek approval shows the fare the trip plan expected
        await pool.execute("INSERT INTO commute_trips (direction, status, plan, chosen) VALUES ('out', 'active', $1, $2)",
                           {"car": {"cost": 95000}, "options": []}, {"ride": {"cost": 17000}, "arrive": "08:41"})
        assert await needs._fare("gojek", "Pesan GoRide ke Stasiun Bogor") == 17000 and await needs._fare("pluang", "x") is None
        pages = (await c.get("/api/v1/app/pages", headers=h)).json()["pages"]
        assert any(p["kind"] == "perjalanan" and "08:41" in p["sub"] for p in pages)

        # the bekam reminder's search is a Hermes mission that contacts nobody
        spawned = []

        async def spawn(title, instruction, **kw):
            spawned.append(instruction)
            return {"id": 61}
        monkeypatch.setattr(workers, "spawn", spawn)

        async def no_city():
            return ("1301", "KOTA BOGOR", None)
        monkeypatch.setattr(ibadah, "city", no_city)
        r = (await c.post("/api/v1/app/ibadah/bekam/find", headers=h)).json()
        assert r["task_id"] == 61 and "KOTA BOGOR" in spawned[-1] and "JANGAN menghubungi" in spawned[-1]

        # a picked file says what it is; a scan is recognised
        from tests.test_app_gaps_d import _blank_pdf, _table_pdf
        a = await attachments.save("scan.pdf", "application/pdf", base64.b64encode(_blank_pdf(3)).decode())
        b = await attachments.save("tabel.pdf", "application/pdf", base64.b64encode(_table_pdf()).decode())
        ia = (await c.get(f"/api/v1/app/files/{a['id']}/info", headers=h)).json()
        ib = (await c.get(f"/api/v1/app/files/{b['id']}/info", headers=h)).json()
        assert ia["pages"] == 3 and ia["scanned"] and ib["pages"] == 1 and not ib["scanned"]
        assert (await c.get("/api/v1/app/files/" + "0" * 32 + "/info", headers=h)).status_code == 404
    assert berkas.info_of(b"x", "image") == {"pages": None, "scanned": False}
    assert commute and phone_agent and hub
