# Hidden tests for problem p2 (spike, ADR-043), from test_16 of the real fix (dc0dfb1), split in its two causes.
import asyncio

import pytest

from tests.test_integration import _no_memory, pool  # noqa: F401  (pool: fixture)

pytestmark = pytest.mark.asyncio


async def _wait(predicate, tries=120, pause=0.05):
    for _ in range(tries):
        if await predicate():
            return True
        await asyncio.sleep(pause)
    return False


async def _status(pool, task_id, want):
    return await pool.fetchval("SELECT status FROM tasks WHERE id = $1", task_id) == want


def _setup(monkeypatch, full_calls: int):
    from app import hermes, memory, workers
    monkeypatch.setattr(memory, "search", _no_memory)
    monkeypatch.setattr(workers, "HERMES_RETRY_S", 0)
    stopped, calls = [], {"n": 0}

    async def stop(run_id):
        stopped.append(run_id)
    monkeypatch.setattr(hermes, "stop", stop)

    async def stream(text, session_id, image=None, **kw):
        calls["n"] += 1
        if calls["n"] <= full_calls:
            raise hermes.HermesError('Hermes HTTP 429: {"error": {"message": "Too many concurrent runs (max 10)"}}')
        yield {"type": "done", "reply": hermes.HermesReply("Akhirnya dapat slot.", 1, 1, 1)}
    monkeypatch.setattr(hermes, "stream", stream)
    return stopped, calls


async def test_a_restart_stops_the_old_hermes_runs(pool, monkeypatch):
    from app import workers
    stopped, _ = _setup(monkeypatch, full_calls=0)
    tid = await pool.fetchval("""INSERT INTO tasks (session_id, title, instruction, kind, category, status, started_at, hermes_run)
                                 VALUES ('s-p2a', 'Terputus', 'Kerjakan tugas yang terputus restart', 'owner', 'web', 'running', now(), 'run-lama-1') RETURNING id""")
    await workers.resume_after_restart()
    assert stopped == ["run-lama-1"]
    assert await _wait(lambda: _status(pool, tid, "completed"))


async def test_a_full_hermes_is_waited_for_not_a_failure(pool, monkeypatch):
    from app import workers
    _, calls = _setup(monkeypatch, full_calls=3)   # full for a while (more than the one automatic second attempt covers)
    tid = await pool.fetchval("""INSERT INTO tasks (session_id, title, instruction, kind, category, status)
                                 VALUES ('s-p2b', 'Penuh', 'Kerjakan walau Hermes sedang penuh', 'owner', 'web', 'queued') RETURNING id""")
    workers._start(tid)
    assert await _wait(lambda: _status(pool, tid, "completed"), tries=400)
    assert calls["n"] >= 4
    assert await pool.fetchval("SELECT recovered FROM tasks WHERE id = $1", tid) == 0   # waited, not failed-and-retried
