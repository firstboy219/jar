"""ADR-065: a dev team job that only a human developer can do stops as such (no coder loop), and the owner is told."""
import pytest

from tests.test_integration import pool  # noqa: F401  (fixture)

pytestmark = pytest.mark.asyncio


async def test_bisan_saying_it_needs_a_human_stops_the_job_and_tells_the_owner(pool, monkeypatch):
    from app import dev, devteam, workers
    started = []
    monkeypatch.setattr(workers, "_start", lambda task_id, context="": started.append(task_id))

    async def fake_sync(wait_s=40.0):
        return True
    monkeypatch.setattr(dev, "sync_mirror", fake_sync)
    job = await devteam.request("Hapus kartu tugas yang sudah selesai dari Meja", "owner")
    await devteam.on_result(started[-1], "HASIL\nBUTUH MANUSIA — perlu core/app/canvas.py (zona terlindungi)\nSPESIFIKASI\nTujuan: bersih")
    j = await devteam._job(job["id"])
    assert j["status"] == "needs_human" and "canvas.py" in j["note"] and "SPESIFIKASI" in j["spec"]
    assert len(started) == 1                                                            # no coder was sent on a job it cannot do
    assert "butuh pengembang manusia" in await pool.fetchval("SELECT text FROM reports ORDER BY id DESC LIMIT 1")
    await devteam.on_result(started[-1], "apa saja")                                    # a late result changes nothing
    assert (await devteam._job(job["id"]))["status"] == "needs_human"
