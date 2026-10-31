"""Al-Qur'an (owner 2026-10-30): the translation read aloud by the device's own voice (app side), and the context of a verse — where and in
which order its surah came down, the period of the mission and what the Prophet ﷺ went through then, the Kemenag tafsir word for word,
and a summary of its occasion drawn from that tafsir only (no occasion in the tafsir → none is made up), kept once made."""
import json
import os

import httpx
import pytest

from tests.test_app_wave1 import FakeClient, FakeResp
from tests.test_integration import pool  # noqa: F401  (fixture)

needs_db = pytest.mark.skipif(not os.getenv("TEST_DATABASE_URL"), reason="needs TEST_DATABASE_URL")


def test_revelation_order_periods_and_the_scholars_difference():
    from app import quran
    assert sorted(quran.ORDER) == list(range(1, 115)) and quran.ORDER[95] == 1 and quran.ORDER[1] == 87   # Al-'Alaq first, Al-Baqarah first in Madinah
    assert quran.period(1)["nama"] == "Makkah awal" and quran.period(80)["nama"] == "Makkah akhir"
    assert quran.period(87)["nama"] == "Madinah awal" and quran.period(113)["nama"] == "Madinah akhir"
    assert "Abu Thalib" in quran.period(70)["nabi"] and "Badar" in quran.period(90)["nabi"]
    assert quran.surah_period("Madinah", 20)["nama"] == "Diperselisihkan"                # Al-Falaq: Kemenag says Madinah, the chronology Makkah
    assert quran.surah_period("Mekah", 20)["nama"] == "Makkah awal"
    assert quran.plain("<i>Abasa</i> artinya &quot;bermuka masam&quot;<br>Turun di Mekah") == 'Abasa artinya "bermuka masam"\nTurun di Mekah'


def test_a_summary_without_an_occasion_in_the_tafsir_stays_without_one():
    from app import quran
    r = quran.clean_context({"ada": True, "sebab": "Teguran tentang 'Abdullah bin Ummi Maktum.", "peristiwa": "Berbicara dengan pembesar Quraisy",
                             "waktu": "di Makkah", "riwayat": None, "lain": "x"})
    assert r == {"sebab": "Teguran tentang 'Abdullah bin Ummi Maktum.", "peristiwa": "Berbicara dengan pembesar Quraisy", "waktu": "di Makkah",
                 "riwayat": None, "ada": True}
    assert quran.clean_context({"ada": True, "sebab": ""})["ada"] is False                   # "yes" with nothing said is no
    assert quran.clean_context({"ada": False, "sebab": "karangan"})["sebab"] is None


@needs_db
async def test_the_context_of_a_verse_from_the_kemenag_tafsir(pool, monkeypatch):
    from app import appauth, devices, gateway, main, quran
    await pool.execute("TRUNCATE quran_surah, quran_tafsir, quran_context, flow_runs RESTART IDENTITY CASCADE")
    lst = [{"nomor": i + 1, "nama": "", "namaLatin": quran.LATIN[i], "jumlahAyat": quran.AYAT[i], "arti": "", "tempatTurun": "Madinah" if i in (1, 112, 113) else "Mekah"}
           for i in range(114)]
    tafsir = {"nomor": 80, "deskripsi": "Surah <i>'Abasa</i> terdiri atas 42 ayat, turun di Mekah.",
              "tafsir": [{"ayat": 1, "teks": "Allah menegur Nabi Muhammad yang bermuka masam kepada 'Abdullah bin Ummi Maktum yang buta, ketika Nabi "
                                            "sedang berbicara dengan para pembesar Quraisy."},
                         {"ayat": 2, "teks": "Karena seorang buta datang kepadanya."}]}
    fetched = []

    def tafsir_route(url):
        fetched.append(url)
        return FakeResp({"data": tafsir})
    monkeypatch.setattr(quran, "_client", lambda: FakeClient({"/tafsir/80": tafsir_route, "/surat": FakeResp({"data": lst})}))
    calls = []

    async def fake(category, body, **kw):
        calls.append(body)
        return {"choices": [{"message": {"content": json.dumps({"ada": True, "sebab": "Teguran Allah karena Rasulullah saw bermuka masam kepada 'Abdullah bin Ummi Maktum.",
                                                                 "peristiwa": "Sedang berbicara dengan para pembesar Quraisy", "waktu": None, "riwayat": None})}}],
                "jarvis_route": {"model": "m/x"}}
    monkeypatch.setattr(gateway, "complete", fake)

    async def check(pw):
        return 401
    monkeypatch.setattr(appauth, "_check", check)
    _, token = await devices.create("HP", "test", scope="owner")
    h = {"Authorization": f"Bearer {token}"}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url="http://t") as c:
        ctx = (await c.get("/api/v1/app/quran/context/80/1", headers=h)).json()
        assert ctx["surah"]["tempat"] == "Mekah" and ctx["surah"]["urutan"] == 24 and ctx["surah"]["periode"]["nama"] == "Makkah pertengahan"
        assert ctx["tafsir"].startswith("Allah menegur Nabi") and ctx["surah"]["pengantar"] == "Surah 'Abasa terdiri atas 42 ayat, turun di Mekah."
        assert ctx["ringkasan"] is None and not calls                                            # opening the context costs no AI
        r = (await c.post("/api/v1/app/quran/context/80/1/summary", headers=h)).json()
        assert r["ada"] and "Ummi Maktum" in r["sebab"]
        sent = calls[0]["messages"]
        assert "HANYA dari teks Tafsir Kemenag" in sent[0]["content"] and "pembesar Quraisy" in sent[1]["content"]
        assert calls[0]["reasoning"] == {"enabled": False}                                          # the light brain, through the master flow
        assert await pool.fetchval("SELECT lane FROM flow_runs WHERE feature = 'quran' AND action = 'konteks'") == "ringan"
        again = (await c.post("/api/v1/app/quran/context/80/1/summary", headers=h)).json()
        assert again == r and len(calls) == 1                                                       # kept: asked once
        assert (await c.get("/api/v1/app/quran/context/80/1", headers=h)).json()["ringkasan"] == r
        assert len(fetched) == 1                                                                    # the tafsir is cached too
        assert (await c.get("/api/v1/app/quran/context/80/43", headers=h)).status_code == 404
        al_falaq = (await c.get("/api/v1/app/quran/context/113/1", headers=h))
        assert al_falaq.status_code in (200, 503)                                                   # (no tafsir route faked for it)
    s = await pool.fetchval("SELECT value FROM settings_kv WHERE key = 'app:quran'")
    assert s is None or "read_mode" not in s or s["read_mode"] in ("arab", "both", "arti")


