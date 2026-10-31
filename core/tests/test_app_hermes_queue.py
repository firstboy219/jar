"""Owner 2026-10-31: every Cek berita worker goes through Hermes first — Hermes knows the context and plans a queue so the workers do not all
run at once — unless Hermes is anomalous (answers anything, gives false data): then the flow skips Hermes. A watchdog watches Hermes. The
page shows a loader and the workers' activity log while it runs."""
import asyncio
import json
import os
import time

import pytest

from tests.test_integration import pool  # noqa: F401  (fixture)

needs_db = pytest.mark.skipif(not os.getenv("TEST_DATABASE_URL"), reason="needs TEST_DATABASE_URL")
WORKERS = ["berita", "pasar", "topik", "sosial", "tren", "sentimen", "agenda", "cuaca"]


def _answer(**kw):
    base = {"token": "AB12CD", "jumlah": 8, "maks_bersamaan": 3, "urutan": ["berita", "sosial", "pasar", "topik", "tren", "sentimen", "cuaca"],
            "lewati": [{"worker": "agenda", "alasan": "kosong di catatan terakhir"}], "catatan": "yang lambat dulu"}
    return "Berikut rencananya:\n```json\n" + json.dumps({**base, **kw}) + "\n```"


def test_the_watchdog_only_lets_a_sound_plan_through():
    from app import hermeswatch as w
    plan, problems = w.check_queue(_answer(), "AB12CD", WORKERS, {"berita", "pasar"}, {"agenda"})
    assert problems == [] and plan["urutan"][0] == "berita" and plan["maks"] == 3 and plan["lewati"][0]["worker"] == "agenda"
    bad = {
        "asal jawab": "Siap, saya akan mengatur antreannya dengan baik!",
        "token": _answer(token="ZZZZZZ"),
        "jumlah": _answer(jumlah=7),
        "nama palsu": _answer(urutan=["berita", "passar", "topik", "sosial", "tren", "sentimen", "cuaca"]),
        "hilang": _answer(urutan=["berita", "sosial", "pasar"]),
        "dua kali": _answer(urutan=["berita", "berita", "sosial", "pasar", "topik", "tren", "sentimen", "cuaca"]),
        "wajib": _answer(urutan=["sosial", "pasar", "topik", "tren", "sentimen", "cuaca", "agenda"], lewati=[{"worker": "berita", "alasan": "lambat"}]),
        "data palsu": _answer(urutan=["berita", "pasar", "topik", "tren", "sentimen", "cuaca", "agenda"], lewati=[{"worker": "sosial", "alasan": "Reddit 429"}]),
        "batas": _answer(maks_bersamaan=40),
    }
    for name, text in bad.items():
        plan, problems = w.check_queue(text, "AB12CD", WORKERS, {"berita", "pasar"}, {"agenda"})
        assert plan is None and problems, name
    assert "passar" in w.check_queue(bad["nama palsu"], "AB12CD", WORKERS, {"berita", "pasar"}, {"agenda"})[1][0]
    assert "tidak sesuai data" in " ".join(w.check_queue(bad["data palsu"], "AB12CD", WORKERS, {"berita", "pasar"}, {"agenda"})[1])
    assert w.too_slow(60, 8) and not w.too_slow(12, 8) and w.too_slow(50, None) and not w.too_slow(20, None)


