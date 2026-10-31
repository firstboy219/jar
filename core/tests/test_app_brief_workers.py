"""Owner 2026-10-31: Cek berita "dengan membagi jadi beberapa worker, seperti untuk pengumpulan dibagi jadi multi worker, lalu setelah data
dikumpulkan siapkan 1 worker untuk menganalisa, lalu setelah 1 worker bertindak menjadi saya mengumpulkan data tentang saya lalu dicompare
dengan data hasil dari cek analisa dari worker sebelumnya"."""
import asyncio
import json
import os

import httpx
import pytest

from tests.test_integration import pool  # noqa: F401  (fixture)

needs_db = pytest.mark.skipif(not os.getenv("TEST_DATABASE_URL"), reason="needs TEST_DATABASE_URL")

ANALYSIS = {"judul": "Rupiah melemah", "situasi": "Dolar kuat.", "suasana": "waspada", "intinya": ["Rupiah Rp18.120"],
            "tema": [{"judul": "Rupiah tertekan", "rantai": ["dolar kuat", "rupiah lemah", "impor mahal"], "alasan": [{"isi": "BI siaga", "nomor": "EKONOMI 1"}]},
                     {"judul": "Emas koreksi", "rantai": ["yield naik", "emas turun"]}]}
PERSONA = {"posisi": {"ringkas": "Dana daruratku tipis, tapi aku punya emas.", "kuat": ["ada emas"], "rentan": ["dana darurat 0,3 bulan"]},
           "dampak": [{"tema": "emas koreksi", "bagiku": "Cicilan emasku lebih murah.", "arah": "untung"},
                      {"tema": "Sesuatu lain", "bagiku": "—", "arah": "rugi"}],
           "rencana": [{"nama": "Benteng dulu", "gaya": "aman", "bulan": 1, "langkah": [{"minggu": 1, "apa": "Bayar tagihan"}]}],
           "ucapan": "Aku tahan dulu."}


def test_the_persona_result_is_laid_over_the_analysis():
    from app import brief
    m = brief.merge(ANALYSIS, PERSONA)
    assert m["tema"][1]["dampak"] == "Cicilan emasku lebih murah." and m["tema"][1]["arah"] == "untung"      # matched by title
    assert m["tema"][0]["dampak"] == "Cicilan emasku lebih murah." or m["tema"][0]["arah"] in ("untung", "rugi")  # else by order
    assert m["posisi"]["rentan"] == ["dana darurat 0,3 bulan"] and m["ucapan"] == "Aku tahan dulu." and m["rencana"][0]["nama"] == "Benteng dulu"
    out = brief.clean_analysis(m, {"ekonomi": [{"title": "BI", "source": "Antara", "link": "https://n/1"}]})
    assert out["posisi"]["kuat"] == ["ada emas"] and out["tema"][1]["arah"] == "untung" and out["tema"][0]["alasan"][0]["link"] == "https://n/1"
    assert brief.merge(ANALYSIS, {})["tema"][0]["dampak"] == "" and brief.clean_analysis(brief.merge(ANALYSIS, {}), {})["posisi"] is None
    text = brief._analysis_text(brief.clean_analysis(ANALYSIS, {}))
    assert "Rupiah tertekan" in text and "nomor" not in text and "http" not in text                          # the next worker reads conclusions


