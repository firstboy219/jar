"""ADR-087 wave 1: prayer times (Kemenag + the fallback calculation), the Hijri calendar and its events, the qibla, the Qur'an reading
progress, the morning brief (gathering, writing through the master flow, sources linked), the weather, and the app clock."""
import os
from datetime import date, datetime, timedelta

import httpx
import pytest

from tests.test_integration import pool  # noqa: F401  (fixture)

needs_db = pytest.mark.skipif(not os.getenv("TEST_DATABASE_URL"), reason="needs TEST_DATABASE_URL")


def _mins(t: str) -> int:
    return int(t[:2]) * 60 + int(t[3:5])


# ---------- pure ----------

def test_the_fallback_prayer_times_are_within_minutes_of_kemenag():
    from app import ibadah
    kemenag_jkt_oct = {"subuh": "04:10", "terbit": "05:24", "dzuhur": "11:40", "ashar": "14:53", "maghrib": "17:49", "isya": "19:00"}
    got = ibadah.compute_times(date(2026, 10, 29), -6.2088, 106.8456)
    for k, v in kemenag_jkt_oct.items():
        assert abs(_mins(got[k]) - _mins(v)) <= 3, (k, got[k], v)
    # Bogor's Kemenag sunrise/sunset carry its own elevation correction: a nearby Kemenag day of the city, moved by the sun, keeps it
    bogor_oct = {"subuh": "04:10", "terbit": "05:20", "dzuhur": "11:40", "ashar": "14:53", "maghrib": "17:54", "isya": "19:01"}
    bogor_mar = {"subuh": "04:43", "terbit": "05:50", "dzuhur": "12:05", "ashar": "15:13", "maghrib": "18:13", "isya": "19:18"}
    lat, lon = -6.5971, 106.8060
    guess = ibadah.shifted(bogor_oct, ibadah.compute_times(date(2026, 10, 29), lat, lon), ibadah.compute_times(date(2026, 11, 20), lat, lon))
    raw = ibadah.compute_times(date(2026, 11, 20), lat, lon)
    assert _mins(guess["maghrib"]) - _mins(raw["maghrib"]) >= 4      # the city's later maghrib is kept (never break the fast early)
    far = ibadah.shifted(bogor_oct, ibadah.compute_times(date(2026, 10, 29), lat, lon), ibadah.compute_times(date(2027, 3, 15), lat, lon))
    for k, v in bogor_mar.items():
        assert abs(_mins(far[k]) - _mins(v)) <= 3, (k, far[k], v)
    kemenag_jkt = {"subuh": "04:43", "dzuhur": "12:05", "ashar": "15:12", "maghrib": "18:09", "isya": "19:18"}
    got = ibadah.compute_times(date(2027, 3, 15), -6.2088, 106.8456)
    for k, v in kemenag_jkt.items():
        assert abs(_mins(got[k]) - _mins(v)) <= 3, (k, got[k], v)


def test_the_hijri_calendar_and_its_days():
    from app import ibadah
    # Kemenag: 29 Oct 2026 = 17 Jumadil Awal 1448; 8 Feb 2027 = 1 Ramadan 1448 — the tabular calendar is within a day; the offset fixes it
    y, m, d = ibadah.tabular_hijri(date(2026, 10, 29))
    assert (y, m) == (1448, 5) and abs(d - 17) <= 1
    off = next(o for o in (-2, -1, 0, 1, 2) if ibadah.tabular_hijri(date(2026, 10, 29) + timedelta(days=o)) == (1448, 5, 17))
    assert ibadah.hijri_of(date(2027, 2, 8), off)[1:] in ((9, 1), (8, 30))
    assert ibadah.hijri_text((1448, 5, 17)) == "17 Jumadil Awal 1448 H"
    kinds = lambda d, h: {e["title"] for e in ibadah.events_for(d, h)}   # noqa: E731
    assert "Puasa Kamis" in kinds(date(2026, 10, 29), (1448, 5, 17))
    assert "Hari bekam sunnah" in kinds(date(2026, 10, 30), (1448, 5, 19))
    assert "Puasa Ayyamul Bidh" in kinds(date(2026, 11, 23), (1448, 6, 13))
    assert "Puasa Arafah" in kinds(date(2027, 5, 15), (1448, 12, 9))
    assert "Iduladha" in kinds(date(2027, 5, 16), (1448, 12, 10)) and "Puasa Senin" not in kinds(date(2027, 5, 17), (1448, 12, 11))
    assert "Puasa Kamis" not in kinds(date(2027, 2, 11), (1448, 9, 4))                     # Ramadan, not a weekly sunnah fast
    assert 290 < ibadah.qibla(-6.5971, 106.8060) < 300                                   # Bogor faces ~295°
    nxt = ibadah.next_prayer({"subuh": "04:10", "dzuhur": "11:40", "ashar": "14:53", "maghrib": "17:54", "isya": "19:01"},
                             datetime(2026, 10, 29, 13, 38))
    assert nxt == {"name": "ashar", "label": "Ashar", "time": "14:53", "in_min": 75}
    assert ibadah.city_words("Jl. Pajajaran No. 1, Kota Bogor, Jawa Barat")[0] == "Bogor"
    assert ibadah.city_words("Jl. Sudirman, Jakarta Pusat, DKI Jakarta")[0] == "Jakarta"


