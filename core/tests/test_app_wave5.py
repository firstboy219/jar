"""ADR-087 wave 5: money — spending recorded from GoPay/bank notifications (never a sensitive one), categories, the pay period and its pots
(80% told once), next period's allocation by the heavy brain; Pluang read on the phone, three options by the heavy brain, his pick carried out
only with the admin password (limit, price guard, PIN his); coffee promos read in Kopi Kenangan & Qpon, the offer, the order paid with GoPay."""
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

def test_money_notifications_categories_and_the_pay_period():
    from app import money
    p = money.parse_tx("com.gojek.gopay", "Pembayaran berhasil", "Pembayaran Rp25.000 ke Kopi Kenangan berhasil.")
    assert p == {"direction": "out", "amount": 25000, "merchant": "Kopi Kenangan", "app": "GoPay"}
    assert money.parse_tx("com.bca", "BCA", "Dana masuk Rp12.500.000 dari PT MAJU JAYA")["direction"] == "in"
    assert money.parse_tx("com.gojek.gopay", "Top up berhasil", "Top up Rp200.000 berhasil") is None          # his own money moving: not spending
    assert money.parse_tx("com.whatsapp", "Budi", "bayar Rp50.000 ya") is None                                # not a money app
    assert money.parse_tx("ovo.id", "OVO", "Promo cashback minggu ini!") is None                              # no amount
    assert money.categorize("Kopi Kenangan") == "kopi" and money.categorize("GoRide") == "transport" and money.categorize("PLN Prabayar") == "tagihan"
    assert money.categorize("Toko Pak Slamet") == "lainnya" and money.categorize("Pluang Emas") == "investasi"
    assert money.period_of(date(2026, 10, 29), 25) == (date(2026, 10, 25), date(2026, 11, 24))
    assert money.period_of(date(2026, 10, 3), 25) == (date(2026, 9, 25), date(2026, 10, 24))
    assert money.period_of(date(2027, 2, 28), 31) == (date(2027, 2, 28), date(2027, 3, 30))                   # payday 31 = the month's last day
    pots = money.pot_status([{"name": "Makan", "amount": 1_000_000, "categories": ["makan", "kopi"]}, {"name": "Transport", "amount": 500_000, "categories": ["transport"]}],
                            {"makan": 700_000, "kopi": 150_000, "transport": 100_000, "hiburan": 90_000}, 80)
    assert [(x["name"], x["pct"], x["level"]) for x in pots] == [("Makan", 85, "warn"), ("Transport", 20, "ok"), ("Di luar pos", 0, "ok")]


def test_invest_options_stay_within_the_rules():
    from app import invest
    p = invest.clean_portfolio({"total": "Rp12.500.000", "kas": 500000, "aset": [{"nama": "Emas", "jenis": "emas", "nilai": "7.000.000", "harga": 1650000, "untung_pct": 4.2},
                                                                             {"nama": "Apple", "kode": "aapl", "jenis": "saham as", "nilai": 5000000}, {"jenis": "x"}]})
    assert p["total"] == 12_500_000 and [a["jenis"] for a in p["aset"]] == ["emas", "saham_as"] and p["aset"][1]["kode"] == "AAPL"
    assert invest.allocation(p) == {"emas": 58.3, "saham_as": 41.7} and invest.ticker_of(p["aset"][1]) == "AAPL" and invest.ticker_of(p["aset"][0]) == "GC=F"
    opts = invest.clean_options({"opsi": [
        {"judul": "Tambah emas", "aksi": [{"jenis": "beli", "aset": "Emas", "nominal": 1_000_000}], "alasan": "x"},
        {"judul": "Borong", "aksi": [{"jenis": "beli", "aset": "Emas", "nominal": 5_000_000}]},             # over his limit: dropped
        {"judul": "Jual Tesla", "aksi": [{"jenis": "jual", "aset": "Tesla", "nominal": 100}]},              # he has no Tesla: dropped
        {"judul": "Top up", "aksi": [{"jenis": "topup", "aset": "kas", "nominal": 100}]},                  # not buy/sell: dropped
        {"judul": "Ambil untung Apple", "aksi": [{"jenis": "jual", "aset": "Apple", "nominal": 1_000_000}]}]}, p, 2_000_000)
    assert [o["id"] for o in opts] == ["A", "B", "C"] and [o["judul"] for o in opts] == ["Tambah emas", "Ambil untung Apple", "Tahan dulu"]   # 'hold' always there
    g = invest.exec_goal(opts[0], p, 1.0, 2_000_000)
    assert "BELI Emas senilai Rp1.000.000" in g and "Rp1.650.000" in g and "lebih dari 1.0%" in g and "PIN diketik pemilik" in g and "Top Up" in g


