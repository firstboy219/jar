"""ADR-073 projects (roles, workers, a model per worker, schedules, web work) and ADR-072 the desk's last activity."""
from datetime import datetime

import pytest

from tests.test_integration import pool  # noqa: F401  (fixture)


def _p(**kw):
    base = {"name": "Cari kerja", "goal": "IT Manager Jakarta", "schedule": "manual",
            "roles": [{"role": "Pencari", "brief": "cari di JobStreet", "workers": 2, "model": "deepseek/deepseek-v4.1-flash", "web": True},
                      {"role": "Penulis", "brief": "surat lamaran", "workers": 1}]}
    return base | kw


def test_a_project_is_checked_before_it_is_kept():
    from app import projects
    p = projects.clean(_p())
    assert [r["workers"] for r in p["roles"]] == [2, 1] and p["roles"][0]["web"] and p["roles"][1]["model"] is None
    for bad, why in ((_p(name=" "), "nama"), (_p(roles=[]), "peran"), (_p(schedule="daily"), "jam"),
                     (_p(schedule="weekly", at_time="08:00"), "hari"), (_p(roles=[{"role": "x", "workers": 5}, {"role": "y", "workers": 5}]), "paling banyak"),
                     (_p(roles=[{"role": "x", "model": "bukan model"}]), "model")):
        with pytest.raises(projects.ProjectError, match=why):
            projects.clean(bad)
    assert projects.clean(_p(roles=[{"role": "x", "workers": 99}]))["roles"][0]["workers"] == 5


def test_the_next_run_follows_the_owners_clock():
    from app import projects
    now = datetime(2026, 10, 27, 7, 30, tzinfo=projects.TZ)   # Tuesday 07:30 WIB
    at = lambda **kw: projects.next_run({"at_time": "08:00", **kw}, now).astimezone(projects.TZ)   # noqa: E731
    assert at(schedule="daily").strftime("%a %H:%M") == "Tue 08:00"
    assert projects.next_run({"schedule": "hourly"}, now).astimezone(projects.TZ).strftime("%H:%M") == "08:00"
    assert at(schedule="weekly", weekday=0).strftime("%a %d") == "Mon 02"                    # next Monday
    sat = datetime(2026, 10, 31, 9, 0, tzinfo=projects.TZ)
    assert projects.next_run({"schedule": "weekdays", "at_time": "08:00"}, sat).astimezone(projects.TZ).strftime("%a %d") == "Mon 02"
    assert projects.next_run({"schedule": "manual"}, now) is None
    assert projects.schedule_text({"schedule": "weekly", "weekday": 4, "at_time": "09:30"}) == "Tiap Jumat 09:30"


def test_a_workers_own_model_goes_first_and_the_category_stays_behind_it():
    from app import gateway
    a, b = (gateway.Route("openrouter", m, "https://x", "k", True, False) for m in ("deepseek/deepseek-v4.1-flash", "qwen/qwen3.7-flash"))
    assert gateway.with_override([b, a], a) == [a, b] and gateway.with_override([b], None) == [b]


@pytest.mark.asyncio
async def test_a_run_starts_every_worker_with_its_role_model_and_the_web_rules(pool, monkeypatch):
    from app import gateway, main, projects, workers
    started = []
    monkeypatch.setattr(workers, "_start", lambda task_id, context="": started.append(task_id))
    dev = {"name": "HP pemilik", "scope": "owner"}
    p = await main.projects_create(main.ProjectIn(**_p(schedule="daily", at_time="08:00")), device=dev)
    assert p["next_run"] and len(p["roles"]) == 2 and p["schedule_text"] == "Tiap hari 08:00"
    r = await main.projects_run(p["id"], device=dev)
    assert r["run"] == 1 and len(r["tasks"]) == 3 == len(started)
    rows = [dict(x) for x in await pool.fetch("SELECT title, instruction, kind, category, model_override, project_run FROM tasks WHERE project_id = $1 ORDER BY id", p["id"])]
    assert [x["title"] for x in rows] == ["Cari kerja · Pencari 1/2", "Cari kerja · Pencari 2/2", "Cari kerja · Penulis"]
    assert all(x["kind"] == "owner" for x in rows) and rows[0]["category"] == "web" and rows[2]["category"] == "analisis"
    assert "MENGOPERASIKAN SITUS" in rows[0]["instruction"] and "BERHENTI sebelum mengirim" in rows[0]["instruction"]
    assert "bagian ke-2" in rows[1]["instruction"] and "MENGOPERASIKAN SITUS" not in rows[2]["instruction"]
    assert rows[0]["model_override"] == "deepseek/deepseek-v4.1-flash" and rows[2]["model_override"] is None
    with pytest.raises(main.HTTPException):
        await main.projects_run(p["id"], device=dev)                                     # the previous run is still busy
    tid = await pool.fetchval("SELECT id FROM tasks WHERE project_id = $1 ORDER BY id LIMIT 1", p["id"])
    gateway._overrides.clear()
    monkeypatch.setattr(gateway, "provider_key", lambda provider, caller="": "test-key")   # the test server has no OpenRouter key
    route = await gateway.override_route(tid, "hermes", False)
    assert route and route.model == "deepseek/deepseek-v4.1-flash"
    assert await gateway.override_route(tid, "hermes", True) is None                     # a private turn never leaves the server
    await pool.execute("UPDATE tasks SET status = 'completed' WHERE project_id = $1", p["id"])
    await pool.execute("UPDATE projects SET next_run = now() - interval '1 minute' WHERE id = $1", p["id"])
    assert await projects.tick() == 1 and (await projects.get(p["id"]))["runs"] == 2           # the schedule starts the next run
    await main.projects_status(p["id"], main.ProjectStatusIn(status="paused"), device=dev)
    assert (await projects.get(p["id"]))["next_run"] is None
    listed = await main.projects_list(device=dev)
    assert listed["projects"][0]["name"] == "Cari kerja" and "cron" in listed


