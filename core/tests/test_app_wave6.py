"""ADR-087 wave 6: media & tools — music by mood with the usual mood learned, YouTube understood from its subtitles (the phone fetches them
when YouTube refuses this server), the PDF tools, today's cinema schedule read without AI (Hermes' browser when the page cannot be read),
bedtime stories, measuring from a photo with the brain's eyes or with the phone's AR, and step-by-step screen guidance — all through the
master flow."""
import base64
import io
import json
import os
import zipfile
from pathlib import Path

import httpx
import pytest

from tests.test_integration import pool  # noqa: F401  (fixture)

needs_db = pytest.mark.skipif(not os.getenv("TEST_DATABASE_URL"), reason="needs TEST_DATABASE_URL")
FIX = Path(__file__).parent / "fixtures"


def reply(content):
    return {"choices": [{"message": {"content": content if isinstance(content, str) else json.dumps(content)}}]}


# ---------- pure ----------

def test_the_usual_mood_and_youtube_subtitles():
    from app import musik, video
    plays = [{"mood": "olahraga", "slot": "pagi", "weekday": 0}, {"mood": "olahraga", "slot": "pagi", "weekday": 2}, {"mood": "santai", "slot": "pagi", "weekday": 1},
             {"mood": "fokus", "slot": "kerja", "weekday": 0}]
    moods = ["fokus", "semangat", "olahraga", "santai", "tidur"]
    assert musik.usual_mood(plays, "pagi", 0, moods)[0] == "olahraga"                                       # learned from what he played
    assert musik.usual_mood(plays, "larut", 3, moods) == ("tidur", "belum ada kebiasaan: pilihan untuk jam segini")
    assert musik.usual_mood([{"mood": "olahraga", "slot": "kerja", "weekday": 4}], "kerja", 3, moods)[0] == "fokus"   # once is not a habit yet
    assert video.video_id("https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=30") == "dQw4w9WgXcQ" and video.video_id("https://youtu.be/dQw4w9WgXcQ") == "dQw4w9WgXcQ"
    assert video.video_id("dQw4w9WgXcQ") == "dQw4w9WgXcQ" and video.video_id("bukan video") is None
    tr = video.parse_json3({"events": [{"tStartMs": 0, "segs": [{"utf8": "Halo semua"}]}, {"tStartMs": 61500, "segs": [{"utf8": "harga kopi"}, {"utf8": " naik"}]}, {"tStartMs": 70000}]})
    assert tr == [{"t": 0.0, "text": "Halo semua"}, {"t": 61.5, "text": "harga kopi naik"}]
    vtt = "WEBVTT\n\n00:00:01.000 --> 00:00:03.000\nSelamat <c>pagi</c>\n\n00:00:03.000 --> 00:00:05.000\nSelamat pagi\n\n00:01:05.500 --> 00:01:07.000\nTopik kedua"
    assert video.parse_vtt(vtt) == [{"t": 1.0, "text": "Selamat pagi"}, {"t": 65.5, "text": "Topik kedua"}]           # repeats dropped
    assert video.mmss(3725) == "1:02:05" and video.mmss(65) == "01:05"
    assert video.as_text(tr).startswith("[00:00] Halo semua") and "[01:01] harga kopi naik" in video.as_text(tr)
    assert video.snippets(tr + [{"t": 200, "text": "penutup"}], "berapa harga kopi?", k=1)[0]["t"] == 61.5
    s = video.clean_summary({"ringkasan": "x", "bab": [{"t": "1:30", "judul": "Harga"}, {"t": 9999, "judul": "kelewat"}, {"t": 10, "judul": "Pembuka"}]}, 300)
    assert [b["judul"] for b in s["bab"]] == ["Pembuka", "Harga"] and s["bab"][1]["t"] == 90


