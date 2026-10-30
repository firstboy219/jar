"""ADR-087 batch H (owner 2026-10-30: "bikin Jarvis eksekusi dari visit langsung ke webnya jadi tidak via API"): pages read directly — by
the phone for sites that refuse the server (a WebView nobody sees), by the server's browser otherwise — a visit that follows links until
the answer, cinema schedules for other days from the chains' own sites, booking up to sign-in/payment in the phone's browser, KCI's own
disruption notes during a trip, and business numbers read off a web dashboard the owner signed into once on his phone."""
import asyncio
import json
import os
from datetime import date

import pytest

from tests.test_integration import pool  # noqa: F401  (fixture)

needs_db = pytest.mark.skipif(not os.getenv("TEST_DATABASE_URL"), reason="needs TEST_DATABASE_URL")


def reply(content):
    return {"choices": [{"message": {"content": content if isinstance(content, str) else json.dumps(content)}}]}


# ---------- pure ----------

def test_site_rules_links_chains_notices_and_pay_guard():
    from app import bioskop, bisnis, commute, needs, phone_agent, webvisit
    assert webvisit.allowed("https://m.21cineplex.com/x", ["21cineplex.com"]) and not webvisit.allowed("http://21cineplex.com", ["21cineplex.com"])
    assert not webvisit.allowed("https://evil21cineplex.com/", ["21cineplex.com"]) and webvisit.allowed("https://www.cgv.id/a", ["www.cgv.id"])
    assert webvisit.phone_first("https://www.kci.id/") and not webvisit.phone_first("https://jadwalnonton.com/")
    assert webvisit.challenged({"title": "Just a moment...", "text": ""}) and not webvisit.challenged({"title": "CINEMA 21", "text": "Jadwal"})
    page = {"url": "https://21cineplex.com/", "links": [{"t": "Jadwal", "h": "https://21cineplex.com/jadwal"}, {"t": "", "h": "https://21cineplex.com/x"},
                                                       {"t": "Iklan", "h": "https://ads.example/"}, {"t": "Jadwal lagi", "h": "https://21cineplex.com/jadwal"}]}
    assert webvisit.links_for(page, ["21cineplex.com"]) == [{"n": 1, "t": "Jadwal", "h": "https://21cineplex.com/jadwal"}]

    a = phone_agent.APPS["web"]
    assert phone_agent.start_url("Di situs cgv.id (https://www.cgv.id/), pesan 2 tiket", a) == "https://www.cgv.id/"
    assert phone_agent.start_url("buka https://bank.example/ dulu", a) == a["home"]
    obs = {"package": "com.android.chrome", "nodes": [{"i": 0, "t": "Bayar Sekarang", "k": 1}, {"i": 1, "t": "Pilih kursi", "k": 1}]}
    assert "pembayaran" in phone_agent.check_action("ketuk", {"nomor": 0}, obs, "web") and phone_agent.check_action("ketuk", {"nomor": 1}, obs, "web") is None
    assert needs.rules_of("web")[0].startswith("Hanya situs 21cineplex.com")

    assert bioskop.chain_of("CGV Grand Indonesia") == "cgv" and bioskop.chain_of("Cinépolis Lippo") == "cinepolis" and bioskop.chain_of("AEON MALL XXI") == "xxi"
    cins = bioskop.to_cinemas({"films": [{"judul": "Agak Laen 2", "bioskop": "Bogor XXI", "jam": ["13:00", "15.30", "nanti"], "harga": "Rp40.000", "jenis": "2D"},
                                         {"judul": "Tanpa jam", "bioskop": "Bogor XXI", "jam": []}]})
    assert cins == [{"name": "Bogor XXI", "films": [{"title": "Agak Laen 2", "rating": "", "today": True, "shows": [{"type": "2D", "price": 40000, "times": ["13:00", "15:30"]}]}]}]

    text = ("Selamat datang di KCI. Perjalanan KRL lintas Bogor mengalami gangguan persinyalan di Manggarai, perjalanan tertahan 15 menit. "
            "Promo kartu baru. Antrean di Stasiun Sudirman padat, gunakan pintu barat.")
    n = commute.kci_notices(text, ["Bogor", "Sudirman"])
    assert len(n) == 2 and "gangguan persinyalan" in n[0] and commute.kci_notices("Promo kartu baru hari ini sampai akhir bulan.", []) == []

    ep = bisnis.clean_endpoint({"metric": "penjualan", "path": "https://seller.contoh.id/dashboard", "mode": "web", "hint": "total penjualan hari ini", "agg": "value"})
    assert ep["mode"] == "web" and ep["hint"] == "total penjualan hari ini"


