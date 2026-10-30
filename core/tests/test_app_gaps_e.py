"""ADR-087 wave 9 gap batch E: the usual coffee learned from orders; the emergency fund and last period's actual per pot; investing with the
salary's investing pot, one recommended option, a post-trade check of the price guard, and a looser guard only with the admin password;
all businesses together and the shipping cutoff; strategy steps as tasks; deep research and "not for me" for opportunities; the flow's
weak points and lane numbers; the brain's models and its changes only with the admin password; pinned shortcuts and the missing catalog
entries (drafts, results, a changed plan)."""
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

def test_usual_emergency_pots_star_guard_cutoff_weak_points_and_pins():
    from app import alur, appapi, bisnis, coffee, home, invest, money
    from app.location import WIB
    assert coffee.learned_usual(["Kopi Kenangan Mantan", "Americano", "Kopi  Kenangan Mantan"]) == "Kopi Kenangan Mantan"
    assert coffee.learned_usual(["Americano", "Latte"]) == ""                                         # no habit yet

    e = money.emergency_status(15_000_000, 6, 5_000_000)
    assert e == {"saved": 15_000_000, "target": 30_000_000, "months": 6, "pct": 50, "covers_months": 3.0, "monthly": 5_000_000}
    assert money.emergency_status(0, 6, 0)["pct"] == 0
    pots = money.with_last([{"name": "Makan", "categories": ["makan", "kopi"]}, {"name": "Lain", "categories": []}], {"makan": 900_000, "kopi": 100_000})
    assert [p["last"] for p in pots] == [1_000_000, 0]

    p = {"aset": [{"nama": "Emas", "kode": "", "jenis": "emas", "nilai": 7_000_000, "harga": 1_650_000}]}
    opts = invest.clean_options({"opsi": [{"judul": "Tambah emas", "aksi": [{"jenis": "beli", "aset": "Emas", "nominal": 500000}], "disarankan": True},
                                          {"judul": "Jual emas", "aksi": [{"jenis": "jual", "aset": "Emas", "nominal": 500000}], "disarankan": True}]}, p, 2_000_000)
    assert [o["disarankan"] for o in opts] == [True, False, False] and opts[2]["judul"] == "Tahan dulu"   # one recommendation at most
    assert invest.verify_exec({"berhasil": [{"jenis": "beli", "aset": "Emas", "nominal": 500000, "harga": 1_660_000}]}, p, 1.0, 2_000_000) == []
    w = invest.verify_exec({"berhasil": [{"jenis": "beli", "aset": "Emas", "nominal": 2_500_000, "harga": 1_700_000}]}, p, 1.0, 2_000_000)
    assert len(w) == 2 and "bergeser 3.0%" in w[0] and "melebihi batas" in w[1]

    cur = {"limit": 2_000_000, "price_guard_pct": 1.0, "password": True}
    assert appapi.loosens_invest(cur, {"limit": 3_000_000}) and appapi.loosens_invest(cur, {"price_guard_pct": 2}) and appapi.loosens_invest(cur, {"password": False})
    assert not appapi.loosens_invest(cur, {"limit": 1_000_000, "risk": "rendah", "targets": {"emas": 50}})

    s = {"cutoff": "15:00", "cutoff_warn_min": 60, "unpacked_after": "23:59"}
    near = bisnis.judge("Renature", datetime(2026, 10, 30, 14, 20, tzinfo=WIB), {"pesanan": 40, "dikemas": 37}, {}, None, s)
    assert [a["key"] for a in near] == ["cutoff:Renature:2026-10-30"] and "3 pesanan" in near[0]["title"] and "40 menit" in near[0]["text"]
    assert bisnis.judge("Renature", datetime(2026, 10, 30, 13, 30, tzinfo=WIB), {"pesanan": 40, "dikemas": 37}, {}, None, s) == []   # not yet
    assert bisnis.judge("Renature", datetime(2026, 10, 30, 14, 20, tzinfo=WIB), {"pesanan": 40, "dikemas": 40}, {}, None, s) == []   # all packed

    jobs = [{"feature": "kopi", "action": "pesan", "runs": 10, "ok_pct": 50, "no_ai_pct": 0, "ringan": 0, "hermes": 10, "avg_s": 300, "cost": 0.1},
            {"feature": "brief", "action": "compose", "runs": 12, "ok_pct": 100, "no_ai_pct": 0, "ringan": 12, "hermes": 0, "avg_s": 4, "cost": 0.01},
            {"feature": "x", "action": "y", "runs": 2, "ok_pct": 0, "no_ai_pct": 0, "ringan": 2, "hermes": 0, "avg_s": 1, "cost": 0}]
    weak = alur.weak_points(jobs)
    assert [(w["job"], w["kind"]) for w in weak] == [("kopi:pesan", "gagal"), ("brief:compose", "bisa-skill")]   # Hermes' own slowness is not a weak point

    assert home.with_pins(["kopi", "bicara", "kopi", "zzz"], ["inbox", "kopi", "musik"], 3) == ["kopi", "inbox", "musik"]   # native/unknown pins ignored
    assert {"draf", "hasil", "berubah"} <= home.FEATURE_IDS


