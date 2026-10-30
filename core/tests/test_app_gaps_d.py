"""ADR-087 wave 9 gap batch D: a meeting on the calendar offers recording at the office, the mosques on the way and the prayers during the
trip, a whole Hijri month, the paint a wall needs, the new file tools (tables to Excel, translate, risky clauses, signing, scanned PDFs read
by the eyes), photo modes (recognise / read / translate / paint), cinemas near the office, closing pages, saving the playing song and
repeating a guide step — all through the master flow."""
import base64
import io
import json
import os
from datetime import datetime, timedelta

import httpx
import pytest

from tests.test_integration import pool  # noqa: F401  (fixture)

needs_db = pytest.mark.skipif(not os.getenv("TEST_DATABASE_URL"), reason="needs TEST_DATABASE_URL")


def reply(content):
    return {"choices": [{"message": {"content": content if isinstance(content, str) else json.dumps(content)}}]}


# ---------- pure ----------

def test_calendar_due_mosques_trip_prayers_paint_and_numbers():
    from app import berkas, habits, ibadah, ukur
    from app.location import WIB
    now = datetime(2026, 10, 30, 9, 56, tzinfo=WIB)
    t = {"type": "calendar", "before": 5}
    assert habits.calendar_due(t, now + timedelta(minutes=4), 7, now, None)
    assert not habits.calendar_due(t, now + timedelta(minutes=9), 7, now, None)                     # too early
    assert not habits.calendar_due(t, now + timedelta(minutes=4), 7, now, 7)                         # offered already
    assert not habits.calendar_due({"type": "time"}, now, 7, now, None)

    hits = [{"name": "Masjid Al-Ikhlas", "display_name": "Masjid Al-Ikhlas, Sudirman", "lat": "-6.2010", "lon": "106.8200"},
            {"name": "Gereja Santo Yosef", "display_name": "Gereja, Sudirman", "lat": "-6.2001", "lon": "106.8201"},
            {"name": "Musholla Stasiun", "display_name": "Musholla Stasiun, Sudirman", "lat": "-6.2002", "lon": "106.8202"}]
    ms = ibadah.mosques_from(hits, -6.2000, 106.8200)
    assert [m["name"] for m in ms] == ["Musholla Stasiun", "Masjid Al-Ikhlas"] and ms[0]["m"] < ms[1]["m"] and "travelmode=walking" in ms[0]["maps"]

    times = {"subuh": "04:30", "dzuhur": "11:50", "ashar": "15:10", "maghrib": "17:55", "isya": "19:05"}
    assert ibadah.during(times, "17:30", "18:40") == ["maghrib"]
    assert ibadah.during(times, "23:30", "04:40") == []                                              # past midnight: subuh is the next day's
    assert ibadah.during(times, "11:00", "15:30") == ["dzuhur", "ashar"]

    p = ukur.paint_estimate(4, 3, 2, 2)
    assert p == {"luas_m2": 10.0, "lapis": 2, "liter": 2.0, "kaleng_5l": 1, "kaleng_2_5l": 1}
    assert ukur.paint_estimate(10, 3)["kaleng_5l"] == 2                                              # 6 litres → two 5 L cans

    assert berkas._num("Rp 1.250.000") == 1250000.0 and berkas._num("12,5") == 12.5 and berkas._num("Jakarta") == "Jakarta"
    assert berkas._num("2026-10-30") == "2026-10-30"


# ---------- file tools ----------

def _table_pdf() -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle
    b = io.BytesIO()
    t = Table([["Produk", "Terjual", "Omzet"], ["Inhaler", "120", "1.200.000"], ["Mouthspray", "80", "960.000"]], colWidths=[150, 80, 120])
    t.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 1, colors.black)]))
    SimpleDocTemplate(b, pagesize=A4).build([t])
    return b.getvalue()


def _blank_pdf(n: int = 1) -> bytes:
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas
    b = io.BytesIO()
    c = canvas.Canvas(b, pagesize=A4)
    for _ in range(n):
        c.rect(72, 72, 100, 100)   # a "scan": no text layer
        c.showPage()
    c.save()
    return b.getvalue()