def test_pages_cinema_pages_stories_measures_and_guide_steps():
    from app import berkas, bimbing, bioskop, dongeng, ukur
    assert berkas.pages_of("1-3, 5, 8-", 9) == [0, 1, 2, 4, 7, 8] and berkas.pages_of("3-1", 5) == [2, 1, 0] and berkas.pages_of("2,2", 3) == [1]
    with pytest.raises(berkas.FileError):
        berkas.pages_of("abc", 3)
    with pytest.raises(berkas.FileError):
        berkas.pages_of("10-12", 3)
    city = bioskop.parse_city((FIX / "jadwalnonton_city.html").read_text())
    assert [c["chain"] for c in city] == ["XXI", "XXI", "XXI"] and city[1]["name"] == "BOGOR SQUARE XXI" and city[1]["slug"] == "bogor-square-xxi-bogor"
    cin = bioskop.parse_cinema((FIX / "jadwalnonton_cinema.html").read_text())
    assert [f["title"] for f in cin["films"]][1:] == ["Pirunduk", "Warga Rusun 609"] and cin["films"][1]["genre"] == "Horror" and cin["films"][1]["minutes"] == 96
    assert cin["films"][1]["shows"] == [{"type": "REGULAR 2D", "price": 38000, "times": ["12:55"]}] and all(f["today"] for f in cin["films"])
    pre = bioskop.parse_cinema((FIX / "jadwalnonton_presale.html").read_text())
    assert pre["films"][0]["today"] is False and pre["films"][0]["day"] == "Kamis, 05 November 2026"
    films = bioskop.by_film([{"name": "Cinepolis Keboen Raya", **cin}, {"name": "Botani XXI", **pre}], "13:00")
    assert [f["title"] for f in films] == ["Warga Rusun 609"] and films[0]["next"] == "15:40" and films[0]["cheapest"] == 38000   # later shows only; presale apart
    assert bioskop.presale([{"name": "Botani XXI", **pre}])[0]["title"] == "GJLS: BERAPI-API"
    assert bioskop.city_slug("Kota Bogor") == "bogor" and bioskop.city_slug("Jakarta Pusat") == "jakarta" and bioskop.city_slug("") == "jakarta"
    assert dongeng.pick_theme(["hewan", "laut", "angkasa"], ["hewan", "hewan", "laut"]) == "angkasa" and dongeng.pick_theme(["hewan"], [], "naga") == "naga"
    st = dongeng.clean_story({"judul": "Kancil", "paragraf": ["kata " * 110, "", "kata " * 110]})
    assert st["menit"] == 2 and len(st["paragraf"]) == 2
    e = ukur.clean_estimate({"objek": "rumah", "lebar": {"perkiraan": "8,5", "min": 7.5, "max": 9.5}, "tinggi": 6, "panjang": {"perkiraan": -3}, "yakin": "SEDANG"})
    assert e["ukuran"] == {"lebar": {"perkiraan": 8.5, "min": 7.5, "max": 9.5}, "tinggi": {"perkiraan": 6.0, "min": 6.0, "max": 6.0}} and e["yakin"] == "sedang"
    assert bimbing.clean_step({"instruksi": "Ketuk Pengaturan", "status": "aneh"})["status"] == "lanjut"
    assert bimbing.screen_key("Pengaturan  Akun") == bimbing.screen_key("pengaturan akun")


# ---------- PDF tools ----------

def _pdf(pages: list[str]) -> bytes:
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas
    b = io.BytesIO()
    c = canvas.Canvas(b, pagesize=A4)
    for t in pages:
        c.setFont("Helvetica-Bold", 20)
        c.drawString(72, 760, t)
        c.setFont("Helvetica", 11)
        c.drawString(72, 730, f"Isi halaman {t}: laporan penjualan Renature naik 12 persen.")
        c.showPage()
    c.save()
    return b.getvalue()


