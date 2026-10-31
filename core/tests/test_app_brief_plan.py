"""Owner 2026-10-31: Cek berita "lebih dipertajam … tp tetap mudah dibaca dan AI memposisikan diri menjadi diri saya dan membuatkan plan …
1-3 bulan kedepan yg bisa saya pilih, plan yg saya pilih akan masuk ke list task di menu catatan"."""
import json
import os
from datetime import date

import httpx
import pytest

from tests.test_integration import pool  # noqa: F401  (fixture)

needs_db = pytest.mark.skipif(not os.getenv("TEST_DATABASE_URL"), reason="needs TEST_DATABASE_URL")

PLAN = {"nama": "Amankan dulu, cicil emas", "gaya": "aman", "bulan": 2, "kenapa": "Dengan kondisiku sekarang, aku akan menebalkan dana darurat dulu.",
        "target": "dana darurat 6 bulan", "risiko": "emas turun", "berhenti_jika": "rupiah menguat di bawah 15.500",
        "langkah": [{"minggu": 3, "apa": "Cicil emas 5% gaji", "kaitan": "emas"}, {"minggu": 1, "apa": "Pindahkan sisa gaji ke tabungan terpisah", "kaitan": "tabungan"},
                    {"minggu": 30, "apa": "Tinjau ulang portofolio", "kaitan": "saham_as"}, {"apa": ""}, "bukan langkah"]}


def test_plans_and_scenarios_are_kept_to_their_shape():
    from app import brief
    p = brief.clean_plan(PLAN)
    assert [s["minggu"] for s in p["langkah"]] == [1, 3, 8]                       # in week order, never past the plan's months
    assert p["gaya"] == "aman" and p["bulan"] == 2 and len(p["langkah"]) == 3
    assert brief.clean_plan({"nama": "x", "bulan": 9, "gaya": "nekat", "langkah": [{"apa": "a", "minggu": "dua"}]}) == {
        "nama": "x", "gaya": "seimbang", "bulan": 3, "kenapa": "", "target": "", "risiko": "", "berhenti_jika": "",
        "langkah": [{"minggu": 1, "apa": "a", "kaitan": "lainnya"}]}
    assert brief.clean_plan({"nama": "tanpa langkah", "langkah": []}) is None
    later = brief.clean_plan({"nama": "Tahap dua", "bulan": 3, "kenapa": "Emas di harga terendah setahun (DUNIA 16, TOPIK 7) — momen mencicil.",
                              "langkah": [{"minggu": 5, "apa": "Cicil emas (PASAR 2)"}, {"minggu": 7, "apa": "Tambah emas bila RSI > 40"}]})
    assert [s["minggu"] for s in later["langkah"]] == [1, 3]                                   # a plan of its own starts now, not after another
    assert later["kenapa"] == "Emas di harga terendah setahun — momen mencicil." and later["langkah"][0]["apa"] == "Cicil emas"
    out = brief.clean_analysis({"judul": "J", "situasi": "S", "intinya": ["satu", "", "dua", 3, "tiga", "empat"],
                                "tema": [{"judul": "Minyak", "rantai": ["minyak naik", "inflasi", "", "BI tahan bunga", "cicilan mahal", "x", "y"]}],
                                "skenario": [{"nama": "Rupiah melemah", "kemungkinan": "pasti", "tanda": "DXY > 105"}],
                                "rencana": [PLAN, {"nama": "kosong"}], "evaluasi_rencana": "Lanjutkan."}, {})
    assert out["intinya"] == ["satu", "dua", "tiga"] and out["tema"][0]["rantai"] == ["minyak naik", "inflasi", "BI tahan bunga", "cicilan mahal", "x"]
    assert out["skenario"][0]["kemungkinan"] == "sedang" and len(out["rencana"]) == 1 and out["evaluasi_rencana"] == "Lanjutkan."
    tasks = brief.plan_tasks(out["rencana"][0], date(2026, 11, 2), keep=[0, 2])
    assert tasks == [{"text": "Pindahkan sisa gaji ke tabungan terpisah — rencana “Amankan dulu, cicil emas”", "due": "2026-11-08", "priority": 2},
                     {"text": "Tinjau ulang portofolio — rencana “Amankan dulu, cicil emas”", "due": "2026-12-27", "priority": None}]
    run = {"nama": "A", "gaya": "aman", "bulan": 2, "day": "2026-11-02", "target": "t", "berhenti_jika": "b", "done": 1, "total": 3,
           "next": {"text": "Cicil emas", "due": "2026-11-22"}}
    assert "selesai 1/3" in brief.running_text(run) and "Cicil emas" in brief.running_text(run) and brief.running_text(None) == ""
    msgs = brief.persona_prompt({"judul": "J", "tema": [{"judul": "Minyak", "rantai": ["a", "b"]}]},
                                {"facts": [], "about": ["- keuangan: gaji Rp10 jt/bulan"], "running": run, "holdings": [], "topics": []}, {"markets": []})
    assert "RENCANA BERJALAN" in msgs[1]["content"] and "gaji Rp10 jt" in msgs[1]["content"] and '"rencana"' in msgs[0]["content"]
    assert "PEMILIK sendiri" in msgs[0]["content"] and '"Minyak"' in msgs[1]["content"]


