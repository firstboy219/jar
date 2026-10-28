"""ADR-081: three lanes — ringan (simple look-ups, no Hermes session, no worker slot), Hermes, OpenJarvis (heavy) — chosen from the task and the load."""
import asyncio
import os

import pytest

from tests.test_acceptance import _done, _hermes, _wait  # noqa: F401
from tests.test_integration import _fake_llm, _no_memory, pool  # noqa: F401  (fixture)

needs_db = pytest.mark.skipif(not os.getenv("TEST_DATABASE_URL"), reason="needs TEST_DATABASE_URL")
CALM = {"slots": 4, "hermes_running": 1, "hermes_queued": 0, "openjarvis_running": 0, "openjarvis_queued": 0, "light_running": 0}
LOOKUP = "Cari harga emas Antam hari ini"


def pick(**kw):
    from app import lanes
    base = dict(kind="owner", category="web", instruction=LOOKUP, image=None, private=False, company_id=None, heavy=False,
                light_on=True, oj_on=False, oj_ok=True, load=CALM)
    return lanes.choose(**{**base, **kw})


def test_a_simple_lookup_takes_the_light_lane():
    assert pick() == ("ringan", "pencarian sederhana")
    assert pick(light_on=False)[0] == "hermes"                              # the owner switched it off
    assert pick(category="analisis")[0] == "hermes"                         # only web look-ups
    assert pick(instruction="Buatkan laporan harga emas mingguan dan kirim ke email")[0] == "hermes"   # it makes / sends something
    assert pick(instruction="Cari harga emas " + "yang panjang " * 60)[0] == "hermes"


def test_only_the_owners_ordinary_tasks_leave_hermes():
    for kw in ({"kind": "selfcheck"}, {"private": True}, {"image": "abc"}, {"company_id": "c1"}, {"kind": "devteam", "heavy": True, "oj_on": True}):
        assert pick(**kw)[0] == "hermes", kw


def test_a_heavy_task_goes_to_openjarvis_unless_it_is_down_or_full():
    assert pick(heavy=True, oj_on=True) == ("openjarvis", "tugas berat")
    assert pick(heavy=True, oj_on=False)[0] == "hermes"                     # the owner has it off — and a heavy task is no quick look-up
    lane, why = pick(heavy=True, oj_on=True, oj_ok=False)
    assert lane == "hermes" and "tidak menjawab" in why
    busy = {**CALM, "openjarvis_running": 2}
    lane, why = pick(heavy=True, oj_on=True, load=busy)
    assert lane == "hermes" and "sedang penuh" in why                       # Hermes has room: it takes the overflow
    full = {**busy, "hermes_running": 4}
    lane, why = pick(heavy=True, oj_on=True, load=full)
    assert lane == "openjarvis" and "antre" in why                          # both full: stay in the lane that suits the task


def test_a_task_that_has_to_queue_says_so():
    assert pick(category="analisis", instruction="bandingkan tiga laptop", load={**CALM, "hermes_running": 4}) == ("hermes", "antre: semua 4 slot Hermes terpakai")
    assert pick(category="analisis", instruction="bandingkan tiga laptop") == ("hermes", "")
    assert pick(load={**CALM, "hermes_running": 4})[0] == "ringan"          # a look-up does not wait for a slot


def test_the_lane_and_load_are_said_on_the_desk():
    from app import lanes
    assert lanes.LANES == ("ringan", "hermes", "openjarvis")


