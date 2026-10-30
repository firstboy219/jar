"""Owner 2026-10-31: hotel choices he can judge (picture, price, rating, reviews, where it is, how to get there from home or the nearest
station) and ask about before picking; a mission page that shows what the web agent is doing, what it waits for and its result; core's
own tasks never sent through the light lane; and YouTube / YouTube Music links made into MP3 by his converter."""
import os

import httpx
import pytest

from tests.test_integration import pool  # noqa: F401  (fixture)

needs_db = pytest.mark.skipif(not os.getenv("TEST_DATABASE_URL"), reason="needs TEST_DATABASE_URL")


def test_options_become_place_cards_with_only_what_the_page_said():
    from app import webagent
    imgs = [{"a": "Lembah Hijau", "s": "https://img.example.com/lh.jpg"}, {"a": "Grand Hill", "s": "https://img.example.com/gh.jpg"}]
    cards = webagent.option_cards([
        {"label": "Lembah Hijau Hotel & Resort", "harga": "Rp 530.000", "rating": "4,4", "ulasan": "2,1 rb ulasan", "alamat": "Cisarua, Bogor",
         "gambar": "g1", "link": "https://www.agoda.com/lembah-hijau", "karangan": "x"},
        {"label": "The Grand Hill", "gambar": "g9", "link": "https://www.bankmandiri.co.id/promo"},
        "Puncak Pass Resort (Rp 620.000)", {"label": ""}], imgs)
    assert cards[0] == {"label": "Lembah Hijau Hotel & Resort", "harga": "Rp 530.000", "rating": "4,4", "ulasan": "2,1 rb ulasan",
                        "alamat": "Cisarua, Bogor", "gambar": "https://img.example.com/lh.jpg", "link": "https://www.agoda.com/lembah-hijau"}
    assert cards[1] == {"label": "The Grand Hill"}                            # no such picture; a bank site is never offered
    assert cards[2] == {"label": "Puncak Pass Resort (Rp 620.000)"} and len(cards) == 3
    assert webagent.maps_link(-6.7, 106.95) == "https://www.google.com/maps/search/?api=1&query=-6.700000,106.950000"
    assert "imgs:imgs" in webagent.STATE_JS


async def test_each_place_gets_its_map_the_drive_from_home_and_the_nearest_station(monkeypatch):
    from app import commute, maps, places, webagent

    async def geocode(q):
        if "Hilang" in q:
            raise maps.MapsError("tidak ditemukan")
        return {"lat": -6.70, "lon": 106.95, "label": q, "address": "Cisarua, Bogor, Jawa Barat"}

    async def listing():
        return [{"name": "rumah", "lat": -6.30, "lon": 106.65}]

    async def leg(a, b, mode="driving"):
        return (95, 62.0) if a["lat"] == -6.30 else (40, 18.0)

    async def station(lat, lon):
        return {"name": "Bogor", "lat": -6.595, "lon": 106.79, "m": 19500}

    async def no_wait(s):
        return None
    monkeypatch.setattr(maps, "geocode", geocode)
    monkeypatch.setattr(places, "listing", listing)
    monkeypatch.setattr(commute, "_leg", leg)
    monkeypatch.setattr(webagent, "_nearest_station", station)
    monkeypatch.setattr(webagent.asyncio, "sleep", no_wait)
    out = await webagent.enrich_places([{"label": "Lembah Hijau", "alamat": "Cisarua"}, {"label": "Hotel Hilang"}], "Cari hotel di Puncak Bogor")
    assert out[0]["peta"].startswith("https://www.google.com/maps/") and out[0]["lokasi"] == "Cisarua, Bogor, Jawa Barat"
    assert out[0]["dari_rumah"] == "±95 mnt naik mobil dari rumah (62 km)"
    assert out[0]["dari_stasiun"] == "Stasiun Bogor (19.5 km) → ±40 mnt naik mobil/ojek"
    assert out[1]["perkiraan"] is True and "dari_stasiun" in out[1]             # the hotel itself not on the map: its area, said to be approximate
    alone = await webagent.enrich_places([{"label": "Hotel Hilang"}], "cari hotel murah")
    assert alone == [{"label": "Hotel Hilang"}]                                 # no area to fall back on: nothing guessed