def test_quran_positions_and_streaks():
    from app import quran
    assert quran.juz_of(18, 45) == 15 and quran.juz_of(18, 75) == 16 and quran.juz_of(1, 1) == 1 and quran.juz_of(114, 6) == 30
    counts = [7, 286] + [100] * 112
    assert quran.position(2, 10, counts) == 17
    today = date(2026, 10, 29)
    assert quran.streak([today - timedelta(days=i) for i in range(6)], today) == 6
    assert quran.streak([today - timedelta(days=i) for i in range(1, 4)], today) == 3       # not yet today: counted to yesterday
    assert quran.streak([today - timedelta(days=3)], today) == 0
    assert quran.per_day_pages(3100, date(2026, 11, 30), today) == pytest.approx(9.5, abs=0.3)


def test_the_brief_parses_feeds_and_links_its_sources():
    from app import brief
    from datetime import timezone
    now = datetime(2026, 10, 29, 0, 0, tzinfo=timezone.utc)
    xml = """<rss><channel>
      <item><title>BI tahan suku bunga</title><description>&lt;p&gt;Rapat dewan&lt;/p&gt;</description><link>https://a/1</link><pubDate>Wed, 28 Oct 2026 10:00:00 +0700</pubDate></item>
      <item><title>Berita lama</title><link>https://a/2</link><pubDate>Mon, 20 Oct 2026 10:00:00 +0700</pubDate></item>
      <item><title>Tanpa tanggal</title><link>https://a/3</link></item></channel></rss>"""
    items = brief.parse_feed(xml, "Antara", now)
    assert [i["title"] for i in items] == ["BI tahan suku bunga", "Tanpa tanggal"] and items[0]["summary"] == "Rapat dewan"
    assert brief.parse_feed("bukan xml", "x", now) == []
    assert brief.change_pct([100, None, 101.5]) == 1.5 and brief.change_pct([None]) is None
    news = {"indonesia": items, "dunia": [{"title": "Minyak naik", "source": "BBC", "link": "https://b/1"}]}
    out = brief.clean_analysis({"judul": "Suku bunga ditahan", "situasi": "Stabil.", "suasana": "aneh",
                                "tema": [{"judul": "Suku bunga", "kesimpulan": "BI menahan", "indikator": [{"nama": "BI rate", "nilai": "6%"}],
                                          "alasan": [{"isi": "BI tahan suku bunga", "nomor": "INDONESIA 1"}, "Minyak naik 4%", {"isi": "x", "nomor": "INDONESIA 9"}]}],
                                "peluang": [{"aksi": "Tambah emas sedikit", "kaitan": "emas", "yakin": "pasti", "horizon": "besok"}, {"kenapa": "tanpa aksi"}],
                                "waspada": [{"isi": "Minyak naik", "nomor": "DUNIA 1"}], "ucapan": "Pagi."}, news)
    assert out["suasana"] == "campuran" and out["tema"][0]["alasan"][0]["link"] == "https://a/1" and out["tema"][0]["alasan"][0]["sumber"] == "Antara"
    assert out["tema"][0]["alasan"][1] == {"isi": "Minyak naik 4%", "sumber": "", "link": ""} and out["tema"][0]["alasan"][2]["link"] == ""
    assert out["peluang"] == [{"aksi": "Tambah emas sedikit", "kenapa": "", "risiko": "", "kaitan": "emas", "horizon": "minggu ini", "yakin": "sedang"}]
    assert out["waspada"][0]["link"] == "https://b/1" and out["ucapan"] == "Pagi."


def test_weather_rain_window_and_clock():
    from app import appclock, weather
    hours = [f"2026-10-29T{h:02d}:00" for h in range(24)]
    probs = [0] * 7 + [45] + [10] * 16
    assert weather.rain_window(hours, probs, datetime(2026, 10, 29, 6, 30)) == ("07", 45)
    assert weather.rain_window(hours, probs, datetime(2026, 10, 29, 9, 0)) is None
    assert weather.describe(63) == "hujan" and weather.describe(None) == "cerah"
    assert appclock.hhmm_due("05:45", datetime(2026, 10, 29, 5, 45)) and not appclock.hhmm_due("05:45", datetime(2026, 10, 29, 5, 44))
    assert not appclock.hhmm_due("bukan", datetime(2026, 10, 29, 5, 44))