@needs_db
async def test_the_picked_plan_becomes_tasks_and_the_next_analysis_sees_it(pool, monkeypatch):
    from app import brief, devices, gateway, main, notes
    await pool.execute("TRUNCATE briefs, flow_runs, note_pages RESTART IDENTITY CASCADE")
    await pool.execute("DELETE FROM settings_kv WHERE key = 'brief:plan'")
    monkeypatch.setattr(brief, "refresh_soon", lambda: None)   # Hermes plans the next queue in the background: not here
    data = {"judul": "J", "situasi": "S", "tema": [], "rencana": [brief.clean_plan(PLAN), brief.clean_plan({**PLAN, "nama": "Seimbang", "gaya": "seimbang"})]}
    await pool.execute("INSERT INTO briefs (day, data, sources) VALUES (current_date, $1, '{}')", data)
    _, token = await devices.create("HP", "test", scope="owner")
    h = {"Authorization": f"Bearer {token}"}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url="http://t") as c:
        assert (await c.get("/api/v1/app/brief", headers=h)).json()["running"] is None
        r = await c.post("/api/v1/app/brief/plan", json={"index": 0, "keep": [0, 1]}, headers=h)
        assert r.status_code == 200 and r.json()["added"] == 2
        tasks = await notes.tasks("all")
        assert [t["text"].split(" — ")[0] for t in tasks] == ["Pindahkan sisa gaji ke tabungan terpisah", "Cicil emas 5% gaji"]
        assert all(t["link"] == "#/brief" and t["due"] for t in tasks) and tasks[0]["priority"] == 2
        again = await c.post("/api/v1/app/brief/plan", json={"index": 0}, headers=h)
        assert again.status_code == 409 and "sudah kamu pilih" in again.json()["detail"]                 # once
        assert (await c.post("/api/v1/app/brief/plan", json={"index": 2}, headers=h)).status_code in (409, 422)
        saved = (await c.get("/api/v1/app/brief", headers=h)).json()
        assert saved["brief"]["data"]["rencana"][0]["dipilih"] and saved["running"]["done"] == 0 and saved["running"]["total"] == 2
        await notes.set_block(tasks[0]["page_id"], tasks[0]["id"], checked=True)                          # he ticks one in Catatan
        run = (await c.get("/api/v1/app/brief", headers=h)).json()["running"]
        assert run["done"] == 1 and run["next"]["text"].startswith("Cicil emas")
    flow = await pool.fetchrow("SELECT lane, status FROM flow_runs WHERE feature = 'brief' AND action = 'pilih-rencana' ORDER BY id LIMIT 1")
    assert dict(flow) == {"lane": "skill", "status": "done"}                                                # through the master flow, no AI

    async def gather(*a):
        return {"news": {"ekonomi": [{"title": "BI tahan bunga", "summary": "", "source": "Antara", "link": "https://n/1"}]}, "markets": [], "weather": "",
                "about": []}
    monkeypatch.setattr(brief, "gather", gather)
    seen = []

    async def fake(category, body, **kw):
        seen.append(body["messages"][1]["content"])
        if "DATA TENTANG AKU" not in seen[-1]:   # the analyst
            return {"choices": [{"message": {"content": json.dumps({"judul": "Bunga ditahan", "situasi": "Stabil.", "intinya": ["BI menahan bunga"]})}}]}
        return {"choices": [{"message": {"content": json.dumps({"rencana": [PLAN], "evaluasi_rencana": "Lanjutkan, cicil emasnya minggu depan."})}}]}
    monkeypatch.setattr(gateway, "complete", fake)
    d = await brief.compose("owner")
    assert "RENCANA BERJALAN" in seen[1] and "selesai 1/2" in seen[1] and "RENCANA BERJALAN" not in seen[0]
    assert d["evaluasi_rencana"].startswith("Lanjutkan") and d["rencana"][0]["langkah"]