# ---------- money ----------

@needs_db
async def test_learned_coffee_emergency_fund_and_investing_pot(pool, monkeypatch):
    from app import appauth, appsettings, coffee, devices, gateway, invest, main, money
    from app.location import WIB
    await pool.execute("TRUNCATE coffee_offers, money_tx, money_plans, invest_snapshots, invest_proposals, flow_runs, settings_kv RESTART IDENTITY CASCADE")
    for menu in ("Kopi Kenangan Mantan", "Kopi Kenangan Mantan", "Americano"):
        await pool.execute("INSERT INTO coffee_offers (status, choice) VALUES ('ordered', $1)", {"menu": menu, "app": "kopikenangan"})
    s = await coffee._settings()
    assert s["usual"] == "Kopi Kenangan Mantan" and s["usual_learned"]
    await appsettings.put("coffee", {"usual": "Latte"}, "owner")
    assert (await coffee._settings())["usual"] == "Latte" and not (await coffee._settings())["usual_learned"]   # typed wins

    today = datetime.now(WIB).date()
    await appsettings.put("money", {"salary": 10_000_000, "payday": 25, "emergency_saved": 6_000_000, "emergency_at": today.isoformat(),
                                    "pots": [{"name": "Makan", "amount": 3_000_000, "categories": ["makan"]},
                                             {"name": "Investasi", "amount": 1_000_000, "categories": ["investasi"]}]}, "owner")
    start, _ = money.period_of(today, 25)
    last_day = datetime(start.year, start.month, start.day, 12, tzinfo=WIB) - timedelta(days=2)
    await pool.execute("INSERT INTO money_tx (at, amount, direction, merchant, category, source) VALUES ($1, 2500000, 'out', 'GoFood', 'makan', 'notif')", last_day)
    await pool.execute("INSERT INTO money_tx (at, amount, direction, merchant, category, source) VALUES (now(), 500000, 'out', 'Tabungan', 'tabungan', 'manual')")
    await pool.execute("INSERT INTO money_tx (at, amount, direction, merchant, category, source) VALUES (now(), 300000, 'out', 'Pluang', 'investasi', 'jarvis')")
    sm = await money.summary(today)
    assert sm["emergency"]["saved"] == 6_500_000 and sm["emergency"]["monthly"] == 2_500_000 and sm["emergency"]["target"] == 15_000_000
    assert [p["last"] for p in sm["pots"] if p["name"] == "Makan"] == [2_500_000] and sm["last_period"]["spent"] == 2_500_000
    b = await invest.pot_budget()
    assert b == {"pot": "Investasi", "amount": 1_000_000, "spent": 300_000, "left": 700_000}

    asked = []

    async def fake(lane, body, **kw):
        asked.append(body["messages"][1]["content"])
        if "ALOKASI GAJI" in body["messages"][0]["content"]:
            return reply({"ringkasan": "ok", "pos": [{"name": "Makan", "amount": 3_000_000, "categories": ["makan"]}], "catatan": "Dana darurat dulu."})
        return reply({"ringkasan": "Emas naik.", "opsi": [{"judul": "Tambah emas", "aksi": [{"jenis": "beli", "aset": "Emas", "nominal": 500000}], "disarankan": True}]})
    monkeypatch.setattr(gateway, "complete", fake)

    async def no_market(p):
        return []
    monkeypatch.setattr(invest, "_market", no_market)
    plan = await money.propose()
    assert "Dana darurat: Rp6,5 jt dari target Rp15 jt" in asked[-1] and plan["catatan"] == "Dana darurat dulu."
    sid = await pool.fetchval("INSERT INTO invest_snapshots (data) VALUES ($1) RETURNING id", {"total": 7_000_000, "kas": 0, "aset": [
        {"nama": "Emas", "kode": "", "jenis": "emas", "nilai": 7_000_000, "harga": 1_650_000, "untung_pct": 2}]})
    a = await invest.analyse(sid)
    assert "sisa Rp700 rb" in asked[-1] and a["budget"]["left"] == 700_000 and a["opsi"][0]["disarankan"]
    await pool.execute("UPDATE invest_proposals SET status = 'running', chosen = 'A' WHERE id = $1", a["id"])
    await invest._exec_done(0, {"ok": True, "data": {"proposal": a["id"]}, "text": '{"berhasil": [{"jenis": "beli", "aset": "Emas", "nominal": 500000, "harga": 1720000}]}'})
    res = await pool.fetchval("SELECT result FROM invest_proposals WHERE id = $1", a["id"])
    assert res["peringatan"] and "bergeser" in res["peringatan"][0]

    async def check(pw):
        return 200 if pw == "pw-admin" else 401
    monkeypatch.setattr(appauth, "_check", check)
    _, token = await devices.create("HP", "test", scope="owner")
    h = {"Authorization": f"Bearer {token}"}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url="http://t") as c:
        assert (await c.put("/api/v1/app/settings/invest", json={"limit": 5_000_000}, headers=h)).status_code == 422
        assert (await appsettings.get("invest"))["limit"] == 2_000_000
        assert (await c.put("/api/v1/app/settings/invest", json={"limit": 5_000_000, "admin_password": "pw-admin"}, headers=h)).json()["limit"] == 5_000_000
        assert (await c.put("/api/v1/app/settings/invest", json={"limit": 1_000_000, "targets": {"emas": 60}}, headers=h)).status_code == 200   # tighter: no password
        st = (await c.get("/api/v1/app/invest", headers=h)).json()
        assert st["budget"]["left"] == 200_000 and st["settings"]["targets"] == {"emas": 60}   # the 500 rb bought is spending of the pot