def test_core_s_own_tasks_are_named_for_who_does_them():
    from app import appapi, workers
    assert workers.core_producer("[WEB-AGEN] #3\ncari hotel") == "web" and workers.core_producer("[OPERASI-HP] #1") == "hp"
    assert workers.core_producer("[DRAF] balas email") == "tulis" and workers.core_producer("cek harga emas") is None
    assert appapi.webstep_text({"op": "klik", "sig": {"l": "Pesan sekarang"}, "commit": True}) == "klik “Pesan sekarang” (ditinjau dulu)"
    assert appapi.webstep_text({"op": "isi", "fields": [1, 2]}) == "isi 2 kolom"


def test_youtube_music_links_and_converter_errors():
    from app import musiclib
    for link in ("https://music.youtube.com/watch?v=dQw4w9WgXcQ&si=x", "https://youtu.be/dQw4w9WgXcQ", "https://www.youtube.com/shorts/dQw4w9WgXcQ"):
        assert musiclib.youtube_link(link) == "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
    assert musiclib.youtube_link("https://example.com/watch?v=dQw4w9WgXcQ") is None and musiclib.youtube_link("lagu tulus") is None
    assert "cek bot" in musiclib.converter_error("error.api.youtube.login")
    assert musiclib.converter_error("error.api.content.too_long") == "videonya terlalu panjang untuk dijadikan MP3"


@needs_db
async def test_a_mission_shows_what_it_waits_for_and_a_pick_can_be_a_question(pool, monkeypatch):
    from app import devices, hub, lanes, main, webagent, workers

    async def quiet(ev):
        return 1
    monkeypatch.setattr(hub, "broadcast", quiet)
    await pool.execute("TRUNCATE web_tasks, web_waits, tasks, owner_questions RESTART IDENTITY CASCADE")

    async def no_lane(**kw):
        raise AssertionError("core's own task asked the lane chooser")
    monkeypatch.setattr(lanes, "pick", no_lane)
    monkeypatch.setattr(workers, "_start", lambda *a, **k: None)
    t = await workers.spawn("Web: cari hotel", f"{webagent.MARK} #1\ncari hotel di Puncak", "web-1", "test", kind="feature")
    row = await pool.fetchrow("SELECT runtime, runtime_note FROM tasks WHERE id = $1", t["id"])
    assert row["runtime"] == "hermes" and "agen web" in row["runtime_note"]
    wid = await pool.fetchval("INSERT INTO web_tasks (goal, start_url, site, task_id, trace) VALUES ('cari hotel di Puncak', 'https://www.google.com/', 'google.com', $1, $2) RETURNING id",
                              t["id"], [{"op": "klik", "sig": {"l": "Hotel"}}])
    cards = [{"label": "Lembah Hijau", "harga": "Rp 530.000", "peta": "https://www.google.com/maps/search/?api=1&query=1,1"}]
    wait = await pool.fetchval("INSERT INTO web_waits (web_task_id, kind, title, detail) VALUES ($1, 'pilih', 'Mana yang dipilih?', $2) RETURNING id",
                               wid, {"options": ["Lembah Hijau"], "cards": cards})
    _, token = await devices.create("HP", "test", scope="owner")
    h = {"Authorization": f"Bearer {token}"}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url="http://t") as c:
        lst = (await c.get("/api/v1/app/missions", headers=h)).json()["missions"]
        assert lst[0]["waiting"] is True
        m = (await c.get(f"/api/v1/app/missions/{t['id']}", headers=h)).json()
        assert m["producer"] == "web" and m["web"]["site"] == "google.com" and m["web"]["steps"] == ["klik “Hotel”"]
        assert m["needs"][0]["kind"] == "web" and m["needs"][0]["cards"] == cards and "instruction" not in m
        r = await c.post(f"/api/v1/app/needs/web/{wait}", json={"text": "lihat ulasan dan foto Lembah Hijau dulu"}, headers=h)
        assert r.status_code == 200
    ans = await pool.fetchval("SELECT answer FROM web_waits WHERE id = $1", wait)
    assert ans == {"text": "lihat ulasan dan foto Lembah Hijau dulu", "free": True}
    with pytest.raises(webagent.WebError):
        await webagent.answer_wait(wait, "owner", option=0)                      # already answered