@needs_db
async def test_a_lookup_is_answered_without_a_worker_slot_or_a_hermes_session(pool, monkeypatch):
    from app import hermes, quick, reports, workers
    _fake_llm(monkeypatch, [])
    monkeypatch.setattr(hermes, "stream", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no Hermes")))
    monkeypatch.setattr(workers, "_sem", asyncio.Semaphore(0))               # every worker slot is taken
    asked = []

    async def fast(instruction):
        asked.append(instruction)
        return "HASIL: Emas Antam Rp1.900.000/gram (logammulia.com)"
    monkeypatch.setattr(quick, "answer", fast)
    t = await workers.spawn("Harga emas", LOOKUP + quick.CONTEXT_MARK + "Pemilik: harga emas?", "s-lane-1", "test", category="web")
    row = await pool.fetchrow("SELECT runtime, runtime_note FROM tasks WHERE id = $1", t["id"])
    assert (row["runtime"], row["runtime_note"]) == ("ringan", "pencarian sederhana")

    async def done():
        return await pool.fetchval("SELECT status FROM tasks WHERE id = $1", t["id"]) == "completed"
    assert await _wait(done)
    assert "logammulia.com" in await pool.fetchval("SELECT result FROM tasks WHERE id = $1", t["id"]) and asked and await reports.unconfirmed()
    assert await pool.fetchval("SELECT runtime FROM tasks WHERE id = $1", t["id"]) == "ringan"


@needs_db
async def test_a_lookup_that_finds_nothing_becomes_a_hermes_task(pool, monkeypatch):
    from app import quick, workers
    monkeypatch.setattr(workers, "_sem", None)

    async def nothing(instruction):
        return None
    monkeypatch.setattr(quick, "answer", nothing)

    async def hermes_answers(n, text, sid):
        async for e in _done("Antam Rp1.900.000/gram, dari Hermes."):
            yield e
    _hermes(monkeypatch, hermes_answers)
    t = await workers.spawn("Harga emas", LOOKUP, "s-lane-2", "test", category="web")

    async def done():
        return await pool.fetchval("SELECT status FROM tasks WHERE id = $1", t["id"]) == "completed"
    assert await _wait(done, tries=200)
    row = await pool.fetchrow("SELECT runtime, runtime_note, result FROM tasks WHERE id = $1", t["id"])
    assert row["runtime"] == "hermes" and "tidak menemukan jawaban" in row["runtime_note"] and "dari Hermes" in row["result"]


@needs_db
async def test_the_load_and_the_switch_are_on_the_desk(pool, monkeypatch):
    from app import lanes, live, main, workers
    monkeypatch.setattr(workers, "_start", lambda *a, **k: None)
    await workers.spawn("Harga emas", LOOKUP, "s-lane-3", "test", category="web")
    await workers.spawn("Bandingkan laptop", "bandingkan tiga laptop untuk kantor", "s-lane-3", "test", category="analisis")
    v = await lanes.view()
    assert v["light_running"] == 1 and v["hermes_queued"] == 1 and v["light_on"] is True and v["slots"] >= 1
    dev = {"name": "HP pemilik", "scope": "owner"}
    assert (await main.worker_lanes(main.LanesIn(light=False), device=dev))["light_on"] is False
    t = await workers.spawn("Harga lagi", LOOKUP, "s-lane-3", "test", category="web")
    assert await pool.fetchval("SELECT runtime FROM tasks WHERE id = $1", t["id"]) == "hermes"      # off: everything through Hermes
    await main.worker_lanes(main.LanesIn(light=True), device=dev)
    snap = await live.snapshot("utama")
    assert snap["lanes"]["light_on"] is True and {w["runtime"] for w in snap["workers"]} == {"ringan", "hermes"}


def test_hermes_learns_from_similar_work_where_it_belongs():
    from app import episodes
    ok = lambda lane: {"success": True, "lesson": f"berhasil dalam 1 menit, model x, jalur {lane}"}   # noqa: E731
    bad = lambda lane: {"success": False, "lesson": f"gagal dalam 9 menit, jalur {lane}"}             # noqa: E731
    assert episodes.lane_hint([ok("ringan")]) == {"prefer": "ringan", "avoid": set()}
    assert episodes.lane_hint([ok("openjarvis"), ok("ringan")])["prefer"] == "openjarvis"               # the newest similar one counts first
    assert episodes.lane_hint([bad("openjarvis")]) == {"prefer": None, "avoid": {"openjarvis"}}
    nothing = {"success": True, "lesson": "berhasil dalam 4 menit, jalur hermes — jalur ringan tidak menemukan jawaban"}
    assert episodes.lane_hint([nothing])["avoid"] == {"ringan"}
    assert episodes.lane_hint([ok("ringan"), bad("ringan")]) == {"prefer": None, "avoid": {"ringan"}}   # it also failed once: do not trust it
    assert episodes.lane_hint([{"success": True, "lesson": None}]) == {"prefer": None, "avoid": set()}
    assert "jalur ringan" in episodes.pattern(1.0, [], "m/x", 0, True, "ringan")
    assert "jalur ringan tidak menemukan" in episodes.pattern(4.0, [], None, 0, True, "hermes", "Jalur ringan tidak menemukan jawaban — Hermes mengerjakannya")


def test_the_choice_follows_what_was_learned():
    avoid_light = {"avoid": {"ringan"}, "prefer": None}
    assert pick(hint=avoid_light)[0] == "hermes"                                                           # a look-up the light lane could not answer before
    assert pick(hint={"avoid": set(), "prefer": "ringan"}, instruction="Berapa kurs dolar sekarang")[0] == "ringan"
    got = pick(hint={"avoid": set(), "prefer": "openjarvis"}, oj_on=True, category="analisis", instruction="hitung rata-rata pemakaian AI")
    assert got == ("openjarvis", "pola serupa berhasil di OpenJarvis")
    assert pick(hint={"avoid": set(), "prefer": "openjarvis"}, oj_on=False, category="analisis", instruction="hitung rata-rata")[0] == "hermes"
    lane, why = pick(hint={"avoid": {"openjarvis"}, "prefer": None}, heavy=True, oj_on=True)
    assert lane == "hermes" and "pernah gagal di OpenJarvis" in why


@needs_db
async def test_the_two_brains_have_their_own_openrouter_models(pool, monkeypatch):
    from app import composition, gateway, quick, workers
    cats = await gateway.categories()
    assert {"ringan", "berat"} <= set(cats) and {"ringan", "berat"} <= composition.BUILTIN
    assert cats["berat"]["worker"] is True and cats["ringan"]["worker"] is False
    assert all(r["provider"] == "openrouter" for c in ("ringan", "berat") for r in cats[c]["routes"])
    import inspect
    src = inspect.getsource(quick)                    # the test fixture replaces quick.answer, so read what the real one asks for
    assert 'category="ringan"' in src and 'category="cepat"' not in src
    assert 'openjarvis.run(text, "berat"' in inspect.getsource(workers)                                     # the heavy brain's own model


def test_the_light_lane_reads_more_pages_and_skips_empty_ones():
    import inspect
    from app import quick
    src = inspect.getsource(quick)   # the fixture replaces quick.answer; the real one is checked by what it reads
    assert "limit=6" in src and "results[:6]" in src and "if p][:4]" in src and "sources[:6500]" in src
