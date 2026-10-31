"""Owner 2026-10-31: a mood or a search → ±20 real songs (the brain names them, YouTube has them) he ticks → downloaded one at a time into
his collection (his converter, or yt-dlp with his own YouTube cookies kept encrypted) → played from the local files like Spotify (all,
shuffled, from a song on, the next when one ends; liked; deleted; into playlists, which then play the local file)."""
import asyncio
import os

import httpx
import pytest

from tests.test_integration import pool  # noqa: F401  (fixture)

needs_db = pytest.mark.skipif(not os.getenv("TEST_DATABASE_URL"), reason="needs TEST_DATABASE_URL")


def test_pure_parts():
    from app import musiclibrary, musik
    assert musiclibrary.valid_cookies("# Netscape HTTP Cookie File\n.youtube.com\tTRUE\t/\tTRUE\t0\tSID\tabc\n")
    assert not musiclibrary.valid_cookies("SID=abc; HSID=def") and not musiclibrary.valid_cookies(".google.com\tTRUE\t/\tTRUE\t0\tSID\tx\n")
    assert musik.clean_suggestions({"lagu": [{"judul": "Monokrom", "artis": "Tulus"}, {"judul": "monokrom", "artis": "tulus"}, {"artis": "x"}]}) == [
        {"judul": "Monokrom", "artis": "Tulus"}]
    found = [{"url": "https://www.youtube.com/watch?v=aaaaaaaaaaa", "title": "PLAYLIST TULUS FULL ALBUM", "channel": "x", "duration_s": 3600},
             {"url": "https://www.youtube.com/watch?v=bbbbbbbbbbb", "title": "Raisa - Kali Kedua", "channel": "Raisa", "duration_s": 240},
             {"url": "https://www.youtube.com/watch?v=ccccccccccc", "title": "TULUS - Monokrom (Official Music Video)", "channel": "Tulus", "duration_s": 219}]
    assert musik.best_hit(found, "Monokrom", "Tulus")["url"].endswith("ccccccccccc")
    assert musik.best_hit(found, "Gajah", "Tulus") is None
    assert musiclibrary.song_words("TULUS - Monokrom (Official Music Video)", "Tulus") == "TULUS - Monokrom"
    assert musiclibrary.song_words("Hati-Hati di Jalan [Lirik]", "Tulus - Topic") == "Tulus - Hati-Hati di Jalan"
    assert musiclibrary.song_words("Sial | Official Lyric Video", "Mahalini") == "Mahalini - Sial"
    assert musiclibrary.same_song({"title": "Monokrom by Tulus (cover)", "artist": "dewi"}, "TULUS - Monokrom")
    assert not musiclibrary.same_song({"title": "Gajah", "artist": "Tulus"}, "TULUS - Monokrom")             # the artist alone is not the song
    assert musiclibrary.same_song({"title": "hati hati di jalan", "artist": "x"}, "Tulus - Hati-Hati di Jalan")