@needs_db
async def test_the_new_file_tools(pool, monkeypatch, tmp_path):
    from openpyxl import load_workbook
    from PIL import Image
    from app import attachments, berkas, documents, gateway
    monkeypatch.setattr(attachments, "ROOT", tmp_path / "att")
    monkeypatch.setattr(documents, "ROOT", tmp_path / "docs")
    await pool.execute("TRUNCATE file_jobs, flow_runs RESTART IDENTITY CASCADE")
    cats = []

    async def fake(category, body, **kw):
        cats.append(category)
        sysmsg = body["messages"][0]["content"]
        if "Salin SEMUA teks" in sysmsg:
            return reply("PERJANJIAN SEWA\nPenyewa wajib membayar denda 10% per hari.")
        if "penasihat hukum" in sysmsg:
            return reply({"ringkasan": "Perjanjian sewa 1 tahun.", "pihak": ["Pemilik", "Penyewa"],
                          "klausul_berisiko": [{"kutipan": "denda 10% per hari", "risiko": "denda sangat besar", "saran": "minta 0,1%", "tingkat": "tinggi"}],
                          "kewajiban_saya": ["bayar tiap tanggal 5"], "tanggal_penting": ["5 tiap bulan"], "tanya_dulu": ["siapa yang menanggung perbaikan?"]})
        return reply("RENTAL AGREEMENT\nThe tenant must pay a 10% daily fine.")
    monkeypatch.setattr(gateway, "complete", fake)

    async def open_doc(r):
        row, path = await documents.get(r["document"]["id"])
        return row, path.read_bytes()

    t = await attachments.save("Penjualan.pdf", "application/pdf", base64.b64encode(_table_pdf()).decode())
    r = await berkas.run("ke_excel", [t["id"]], {}, "test")
    row, data = await open_doc(r)
    ws = load_workbook(io.BytesIO(data)).worksheets[0]
    vals = [[c.value for c in r] for r in ws.iter_rows()]
    assert vals[0] == ["Produk", "Terjual", "Omzet"] and vals[1] == ["Inhaler", 120, 1200000] and row["format"] == "xlsx"

    scan = await attachments.save("Sewa.pdf", "application/pdf", base64.b64encode(_blank_pdf(2)).decode())
    assert (await berkas.text_of(_blank_pdf(2), "pdf"))[0].startswith("PERJANJIAN SEWA")                # no text layer → the eyes read it
    assert cats[:2] == ["penglihatan", "penglihatan"]
    r = await berkas.run("cek_klausul", [scan["id"]], {}, "test")
    assert r["analysis"]["klausul_berisiko"][0]["tingkat"] == "tinggi" and r["document"]["format"] == "docx"
    r = await berkas.run("terjemah", [scan["id"]], {"lang": "en"}, "test")
    assert "(en)" in r["document"]["title"] and "analysis" not in r

    im = Image.new("RGB", (600, 200), "white")
    for x in range(100, 500):
        im.putpixel((x, 100), (10, 10, 60))
    b = io.BytesIO()
    im.save(b, "JPEG")
    sig = await attachments.save("ttd.jpg", "image/jpeg", base64.b64encode(b.getvalue()).decode())
    doc = await attachments.save("Kontrak.pdf", "application/pdf", base64.b64encode(_table_pdf()).decode())
    with pytest.raises(berkas.FileError):
        await berkas.run("tanda_tangan", [sig["id"], doc["id"]], {}, "test")                         # the PDF first, then the signature
    r = await berkas.run("tanda_tangan", [doc["id"], sig["id"]], {"pages": "x"}, "test")
    _, data = await open_doc(r)
    import fitz
    pdf = fitz.open(stream=data, filetype="pdf")
    assert len(pdf[-1].get_images()) == 1

    ops = [x["action"] for x in await pool.fetch("SELECT action FROM flow_runs WHERE feature = 'berkas' AND status = 'done' ORDER BY id")]
    assert {"ke_excel", "cek_klausul", "terjemah", "tanda_tangan", "ocr", "cek-klausul"} <= set(ops)


# ---------- habits, media, guide, pages ----------

