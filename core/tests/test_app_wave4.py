"""ADR-087 wave 4: the owner's businesses from their own APIs — sources with encrypted keys, numbers read out of any JSON (paths, filters,
sums, per marketplace, pages, months of history), polled by the clock through the master flow as a skill, alerts without AI (behind the
usual for this hour, not packed, a record day, a failing source), trends, the heavy brain's strategy, Hermes' research for opportunities,
and pasted API docs filling the form in."""
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

def test_numbers_are_read_out_of_any_json():
    from app import bisnis
    doc = {"data": {"orders": [
        {"id": 1, "total": "Rp125.000", "status": "paid", "channel": {"name": "Shopee"}, "created_at": "2026-10-29T09:10:00+07:00"},
        {"id": 2, "total": 80000, "status": "cancelled", "channel": {"name": "Shopee"}, "created_at": "2026-10-29T10:00:00+07:00"},
        {"id": 3, "total": "1.250.000", "status": "packed", "channel": {"name": "TikTok"}, "created_at": "2026-10-29T01:00:00Z"},
        {"id": 4, "total": 50000, "status": "paid", "channel": {"name": "Tokopedia"}, "created_at": "2026-10-28T23:00:00+07:00"}],
        "summary": {"payout": "4,5"}}}
    today = date(2026, 10, 29)
    assert bisnis.walk(doc, "data.orders[*].id") == [1, 2, 3, 4] and bisnis.walk(doc, "data.orders.id") == [1, 2, 3, 4]
    assert bisnis.walk(doc, "data.orders[-1].channel.name") == ["Tokopedia"] and bisnis.walk(doc, "nope.x") == []
    ep = {"items": "data.orders", "value": "total", "filter": "status!=cancelled", "agg": "sum", "date": "created_at", "split": "channel.name"}
    out = bisnis.extract(doc, ep, today)
    assert out["value"] == 1_375_000 and out["rows"] == 2 and out["split"] == {"Shopee": 125_000, "TikTok": 1_250_000}   # yesterday's & cancelled left out
    assert bisnis.extract(doc, {"items": "data.orders", "filter": "status=packed,shipped", "agg": "count"}, today)["value"] == 1
    assert bisnis.extract(doc, {"items": "data.summary.payout", "agg": "value"}, today)["value"] == 4.5
    s = bisnis.extract(doc, {"items": "data.orders", "value": "total", "agg": "sum", "mode": "series", "date": "created_at", "split": "channel.name"}, today)
    assert s["series"] == {"2026-10-28": 50_000, "2026-10-29": 1_455_000} and s["split_series"]["Tokopedia"] == {"2026-10-28": 50_000}
    assert [bisnis.to_number(x) for x in ("Rp1.234.000", "1,234.56", "4,5", "12.500", "1.5", "abc", 7)] == [1234000, 1234.56, 4.5, 12500, 1.5, None, 7]
    from app.location import WIB
    ts = int(datetime(2026, 10, 29, 6, 0, tzinfo=WIB).timestamp())
    assert bisnis.day_of(ts) == date(2026, 10, 29) and bisnis.day_of(str(ts * 1000)) == date(2026, 10, 29) and bisnis.day_of("29/10/2026") == date(2026, 10, 29)
    assert bisnis.day_of("2026-10-28T23:30:00Z") == date(2026, 10, 29)                               # UTC late evening = next morning in WIB
    assert bisnis.keep({"total": 10, "paid": True}, "total>5; paid=true") and not bisnis.keep({"total": 3}, "total>5")