@needs_db
async def test_a_youtube_link_becomes_an_mp3_through_the_converter(pool, monkeypatch):
    from app import config, devices, hub, main, media_tools, musiclib, musik, playlists

    async def quiet(ev):
        return 1
    monkeypatch.setattr(hub, "broadcast", quiet)
    _, token = await devices.create("HP", "test", scope="owner")
    h = {"Authorization": f"Bearer {token}"}
    monkeypatch.setattr(config.settings, "mp3_converter_url", "")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url="http://t") as c:
        r = await c.post("/api/v1/app/music/convert", json={"url": "https://music.youtube.com/watch?v=dQw4w9WgXcQ"}, headers=h)
        assert r.status_code == 409 and "belum dinyalakan" in r.json()["detail"]
        assert (await c.get("/api/v1/app/music", headers=h)).json()["converter"] is False
        monkeypatch.setattr(config.settings, "mp3_converter_url", "http://jarvis-converter:9000/")
        assert (await c.post("/api/v1/app/music/convert", json={"url": "https://example.com/lagu"}, headers=h)).status_code == 409
        got, kept = [], []

        async def convert_link(link, title, artist):
            got.append(link)
            return {"media_id": "m1", "url": "/api/v1/media/m1", "title": title, "artist": artist, "source_url": link}

        async def show_song(m, source):
            return {"playing": m["title"], "artist": m["artist"], "source": source, "stage_id": "s1"}

        async def add(songs, name=None, source="", actor=""):
            kept.append(songs)
            return {"playlist": "Playlist saya"}
        monkeypatch.setattr(musiclib, "convert_link", convert_link)
        monkeypatch.setattr(media_tools, "_show_song", show_song)
        monkeypatch.setattr(playlists, "add", add)
        r = (await c.post("/api/v1/app/music/convert", json={"url": "https://youtu.be/dQw4w9WgXcQ"}, headers=h)).json()
        assert got == ["https://www.youtube.com/watch?v=dQw4w9WgXcQ"] and r["media_url"] == "/api/v1/media/m1" and r["saved"] and kept
    assert await pool.fetchval("SELECT lane FROM flow_runs WHERE feature = 'musik' AND action = 'konversi' ORDER BY id DESC LIMIT 1") == "skill"
    assert musik


def test_a_screen_the_app_barely_describes_is_read_from_its_picture():
    from app import phone_agent
    assert phone_agent.sparse({"nodes": [{"t": "Beranda"}, {"c": "View"}, {"c": "View"}]})
    assert not phone_agent.sparse({"nodes": [{"t": f"Aset {i}"} for i in range(8)]})


async def test_an_app_that_hides_its_screen_is_given_up_on_with_the_reason(monkeypatch):
    from app import llm, phone_agent, screen_reader
    blank = {"package": "com.EmasDigi", "nodes": [{"i": 0, "c": "View", "k": 1}, {"i": 1, "c": "View", "k": 1}]}
    told = []

    async def op(name, **args):
        told.append(name)
        return {"jpeg": ""} if name == "screenshot" else blank
    monkeypatch.setattr(phone_agent, "op", op)

    async def nothing(img, private=False):
        return ""
    monkeypatch.setattr(screen_reader, "read", nothing)

    async def model(messages, tools=None, **k):
        yield {"type": "done", "completion": llm.Completion(tool_calls=[llm.ToolCall("c", "ketuk", {"nomor": 0})])}
    monkeypatch.setattr(phone_agent.llm, "stream_chat", model)

    async def quiet(*a, **k):
        return None
    with pytest.raises(phone_agent.PhoneError, match="tidak bisa dibaca JARVIS"):
        await phone_agent._loop(1, "pluang", phone_agent.APPS["pluang"], "baca portofolio", quiet, quiet, blank)
    assert told.count("tap") <= 3                                                  # not 45 blind taps