@needs_db
async def test_collectors_then_the_analyst_then_the_worker_that_is_him(pool, monkeypatch):
    from app import brief, devices, gateway, hub, main, memory, signals
    await pool.execute("TRUNCATE briefs, flow_runs RESTART IDENTITY CASCADE")
    monkeypatch.setattr(signals, "REDDIT_PAUSE", 0)
    rss = """<rss><channel><item><title>BI siaga rupiah</title><link>https://n/1</link><pubDate>{d}</pubDate></item></channel></rss>"""
    from datetime import datetime, timezone
    from email.utils import format_datetime
    from tests.test_app_wave1 import FakeClient, FakeResp
    monkeypatch.setattr(brief, "_client", lambda: FakeClient({
        "finance.yahoo.com": FakeResp({"chart": {"result": [{"indicators": {"quote": [{"close": [100 + i for i in range(40)]}]}}]}}),
        "": FakeResp(None, rss.format(d=format_datetime(datetime.now(timezone.utc))))}))

    async def facts(kind, limit=30):
        return [{"text": "Pemilik punya anak satu dan cicilan KPR", "stale": False}]
    monkeypatch.setattr(memory, "list_", facts)

    async def money_ctx():
        return "gaji Rp18 jt/bulan; dana darurat Rp3,4 jt"
    monkeypatch.setitem(brief.CONTEXT, "keuangan", money_ctx)
    prompts, events = [], []

    async def fake(category, body, **kw):
        prompts.append(body["messages"])
        await asyncio.sleep(0)
        res = PERSONA if "DATA TENTANG AKU" in body["messages"][1]["content"] else ANALYSIS
        return {"choices": [{"message": {"content": json.dumps(res)}}]}
    monkeypatch.setattr(gateway, "complete", fake)

    async def tap(ev):
        if ev.get("type") == "brief":
            events.append(ev)
    hub.tap(tap)
    d = await brief.compose("owner")
    analyst, persona = prompts[0], prompts[1]
    assert "ANALIS JARVIS" in analyst[0]["content"] and "BI siaga rupiah" in analyst[1]["content"]
    assert "KPR" not in analyst[1]["content"] and "Rp18 jt" not in analyst[1]["content"]                  # the analyst knows nothing about him
    assert "PEMILIK sendiri" in persona[0]["content"] and "KPR" in persona[1]["content"] and "Rp18 jt" in persona[1]["content"]
    assert "Rupiah tertekan" in persona[1]["content"] and "BI siaga rupiah" not in persona[1]["content"]   # it compares with the analysis
    runs = [r["action"] for r in await pool.fetch("SELECT action FROM flow_runs WHERE feature = 'brief' ORDER BY id")]
    kumpul = [a for a in runs if a.startswith("kumpul-") and a != "kumpul-tentang-aku"]
    assert sorted(kumpul) == sorted(f"kumpul-{k}" for k, _, _ in brief.COLLECTORS)                         # one worker per source
    assert runs.index("analisa") > max(runs.index(a) for a in kumpul) and runs[-2:] == ["kumpul-tentang-aku", "jadi-pemilik"]
    assert d["posisi"]["ringkas"].startswith("Dana daruratku") and d["tema"][1]["arah"] == "untung" and d["rencana"][0]["nama"] == "Benteng dulu"
    stages = [st["stage"] for st in d["pipeline"]]
    assert stages.count("kumpul") == len(brief.COLLECTORS) and stages[-3:] == ["analisa", "jadi-kamu", "jadi-kamu"]
    assert all(st["status"] == "selesai" and st["run_id"] for st in d["pipeline"])
    assert events and events[-1]["running"] is False and any(e["running"] for e in events)                 # followed live

    async def broken(category, body, **kw):   # the worker that is him fails: the analysis still stands, and says so
        if "DATA TENTANG AKU" in body["messages"][1]["content"]:
            raise gateway.GatewayError("upstream 500") if hasattr(gateway, "GatewayError") else RuntimeError("upstream 500")
        return {"choices": [{"message": {"content": json.dumps(ANALYSIS)}}]}
    monkeypatch.setattr(gateway, "complete", broken)
    d2 = await brief.compose("owner")
    assert d2["judul"] == "Rupiah melemah" and d2["rencana"] == [] and d2["persona_error"]

    started = asyncio.Event()

    async def slow(trigger="schedule", reserved=False):
        brief._state.update(running=True)
        started.set()
        await asyncio.sleep(0.2)
        brief._state["running"] = False
        return {}
    monkeypatch.setattr(brief, "compose", slow)
    _, token = await devices.create("HP", "test", scope="owner")
    h = {"Authorization": f"Bearer {token}"}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url="http://t") as c:
        r = await c.post("/api/v1/app/brief/now", headers=h)                                              # answers at once; the workers go on
        assert r.status_code == 200 and r.json()["started"] is True
        await asyncio.wait_for(started.wait(), 2)
        assert (await c.get("/api/v1/app/brief", headers=h)).json()["progress"]["running"] is True
        await asyncio.sleep(0.3)
        assert (await c.get("/api/v1/app/brief", headers=h)).json()["progress"]["running"] is False