def test_date_parameters_trends_and_alerts():
    from app import bisnis
    from app.location import WIB
    now = datetime(2026, 10, 29, 15, 30, tzinfo=WIB)
    got = bisnis.fill({"from": "{from}", "to": "{to}", "d": "{days_ago:7}", "ts": "{from_ts}", "x": ["{today}"], "keep": "{unknown}"}, now, window=3)
    assert got == {"from": "2026-10-27", "to": "2026-10-29", "d": "2026-10-22", "ts": str(int(datetime(2026, 10, 27, tzinfo=WIB).timestamp())), "x": ["2026-10-29"], "keep": "{unknown}"}
    today = date(2026, 10, 29)
    pts = {(today - timedelta(days=i)).isoformat(): (200.0 if i <= 30 else 100.0) for i in range(1, 91)}
    t = bisnis.trend(pts, today)
    assert t["last30"] == 6000 and t["prev30"] == 3000 and t["change30"] == 100.0 and len(t["daily"]) == 90 and t["days_with_data"] == 90
    s = {"behind_pct": 60, "unpacked_after": "14:00"}
    a = bisnis.judge("Renature", now, {"penjualan": 1_000_000, "pesanan": 40, "dikemas": 20}, {"penjualan": [3_000_000, 2_800_000, None], "pesanan": [42, 40]}, 2_500_000, s)
    keys = [x["key"] for x in a]
    assert keys == ["behind:Renature:penjualan:2026-10-29", "unpacked:Renature:2026-10-29"]          # sales behind, orders fine, 20 unpacked
    assert "tertinggal 66%" in a[0]["title"] and "Kamis" in a[0]["text"]
    rec = bisnis.judge("Renature", now.replace(hour=10), {"penjualan": 9_000_000}, {}, 5_000_000, s)
    assert [x["key"] for x in rec] == ["record:Renature:2026-10-29"]                                    # before 11.00: no "behind", but a record
    assert bisnis.rp_short(4_250_000) == "Rp4,2 jt" or bisnis.rp_short(4_250_000) == "Rp4,3 jt"
    assert bisnis.label_of("penjualan@Shopee") == ("Penjualan · Shopee", "rp") and bisnis.label_of("toko_aktif")[1] == "n"


def test_source_addresses_and_endpoints_are_checked():
    from app import bisnis
    for bad in ("http://api.x.id", "https://localhost/x", "https://jarvis-admin/x", "https://10.0.0.5/x", "https://169.254.169.254/latest", "ftp://x.id"):
        with pytest.raises(bisnis.BisnisError):
            bisnis.check_url(bad)
    assert bisnis.check_url("https://api.autotoko.id/") == "https://api.autotoko.id"
    with pytest.raises(bisnis.BisnisError):
        bisnis.clean_endpoint({"metric": "Penjualan Hari Ini", "path": "/x"})
    with pytest.raises(bisnis.BisnisError):
        bisnis.clean_endpoint({"metric": "penjualan", "path": "/x", "agg": "median"})
    e = bisnis.clean_endpoint({"metric": "mrr", "path": "/saas/mrr", "items": "data.mrr", "agg": "value", "unit": "rp", "page": {"x": 1}})
    assert e["unit"] == "rp" and e["page"] is None and e["mode"] == "today" and e["method"] == "GET"


# ---------- a source, polled through the master flow ----------

def _fake_api(calls):
    from app.location import WIB
    today = datetime.now(WIB).date()

    def handler(req: httpx.Request):
        calls.append((req.url.path, dict(req.url.params), req.headers.get("x-api-key")))
        if req.headers.get("x-api-key") != "sk-live-RAHASIA-9f3a":
            return httpx.Response(401, json={"error": "unauthorized"})
        if req.url.path == "/v1/orders":
            return httpx.Response(200, json={"data": {"orders": [
                {"total": 450000, "status": "paid", "marketplace": "Shopee", "created_at": f"{today}T08:00:00+07:00"},
                {"total": 300000, "status": "packed", "marketplace": "TikTok", "created_at": f"{today}T09:00:00+07:00"},
                {"total": 99000, "status": "cancelled", "marketplace": "Shopee", "created_at": f"{today}T09:30:00+07:00"}]}})
        if req.url.path == "/v1/payouts/today":
            return httpx.Response(200, json={"result": {"amount": "Rp2.150.000"}})
        if req.url.path == "/v1/reports/daily":   # 120 days of history, 50 per page
            page = int(req.url.params.get("page", "1"))
            days = [today - timedelta(days=i) for i in range(1, 121)]
            chunk = days[(page - 1) * 50: page * 50]
            return httpx.Response(200, json={"rows": [{"date": d.isoformat(), "sales": 1_000_000 + (d.toordinal() % 7) * 100_000} for d in chunk]})
        return httpx.Response(404)
    return handler