def test_a_long_translation_is_read_in_pieces_one_voice_call_takes():
    from app import quran
    short = "Segala puji bagi Allah, Tuhan seluruh alam."
    assert quran.voice_chunks(short) == [short]
    long = " ".join(f"Kalimat nomor {i} yang cukup panjang untuk diuji." for i in range(60))
    parts = quran.voice_chunks(long, 300)
    assert all(len(p) <= 300 for p in parts) and " ".join(parts) == long and len(parts) > 5
    run_on = "kata " * 400                                   # no sentence end at all: cut at spaces
    assert all(len(p) <= 300 for p in quran.voice_chunks(run_on, 300))
    a, b = quran.voice_path(1, 2, "elevenlabs/x", "george", "teks"), quran.voice_path(1, 2, "elevenlabs/x", "sarah", "teks")
    assert a.name.startswith("001-002-") and a != b                     # another voice is another recording


@needs_db
async def test_a_verse_translation_is_voiced_once_then_kept(pool, monkeypatch, tmp_path):
    from app import appauth, devices, main, quran, voice
    await pool.execute("TRUNCATE quran_surah, flow_runs RESTART IDENTITY CASCADE")
    monkeypatch.setattr(voice, "VOICE_DIR", tmp_path)

    async def surah(nomor, qari="05"):
        return {"latin": "Al-Fatihah", "ayat": [{"n": 1, "arti": "Dengan nama Allah Yang Maha Pengasih, Maha Penyayang."}]}
    monkeypatch.setattr(quran, "surah", surah)

    async def settings_():
        return {"engine": "android", "model": "openai/tts", "voice": "george", "speed": 1.0}
    monkeypatch.setattr(voice, "tts_settings", settings_)
    calls = []

    async def synth(text, model=None, voice_name=None, *, preview=False):
        calls.append((text, model, voice_name, preview))
        return b"ID3fake-mp3"
    monkeypatch.setattr(voice, "synthesize", synth)
    _, token = await devices.create("HP", "test", scope="owner")
    h = {"Authorization": f"Bearer {token}"}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url="http://t") as c:
        r = await c.get("/api/v1/app/quran/voice/1/1", headers=h)
        assert r.status_code == 200 and r.content == b"ID3fake-mp3" and r.headers["content-type"] == "audio/mpeg"
        assert calls == [("Dengan nama Allah Yang Maha Pengasih, Maha Penyayang.", quran.VOICE_MODEL, "george", True)]   # ElevenLabs, not the chat voice
        assert (await c.get("/api/v1/app/quran/voice/1/1", headers=h)).content == b"ID3fake-mp3" and len(calls) == 1   # the kept recording
        assert (await c.get("/api/v1/app/quran/voice/1/9", headers=h)).status_code == 404

        async def broke(text, model=None, voice_name=None, *, preview=False):
            raise voice.VoiceError("anggaran AI bulan ini habis — pakai suara HP", 402)
        monkeypatch.setattr(voice, "synthesize", broke)

        async def surah2(nomor, qari="05"):
            return {"latin": "Al-Baqarah", "ayat": [{"n": 2, "arti": "Kitab (Al-Qur'an) ini tidak ada keraguan padanya."}]}
        monkeypatch.setattr(quran, "surah", surah2)
        assert (await c.get("/api/v1/app/quran/voice/2/2", headers=h)).status_code == 503       # the app reads it with the device's voice
    assert quran.voice_kept() == 1
    assert await pool.fetchval("SELECT lane FROM flow_runs WHERE feature = 'quran' AND action = 'suara-terjemahan' ORDER BY id LIMIT 1") == "skill"