def test_coffee_promos_and_the_order():
    from app import coffee
    promos = coffee.clean_promos({"promo": [{"menu": "Kopi Kenangan Mantan", "harga": "18.000", "harga_normal": "28.000", "voucher": "MANTAN18"},
                                            {"menu": "Americano", "harga": 22000}, {"menu": "Signature Latte", "harga": 90000}, {"harga": 1}]}, "kopikenangan")
    assert [p["menu"] for p in promos] == ["Kopi Kenangan Mantan", "Americano", "Signature Latte"] and promos[0]["hemat_pct"] == 36
    top = coffee.best(promos, "Americano less sugar", 75000)
    assert [p["menu"] for p in top] == ["Americano", "Kopi Kenangan Mantan"]                                  # his usual first; over the limit left out
    more = promos + coffee.clean_promos({"promo": [{"menu": "Es Kopi Susu Gula Aren", "harga": 15000, "harga_normal": 24000}]}, "qpon")
    assert coffee.best(more, "Kopi Kenangan Mantan", 75000)[0]["menu"] == "Kopi Kenangan Mantan"             # "kopi" alone is not his usual
    g = coffee.order_goal(top[1], {"pickup": True, "outlet": "Sudirman", "sugar": "less sugar", "max_price": 75000})
    assert "Pick Up" in g and "Sudirman" in g and "MANTAN18" in g and "GoPay" in g and "Rp75.000" in g and "PIN GoPay diketik pemilik" in g


def test_the_new_phone_apps_are_approved_with_their_payment_screens():
    from app import phone_agent
    assert phone_agent.APPS["pluang"]["packages"] == ["com.EmasDigi"]                                       # Pluang alone: no wallet app
    assert "com.gojek.gopay" in phone_agent.APPS["kopikenangan"]["packages"] and "com.qpon.platform" in phone_agent.APPS["qpon"]["packages"]
    assert phone_agent.detect_app("pesan kopi kenangan mantan") == "kopikenangan" and phone_agent.detect_app("cek portofolio pluang") == "pluang"
    obs = {"package": "com.EmasDigi", "nodes": [{"i": 1, "t": "Top Up", "k": True}, {"i": 2, "t": "Tarik Tunai", "k": True}]}
    assert phone_agent.check_action("ketuk", {"nomor": 1}, obs, "pluang") and phone_agent.check_action("ketuk", {"nomor": 2}, obs, "pluang")   # never


# ---------- money ----------

@needs_db
async def test_spending_is_recorded_from_notifications_and_pots_warn_once(pool, monkeypatch):
    from app import hub, money
    await pool.execute("TRUNCATE money_tx, money_plans, notifications, flow_runs, settings_kv RESTART IDENTITY CASCADE")
    await pool.execute("""INSERT INTO settings_kv (key, value) VALUES ('app:money', '{"salary": 10000000, "payday": 25, "pots": [{"name": "Makan & kopi", "amount": 100000, "categories": ["makan", "kopi"]}]}')""")
    now = datetime.now().astimezone()
    await pool.execute("""INSERT INTO notifications (app, package, title, text, posted_at, sensitive) VALUES
        ('GoPay', 'com.gojek.gopay', 'Pembayaran berhasil', 'Pembayaran Rp45.000 ke Kopi Kenangan berhasil.', $1, false),
        ('GoPay', 'com.gojek.gopay', 'Pembayaran berhasil', 'Pembayaran Rp40.000 ke GoFood Bakso Pak Kumis berhasil.', $1, false),
        ('BCA', 'com.bca', 'BCA: notifikasi sensitif', '(isi disembunyikan)', $1, true),
        ('WhatsApp', 'com.whatsapp', 'Budi', 'transfer Rp5.000.000 ya', $1, false)""", now)
    hub.reset()
    seen = []

    async def listen(ev):
        seen.append(ev)
    hub.register(listen)
    r = await money.tick()
    assert r == {"new": 2, "seen": 2, "alerts": 1}                                                          # the sensitive & WhatsApp ones never
    assert await pool.fetchval("SELECT feature || ':' || action || ':' || lane FROM flow_runs") == "uang:catat:skill"
    assert await money.tick() is None                                                                     # nothing new: no run at all
    assert await pool.fetchval("SELECT count(*) FROM flow_runs") == 1
    s = await money.summary()
    assert s["spent"] == 85_000 and s["pots"][0]["pct"] == 85 and s["pots"][0]["level"] == "warn"
    assert [e["title"] for e in seen if e.get("type") == "notify"] == ["Pos Makan & kopi sudah 85%"]
    assert await money.check_pots() == []                                                                 # told once per period
    await money.record(30_000, "Kopi Kenangan", "coffee:9", "kopi")
    await money.record(30_000, "Kopi Kenangan", "coffee:9", "kopi")                                       # the same purchase never twice
    s = await money.summary()
    assert s["spent"] == 115_000 and s["pots"][0]["level"] == "over"
    assert [e["title"] for e in seen if e.get("type") == "notify"][-1] == "Pos Makan & kopi terlewati"
    hub.reset()