SOURCE = {"business": "Renature", "name": "Renature Store API", "base_url": "https://api.renature.id", "auth": {"type": "header", "name": "X-API-Key"},
          "key": "sk-live-RAHASIA-9f3a", "poll_min": 15, "endpoints": [
              {"metric": "penjualan", "path": "/v1/orders", "params": {"date": "{today}"}, "items": "data.orders", "value": "total", "filter": "status!=cancelled",
               "agg": "sum", "date": "created_at", "split": "marketplace"},
              {"metric": "pesanan", "path": "/v1/orders", "params": {"date": "{today}"}, "items": "data.orders", "filter": "status!=cancelled", "agg": "count"},
              {"metric": "dikemas", "path": "/v1/orders", "params": {"date": "{today}"}, "items": "data.orders", "filter": "status=packed,shipped", "agg": "count"},
              {"metric": "pencairan", "path": "/v1/payouts/today", "items": "result.amount", "agg": "value"},
              {"metric": "penjualan", "path": "/v1/reports/daily", "params": {"from": "{from}", "to": "{to}"}, "items": "rows", "value": "sales", "agg": "sum",
               "mode": "series", "date": "date", "page": {"param": "page", "start": 1, "max": 5, "size": 50}}]}


@needs_db
async def test_a_source_keeps_its_key_secret_and_is_polled_as_a_skill(pool, monkeypatch):
    from app import bisnis, hub
    monkeypatch.setenv("VAULT_KEY", "33" * 32)
    await pool.execute("TRUNCATE biz_sources, biz_snapshots, biz_daily, biz_insights, flow_runs, settings_kv RESTART IDENTITY CASCADE")
    calls = []
    monkeypatch.setattr(bisnis, "_client", lambda timeout=20: httpx.AsyncClient(transport=httpx.MockTransport(_fake_api(calls))))
    hub.reset()
    seen = []

    async def listen(ev):
        seen.append(ev)
    hub.register(listen)
    src = await bisnis.save_source(None, SOURCE, "test")
    raw = await pool.fetchrow("SELECT * FROM biz_sources WHERE id = $1", src["id"])
    assert b"RAHASIA" not in bytes(raw["secret"]) and "RAHASIA" not in json.dumps(src, default=str) and src["key_hint"] == "••••9f3a"   # encrypted, never shown

    assert await bisnis.tick() == [src["id"]]                                                        # due: the first poll fills 120 days of history
    run = await pool.fetchrow("SELECT feature, action, lane, status FROM flow_runs ORDER BY id LIMIT 1")
    assert dict(run) == {"feature": "bisnis", "action": "riwayat", "lane": "skill", "status": "done"}  # router → Hermes → skill, no AI
    hist = [c for c in calls if c[0] == "/v1/reports/daily"]
    assert [c[1]["page"] for c in hist] == ["1", "2", "3"] and hist[0][1]["from"] < hist[0][1]["to"]   # pages until a short one
    assert await pool.fetchval("SELECT count(*) FROM biz_daily WHERE metric = 'penjualan' AND business = 'Renature'") >= 120
    assert await bisnis.tick() == []                                                                 # not due again before 15 minutes
    await pool.execute("UPDATE biz_sources SET last_poll = now() - interval '20 minutes'")
    assert await bisnis.tick() == [src["id"]]
    assert await pool.fetchval("SELECT action FROM flow_runs ORDER BY id DESC LIMIT 1") == "sinkron"
    v = (await bisnis.today_view())["businesses"][0]
    k = {x["metric"]: x for x in v["kpis"]}
    assert k["penjualan"]["value"] == 750_000 and k["pesanan"]["value"] == 2 and k["dikemas"]["value"] == 1 and k["pencairan"]["value"] == 2_150_000
    assert v["packed"] == {"done": 1, "total": 2, "pct": 50} and [c["name"] for c in v["channels"]] == ["Shopee", "TikTok"]
    assert any(e.get("type") == "bisnis" and e["business"] == "Renature" for e in seen)              # the screen re-reads
    t = (await bisnis.history("Renature", "penjualan", 120))["trend"]
    assert t["last30"] > 0 and t["best_weekday"] is not None
    test = await bisnis.test_source({}, src["id"])
    assert all(x["ok"] for x in test) and test[0]["value"] == 750_000 and '"orders"' in test[0]["sample"]

    await pool.execute("UPDATE biz_sources SET last_poll = now() - interval '1 hour'")
    calls.clear()
    from app import vault
    await pool.execute("UPDATE biz_sources SET secret = $1", vault.encrypt("salah"))
    for _ in range(3):                                                                               # a failing source: kept, counted, told once
        await pool.execute("UPDATE biz_sources SET last_poll = now() - interval '1 hour'")
        await bisnis.tick()
    row = await pool.fetchrow("SELECT fails, last_error FROM biz_sources")
    assert row["fails"] == 3 and "HTTP 401" in row["last_error"]
    assert await pool.fetchval("SELECT count(*) FROM biz_insights WHERE kind = 'alert' AND key LIKE 'fail:%'") == 1
    assert await pool.fetchval("SELECT count(*) FROM flow_runs WHERE action = 'sinkron' AND status = 'failed'") == 3
    hub.reset()