@needs_db
async def test_meeting_offer_photo_modes_music_save_guide_repeat_and_pages(pool, monkeypatch, tmp_path):
    from PIL import Image
    from app import attachments, bimbing, gateway, habits, hub, meetings, playlists, stage, ukur
    from app.location import WIB
    monkeypatch.setattr(attachments, "ROOT", tmp_path / "att")
    await pool.execute("TRUNCATE habits, calendar_events, settings_kv, flow_runs, guide_sessions, playlists, playlist_items RESTART IDENTITY CASCADE")
    await habits.ensure_builtin()
    hub.reset()
    told = []

    async def listen(e):
        told.append(e)
    hub.register(listen)
    now = datetime.now(WIB).replace(microsecond=0)
    await pool.execute("INSERT INTO calendar_events (source, ext_id, title, start_at, end_at) VALUES ('outlook', 'e1', 'Rapat mingguan', $1, $2)",
                       now + timedelta(minutes=4), now + timedelta(minutes=64))
    assert await habits._calendar(now, "rumah") == []                                               # at home: the office habit waits
    assert await habits._calendar(now, "kantor") == ["rapat.rekam"]
    assert meetings._desk["want"]["title"] == "Rapat mingguan" and any(e.get("route") == "#/rapat" for e in told)
    assert await habits._calendar(now, "kantor") == []                                               # once per meeting

    async def fake(category, body, **kw):
        sysmsg = body["messages"][0]["content"]
        if "UKURAN" in sysmsg:
            return reply({"objek": "dinding", "lebar": {"perkiraan": 4, "min": 3.5, "max": 4.5}, "tinggi": {"perkiraan": 3, "min": 2.8, "max": 3.2}, "yakin": "sedang"})
        if sysmsg.startswith("Salin semua teks"):
            return reply("DILARANG PARKIR")
        return reply("Ini tanaman monstera; siram seminggu sekali.")
    monkeypatch.setattr(gateway, "complete", fake)
    b = io.BytesIO()
    Image.new("RGB", (400, 300), "gray").save(b, "JPEG")
    a = await attachments.save("foto.jpg", "image/jpeg", base64.b64encode(b.getvalue()).decode())
    assert (await ukur.look(a["id"], "baca"))["text"] == "DILARANG PARKIR"
    assert "monstera" in (await ukur.look(a["id"], "kenali"))["text"]

    monkeypatch.setattr(stage, "desk_player", lambda: {"id": "s1", "title": "Laskar Pelangi", "artist": "Nidji"})
    from app import devices, main
    _, token = await devices.create("HP", "test", scope="owner")
    h = {"Authorization": f"Bearer {token}"}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url="http://t") as c:
        r = (await c.post("/api/v1/app/measure/photo", json={"attachment_id": a["id"], "mode": "cat"}, headers=h)).json()
        assert r["cat"] == {"luas_m2": 12.0, "lapis": 2, "liter": 2.4, "kaleng_5l": 1, "kaleng_2_5l": 1}
        assert (await c.post("/api/v1/app/measure/paint?width=4&height=3&coats=2&openings=2", headers=h)).json()["liter"] == 2.0
        assert (await c.post("/api/v1/app/measure/paint?width=0&height=3", headers=h)).status_code == 422
        assert (await c.post("/api/v1/app/measure/photo", json={"attachment_id": a["id"], "mode": "terjemah"}, headers=h)).json()["mode"] == "terjemah"

        assert (await c.post("/api/v1/app/music/save", json={}, headers=h)).json()["saved"] == "Laskar Pelangi"
        assert [s["title"] for s in await playlists.items(None)] == ["Laskar Pelangi"]

        g = await bimbing.start("aktifkan notifikasi tagihan")
        assert (await c.post(f"/api/v1/app/guide/{g['id']}/repeat", headers=h)).status_code == 409    # no step yet
        await pool.execute("""UPDATE guide_sessions SET steps = '[{"n": 1, "instruksi": "Ketuk Pengaturan", "target": "Pengaturan", "posisi": "kanan atas"}]' WHERE id = $1""", g["id"])
        told.clear()
        assert (await c.post(f"/api/v1/app/guide/{g['id']}/repeat", headers=h)).json()["instruksi"] == "Ketuk Pengaturan"
        assert any(e.get("type") == "guide" and e.get("instruksi") == "Ketuk Pengaturan" for e in told)

        cards = {"video": {"items": [{"title": "Tutorial cat dinding"}]}}
        monkeypatch.setattr(stage, "desk_cards", lambda: cards)
        ids = [p["id"] for p in (await c.get("/api/v1/app/pages", headers=h)).json()["pages"]]
        assert ids[:2] == ["player", "card:video"]
        assert (await c.post("/api/v1/app/pages/hide", json={"ids": ["card:video"]}, headers=h)).json()["hidden"] == 1
        after = (await c.get("/api/v1/app/pages", headers=h)).json()
        assert "card:video" not in [p["id"] for p in after["pages"]] and after["hidden"] == 1
        cards["video"]["items"][0]["title"] = "Video lain"                                           # something new in the same slot comes back
        assert "card:video" in [p["id"] for p in (await c.get("/api/v1/app/pages", headers=h)).json()["pages"]]

        m = (await c.get("/api/v1/app/ibadah/month?offset=1", headers=h)).json()
        assert 29 <= len(m["days"]) <= 30 and [d["day"] for d in m["days"]] == list(range(1, len(m["days"]) + 1)) and m["title"].endswith("H")
        assert not any(d["today"] for d in m["days"])

    flows = {x["feature"] + ":" + x["action"] for x in await pool.fetch("SELECT feature, action FROM flow_runs")}
    assert {"kebiasaan:meeting.offer", "kamera:baca", "kamera:kenali", "kamera:ukur-foto", "musik:simpan", "bimbing:ulangi"} <= flows
    hub.reset()


@needs_db
async def test_cinemas_near_the_office(pool, monkeypatch):
    from app import appsettings, bioskop
    await pool.execute("TRUNCATE settings_kv RESTART IDENTITY CASCADE")
    await appsettings.put("cinema", {"city": "Kota Bogor", "office_city": "Jakarta Selatan"}, "owner")
    assert await bioskop._city("") == "bogor" and await bioskop._city("kantor") == "jakarta"
    await appsettings.put("cinema", {"office_city": ""}, "owner")
    assert await bioskop._city("kantor") == "bogor"                                                  # no office city: home's