@needs_db
async def test_the_allocation_is_proposed_by_the_heavy_brain_and_applied(pool, monkeypatch):
    from app import appsettings, gateway, modelrouter, money
    await pool.execute("TRUNCATE money_tx, money_plans, flow_runs, settings_kv RESTART IDENTITY CASCADE")
    with pytest.raises(money.MoneyError):
        await money.propose()                                                                             # no salary yet: says so
    await appsettings.put("money", {"salary": 10_000_000, "payday": 25}, "test")
    await pool.execute("INSERT INTO money_tx (at, amount, direction, merchant, category, source) VALUES (now() - interval '2 days', 600000, 'out', 'PLN', 'tagihan', 'manual')")
    calls = []

    async def fake(lane, body, **kw):
        calls.append((lane, modelrouter.NO_FREE.get(), body["messages"][1]["content"]))
        if "kategori pengeluaran" in body["messages"][0]["content"]:
            return reply({"items": [{"id": 2, "kategori": "makan"}, {"id": 99, "kategori": "makan"}]})
        return reply({"ringkasan": "Tagihan dulu, tabung 20%.", "pos": [{"name": "Tagihan", "amount": "1.500.000", "categories": ["tagihan"], "alasan": "PLN, internet"},
                                                                        {"name": "Tabungan", "amount": 2000000, "categories": []}, {"amount": 5}], "hemat": ["Kurangi GoFood"]})
    monkeypatch.setattr(gateway, "complete", fake)
    p = await money.propose()
    assert [x["name"] for x in p["pos"]] == ["Tagihan", "Tabungan"] and p["pos"][0]["amount"] == 1_500_000 and p["lane"] == "berat"
    assert calls[-1][0] == "berat" and calls[-1][1] is True and "Gaji: Rp10.000.000" in calls[-1][2] and "tagihan" in calls[-1][2]
    s = await money.apply_plan(p["id"], [{"name": "Tagihan", "amount": 1_700_000, "categories": ["tagihan"]}], "test")
    assert s["pots"][0]["amount"] == 1_700_000 and s["pots"][0]["spent"] == 600_000
    with pytest.raises(money.MoneyError):
        await money.apply_plan(p["id"], None, "test")                                                     # used once
    await pool.execute("INSERT INTO money_tx (amount, direction, merchant, source) VALUES (35000, 'out', 'Toko Pak Slamet', 'manual')")
    assert (await money.label_unknown()) == {"labeled": 1}                                                # the light brain labels what rules could not
    assert await pool.fetchval("SELECT category || ':' || labeled_by FROM money_tx WHERE id = 2") == "makan:ai"


# ---------- Pluang ----------

def _fake_phone(monkeypatch, pool, jobs):
    from app import phone_agent

    async def request(goal, app, actor, session_id=None, scheduled=False, project=None, by="jadwal"):
        tid = await pool.fetchval("INSERT INTO tasks (session_id, title, instruction, kind, status) VALUES ('phone', $1, $2, 'owner', 'running') RETURNING id", app, goal)
        jobs.append({"app": app, "goal": goal, "scheduled": scheduled, "task_id": tid})
        return {"id": len(jobs), "task_id": tid, "status": "approved"}
    monkeypatch.setattr(phone_agent, "request", request)


async def _finish(pool, task_id, result, ok=True):
    from app import master
    await pool.execute("UPDATE tasks SET status = $2, result = $3 WHERE id = $1", task_id, "completed" if ok else "failed", result)
    await master.on_task_finished(task_id)