# ---------- business ----------

@needs_db
async def test_strategy_tasks_deep_research_and_not_for_me(pool, monkeypatch):
    from app import bisnis, master, notes, workers
    await pool.execute("TRUNCATE biz_sources, biz_daily, biz_insights, flow_runs, settings_kv, note_pages RESTART IDENTITY CASCADE")
    await pool.execute("INSERT INTO biz_insights (kind, business, data) VALUES ('strategy', 'Renature', $1)",
                       {"ringkasan": "x", "minggu_ini": ["Live TikTok Sabtu", "Bundling inhaler"]})
    t = await bisnis.strategy_tasks("Renature", "test")
    assert [x["task"]["text"] for x in t] == ["Renature: Live TikTok Sabtu", "Renature: Bundling inhaler"]
    assert await bisnis.strategy_tasks("Renature", "test") == []                                     # not twice
    assert {x["link"] for x in await notes.tasks()} == {"#/tren?b=Renature"}
    with pytest.raises(bisnis.BisnisError):
        await bisnis.strategy_tasks("Autotoko", "test")

    bid = await pool.fetchval("INSERT INTO biz_insights (kind, data) VALUES ('opportunity', $1) RETURNING id",
                              {"peluang": [{"judul": "Kedai kopi", "ringkasan": "F&B"}, {"judul": "Aromaterapi roll-on", "ringkasan": "herbal"}]})
    await bisnis.dismiss_opportunity(bid, 0, "tidak suka F&B", "test")
    assert await bisnis._not_for_me() == ["Kedai kopi (tidak suka F&B)"]
    spawned = []

    async def spawn(title, instruction, **kw):
        spawned.append((title, instruction))
        return {"id": 900 + len(spawned)}
    monkeypatch.setattr(workers, "spawn", spawn)
    r = await bisnis.find_opportunities("owner")
    assert "Kedai kopi (tidak suka F&B)" in spawned[-1][1]                                           # the research learns his taste
    d = await bisnis.deep_research(bid, 1)
    assert d["lane"] == "hermes" and "Aromaterapi roll-on" in spawned[-1][1] and "HPP" in spawned[-1][1]
    o = (await bisnis.opportunities())["batches"]
    mine = next(b for b in o if b["id"] == bid)
    assert mine["peluang"][1]["riset"]["status"] == "running"
    run = await pool.fetchval("SELECT id FROM flow_runs WHERE action = 'riset-dalam'")
    await bisnis._deep_done(run, {"ok": True, "data": {"batch": bid, "index": 1},
                                  "text": '{"kesimpulan": "Layak, margin 55%", "hitungan": {"margin": "55%"}, "pesaing": [{"nama": "A", "harga": "Rp25 rb"}]}'})
    got = await pool.fetchval("SELECT data FROM biz_insights WHERE id = $1", bid)
    assert got["peluang"][1]["riset"]["kesimpulan"].startswith("Layak") and got["peluang"][0]["dismissed"]
    assert r["status"] == "waiting" and master  # the weekly research went through the master flow too