@needs_db
async def test_the_pdf_tools_make_real_files_through_the_master_flow(pool, monkeypatch, tmp_path):
    from pypdf import PdfReader
    from app import attachments, berkas, documents, gateway
    monkeypatch.setattr(attachments, "ROOT", tmp_path / "att")
    monkeypatch.setattr(documents, "ROOT", tmp_path / "docs")
    await pool.execute("TRUNCATE file_jobs, flow_runs RESTART IDENTITY CASCADE")
    a = await attachments.save("Laporan A.pdf", "application/pdf", base64.b64encode(_pdf(["A1", "A2", "A3"])).decode())
    b = await attachments.save("Laporan B.pdf", "application/pdf", base64.b64encode(_pdf(["B1"])).decode())

    async def open_doc(r):
        row, path = await documents.get(r["document"]["id"])
        return row, path.read_bytes()
    r = await berkas.run("gabung", [a["id"], b["id"]], {}, "test")
    row, data = await open_doc(r)
    assert row["format"] == "pdf" and len(PdfReader(io.BytesIO(data)).pages) == 4 and r["lane"] == "skill"
    r = await berkas.run("pisah", [a["id"]], {"pages": "3,1"}, "test")
    _, data = await open_doc(r)
    assert [p.extract_text().split("\n")[0] for p in PdfReader(io.BytesIO(data)).pages] == ["A3", "A1"]
    r = await berkas.run("kunci", [b["id"]], {"password": "rahasia1"}, "test")
    _, data = await open_doc(r)
    assert PdfReader(io.BytesIO(data)).is_encrypted
    with pytest.raises(berkas.FileError):
        await berkas.run("kunci", [b["id"]], {"password": "x"}, "test")
    r = await berkas.run("ke_gambar", [a["id"]], {}, "test")
    row, data = await open_doc(r)
    assert row["format"] == "zip" and len(zipfile.ZipFile(io.BytesIO(data)).namelist()) == 3
    r = await berkas.run("ke_word", [a["id"]], {}, "test")
    row, data = await open_doc(r)
    from docx import Document
    assert row["format"] == "docx" and "Renature" in "\n".join(p.text for p in Document(io.BytesIO(data)).paragraphs)
    r = await berkas.run("ke_teks", [a["id"]], {}, "test")
    _, data = await open_doc(r)
    assert data.decode().startswith("--- Halaman 1 ---")
    r = await berkas.run("kompres", [a["id"]], {}, "test")
    assert r["after"] <= r["before"]
    from PIL import Image
    im = io.BytesIO()
    Image.new("RGB", (400, 300), "white").save(im, "PNG")
    img = await attachments.save("foto.png", "image/png", base64.b64encode(im.getvalue()).decode())
    r = await berkas.run("gambar_ke_pdf", [img["id"], img["id"]], {}, "test")
    _, data = await open_doc(r)
    assert len(PdfReader(io.BytesIO(data)).pages) == 2
    with pytest.raises(berkas.FileError):
        await berkas.run("gabung", [img["id"]], {}, "test")                                               # a picture is not a PDF
    ops = [x["action"] for x in await pool.fetch("SELECT action FROM flow_runs WHERE feature = 'berkas' AND status = 'done' ORDER BY id")]
    assert ops == ["gabung", "pisah", "kunci", "ke_gambar", "ke_word", "ke_teks", "kompres", "gambar_ke_pdf"]
    assert await pool.fetchval("SELECT count(*) FROM file_jobs") == 8 and "rahasia1" not in json.dumps([dict(x) for x in await pool.fetch("SELECT inputs FROM file_jobs")], default=str)

    async def fake(lane, body, **kw):
        if "Ringkas dokumen" in body["messages"][0]["content"]:
            return reply({"ringkasan": "Penjualan naik 12%.", "poin": ["A1–A3"], "angka_penting": ["12%"], "tindakan": []})
        return reply("Di halaman A2: naik 12 persen.")
    monkeypatch.setattr(gateway, "complete", fake)
    assert (await berkas.summarize(a["id"]))["ringkasan"] == "Penjualan naik 12%."
    assert "12 persen" in (await berkas.ask(a["id"], "berapa kenaikannya?"))["answer"]


# ---------- music, video ----------

@needs_db
async def test_music_plays_by_mood_and_learns_and_video_subtitles_come_from_the_phone(pool, monkeypatch):
    from app import gateway, media_tools, musik, phone_agent, video
    await pool.execute("TRUNCATE media_log, video_notes, flow_runs RESTART IDENTITY CASCADE")
    played = []

    async def play(q, playlist=None):
        played.append(q)
        return {"playing": "Lagu Semangat", "artist": "Band", "stage_id": "s1"}
    monkeypatch.setattr(media_tools, "play", play)
    r = await musik.play("olahraga")
    assert played == ["musik olahraga energik"] and r["lane"] == "skill" and r["mood"] == "olahraga"
    with pytest.raises(musik.MusicError):
        await musik.play("dangdut-koplo-tidak-ada")
    await musik.play("olahraga")
    st = await musik.state()
    assert st["usual"]["mood"] == "olahraga" and st["usual"]["why"].startswith("biasanya") and st["recent"][0]["title"] == "Lagu Semangat — Band"
    from app import habits
    assert "music.mood" in habits.ACTIONS and any(h["key"] == "pagi.musik" for h in habits.BUILTIN)

    def refuse(vid):
        raise RuntimeError("Sign in to confirm you're not a bot")
    monkeypatch.setattr(video, "_server_captions", refuse)
    ops = []

    async def op(name, **args):
        ops.append((name, args))
        return {"json3": json.dumps({"events": [{"tStartMs": 0, "segs": [{"utf8": "Pembukaan resep kopi susu"}]}, {"tStartMs": 95000, "segs": [{"utf8": "takaran gula aren dua sendok"}]}]}),
                "title": "Resep Kopi Susu", "channel": "Dapur", "duration": 300, "lang": "id"}
    monkeypatch.setattr(phone_agent, "op", op)

    async def fake(lane, body, **kw):
        if "Ringkas video" in body["messages"][0]["content"]:
            return reply({"ringkasan": "Cara membuat kopi susu.", "poin": ["gula aren"], "bab": [{"t": 0, "judul": "Pembuka"}, {"t": 95, "judul": "Takaran"}]})
        return reply("Takarannya dua sendok gula aren [01:35].")
    monkeypatch.setattr(gateway, "complete", fake)
    n = await video.summarize("dQw4w9WgXcQ")
    assert ops[0][0] == "yt_captions" and n["source"] == "phone" and n["summary"]["bab"][1] == {"t": 95.0, "judul": "Takaran"}
    a = await video.ask("dQw4w9WgXcQ", "berapa takaran gula?")
    assert "[01:35]" in a["answer"] and a["moments"][0]["t"] in (0.0, 95.0)
    await video.summarize("dQw4w9WgXcQ")
    assert len(ops) == 1                                                                                 # kept: not fetched twice