# ---------- reading and visiting ----------

@needs_db
async def test_reads_go_to_the_phone_or_the_server_and_a_visit_follows_links(pool, monkeypatch):
    from app import gateway, phone_agent, webvisit
    await pool.execute("TRUNCATE flow_runs RESTART IDENTITY CASCADE")
    calls = []

    async def op(name, **kw):
        calls.append(("hp", name, kw.get("url"), kw.get("domains")))
        u = kw["url"]
        if "kci" in u:
            return {"url": u, "title": "Just a moment...", "text": "", "links": [], "challenged": True}
        if u.endswith("/jadwal"):
            return {"url": u, "title": "Jadwal", "text": "Bogor XXI: Agak Laen 2 13:00 15:30 Rp40.000", "links": [], "challenged": False}
        return {"url": u, "title": "CINEMA 21", "text": "Beranda 21", "links": [{"t": "Promo", "h": "https://21cineplex.com/promo"}, {"t": "Jadwal film", "h": "https://21cineplex.com/jadwal"}]}

    async def server(url, wait_s=12):
        calls.append(("server", url))
        if "blocked" in url:
            return {"title": "Access Restricted", "text": "We were unable to process your request", "links": []}
        return {"url": url, "title": "Cinépolis", "text": "Jadwal Cinépolis", "links": []}
    monkeypatch.setattr(phone_agent, "op", op)
    monkeypatch.setattr(webvisit, "_server_read", server)

    p = await webvisit.read("https://21cineplex.com/", ["21cineplex.com"])
    assert p["by"] == "hp" and calls[-1] == ("hp", "web_read", "https://21cineplex.com/", ["21cineplex.com"])
    p = await webvisit.read("https://www.cinemas-ok.id/", ["cinemas-ok.id"])
    assert p["by"] == "server"
    p = await webvisit.read("https://blocked.example.id/", ["blocked.example.id"])
    assert p["by"] == "hp"                                                                     # a bot wall on the server → the phone
    with pytest.raises(webvisit.WebError):
        await webvisit.read("https://www.kci.id/", ["kci.id"])                                # still walled on the phone: said so
    with pytest.raises(webvisit.WebError):
        await webvisit.read("https://bank.example/", ["21cineplex.com"])                       # not a site of this visit

    steps = iter([{"jawaban": None, "buka": 2, "alasan": "jadwal ada di sana"},
                  {"jawaban": {"films": [{"judul": "Agak Laen 2", "bioskop": "Bogor XXI", "jam": ["13:00", "15:30"], "harga": 40000}]}, "buka": None}])

    async def fake(lane, body, **kw):
        return reply(next(steps))
    monkeypatch.setattr(gateway, "complete", fake)
    r = await webvisit.visit("jadwal besok", "https://21cineplex.com/", ["21cineplex.com"], "{}", feature="bioskop", action="hari-lain")
    assert r["answer"]["films"][0]["judul"] == "Agak Laen 2" and r["pages"] == ["https://21cineplex.com/", "https://21cineplex.com/jadwal"] and r["by"] == "hp"
    assert await pool.fetchval("SELECT count(*) FROM flow_runs WHERE feature = 'bioskop' AND action = 'hari-lain-baca' AND status = 'done'") == 2


# ---------- cinema, KCI, web sources ----------