@needs_db
async def test_hermes_plans_the_queue_ahead_and_is_passed_over_when_it_misbehaves(pool, monkeypatch):
    from app import brief, hermes, hermeswatch, master
    await pool.execute("TRUNCATE briefs, flow_runs RESTART IDENTITY CASCADE")
    await pool.execute("DELETE FROM settings_kv WHERE key IN ('hermes:watch', 'brief:antrean')")
    replies, asked = [], []

    async def stream(text, session_id, model="jarvis-web", **kw):
        asked.append((text, session_id, model))
        token = text.split('"token": "')[1][:6]
        reply = replies.pop(0).replace("AB12CD", token)
        yield {"type": "done", "reply": hermes.HermesReply(reply, None, None, 10)}
    monkeypatch.setattr(hermes, "stream", stream)

    # a sound plan: kept, and the run follows it — in its order, never more than its number at once, nobody waiting for Hermes
    replies.append(_answer(lewati=[], urutan=WORKERS, maks_bersamaan=2))
    rec = await brief.refresh_plan()
    assert rec and rec["plan"]["maks"] == 2 and "WAJIB" in asked[0][0] and asked[0][1] == brief.HERMES_SESSION
    assert "BEBAN SERVER SEKARANG" in asked[0][0] and (await hermeswatch.state())["checks"][0]["ok"]
    now_running, peak, started = [0], [0], []

    def collector(key):
        async def run(now):
            started.append(key)
            now_running[0] += 1
            peak[0] = max(peak[0], now_running[0])
            await asyncio.sleep(0.02)
            now_running[0] -= 1
            return [1] if key != "berita" else {"ekonomi": [{"title": "x", "summary": "", "source": "A", "link": ""}]}
        return run
    monkeypatch.setattr(brief, "COLLECTORS", [(k, k.title(), collector(k)) for k in WORKERS])
    monkeypatch.setattr(brief, "refresh_soon", lambda: None)
    g = await brief.gather("owner")
    assert started == WORKERS and peak[0] == 2 and g["queue"]["source"] == "hermes"
    steps = [r["steps"] for r in await pool.fetch("SELECT steps FROM flow_runs WHERE action = 'kumpul-berita'")]
    hermes_step = [x for x in (json.loads(steps[0]) if isinstance(steps[0], str) else steps[0]) if x["stage"] == "hermes"][0]
    assert "antrean Hermes: ke-1 dari 8, maks 2 bersamaan" in hermes_step["text"]                       # each worker passed Hermes
    assert any("lolos pengawas" in line["text"] for line in brief._state["log"])

    # Hermes skips a source that really came back empty last time: allowed, shown as skipped
    await pool.execute("INSERT INTO briefs (day, data, sources) VALUES (current_date - 1, $1, '{}')",
                       {"pipeline": [{"key": "agenda", "status": "selesai", "n": 0}], "judul": "x"})
    replies.append(_answer(urutan=[k for k in WORKERS if k != "agenda"], lewati=[{"worker": "agenda", "alasan": "kosong terakhir kali"}]))
    assert await brief.refresh_plan()
    started.clear()
    brief._state["steps"] = []
    await brief.gather("owner")
    assert "agenda" not in started and any(st["status"] == "dilewati" and st["key"] == "agenda" for st in brief._state["steps"])

    # anomalies: a made-up worker, then an answer that is not for this request → passed over for an hour, the built-in order runs
    replies.append(_answer(urutan=["berita", "passar", "topik", "sosial", "tren", "sentimen", "cuaca", "agenda"], lewati=[]))
    assert await brief.refresh_plan() is None
    replies.append(_answer().replace("AB12CD", "QQQQQQ").replace('"token": "', '"token": "X'))
    assert await brief.refresh_plan() is None
    st = await hermeswatch.state()
    assert st["bad_streak"] == 2 and st["bypass_until"] > time.time() and "passar" in json.dumps(st["checks"])
    assert await hermeswatch.bypassed()
    n = len(asked)
    assert await brief.refresh_plan() is None and len(asked) == n                                          # not even asked while passed over
    started.clear()
    g = await brief.gather("owner")
    assert g["queue"]["source"] == "bawaan" and sorted(started) == sorted(WORKERS)
    assert any("Pengawas Hermes" in line["text"] and line["kind"] == "warn" for line in brief._state["log"])

    # Hermes down: no waiting for it either
    await pool.execute("DELETE FROM settings_kv WHERE key = 'hermes:watch'")

    async def down(*a, **k):
        raise hermes.HermesError("Hermes HTTP 502")
        yield  # pragma: no cover
    monkeypatch.setattr(hermes, "stream", down)
    assert await brief.refresh_plan() is None and "tidak bisa dihubungi" in (await hermeswatch.state())["checks"][0]["problems"][0]
    assert master  # the master flow ran every worker above


@needs_db
async def test_the_page_shows_a_loader_card_and_the_log_while_it_runs(pool, monkeypatch):
    from app import brief, devices, home, main
    import httpx
    brief._state.update(running=True, steps=[{"stage": "kumpul", "key": "berita", "label": "Berita", "status": "selesai"},
                                             {"stage": "kumpul", "key": "pasar", "label": "Pasar", "status": "jalan"}],
                        log=[{"at": "2026-11-01T00:00:00+00:00", "text": "✓ Berita selesai", "kind": "ok"}])
    monkeypatch.setattr(brief, "refresh_soon", lambda: None)
    try:
        from datetime import datetime
        cards = await brief._home(home.Moment(now=datetime.now(brief.WIB), slot="malam", tags=set()))
        assert cards[0]["title"] == "Cek berita sedang dianalisis…" and "1/" in cards[0]["sub"]
        _, token = await devices.create("HP", "test", scope="owner")
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url="http://t") as c:
            d = (await c.get("/api/v1/app/brief", headers={"Authorization": f"Bearer {token}"})).json()
        assert d["progress"]["running"] and d["progress"]["log"][0]["text"] == "✓ Berita selesai" and "bypass" in d["hermes"]
    finally:
        brief._state.update(running=False, steps=[], log=[])
