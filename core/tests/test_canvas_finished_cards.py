"""ADR-067 (spec: bisan, dev job 6): the desk shows only work in progress — the cards of tasks that ended leave the board by themselves."""
import pytest

from tests.test_integration import pool  # noqa: F401  (fixture)


def test_which_tasks_have_ended():
    from app import canvas
    assert not canvas.task_done("queued") and not canvas.task_done("running")
    for s in ("completed", "failed", "cancelled", "stopped"):
        assert canvas.task_done(s)
    assert not canvas.task_done("something-new") and not canvas.task_done(None)     # unknown: still going, the card stays


@pytest.mark.asyncio
async def test_ended_task_cards_leave_the_board_and_nothing_else_does(pool):
    from app import canvas
    await pool.execute("TRUNCATE canvases CASCADE")

    async def task(title, status):
        return await pool.fetchval("INSERT INTO tasks (session_id, title, instruction, status, result) VALUES ('s', $1, $1, $2, 'hasil') RETURNING id",
                                   title, status)
    going, done, failed, pinned = (await task("Riset", "running"), await task("Laporan", "completed"),
                                   await task("Gagal", "failed"), await task("Penting", "completed"))
    mem = await pool.fetchval("INSERT INTO memories (text, category, source) VALUES ('Suka kopi', 'personal', 'owner') RETURNING id")
    ids = {}
    for ref in (f"task:{going}", f"task:{done}", f"task:{failed}", f"task:{pinned}", f"memory:{mem}"):
        ids[ref] = (await canvas.add("utama", ref, "owner"))["id"]
    await canvas.move(ids[f"task:{pinned}"], "owner", pinned=True)
    await canvas.link(ids[f"task:{going}"], ids[f"task:{done}"], "owner", "lanjutan")
    cid = await pool.fetchval("SELECT canvas_id FROM canvas_nodes WHERE id = $1", ids[f"task:{going}"])
    before = await pool.fetchval("SELECT version FROM canvases WHERE id = $1", cid)

    v = await canvas.view(cid, since=before)
    assert not v.get("unchanged")                                                      # a poller with ?since= sees them go
    refs = {c["ref"] for c in v["cards"]}
    assert refs == {f"task:{going}", f"task:{pinned}", f"memory:{mem}"}                 # running, pinned and non-task cards stay
    assert v["edges"] == []                                                             # the link to the removed card went with it
    left = {r["ref"] for r in await pool.fetch("SELECT ref FROM canvas_nodes WHERE canvas_id = $1", cid)}
    assert f"task:{done}" not in left and f"task:{failed}" not in left
    assert await pool.fetchval("SELECT result FROM tasks WHERE id = $1", done) == "hasil"   # the task and its result are untouched
    assert v["version"] == before + 1                                                   # one change for the whole sweep
    again = await canvas.view(cid)
    assert again["version"] == v["version"]                                             # nothing left to sweep: no needless bump
    await pool.execute("UPDATE tasks SET status = 'completed' WHERE id = $1", going)
    assert f"task:{going}" not in {c["ref"] for c in (await canvas.view(cid))["cards"]}  # it goes as soon as it ends