@needs_db
async def test_pluang_is_read_analysed_and_his_pick_needs_the_admin_password(pool, monkeypatch):
    from app import appauth, brief, devices, gateway, main, modelrouter
    await pool.execute("TRUNCATE invest_snapshots, invest_proposals, money_tx, flow_runs, tasks, settings_kv RESTART IDENTITY CASCADE")
    jobs = []
    _fake_phone(monkeypatch, pool, jobs)
    monkeypatch.setattr(brief, "_client", lambda: httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"chart": {"result": [
        {"indicators": {"quote": [{"close": [100, 101, 103]}]}}]}}))))
    calls = []

    async def fake(lane, body, **kw):
        calls.append((lane, modelrouter.NO_FREE.get(), body["messages"][1]["content"]))
        return reply({"ringkasan": "Emas naik 3% sebulan.", "kondisi": ["Rupiah melemah"], "opsi": [
            {"judul": "Tambah emas", "aksi": [{"jenis": "beli", "aset": "Emas", "nominal": 1000000}], "alasan": "lindung nilai"},
            {"judul": "Tambah Apple", "aksi": [{"jenis": "beli", "aset": "Apple", "nominal": 500000}], "alasan": "koreksi"}]})
    monkeypatch.setattr(gateway, "complete", fake)

    async def check(pw):
        return 200 if pw == "rahasia-admin" else 401
    monkeypatch.setattr(appauth, "_check", check)
    _, token = await devices.create("HP", "test", scope="owner")
    h = {"Authorization": f"Bearer {token}"}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url="http://t") as c:
        r = (await c.post("/api/v1/app/invest/read", headers=h)).json()
        assert r["status"] == "waiting" and r["lane"] == "hermes" and jobs[0]["app"] == "pluang" and "JANGAN membeli" in jobs[0]["goal"]
        await _finish(pool, jobs[0]["task_id"], 'Selesai. {"total": 12500000, "kas": 500000, "aset": [{"nama": "Emas", "jenis": "emas", "nilai": 7000000, "harga": 1650000}, '
                                                '{"nama": "Apple", "kode": "AAPL", "jenis": "saham_as", "nilai": 5000000}]}')
        st = (await c.get("/api/v1/app/invest", headers=h)).json()
        assert st["snapshot"]["data"]["total"] == 12_500_000 and st["proposal"]["fresh"] and [o["id"] for o in st["proposal"]["data"]["opsi"]] == ["A", "B", "C"]
        assert calls[-1][0] == "berat" and calls[-1][1] is True and "Emas (emas)" in calls[-1][2] and "Pasar:" in calls[-1][2]
        pid = st["proposal"]["id"]
        bad = await c.post(f"/api/v1/app/invest/proposal/{pid}/choose", json={"option": "A", "password": "salah"}, headers=h)
        assert bad.status_code == 422 and bad.json()["detail"] == "Password admin salah" and len(jobs) == 1   # nothing opened
        ok = (await c.post(f"/api/v1/app/invest/proposal/{pid}/choose", json={"option": "A", "password": "rahasia-admin"}, headers=h)).json()
        assert ok["status"] == "waiting" and jobs[1]["app"] == "pluang" and "BELI Emas senilai Rp1.000.000" in jobs[1]["goal"] and "Rp1.650.000" in jobs[1]["goal"]
        assert (await c.post(f"/api/v1/app/invest/proposal/{pid}/choose", json={"option": "B", "password": "rahasia-admin"}, headers=h)).status_code == 409   # once
        await _finish(pool, jobs[1]["task_id"], '{"berhasil": [{"jenis": "beli", "aset": "Emas", "nominal": 1000000, "harga": 1651000}], "batal": []}')
        assert await pool.fetchval("SELECT status FROM invest_proposals WHERE id = $1", pid) == "done"
        assert await pool.fetchval("SELECT amount::int || ':' || category FROM money_tx") == "1000000:investasi"   # recorded in Gaji
        flow = [(x["action"], x["lane"], x["status"]) for x in await pool.fetch("SELECT action, lane, status FROM flow_runs ORDER BY id")]
        assert flow == [("baca", "hermes", "done"), ("analisa", "berat", "done"), ("eksekusi", "hermes", "done")]


@needs_db
async def test_an_old_proposal_must_be_read_again_and_hold_needs_no_phone(pool, monkeypatch):
    from app import invest
    await pool.execute("TRUNCATE invest_snapshots, invest_proposals, flow_runs RESTART IDENTITY CASCADE")
    opts = [{"id": "A", "judul": "Tambah emas", "aksi": [{"jenis": "beli", "aset": "Emas", "nominal": 100}]}, {"id": "B", "judul": "Tahan dulu", "aksi": []}]
    old = await pool.fetchval("INSERT INTO invest_proposals (data, created_at) VALUES ($1, now() - interval '13 hours') RETURNING id", {"opsi": opts})
    with pytest.raises(invest.InvestError, match="baca portofolio lagi"):
        await invest.choose(old, "A", "test")
    new = await pool.fetchval("INSERT INTO invest_proposals (data) VALUES ($1) RETURNING id", {"opsi": opts})
    assert (await invest.choose(new, "B", "test"))["hold"] and await pool.fetchval("SELECT count(*) FROM flow_runs") == 0


