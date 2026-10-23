"""Blueprint v2 §15 acceptance criteria, one test each, with fake providers (the living specification of "adaptive").
Heavier mechanics have their own unit/integration tests; these check the CRITERION as the owner would state it."""

import asyncio
import os

import pytest

from tests.test_integration import (_collect, _fake_embed, _fake_providers, _no_memory, _sse, pool)  # noqa: F401  (pool: fixture)

pytestmark = pytest.mark.asyncio


async def _wait(predicate, tries=120, pause=0.05):
    for _ in range(tries):
        if await predicate():
            return True
        await asyncio.sleep(pause)
    return False


def _hermes(monkeypatch, behaviour):
    from app import hermes, memory
    monkeypatch.setattr(memory, "search", _no_memory)
    prompts = []

    async def stream(text, session_id, image=None, **kw):
        prompts.append(text)
        async for ev in behaviour(len(prompts), text, session_id):
            yield ev
    monkeypatch.setattr(hermes, "stream", stream)
    return prompts


async def _done(text="Selesai."):
    from app import hermes
    yield {"type": "done", "reply": hermes.HermesReply(text, 1, 1, 1)}


async def test_01_a_known_task_reuses_the_relevant_skill(pool, monkeypatch):
    from app import capabilities, workers
    _fake_embed(monkeypatch)
    await pool.execute("TRUNCATE capabilities CASCADE")
    await capabilities._upsert("skill:riset-harga", "skill", "riset-harga", "cari harga emas antam sumber terpercaya", own=True)
    await capabilities.record("skill:riset-harga", True, verified=True)

    async def ok(n, text, sid):
        async for e in _done():
            yield e
    prompts = _hermes(monkeypatch, ok)
    await workers.spawn("Cek emas", "Cari harga emas Antam sumber terpercaya hari ini", "s-1", "test")
    assert await _wait(lambda: _prompted(prompts))
    assert "skill:riset-harga" in prompts[0] and "teruji, berhasil 1 dari 1" in prompts[0]  # offered first, with its record


async def _prompted(prompts):
    return bool(prompts)


async def test_02_a_new_task_is_told_how_to_find_methods_and_has_the_tools(pool, monkeypatch):
    from app import mcp_server, workers
    names = {t.name for t in await mcp_server.mcp.list_tools()}
    assert {"capability_search", "task_plan", "task_verify", "skill_submit", "skill_status", "memory_correct"} <= names
    for tool in ("capability_search", "task_plan", "task_verify"):
        assert tool in workers.WORKER_BRIEF or tool.split("_")[0] in workers.WORKER_BRIEF
    assert "kemampuan yang sudah ada" in workers.WORKER_BRIEF and "bukti nyata" in workers.WORKER_BRIEF


async def test_03_a_new_skill_is_tested_before_it_is_published(pool, monkeypatch, tmp_path):
    from app import skills_pipeline as sp
    from tests.test_unit import CASES, GOOD_BODY
    monkeypatch.setattr(sp, "LEARNED_DIR", tmp_path / "learned")
    monkeypatch.setattr(sp, "SANDBOX_DIR", tmp_path / "sb")
    await pool.execute("TRUNCATE skill_drafts, capabilities, reports CASCADE")

    async def doubtful(messages, **kw):
        return '{"ok": false, "alasan": "tidak tercakup"}'
    monkeypatch.setattr(sp.llm, "complete", doubtful)
    await sp.submit("skill-baru", "Membuat laporan tren produk dari sebuah platform beserta rekomendasi", GOOD_BODY, CASES, None)
    for _ in range(100):
        if (await sp.status("skill-baru"))["status"] != "evaluating":
            break
        await asyncio.sleep(0.03)
    assert (await sp.status("skill-baru"))["status"] == "failed_tests" and not (tmp_path / "learned" / "skill-baru").exists()


async def test_04_a_failed_task_records_cause_and_recovery(pool, monkeypatch):
    from app import hermes, workers
    await pool.execute("TRUNCATE episodes")

    async def always_fails(n, text, sid):
        raise hermes.HermesError("HTTP 500: upstream broke")
        yield  # pragma: no cover
    prompts = _hermes(monkeypatch, always_fails)
    t = await workers.spawn("Riset gagal", "Cari data yang tidak pernah berhasil diambil", "s-4", "test")

    async def finished():
        return await pool.fetchval("SELECT status FROM tasks WHERE id = $1", t["id"]) == "failed"
    assert await _wait(finished, tries=200)
    row = await pool.fetchrow("SELECT recovered, error FROM tasks WHERE id = $1", t["id"])
    assert row["recovered"] == 1 and len(prompts) == 2 and "PERCOBAAN KEDUA" in prompts[1]   # one different attempt, then honest failure
    assert await pool.fetchval("SELECT count(*) FROM audit_events WHERE action = 'task.recovering'") >= 1
    assert await _wait(lambda: _episode(pool, t["id"]))
    lesson = await pool.fetchval("SELECT lesson FROM episodes WHERE task_id = $1", t["id"])
    assert lesson and "500" in lesson or "HTTP" in lesson  # the cause is kept for next time