@needs_db
async def test_ticked_songs_are_collected_downloaded_and_played_locally(pool, monkeypatch, tmp_path):
    from app import devices, hub, main, media_tools, musiclib, musiclibrary, musik, playlists
    monkeypatch.setenv("VAULT_KEY", "44" * 32)
    monkeypatch.setattr(musiclib, "ROOT", tmp_path)
    await pool.execute("TRUNCATE music_picks, music_library, playlists, flow_runs RESTART IDENTITY CASCADE")
    await pool.execute("DELETE FROM settings_kv WHERE key = 'music:ytcookies'")
    told = []

    async def tell(ev):
        told.append(ev)
        return 1
    monkeypatch.setattr(hub, "broadcast", tell)
    shown = []

    async def show(panel, payload, caption="", actor="jarvis"):
        shown.append((panel, payload["url"], payload.get("playlist")))
        return {"id": f"s{len(shown)}"}
    monkeypatch.setattr(media_tools, "_show", show)
    looked = []

    async def soundcloud(q, accept):   # the free fallback: not there for these songs
        looked.append((q, accept({"title": q, "artist": ""}), accept({"title": "Sesuatu yang lain", "artist": "Tulus"})))
        raise ValueError("lagunya tidak ketemu di SoundCloud")
    monkeypatch.setattr(musiclib, "soundcloud_mp3", soundcloud)
    opts = [{"url": f"https://www.youtube.com/watch?v=song{i:07d}", "title": f"Lagu {i}", "channel": "Tulus", "duration_s": 200 + i,
             "cover": f"https://i.ytimg.com/vi/song{i:07d}/mqdefault.jpg"} for i in range(3)]
    pid = await pool.fetchval("INSERT INTO music_picks (query, options) VALUES ('santai', $1) RETURNING id", opts)
    _, token = await devices.create("HP", "test", scope="owner")
    h = {"Authorization": f"Bearer {token}"}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url="http://t") as c:
        r = (await c.post(f"/api/v1/app/music/picks/{pid}", json={"choose": [0, 2]}, headers=h)).json()
        assert r["count"] == 2 and r["cookies"] is False and len(r["collected"]) == 2
        for _ in range(60):   # no converter, no cookies: they wait as failed, saying what is missing
            if await pool.fetchval("SELECT count(*) FROM music_library WHERE status = 'gagal'") == 2:
                break
            await asyncio.sleep(0.05)
        lib = (await c.get("/api/v1/app/music/library", headers=h)).json()
        assert lib["failed"] == 2 and "cookies" in lib["songs"][0]["error"] and not shown            # nothing played behind his back
        assert sorted(looked) == [("Tulus - Lagu 0", True, False), ("Tulus - Lagu 2", True, False)]   # SoundCloud tried first, same song only

        made = []

        def fake_ytdlp(url, cookies, meta):
            assert open(cookies).read().startswith("# Netscape")                                       # his cookies, in a private temp file
            made.append(url)
            media_id = f"m{len(made)}"
            (tmp_path / f"{media_id}.mp3").write_bytes(b"ID3" + b"0" * 100)
            return musiclib._save_meta(media_id, tmp_path / f"{media_id}.mp3", meta | {"license": "", "source_url": url})
        monkeypatch.setattr(musiclibrary, "_ytdlp_mp3", fake_ytdlp)
        bad = await c.put("/api/v1/app/music/library/cookies", json={"text": "SID=abc; this is not a cookies file"}, headers=h)
        assert bad.status_code == 422
        ck = await c.put("/api/v1/app/music/library/cookies", json={"text": "# Netscape HTTP Cookie File\n.youtube.com\tTRUE\t/\tTRUE\t0\tSID\tabc\n"}, headers=h)
        assert ck.json()["cookies"] is True
        stored = await pool.fetchval("SELECT value FROM settings_kv WHERE key = 'music:ytcookies'")
        assert "SID" not in str(stored)                                                                 # encrypted at rest
        for _ in range(80):   # adding cookies retries the failed ones
            if await pool.fetchval("SELECT count(*) FROM music_library WHERE status = 'siap'") == 2:
                break
            await asyncio.sleep(0.05)
        lib = (await c.get("/api/v1/app/music/library", headers=h)).json()
        assert lib["count"] == 2 and lib["bytes"] > 0 and len(made) == 2
        ids = [s["id"] for s in lib["songs"]]
        p = (await c.post("/api/v1/app/music/library/play", json={"ids": ids, "start": 1}, headers=h)).json()
        assert p["index"] == 1 and p["total"] == 2 and shown[-1][1].startswith("/api/v1/media/m")
        assert musiclibrary.on_stage_event("prev") is True                                              # the song ended / ⏮: the queue moves
        await asyncio.sleep(0.1)
        assert len(shown) == 2 and musiclibrary._queue["i"] == 0
        assert (await c.post(f"/api/v1/app/music/library/{ids[0]}/like", headers=h)).json() == {"liked": True}
        assert (await c.post(f"/api/v1/app/music/library/{ids[0]}/playlist", json={"name": "Santai"}, headers=h)).status_code == 200
        song = (await pool.fetchrow("SELECT title, artist FROM music_library WHERE id = $1", ids[0]))
        r = await playlists.play("Santai", 0)                                                           # a playlist song in the collection: local file
        assert r["song"]["title"] == song["title"] and shown[-1][1].startswith("/api/v1/media/m") and shown[-1][2]["name"] == "Santai"
        media = await pool.fetchval("SELECT media_id FROM music_library WHERE id = $1", ids[1])
        assert (await c.delete(f"/api/v1/app/music/library/{ids[1]}", headers=h)).status_code == 200
        assert not (tmp_path / f"{media}.mp3").exists()                                                # the file goes with it
        assert (await c.post("/api/v1/app/music/library/link", json={"url": "https://example.com/x"}, headers=h)).status_code == 422
    assert await pool.fetchval("SELECT count(*) FROM flow_runs WHERE feature = 'musik' AND action = 'unduh' AND lane = 'skill'") >= 2
    assert musik