@needs_db
async def test_alerts_compare_with_this_hour_of_the_same_weekday_once_a_day(pool, monkeypatch):
    from app import bisnis
    from app.location import WIB
    await pool.execute("TRUNCATE biz_sources, biz_snapshots, biz_daily, biz_insights, settings_kv RESTART IDENTITY CASCADE")
    sid = await pool.fetchval("INSERT INTO biz_sources (business, name, base_url, endpoints) VALUES ('Renature', 'x', 'https://a.id', '[]') RETURNING id")
    now = datetime.now(WIB).replace(hour=15, minute=0, second=0, microsecond=0)
    for w in (1, 2, 3):
        await pool.execute("INSERT INTO biz_snapshots (source_id, business, metric, value, at) VALUES ($1, 'Renature', 'penjualan', 3000000, $2)",
                           sid, now - timedelta(days=7 * w, minutes=20))
    for i in range(1, 20):
        await pool.execute("INSERT INTO biz_daily (business, metric, day, value, unit) VALUES ('Renature', 'penjualan', $1, 4000000, 'rp')", now.date() - timedelta(days=i))
    await pool.execute("INSERT INTO biz_daily (business, metric, day, value, unit) VALUES ('Renature', 'penjualan', $1, 900000, 'rp'), ('Renature', 'pesanan', $1, 30, 'n'), ('Renature', 'dikemas', $1, 10, 'n')",
                       now.date())
    a = await bisnis.alerts("Renature", now)
    assert sorted(x["key"].split(":")[0] for x in a) == ["behind", "unpacked"]
    assert await bisnis.alerts("Renature", now) == []                                                # once a day
    await pool.execute("UPDATE biz_daily SET value = 9000000 WHERE metric = 'penjualan' AND day = $1", now.date())
    assert [x["key"].split(":")[0] for x in await bisnis.alerts("Renature", now)] == ["record"]
    await pool.execute("INSERT INTO settings_kv (key, value) VALUES ('app:bisnis', '{\"alerts\": false}')")
    await pool.execute("DELETE FROM biz_insights")
    assert await bisnis.alerts("Renature", now) == []                                                # he can switch them off