@needs_db
async def test_cinema_other_day_booking_kci_and_web_dashboard(pool, monkeypatch):
    from app import bioskop, bisnis, commute, gateway, phone_agent, webvisit
    await pool.execute("TRUNCATE cinema_cache, flow_runs, settings_kv, tasks, commute_trips, biz_sources, biz_daily, biz_snapshots RESTART IDENTITY CASCADE")

    async def cins(city):
        return [{"slug": "bogor-xxi", "name": "Bogor XXI", "chain": "XXI", "url": ""}, {"slug": "cgv-btm", "name": "CGV BTM", "chain": "CGV", "url": ""}]

    async def city(where=""):
        return "bogor"
    seen = []

    async def visit(goal, url, domains, schema, **kw):
        seen.append((url, domains[0], goal))
        name = "Bogor XXI" if "21" in url else "CGV BTM"
        return {"answer": {"films": [{"judul": "Film Besok", "bioskop": name, "jam": ["19:00"], "harga": 45000}]}, "pages": [url], "by": "hp"}
    monkeypatch.setattr(bioskop, "cinemas_of", cins)
    monkeypatch.setattr(bioskop, "_city", city)
    monkeypatch.setattr(webvisit, "visit", visit)
    v = await bioskop.day_view(2)
    assert v["loading"] and v["films"] == []
    for _ in range(50):
        if not bioskop._loading:
            break
        await asyncio.sleep(0.1)
    v = await bioskop.day_view(2)
    assert not v.get("loading") and v["films"][0]["title"] == "Film Besok" and {a["cinema"] for a in v["films"][0]["at"]} == {"Bogor XXI", "CGV BTM"}
    assert {s[1] for s in seen} == {"21cineplex.com", "cgv.id"} and all("tanggal" in s[2] and "Bogor" in s[2] for s in seen)

    jobs = []

    async def request(goal, app, actor, session_id=None, scheduled=False, project=None, by="jadwal"):
        t = await pool.fetchval("INSERT INTO tasks (session_id, title, instruction, kind, status) VALUES ('phone', $1, $2, 'owner', 'running') RETURNING id", app, goal)
        jobs.append((app, goal))
        return {"id": len(jobs), "task_id": t, "status": "approved"}
    monkeypatch.setattr(phone_agent, "request", request)
    b = await bioskop.book("Film Besok", "CGV BTM", "2026-11-01", "19:00", 3)
    assert b["site"] == "cgv.id" and jobs[-1][0] == "web" and "3 tiket" in jobs[-1][1] and "BERHENTI" in jobs[-1][1] and "jangan bayar" in jobs[-1][1]

    tid = await pool.fetchval("INSERT INTO commute_trips (direction, status, plan, chosen) VALUES ('out', 'active', $1, $2) RETURNING id",
                              {"from": {"name": "Bogor"}, "to": {"name": "Sudirman"}}, {"leave": "07:00", "dep": "07:15", "arr": "08:10", "arrive": "08:30"})

    async def read(url, domains, phone_sites=None):
        return {"url": "https://www.kci.id/", "title": "KCI", "text": "Perjalanan KRL lintas Bogor tertahan karena gangguan di Manggarai. Promo baru.", "by": "hp"}
    monkeypatch.setattr(webvisit, "read", read)
    assert len(await commute.kci_check(tid)) == 1
    assert await commute.kci_check(tid) == []                                                  # the same note is told once
    assert (await commute.trip_view(tid))["kci"][0]["text"].startswith("Perjalanan KRL lintas Bogor")
    await pool.execute("UPDATE commute_trips SET status = 'done'")
    assert await commute._kci_tick() is None                                                   # no trip: no run

    src = await bisnis.save_source(None, {"business": "Renature", "name": "Seller center", "base_url": "https://seller.contoh.id", "auth": {"type": "web"},
                                          "endpoints": [{"metric": "penjualan", "path": "/dashboard", "mode": "web", "hint": "penjualan hari ini", "agg": "value"},
                                                        {"metric": "pesanan", "path": "/dashboard", "mode": "web", "hint": "pesanan hari ini", "agg": "value"}]}, "test")
    pages = []

    async def read2(url, domains, phone_sites=None):
        pages.append((url, domains, phone_sites))
        return {"url": url, "title": "Dashboard", "text": "Ringkasan hari ini — Penjualan Rp1,25 jt · 18 pesanan · " + "x " * 2000, "by": "hp"}
    monkeypatch.setattr(webvisit, "read", read2)

    async def fake(lane, body, **kw):
        return reply({"angka": {"penjualan": 1250000, "pesanan": 18}})
    monkeypatch.setattr(gateway, "complete", fake)
    row = dict(await pool.fetchrow("SELECT * FROM biz_sources WHERE id = $1", src["id"]))
    r = await bisnis.poll_source(row)
    assert r["values"] == {"penjualan": 1250000, "pesanan": 18} and len(pages) == 1                # one page read once for both numbers
    assert pages[0] == ("https://seller.contoh.id/dashboard", ["seller.contoh.id"], {"seller.contoh.id"})
    assert await pool.fetchval("SELECT value::int FROM biz_daily WHERE metric = 'penjualan'") == 1250000

    async def login_page(url, domains, phone_sites=None):
        return {"url": url, "title": "Masuk", "text": "Masuk ke akun penjual. Email. Kata sandi.", "by": "hp"}
    monkeypatch.setattr(webvisit, "read", login_page)
    t = await bisnis.test_source({}, src["id"])
    assert not t[0]["ok"] and "Masuk di HP" in t[0]["error"]
    assert date.today()