async def _episode(pool, task_id):
    return bool(await pool.fetchval("SELECT 1 FROM episodes WHERE task_id = $1", task_id))


async def test_05_a_repeated_task_starts_from_the_previous_result(pool, monkeypatch):
    from app import config, workers
    monkeypatch.setattr(config.settings, "memory_collection", "test_memory_v2")
    await pool.execute("TRUNCATE episodes")

    async def ok(n, text, sid):
        async for e in _done("Antam Rp1.900.000/gram (logammulia.com)"):
            yield e
    prompts = _hermes(monkeypatch, ok)
    first = await workers.spawn("Harga emas", "Cek harga emas Antam hari ini", "s-5", "test")
    assert await _wait(lambda: _episode(pool, first["id"]))
    await workers.spawn("Harga emas lagi", "Tolong cek harga emas Antam hari ini lagi", "s-5", "test")
    assert await _wait(lambda: _two(prompts))
    assert "TUGAS SERUPA PERNAH DIKERJAKAN" in prompts[1] and "logammulia.com" in prompts[1] and "TUGAS SERUPA" not in prompts[0]


async def _two(prompts):
    return len(prompts) >= 2


async def test_06_a_failing_free_model_is_diagnosed_before_any_paid_fallback(pool, monkeypatch):
    import httpx
    from app import gateway, modelrouter
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")
    gateway._bad.clear()
    modelrouter.forget_health()
    await pool.execute("TRUNCATE llm_usage")
    for _ in range(8):
        await pool.execute("INSERT INTO llm_usage (category, caller, provider, model, ok, latency_ms) VALUES ('web','hermes','openrouter','ok/free:free',true,700)")
    await pool.execute("""UPDATE llm_categories SET allow_free = true, routes = '[{"provider":"openrouter","model":"bad/free:free"},
                          {"provider":"openrouter","model":"paid/model"}]' WHERE name = 'web'""")
    seen = []

    def handler(req):
        import json
        model = json.loads(req.content)["model"]
        seen.append(model)
        return httpx.Response(429, text="rate") if model == "bad/free:free" else httpx.Response(200, content=_sse("ok"), headers={"content-type": "text/event-stream"})
    _fake_providers(monkeypatch, handler)
    await _collect("web", caller="hermes")
    assert seen == ["bad/free:free", "ok/free:free"] and "paid/model" not in seen   # a proven FREE alternative before paying
    assert await pool.fetchval("SELECT fallback_reason FROM llm_usage WHERE model = 'ok/free:free' ORDER BY id DESC LIMIT 1") == "kena batas permintaan (429)"


async def test_07_a_task_over_budget_stops_paying_and_asks(pool, monkeypatch):
    from app import approvals, gateway, modelrouter
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")
    gateway._bad.clear()
    await pool.execute("TRUNCATE llm_usage, approvals CASCADE")
    tid = await pool.fetchval("""INSERT INTO tasks (session_id, title, instruction, kind, category, status, budget_usd)
                                 VALUES ('s', 'Mahal', 'x', 'owner', 'coding', 'running', 0.05) RETURNING id""")
    await pool.execute("INSERT INTO llm_usage (category, caller, provider, model, ok, cost_usd, task_id) VALUES ('coding','hermes','openrouter','p/x',true,0.06,$1)", tid)
    assert await modelrouter.task_over_budget(tid)
    await modelrouter.ask_more_budget(tid)
    assert await pool.fetchval("SELECT phase FROM tasks WHERE id = $1", tid) == "waiting_approval"
    ap = await pool.fetchrow("SELECT id, kind FROM approvals")
    assert ap["kind"] == "task_budget"
    await approvals.decide(ap["id"], True, "owner")
    assert not await modelrouter.task_over_budget(tid)  # approved: the budget grew and work continues


async def test_08_tasks_run_with_the_app_closed_and_wait_for_the_owner(pool, monkeypatch):
    from app import hub, reports, workers
    hub.reset()  # no phone connected
    assert not hub.online()

    async def ok(n, text, sid):
        async for e in _done("Laporan siap."):
            yield e
    _hermes(monkeypatch, ok)
    t = await workers.spawn("Laporan", "Susun laporan singkat tentang cuaca besok", "s-8", "test")
    assert await _wait(lambda: _status(pool, t["id"], "completed"))

    async def reported():
        return any(r["status"] == "pending" for r in await reports.unconfirmed())
    assert await _wait(reported, tries=200)  # the report is kept, pending, until the owner hears it (the wording may take a moment)