# ---------- cinema ----------

@needs_db
async def test_the_cinema_schedule_is_read_without_ai_and_hermes_looks_when_it_cannot(pool, monkeypatch):
    from app import bioskop, workers
    await pool.execute("TRUNCATE cinema_cache, flow_runs, settings_kv RESTART IDENTITY CASCADE")
    await pool.execute("""INSERT INTO settings_kv (key, value) VALUES ('app:cinema', '{"city": "Bogor", "cinemas": ["bogor-square-xxi-bogor"], "max": 2}')""")
    hits = []
    pages = {"/bioskop/di-bogor/": (FIX / "jadwalnonton_city.html").read_text(),
             "/bioskop/di-bogor/bogor-square-xxi-bogor.html": (FIX / "jadwalnonton_cinema.html").read_text()}

    def handler(req):
        hits.append(req.url.path)
        return httpx.Response(200, text=pages.get(req.url.path, "<html></html>"))
    monkeypatch.setattr(bioskop, "_client", lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    d = await bioskop.today()
    assert d["city"] == "bogor" and [c["name"] for c in d["cinemas"]] == ["BOGOR SQUARE XXI"] and d["source"] == "jadwalnonton.com"   # his pick only
    assert await pool.fetchval("SELECT feature || ':' || action || ':' || lane FROM flow_runs") == "bioskop:jadwal:skill"
    n = len(hits)
    await bioskop.today()
    assert len(hits) == n                                                                                # one reading per day is kept
    pages["/bioskop/di-bogor/bogor-square-xxi-bogor.html"] = "<html>halaman baru tanpa jadwal</html>"
    spawned = []

    async def spawn(title, instruction, **kw):
        spawned.append(instruction)
        return {"id": await pool.fetchval("INSERT INTO tasks (session_id, title, instruction, kind, status) VALUES ('x', $1, $2, 'feature', 'running') RETURNING id", title, instruction)}
    monkeypatch.setattr(workers, "spawn", spawn)
    w = await bioskop.today(force=True)
    assert w["waiting"] and "jadwalnonton" in spawned[0]                                                 # the page changed: Hermes' browser
    from app import master
    await pool.execute("UPDATE tasks SET status = 'completed', result = $2 WHERE id = $1", w["task_id"],
                       '{"cinemas": [{"name": "Botani XXI", "films": [{"title": "Film Malam", "shows": [{"type": "2D", "price": 45000, "times": ["23:59"]}]}]}]}')
    await master.on_task_finished(w["task_id"])
    d = await bioskop.today()
    assert d["films"][0]["title"] == "Film Malam" and d["source"] == "browser Hermes"


# ---------- stories, measuring, guidance ----------

@needs_db
async def test_stories_photo_measures_ar_and_guidance(pool, monkeypatch):
    from app import attachments, bimbing, dongeng, gateway, habits, hub, ukur
    monkeypatch.setattr(attachments, "ROOT", Path("/tmp") / f"att-{os.getpid()}")
    await pool.execute("TRUNCATE stories, measures, guide_sessions, flow_runs, settings_kv RESTART IDENTITY CASCADE")
    cats = []

    async def fake(category, body, **kw):
        cats.append(category)
        sysmsg = body["messages"][0]["content"]
        if "pendongeng" in sysmsg:
            return reply({"judul": "Kancil dan Bintang", "tokoh": ["Kancil"], "paragraf": ["Suatu malam…", "Kancil tidur."], "pesan": "Berbagi itu indah."})
        if "UKURAN" in sysmsg:
            return reply({"objek": "rumah", "lebar": {"perkiraan": 8, "min": 7, "max": 9}, "tinggi": {"perkiraan": 6, "min": 5.5, "max": 6.5}, "acuan": ["pintu"], "yakin": "sedang"})
        return reply({"instruksi": "Ketuk 'Pengaturan' di kanan atas", "target": "Pengaturan", "posisi": "kanan atas", "status": "lanjut"})
    monkeypatch.setattr(gateway, "complete", fake)
    hub.reset()
    told = []

    async def listen(ev):
        told.append(ev)
    hub.register(listen)
    r = await habits.ACTIONS["story.offer"][1]({"key": "malam.dongeng"})
    s = await dongeng.tonight()
    assert r["story"] == s["id"] and s["title"] == "Kancil dan Bintang" and any(e.get("title") == "Dongeng malam ini siap" for e in told)
    await habits.ACTIONS["story.offer"][1]({"key": "malam.dongeng"})
    assert await pool.fetchval("SELECT count(*) FROM stories") == 1                                     # tonight's story is not written twice

    from PIL import Image
    im = io.BytesIO()
    Image.new("RGB", (800, 600), "gray").save(im, "JPEG")
    a = await attachments.save("rumah.jpg", "image/jpeg", base64.b64encode(im.getvalue()).decode())
    m = await ukur.from_photo(a["id"], "lebar rumah")
    assert m["ukuran"]["lebar"] == {"perkiraan": 8.0, "min": 7.0, "max": 9.0} and cats[-1] == "penglihatan"   # the brain's eyes
    with pytest.raises(ukur.MeasureError):
        await ukur.from_photo("0" * 32, "x")

    g = await bimbing.start("aktifkan notifikasi tagihan")
    s1 = await bimbing.step(g["id"], "Beranda\nRekening\nPengaturan", "BCA mobile")
    assert s1["instruksi"].startswith("Ketuk") and s1["n"] == 1
    assert (await bimbing.step(g["id"], "Beranda  Rekening Pengaturan"))["same_screen"]                   # the screen did not change: no new AI step
    assert any(e.get("type") == "guide" and e.get("mode") == "step" for e in told)
    await bimbing.stop(g["id"])
    with pytest.raises(bimbing.GuideError):
        await bimbing.step(g["id"], "layar lain")
    flows = {x["feature"] + ":" + x["action"] for x in await pool.fetch("SELECT feature, action FROM flow_runs")}
    assert {"dongeng:tulis", "kamera:ukur-foto", "bimbing:langkah"} <= flows
    hub.reset()


@needs_db
async def test_wave6_screens_get_real_answers(pool, monkeypatch):
    from app import devices, main
    await pool.execute("TRUNCATE measures, guide_sessions, stories, file_jobs, video_notes, media_log RESTART IDENTITY CASCADE")
    _, token = await devices.create("HP", "test", scope="owner")
    h = {"Authorization": f"Bearer {token}"}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url="http://t") as c:
        m = (await c.get("/api/v1/app/music", headers=h)).json()
        assert "olahraga" in m["moods"] and m["usual"]["mood"] in m["moods"]
        assert (await c.post("/api/v1/app/music/zzz", headers=h)).status_code == 404
        assert (await c.get("/api/v1/app/video", headers=h)).json()["recent"] == []
        assert (await c.get("/api/v1/app/video/bukan-id-video", headers=h)).status_code == 404
        f = (await c.get("/api/v1/app/files", headers=h)).json()
        assert {t["op"] for t in f["tools"]} >= {"gabung", "kompres", "ke_word", "gambar_ke_pdf"} and f["recent"] == []
        assert (await c.post("/api/v1/app/files/run", json={"op": "gabung", "ids": ["0" * 32]}, headers=h)).status_code == 409
        ar = (await c.post("/api/v1/app/measure/ar", json={"label": "Meja", "segments": [1.2, 0.6]}, headers=h)).json()
        assert ar["total"] == 1.8 and (await c.get("/api/v1/app/measure", headers=h)).json()["measures"][0]["label"] == "Meja"
        assert (await c.post("/api/v1/app/measure/ar", json={"segments": [500]}, headers=h)).status_code == 422
        st = (await c.get("/api/v1/app/story", headers=h)).json()
        assert st["tonight"] is None and st["settings"]["child_age"] == 5
        g = (await c.post("/api/v1/app/guide", json={"goal": "cara bayar BPJS"}, headers=h)).json()
        assert (await c.get("/api/v1/app/guide", headers=h)).json()["active"]["id"] == g["id"]
        assert (await c.get("/api/v1/app/music")).status_code in (401, 403)
