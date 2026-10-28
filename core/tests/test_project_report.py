"""ADR-078: a project's report over all its runs, next to each run's results."""
import os

import pytest

from tests.test_integration import pool  # noqa: F401  (fixture)

needs_db = pytest.mark.skipif(not os.getenv("TEST_DATABASE_URL"), reason="needs TEST_DATABASE_URL")


def test_the_report_adds_up_the_runs():
    from app import projects
    h = [{"run": 3, "started": "c", "total": 2, "completed": 0, "failed": 0, "busy": 2, "cost": 0.0, "minutes": None},
         {"run": 2, "started": "b", "total": 2, "completed": 1, "failed": 1, "busy": 0, "cost": 0.02, "minutes": 12.0},
         {"run": 1, "started": "a", "total": 3, "completed": 3, "failed": 0, "busy": 0, "cost": 0.01, "minutes": 6.0}]
    r = projects.report(h)
    assert r == {"runs": 3, "workers": 7, "completed": 4, "failed": 1, "busy": 2, "success_pct": 80, "cost_usd": 0.03,
                 "median_minutes": 12.0, "last_run": "c"}
    empty = projects.report([])
    assert empty["runs"] == 0 and empty["success_pct"] is None and empty["median_minutes"] is None and empty["last_run"] is None


@needs_db
async def test_the_results_page_carries_the_run_history(pool, monkeypatch):
    from app import main, workers
    monkeypatch.setattr(workers, "_start", lambda task_id, context="": None)
    await pool.execute("DELETE FROM projects")
    dev = {"name": "HP pemilik", "scope": "owner"}
    p = await main.projects_create(main.ProjectIn(name="Laporan emas", roles=[{"role": "Peneliti", "workers": 2}]), device=dev)
    await main.projects_run(p["id"], device=dev)
    await pool.execute("""UPDATE tasks SET status = 'completed', started_at = now() - interval '5 minutes', finished_at = now(), cost_usd = 0.01
                          WHERE id = (SELECT min(id) FROM tasks WHERE project_id = $1)""", p["id"])
    await pool.execute("UPDATE tasks SET status = 'failed', finished_at = now() WHERE project_id = $1 AND status = 'queued'", p["id"])
    await main.projects_run(p["id"], device=dev)
    got = await main.projects_results(p["id"], device=dev)
    assert [h["run"] for h in got["history"]] == [2, 1]
    assert got["history"][1]["completed"] == 1 and got["history"][1]["failed"] == 1 and got["history"][0]["busy"] == 2
    assert got["report"]["runs"] == 2 and got["report"]["success_pct"] == 50 and got["report"]["busy"] == 2
    await pool.execute("DELETE FROM projects")