async def _status(pool, task_id, want):
    return await pool.fetchval("SELECT status FROM tasks WHERE id = $1", task_id) == want


async def test_09_after_a_backend_restart_interrupted_tasks_are_resumed(pool, monkeypatch):
    from app import workers

    async def ok(n, text, sid):
        async for e in _done("Dilanjutkan."):
            yield e
    _hermes(monkeypatch, ok)
    tid = await pool.fetchval("""INSERT INTO tasks (session_id, title, instruction, kind, category, status, started_at)
                                 VALUES ('s-9', 'Terputus', 'Kerjakan tugas yang terputus restart', 'owner', 'web', 'running', now()) RETURNING id""")
    assert await workers.resume_after_restart() >= 1
    assert await _wait(lambda: _status(pool, tid, "completed"))


async def test_10_an_artifact_really_exists_and_can_be_opened(pool, tmp_path, monkeypatch):
    from docx import Document
    from app import documents
    monkeypatch.setattr(documents, "ROOT", tmp_path)
    doc = await documents.create("Laporan uji", "docx", "# Judul\n\nIsi laporan yang bisa diperiksa.", "test")
    path = next(tmp_path.glob("*.docx"))
    assert path.stat().st_size > 1000 and doc["url"].startswith("/api/v1/documents/")
    text = "\n".join(p.text for p in Document(str(path)).paragraphs)
    assert "Judul" in text and "Isi laporan yang bisa diperiksa." in text   # reopened and read back, not just "created"


async def test_11_risky_changes_need_approval_and_leave_an_audit_trail(pool, monkeypatch, tmp_path):
    from app import approvals, skills_pipeline as sp
    from tests.test_unit import GOOD_BODY
    monkeypatch.setattr(sp, "LEARNED_DIR", tmp_path / "learned")
    monkeypatch.setattr(sp, "SANDBOX_DIR", tmp_path / "sb")
    await pool.execute("TRUNCATE skill_drafts, capabilities, approvals, audit_events CASCADE")
    cases = [{"name": "a", "args": ["1"], "expect": "1"}, {"name": "b", "args": ["2"], "expect": "2"}]
    r = await sp.submit("skrip-uji", "Mencetak angka yang diberikan lewat argumen", GOOD_BODY, cases,
                        {"scripts/main.py": "import sys\nprint(sys.argv[1])\n"})
    for _ in range(100):
        if (await sp.status("skrip-uji"))["status"] == "sandbox_testing":
            break
        await asyncio.sleep(0.03)
    import json
    (tmp_path / "sb" / "results").mkdir(parents=True, exist_ok=True)
    (tmp_path / "sb" / "results" / f"{r['draft_id']}.json").write_text(json.dumps({"cases": [{"name": "a", "ok": True}, {"name": "b", "ok": True}]}))
    await sp.poll()
    assert (await sp.status("skrip-uji"))["status"] == "awaiting_approval" and not (tmp_path / "learned" / "skrip-uji").exists()
    assert await pool.fetchval("SELECT count(*) FROM audit_events WHERE action = 'approval.requested'") == 1
    assert await pool.fetchval("SELECT count(*) FROM audit_events WHERE action = 'skill.submitted'") == 1


async def test_12_an_unavailable_endpoint_goes_to_a_compatible_alternative_or_is_reported(pool, monkeypatch):
    import httpx
    from app import gateway
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")
    gateway._bad.clear()
    await pool.execute("""UPDATE llm_categories SET routes = '[{"provider":"openrouter","model":"dead/one"},
                          {"provider":"openrouter","model":"alive/two"}]' WHERE name = 'ngobrol'""")
    gateway.invalidate()
    _fake_providers(monkeypatch, lambda req: httpx.Response(503, text="down") if b"dead/one" in req.content
                    else httpx.Response(200, content=_sse("dari cadangan"), headers={"content-type": "text/event-stream"}))
    assert await _collect("ngobrol", caller="chat") == "dari cadangan"
    _fake_providers(monkeypatch, lambda req: httpx.Response(503, text="semua mati"))   # everything down: said plainly, not hidden
    with pytest.raises(gateway.GatewayError, match="semua model gagal"):
        await _collect("ngobrol", caller="chat")