# ---------- with the database ----------

class FakeResp:
    def __init__(self, data=None, text="", status=200):
        self._d, self.text, self.status_code = data, text, status

    def json(self):
        return self._d

    def raise_for_status(self):
        pass


class FakeClient:
    def __init__(self, routes):
        self.routes = routes

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def get(self, url, params=None):
        for key, val in self.routes.items():
            if key in url:
                return val(url) if callable(val) else val
        return FakeResp({}, "", 404)


@needs_db
async def test_prayer_times_reminders_and_the_hijri_offset(pool, monkeypatch):
    from app import hub, ibadah
    await pool.execute("TRUNCATE prayer_days, flow_runs RESTART IDENTITY")
    month = {"data": {"jadwal": [{"date": "2026-10-29", "imsak": "04:00", "subuh": "04:10", "terbit": "05:20", "dhuha": "05:51", "dzuhur": "11:40",
                                  "ashar": "14:53", "maghrib": "17:54", "isya": "19:01"}]}}
    monkeypatch.setattr(ibadah, "_client", lambda: FakeClient({
        "/sholat/jadwal/": FakeResp(month), "/cal/hijr/": FakeResp({"data": {"num": [5, 29, 10, 2026, 17, 5, 1448]}}),
        "/sholat/kota/cari/": FakeResp({"data": [{"id": "1222", "lokasi": "KOTA BOGOR"}]})}))
    await pool.execute("""INSERT INTO settings_kv (key, value) VALUES ('last_location', '{"lat": -6.5971, "lon": 106.806, "address": "Jl. Pajajaran, Kota Bogor, Jawa Barat"}')""")
    v = await ibadah.today_view(datetime(2026, 10, 29, 13, 38, tzinfo=ibadah.WIB))
    assert v["city"] == "KOTA BOGOR" and v["source"] == "kemenag" and v["next"]["name"] == "ashar" and v["hijri"] == "17 Jumadil Awal 1448 H"
    assert any(e["title"] == "Puasa Kamis" for e in v["today_events"])
    sent = []

    async def tap(ev):
        if ev.get("type") == "notify":
            sent.append(ev)
    hub.tap(tap)
    done = await ibadah.tick(datetime(2026, 10, 29, 14, 54, tzinfo=ibadah.WIB))
    assert done == ["ashar"] and sent[0]["title"] == "Waktunya Ashar 14.53" and sent[0]["route"] == "#/sholat"
    assert await ibadah.tick(datetime(2026, 10, 29, 14, 56, tzinfo=ibadah.WIB)) == []        # once
    run = await pool.fetchrow("SELECT feature, lane, status FROM flow_runs WHERE feature = 'sholat'")
    assert dict(run) == {"feature": "sholat", "lane": "skill", "status": "done"}             # through the master flow, without AI


@needs_db
async def test_reading_marks_progress_and_khatam(pool, monkeypatch):
    from app import quran
    await pool.execute("TRUNCATE quran_surah, quran_reads RESTART IDENTITY")
    lst = [{"nomor": i, "nama": "س", "namaLatin": f"S{i}", "jumlahAyat": 7 if i == 1 else (6 if i == 114 else 50), "arti": "a", "tempatTurun": "Mekah"}
           for i in range(1, 115)]
    one = {"nomor": 18, "nama": "الكهف", "namaLatin": "Al-Kahf", "arti": "Goa", "jumlahAyat": 2, "tempatTurun": "Mekah", "audioFull": {"05": "https://x/full.mp3"},
           "ayat": [{"nomorAyat": "1", "teksArab": "ا", "teksLatin": "a", "teksIndonesia": "b", "audio": {"05": "https://x/1.mp3"}}]}
    monkeypatch.setattr(quran, "_client", lambda: FakeClient({"/surat/18": FakeResp({"data": one}), "/surat": FakeResp({"data": lst})}))
    s = await quran.surah(18)
    assert s["latin"] == "Al-Kahf" and s["ayat"][0]["audio"] == "https://x/1.mp3" and s["ayat"][0]["juz"] == 15
    p = await quran.mark(18, 45)
    assert p["last"]["latin"] == "S18" and p["last"]["ayah"] == 45 and p["streak"] == 1 and 0 < p["pct"] < 100
    with pytest.raises(ValueError):
        await quran.mark(1, 8)
    p = await quran.mark(114, 6)
    assert p["khatam"] == 1 and p["pct"] == 100