@needs_db
async def test_strategy_opportunities_and_autofill_go_through_the_master_flow(pool, monkeypatch):
    from app import bisnis, gateway, master, modelrouter, notes, workers
    await pool.execute("TRUNCATE biz_sources, biz_daily, biz_insights, flow_runs, settings_kv, note_pages RESTART IDENTITY CASCADE")
    today = date.today()
    for i in range(1, 100):
        await pool.execute("INSERT INTO biz_daily (business, metric, day, value, unit) VALUES ('Renature', 'penjualan', $1, $2, 'rp')", today - timedelta(days=i), 1_000_000 + i * 1000)
    await pool.execute("INSERT INTO biz_sources (business, name, base_url, endpoints) VALUES ('Renature', 'x', 'https://a.id', '[]')")
    calls = []

    async def fake(lane, body, **kw):
        calls.append((lane, modelrouter.NO_FREE.get(), body["messages"][-1]["content"]))
        sysmsg = body["messages"][0]["content"]
        if "konsultan" in sysmsg:
            return reply({"ringkasan": "Penjualan turun pelan.", "temuan": ["Sabtu terbaik"], "strategi": [{"judul": "Bundling inhaler + mouth spray", "kenapa": "AOV", "langkah": ["a"], "dampak": "+10%", "usaha": "rendah", "ukur": "AOV"}],
                          "minggu_ini": ["Live TikTok Sabtu"], "risiko": []})
        if "dokumentasi API" in sysmsg:
            return reply({"name": "Autotoko API", "base_url": "https://api.autotoko.id", "auth": {"type": "bearer"}, "endpoints": [
                {"metric": "penjualan", "path": "/v2/orders", "items": "data", "value": "grand_total", "agg": "sum", "date": "created_at"},
                {"metric": "Bukan Valid", "path": "/x"}, {"metric": "mrr", "path": "/v2/billing/mrr", "items": "mrr", "agg": "value", "unit": "rp"}], "catatan": "cek zona waktu"})
        return reply({"peluang": [{"judul": "Aromaterapi roll-on", "skor": 8, "langkah_pertama": "uji 50 pcs", "sumber": ["https://trends.google.com/x", "bukan-url"]}]})
    monkeypatch.setattr(gateway, "complete", fake)
    s = await bisnis.strategy("Renature")
    assert s["strategi"][0]["judul"].startswith("Bundling") and s["lane"] == "berat" and calls[-1][0] == "berat" and calls[-1][1] is True   # heavy, never free
    assert "Penjualan" in calls[-1][2] and "per bulan" in calls[-1][2]
    assert (await bisnis.latest_strategy("Renature"))["id"] == s["id"]
    with pytest.raises(bisnis.BisnisError):
        await bisnis.strategy("Tidak Ada")

    spawned = []

    async def spawn(title, instruction, **kw):
        spawned.append((title, instruction, kw))
        return {"id": 777}
    monkeypatch.setattr(workers, "spawn", spawn)
    r = await bisnis.find_opportunities("owner")
    assert r["status"] == "waiting" and r["lane"] == "hermes" and spawned[0][2]["kind"] == "feature" and "Renature" in spawned[0][1]   # Hermes + tools
    assert (await bisnis.opportunities())["running_task"] == 777
    await bisnis._opportunities_done(r["run_id"], {"ok": True, "text": "Hasil riset: semua bagus, tanpa JSON.", "task_id": 777})   # prose → tidied by the light brain
    o = (await bisnis.opportunities())["batches"][0]
    assert o["peluang"][0]["judul"] == "Aromaterapi roll-on" and o["peluang"][0]["sumber"] == ["https://trends.google.com/x"]
    await bisnis.save_opportunity(o["id"], 0, "test")
    assert any(t["text"].startswith("Coba peluang: Aromaterapi roll-on") for t in await notes.tasks("all"))
    assert (await bisnis.opportunities())["batches"][0]["peluang"][0]["saved"] is True

    g = await bisnis.autofill("Dokumentasi Autotoko API v2. GET /v2/orders returns {data: [{grand_total, created_at}]}. Authorization: Bearer <token>")
    assert g["base_url"] == "https://api.autotoko.id" and g["auth"]["type"] == "bearer" and [e["metric"] for e in g["endpoints"]] == ["penjualan", "mrr"]
    assert all(c[1] for c in calls)                                                                 # business data never reached a free endpoint
    kinds = {(x["action"], x["lane"]) for x in await pool.fetch("SELECT action, lane FROM flow_runs")}
    assert {("strategi", "berat"), ("peluang", "hermes"), ("peluang-rapikan", "ringan"), ("isi-sumber", "ringan")} <= kinds


@needs_db
async def test_wave4_screens_get_real_answers(pool, monkeypatch):
    from app import devices, main
    monkeypatch.setenv("VAULT_KEY", "33" * 32)
    await pool.execute("TRUNCATE biz_sources, biz_daily, biz_insights, flow_runs, settings_kv RESTART IDENTITY CASCADE")
    _, token = await devices.create("HP", "test", scope="owner")
    h = {"Authorization": f"Bearer {token}"}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url="http://t") as c:
        assert (await c.get("/api/v1/app/bisnis", headers=h)).json()["businesses"] == []
        meta = (await c.get("/api/v1/app/bisnis/sources", headers=h)).json()
        assert meta["sources"] == [] and meta["businesses"] == ["Autotoko", "Renature"] and any(m["metric"] == "dikemas" for m in meta["metrics"])
        bad = await c.post("/api/v1/app/bisnis/sources", json={**SOURCE, "base_url": "http://api.renature.id"}, headers=h)
        assert bad.status_code == 409 and "https" in bad.json()["detail"]
        assert (await c.post("/api/v1/app/bisnis/strategy", json={"business": "Renature"}, headers=h)).status_code == 409
        assert (await c.get("/api/v1/app/bisnis/opportunities", headers=h)).json() == {"batches": [], "running_task": None}
        tr = (await c.get("/api/v1/app/bisnis/trend?business=Renature", headers=h)).json()
        assert tr["trend"]["last30"] == 0 and tr["strategy"] is None
        assert (await c.put("/api/v1/app/settings/bisnis", json={"behind_pct": 50}, headers=h)).json()["behind_pct"] == 50
        assert (await c.post("/api/v1/app/bisnis/sources/99/sync", headers=h)).status_code == 404
        assert (await c.get("/api/v1/app/bisnis")).status_code in (401, 403)