async def test_13_secret_data_never_reaches_an_endpoint_that_does_not_fit(pool, monkeypatch):
    from app import gateway, memory, modelrouter
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")
    await pool.execute("""UPDATE llm_categories SET allow_free = true, routes = '[{"provider":"openrouter","model":"x/free:free"},
                          {"provider":"openrouter","model":"x/paid"}]' WHERE name = 'ngobrol'""")
    gateway.invalidate()
    assert [r.model for r in await gateway.plan("ngobrol", private=True)] == ["qwen-lokal"]        # /privat: local only
    modelrouter.NO_FREE.set(True)                                                                   # the owner's own documents
    assert not any(r.model.endswith(":free") or r.model == "openrouter/free" for r in await gateway.plan("ngobrol"))
    modelrouter.NO_FREE.set(False)
    with pytest.raises(memory.MemoryError_):                                                        # secrets never become memories
        await memory.save("api key: sk-or-v1-abcdefghijklmnopqrstuvwxyz123456", "personal", "test")


async def test_14_the_cost_and_model_of_a_hermes_task_are_tracked(pool, monkeypatch):
    import httpx
    from app import gateway
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")
    gateway._bad.clear()
    await pool.execute("TRUNCATE llm_usage")
    await pool.execute("""UPDATE llm_categories SET routes = '[{"provider":"openrouter","model":"p/model"}]' WHERE name = 'web'""")
    gateway.invalidate()
    tid = await pool.fetchval("""INSERT INTO tasks (session_id, title, instruction, kind, category, status, budget_usd)
                                 VALUES ('s', 'x', 'y', 'owner', 'web', 'running', 1.0) RETURNING id""")
    _fake_providers(monkeypatch, lambda req: httpx.Response(200, content=_sse("ok", cost=0.004), headers={"content-type": "text/event-stream"}))
    body = {"messages": [{"role": "user", "content": f"[tugas #{tid}] Cari sesuatu"}]}   # no session header, like real Hermes
    async for _ in gateway.stream("web", body, caller="hermes", worker=True):
        pass
    row = await pool.fetchrow("SELECT cost_usd::float AS c, model_used FROM tasks WHERE id = $1", tid)
    assert row["c"] == pytest.approx(0.004) and row["model_used"] == "p/model"
    assert await pool.fetchval("SELECT task_id FROM llm_usage ORDER BY id DESC LIMIT 1") == tid


async def test_15_a_cancel_after_the_task_finished_does_not_undo_completed(pool, monkeypatch):
    from app import hermes, memory, reports, workers
    monkeypatch.setattr(memory, "search", _no_memory)
    gate = asyncio.Event()

    async def ok(text, session_id, image=None, **kw):
        yield {"type": "done", "reply": hermes.HermesReply("Selesai.", 1, 1, 1)}
    monkeypatch.setattr(hermes, "stream", ok)

    async def slow_report(task_id, title, result, session_id):  # delivery still running when the cancel arrives
        await gate.wait()
    monkeypatch.setattr(reports, "from_task", slow_report)
    t = await workers.spawn("Laporan", "Susun laporan singkat tentang cuaca besok", "s-15", "test")
    assert await _wait(lambda: _status(pool, t["id"], "completed"))
    workers._running[t["id"]].cancel()  # what a shutdown does to a task that is only delivering its report
    await asyncio.sleep(0.2)
    assert await pool.fetchval("SELECT status FROM tasks WHERE id = $1", t["id"]) == "completed"


async def test_16_a_restart_stops_the_old_hermes_runs_and_a_full_hermes_is_waited_for(pool, monkeypatch):
    from app import hermes, memory, workers
    monkeypatch.setattr(memory, "search", _no_memory)
    monkeypatch.setattr(workers, "HERMES_RETRY_S", 0)
    stopped, calls = [], {"n": 0}

    async def stop(run_id):
        stopped.append(run_id)
    monkeypatch.setattr(hermes, "stop", stop)

    async def full_then_ok(text, session_id, image=None, **kw):
        calls["n"] += 1
        if calls["n"] == 1:
            raise hermes.HermesError('Hermes HTTP 429: {"error": {"message": "Too many concurrent runs (max 10)"}}')
        yield {"type": "done", "reply": hermes.HermesReply("Akhirnya dapat slot.", 1, 1, 1)}
    monkeypatch.setattr(hermes, "stream", full_then_ok)
    tid = await pool.fetchval("""INSERT INTO tasks (session_id, title, instruction, kind, category, status, started_at, hermes_run)
                                 VALUES ('s-16', 'Terputus', 'Kerjakan tugas yang terputus restart', 'owner', 'web', 'running', now(), 'run-lama-1') RETURNING id""")
    await workers.resume_after_restart()
    assert stopped == ["run-lama-1"]                        # the orphan is stopped, not left to pile up
    assert await _wait(lambda: _status(pool, tid, "completed"))
    assert calls["n"] == 2                                  # "max 10 runs" was waited out, not turned into a failure