@needs_db
async def test_the_brief_is_written_through_the_master_flow(pool, monkeypatch):
    from app import brief, gateway, hub, weather
    await pool.execute("TRUNCATE briefs, flow_runs RESTART IDENTITY")
    rss = """<rss><channel><item><title>Biaya admin marketplace naik</title><link>https://n/1</link><pubDate>{d}</pubDate></item></channel></rss>"""
    from email.utils import format_datetime
    from datetime import timezone
    pub = format_datetime(datetime.now(timezone.utc))
    monkeypatch.setattr(brief, "_client", lambda: FakeClient({
        "finance.yahoo.com": FakeResp({"chart": {"result": [{"indicators": {"quote": [{"close": [100, 101]}]}}]}}),
        "": FakeResp(None, rss.format(d=pub))}))

    async def no_weather():
        return "Cuaca cerah, 23°C."
    monkeypatch.setattr(weather, "today_text", no_weather)
    asked = []

    async def fake(category, body, **kw):
        asked.append(category)
        return {"choices": [{"message": {"content": '{"judul": "Biaya jualan online naik", "situasi": "Marketplace menaikkan biaya.", "suasana": "waspada",'
                                                    ' "tema": [{"judul": "Biaya marketplace", "alasan": [{"isi": "Biaya admin naik", "nomor": "EKONOMI 1"}],'
                                                    ' "dampak": "margin Autotoko turun"}], "peluang": [{"aksi": "Dorong penjualan lewat website sendiri",'
                                                    ' "kaitan": "bisnis"}], "ucapan": "Selamat pagi."}'}}]}
    monkeypatch.setattr(gateway, "complete", fake)
    sent = []

    async def tap(ev):
        if ev.get("type") == "notify":
            sent.append(ev)
    hub.tap(tap)
    d = await brief.compose()
    assert asked == ["berat"] and d["tema"][0]["alasan"][0]["link"] == "https://n/1" and d["markets"][0]["change"] == 1.0 and d["weather"]
    assert d["peluang"][0]["kaitan"] == "bisnis" and d["suasana"] == "waspada"
    assert sent and sent[-1]["route"] == "#/brief" and sent[-1]["title"] == "Cek berita siap" and (await brief.today())["data"]["ucapan"] == "Selamat pagi."
    assert await pool.fetchval("SELECT lane FROM flow_runs WHERE feature = 'brief'") == "berat"     # an analysis: the heavy brain


@needs_db
async def test_daily_jobs_run_once_a_day(pool):
    from app import appclock
    ran = []

    @appclock.daily(lambda: "05:45", "test.daily")
    async def job():
        ran.append(1)
    try:
        t = datetime(2026, 10, 29, 5, 40, tzinfo=appclock.WIB)
        assert "test.daily" not in await appclock.run_once(t)
        assert "test.daily" in await appclock.run_once(t.replace(minute=46))
        assert "test.daily" not in await appclock.run_once(t.replace(hour=9))
        assert "test.daily" in await appclock.run_once(t + timedelta(days=1, hours=1))
        assert ran == [1, 1]
    finally:
        appclock._daily.pop("test.daily", None)


@needs_db
async def test_wave1_screens_get_real_answers(pool, monkeypatch):
    from app import brief, devices, ibadah, main, quran
    await pool.execute("TRUNCATE prayer_days, quran_surah, quran_reads, briefs RESTART IDENTITY")
    monkeypatch.setattr(ibadah, "_client", lambda: FakeClient({"/sholat/jadwal/": FakeResp({"data": {"jadwal": []}}), "/cal/hijr/": FakeResp({}, "", 500)}))
    lst = [{"nomor": i, "nama": "س", "namaLatin": f"S{i}", "jumlahAyat": 10, "arti": "a", "tempatTurun": "Mekah"} for i in range(1, 115)]
    monkeypatch.setattr(quran, "_client", lambda: FakeClient({"/surat": FakeResp({"data": lst})}))
    _, token = await devices.create("HP", "test", scope="owner")
    h = {"Authorization": f"Bearer {token}"}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url="http://t") as c:
        today = (await c.get("/api/v1/app/ibadah/today", headers=h)).json()
        assert today["source"] == "hitungan" and today["times"]["subuh"] and today["next"]["label"]   # Kemenag down → computed here
        cal = (await c.get("/api/v1/app/ibadah/calendar?days=60", headers=h)).json()
        assert cal["events"] and cal["hijri"].endswith("H")
        assert (await c.get("/api/v1/app/quran", headers=h)).json()["surahs"][0]["latin"] == "S1"
        assert (await c.post("/api/v1/app/quran/read", json={"surah": 2, "ayah": 5}, headers=h)).json()["last"]["ayah"] == 5
        assert (await c.get("/api/v1/app/brief", headers=h)).json()["brief"] is None
        wake = (await c.get("/api/v1/app/ibadah/wake", headers=h)).json()
        assert wake["text"].startswith("Selamat pagi.")
        home = (await c.get("/api/v1/app/home?slot=subuh", headers=h)).json()
        assert any(x["kind"] == "sholat" for x in home["all"])
        put = await c.put("/api/v1/app/settings/alarm", json={"time": "04:15"}, headers=h)
        assert put.json()["time"] == "04:15"
