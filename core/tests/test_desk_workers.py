import asyncio

from app import workers


def row(i: int, **extra) -> dict:
    """One task row as `overview()` feeds it (the dev_role column included)."""
    r = {"id": i, "title": f"tugas {i}", "status": "running", "kind": "task", "category": "analisis", "runtime": "hermes",
         "model_used": None, "hermes_run": f"run-{i}", "error": None, "seconds": 12, "cost_usd": 0.0, "budget_usd": None}
    r.update(extra)
    return r


def test_devteam_rows_are_dropped():
    rows = [row(1), row(2, dev_role="bisan"), row(3, dev_role="coder"), row(4, dev_role="qaqa")]
    assert [r["task_id"] for r in workers.desk_list(rows, {})] == [1]


def test_rows_missing_or_empty_dev_role_stay_in_order():
    rows = [row(5, dev_role=None), row(6), row(7, dev_role=None)]
    assert [r["task_id"] for r in workers.desk_list(rows, {})] == [5, 6, 7]


def test_limit_applies_after_dropping():
    rows = [row(i, dev_role="coder" if i <= 6 else None) for i in range(1, 21)]  # 20 rows, 6 of them dev-team
    out = workers.desk_list(rows, {})   # default limit: DESK_LIMIT
    assert len(out) == workers.DESK_LIMIT == 14
    assert [r["task_id"] for r in out] == list(range(7, 21))


def test_output_shape_keeps_dev_role_out():
    out = workers.desk_list([row(9, dev_role="bisan")], {})  # dropped, nothing to inspect
    assert out == []
    for r in workers.desk_list([row(10), row(11, dev_role=None)], {}):
        assert "dev_role" not in r


def test_devteam_kind_is_never_on_the_worker_board():
    assert workers.on_board("owner") and workers.on_board("routine")
    assert not workers.on_board("devteam")


def test_owner_tasks_drops_the_dev_teams_tasks():
    rows = [row(1, kind="owner"), row(2, kind="devteam"), row(3, kind="devteam"), row(4)]
    assert [r["id"] for r in workers.owner_tasks(rows)] == [1, 4]
    assert workers.owner_tasks([row(5, kind="devteam")]) == []


def test_devteam_is_announced_to_the_desk_but_not_as_a_phone_worker(monkeypatch):
    """The phone builds `Board.workers` from `task` events: a dev-team task goes out as `devtask`, which only the desk's live view reads (ADR-076)."""
    sent = []

    async def fake(payload):
        sent.append(payload)

    monkeypatch.setattr(workers.hub, "broadcast", fake)
    asyncio.run(workers._announce({"id": 7, "title": "bisan · spesifikasi", "kind": "devteam"}, "running"))
    asyncio.run(workers._announce({"id": 8, "title": "laporan", "kind": "owner"}, "running"))
    assert sent == [{"type": "devtask", "id": 7, "title": "bisan · spesifikasi", "status": "running", "kind": "devteam"},
                    {"type": "task", "id": 8, "title": "laporan", "status": "running", "kind": "owner"}]


def test_the_live_view_makes_a_station_for_a_devtask(monkeypatch):
    from app import live
    live.stations.clear()

    class Row(dict):
        pass

    class Pool:
        async def fetchrow(self, *a):
            return Row(private=False, company_id=None)
    monkeypatch.setattr(live.db, "pool", lambda: Pool())
    asyncio.run(live.on_event({"type": "devtask", "id": 41, "title": "coder · perbaiki", "status": "running", "kind": "devteam"}))
    assert 41 in live.stations and live.stations[41].kind == "devteam"
    live.stations.clear()
