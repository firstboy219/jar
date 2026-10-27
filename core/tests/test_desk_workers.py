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