# ---------- brain, flow, catalog ----------

@needs_db
async def test_flow_lanes_brain_models_pins_drafts_and_results(pool, monkeypatch):
    from app import alur, appsettings, attention, bengkel, devices, home, main
    await pool.execute("TRUNCATE flow_runs, settings_kv, inbox_items, app_usage, tasks RESTART IDENTITY CASCADE")
    for i in range(4):
        await pool.execute("""INSERT INTO flow_runs (feature, action, goal, lane, status, model, cost_usd, started_at, finished_at) VALUES
            ('kopi', 'pesan', 'pesan kopi', 'hermes', $1, 'openai/gpt-5.1', 0.02, now() - interval '30 minutes', now() - interval '20 minutes')""", "failed" if i < 3 else "done")
    v = await alur.view(48)
    assert v["hours"] == 48 and v["stations"]["hermes"] == {"runs": 4, "failed": 3, "ok_pct": 25, "cost": 0.08, "avg_s": 600.0}
    assert v["weak"][0]["job"] == "kopi:pesan" and v["weak"][0]["kind"] == "gagal"
    m = await bengkel.models()
    assert set(m["lanes"]) == {"ringan", "berat", "penglihatan"} and m["usage"][0]["model"] == "openai/gpt-5.1" and m["usage"][0]["ok_pct"] == 25

    await appsettings.put("home", {"pinned": ["kopi", "bicara"]}, "owner")
    sc = await home.shortcuts(await home.moment())
    assert sc[0]["id"] == "kopi" and sc[0]["pinned"] and "bicara" not in [s["id"] for s in sc] and len(sc) == 7

    await pool.execute("""INSERT INTO inbox_items (source, ext_id, sender, subject, snippet, received_at, triage, draft) VALUES
        ('outlook', 'O1', 'Sari', 'Laporan', 'x', now(), 'needs', '{"body": "Halo Sari, sudah saya cek.", "style": "kamu"}'),
        ('outlook', 'O2', 'Budi', 'Rapat', 'y', now(), 'needs', '{"body": "Siap.", "sent": true}'),
        ('outlook', 'O3', 'Promo', 'Diskon', 'z', now(), 'ignore', NULL)""")
    ds = await attention.drafts()
    assert [(d["sender"], d["sent"]) for d in ds] == [("Sari", False), ("Budi", True)] and ds[0]["preview"].startswith("Halo Sari")
    await pool.execute("INSERT INTO tasks (session_id, title, instruction, kind, status, result) VALUES ('s', 'Riset harga', 'x', 'owner', 'completed', 'Harga rata-rata Rp25 rb'), ('s', 'Jalan', 'y', 'owner', 'running', NULL)")
    _, token = await devices.create("HP", "test", scope="owner")
    h = {"Authorization": f"Bearer {token}"}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url="http://t") as c:
        done = (await c.get("/api/v1/app/missions?done=true", headers=h)).json()["missions"]
        assert [x["title"] for x in done] == ["Riset harga"] and done[0]["preview"] == "Harga rata-rata Rp25 rb"
        assert len((await c.get("/api/v1/app/missions", headers=h)).json()["missions"]) == 2
        assert len((await c.get("/api/v1/app/inbox/drafts", headers=h)).json()["drafts"]) == 2
        assert (await c.get("/api/v1/app/flow?hours=48", headers=h)).json()["weak"]
        feats = {f["id"] for f in (await c.get("/api/v1/app/features", headers=h)).json()["features"]}
        assert {"draf", "hasil", "berubah"} <= feats
    assert date.today()