# ---------- coffee ----------

@needs_db
async def test_coffee_promos_are_checked_then_offered_then_ordered(pool, monkeypatch):
    from app import coffee, habits, hub
    await pool.execute("TRUNCATE coffee_offers, money_tx, flow_runs, tasks, settings_kv RESTART IDENTITY CASCADE")
    jobs = []
    _fake_phone(monkeypatch, pool, jobs)
    hub.reset()
    seen = []

    async def listen(ev):
        seen.append(ev)
    hub.register(listen)
    assert "coffee.offer" in habits.ACTIONS                                                                 # the 14.30 habit at the office
    r = await coffee._habit({"key": "siang.kopi"})
    assert [j["app"] for j in jobs] == ["kopikenangan", "qpon"] and all("JANGAN" in j["goal"] for j in jobs)
    oid = r["offer"]
    await _finish(pool, jobs[0]["task_id"], '{"promo": [{"menu": "Kopi Kenangan Mantan", "harga": 18000, "harga_normal": 28000, "voucher": "MANTAN18"}]}')
    assert await pool.fetchval("SELECT status FROM coffee_offers WHERE id = $1", oid) == "checking"            # waits for Qpon too
    await _finish(pool, jobs[1]["task_id"], "tidak bisa membuka Qpon", ok=False)
    st = await coffee.state()
    assert st["offer"]["status"] == "offered" and st["offer"]["best"][0]["menu"] == "Kopi Kenangan Mantan"
    ask = [e for e in seen if e.get("type") == "notify"][-1]
    assert ask["title"] == "Mau kopi?" and "Kopi Kenangan Mantan" in ask["text"] and "Rp18 rb" in ask["text"]
    assert (await coffee.check("habit"))["id"] == oid and len(jobs) == 2                                   # a fresh check is reused
    o = await coffee.order(oid, 0, "", "device:HP")
    assert o["status"] == "waiting" and jobs[2]["app"] == "kopikenangan" and "MANTAN18" in jobs[2]["goal"] and "GoPay" in jobs[2]["goal"]
    await _finish(pool, jobs[2]["task_id"], '{"pesanan": "Kopi Kenangan Mantan less sugar", "total": "Rp18.000", "outlet": "Sudirman", "kode": "A12", "siap": "10 menit"}')
    assert await pool.fetchval("SELECT status FROM coffee_offers WHERE id = $1", oid) == "ordered"
    assert await pool.fetchval("SELECT amount::int || ':' || category || ':' || ref FROM money_tx") == f"18000:kopi:coffee:{oid}"
    assert [e["title"] for e in seen if e.get("type") == "notify"][-1] == "Kopi dipesan ☕"
    with pytest.raises(coffee.CoffeeError):
        await coffee.order(oid, 0, "", "device:HP")                                                         # not twice
    hub.reset()


@needs_db
async def test_wave5_screens_get_real_answers(pool, monkeypatch):
    from app import devices, main
    await pool.execute("TRUNCATE money_tx, money_plans, invest_snapshots, invest_proposals, coffee_offers, settings_kv RESTART IDENTITY CASCADE")
    _, token = await devices.create("HP", "test", scope="owner")
    h = {"Authorization": f"Bearer {token}"}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url="http://t") as c:
        m = (await c.get("/api/v1/app/money", headers=h)).json()
        assert m["salary"] == 0 and m["spent"] == 0 and "kopi" in m["categories"]
        assert (await c.post("/api/v1/app/money/plan", headers=h)).status_code == 409
        assert (await c.post("/api/v1/app/money/tx", json={"amount": 50000, "merchant": "Indomaret"}, headers=h)).json()["id"]
        m = (await c.get("/api/v1/app/money", headers=h)).json()
        assert m["recent"][0]["category"] == "belanja" and m["spent"] == 50000
        assert (await c.put(f"/api/v1/app/money/tx/{m['recent'][0]['id']}", json={"category": "bukan"}, headers=h)).status_code == 422
        i = (await c.get("/api/v1/app/invest", headers=h)).json()
        assert i["snapshot"] is None and i["settings"]["limit"] == 2_000_000
        assert (await c.post("/api/v1/app/invest/analyse", headers=h)).status_code == 409
        k = (await c.get("/api/v1/app/coffee", headers=h)).json()
        assert k["offer"] is None and k["settings"]["max_price"] == 75000
        assert (await c.post("/api/v1/app/coffee/1/order", json={"index": 0}, headers=h)).status_code == 409
        assert (await c.get("/api/v1/app/money")).status_code in (401, 403)
