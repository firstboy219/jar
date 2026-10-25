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


# ---------- Blueprint v4, Fase 0: the control point (ADR-047) ----------

async def _code_change_approval(pool):
    from app import approvals
    await pool.execute("TRUNCATE approvals, dev_changes, dev_designs CASCADE")
    cid = await pool.fetchval("INSERT INTO dev_changes (branch, title, why, status) VALUES ('jarvis/uji', 'Uji', 'x', 'awaiting_approval') RETURNING id")
    a = await approvals.create("code_change", "Uji", {"change_id": cid, "branch": "jarvis/uji", "commit": "c"}, "hermes", "high")
    return a["id"], cid


async def test_v4_f0_code_changes_are_approved_only_at_the_admin_page(pool, monkeypatch):
    import httpx
    from app import config, devices, dev, main
    aid, cid = await _code_change_approval(pool)
    _, token = await devices.create("HP pemilik", "test", scope="owner")
    monkeypatch.setattr(config.settings, "admin_token", "admin-secret")
    written = []
    monkeypatch.setattr(dev, "_write_request", lambda change_id, action, **kw: written.append((change_id, action)))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url="http://t") as c:
        r = await c.post(f"/api/v1/console/approvals/{aid}", json={"approve": True}, headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 403 and "halaman admin" in r.json()["detail"]
        assert await pool.fetchval("SELECT status FROM approvals WHERE id = $1", aid) == "awaiting_approval"   # nothing happened
        r = await c.post(f"/admin/approvals/{aid}", json={"approve": True}, headers={"X-Admin-Token": "admin-secret"})
        assert r.status_code == 200 and r.json()["status"] == "completed" and written == [(cid, "deploy")]
        # the app can still REJECT (that is always safe)
        aid2, _ = await _code_change_approval(pool)
        r = await c.post(f"/api/v1/console/approvals/{aid2}", json={"approve": False}, headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 200 and r.json()["status"] == "rejected"
        # and the pause / T2 switches cannot be flipped from the app
        r = await c.post("/api/v1/console/selfdev/control", json={"paused": False}, headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 403


async def test_v4_f0_voice_or_chat_cannot_approve_code_either(pool, monkeypatch):
    from app import chat
    aid, _ = await _code_change_approval(pool)
    t = await chat.handle(f"setujui {aid}", "s-f0", actor="device:HP")
    assert "halaman admin" in t.reply
    assert await pool.fetchval("SELECT status FROM approvals WHERE id = $1", aid) == "awaiting_approval"


async def test_v4_f0_the_pause_switch_stops_every_new_self_change(pool, monkeypatch, tmp_path):
    from app import dev, skills_pipeline as sp
    from tests.test_unit import CASES, GOOD_BODY
    await pool.execute("DELETE FROM settings_kv WHERE key = 'selfdev:control'")
    monkeypatch.setattr(dev, "ROOT", tmp_path)
    await dev.set_control("owner", paused=True)
    with pytest.raises(dev.DevError, match="DIJEDA"):
        await dev.propose("jarvis/lebih-cepat", "Lebih cepat", "alasan")
    with pytest.raises(sp.SkillError, match="DIJEDA"):
        await sp.submit("skill-saat-jeda", "Membuat laporan tren produk dari sebuah platform beserta rekomendasi", GOOD_BODY, CASES, None)
    assert not list(tmp_path.glob("requests/*.json"))            # nothing reached the runner
    await dev.set_control("owner", paused=False)
    r = await dev.propose("jarvis/lebih-cepat", "Lebih cepat", "alasan")
    assert r["status"] == "testing"
    import json
    req = json.loads(next(tmp_path.glob("requests/*.json")).read_text())
    assert req["max_tier"] == 1                                    # without an approved design: T1 only


async def test_v4_f0_t2_needs_the_switch_and_an_approved_design(pool, monkeypatch, tmp_path):
    import json
    from app import approvals, dev
    await pool.execute("TRUNCATE approvals, dev_designs CASCADE")
    await pool.execute("DELETE FROM settings_kv WHERE key = 'selfdev:control'")
    monkeypatch.setattr(dev, "ROOT", tmp_path)
    plan = "Masalah: X lambat. Perubahan: modul A dipecah jadi dua. Risiko: regresi. Uji: tes baru. Batal: revert commit."
    with pytest.raises(dev.DevError, match="belum dibuka"):
        await dev.propose_design("Rekonstruksi A", plan, ["android/app/src/main/java/online/cosger/jarvis/net/CoreApi.kt"])
    await dev.set_control("owner", t2_enabled=True)
    with pytest.raises(dev.DevError, match="zona terlindungi"):
        await dev.propose_design("Ubah admin", plan, ["infra/admin/app/main.py"])
    d = await dev.propose_design("Rekonstruksi A", plan, ["android/app/src/main/java/online/cosger/jarvis/net/CoreApi.kt"])
    with pytest.raises(dev.DevError, match="belum disetujui"):
        await dev.propose("jarvis/rekonstruksi-a", "Rekonstruksi A", "x", design_id=d["design_id"])
    with pytest.raises(approvals.AdminOnly):
        await approvals.decide(d["approval_id"], True, "device:HP")              # not from the app
    await approvals.decide(d["approval_id"], True, "owner", channel="admin")
    r = await dev.propose("jarvis/rekonstruksi-a", "Rekonstruksi A", "x", design_id=d["design_id"])
    assert r["status"] == "testing"
    assert json.loads(next(tmp_path.glob("requests/*.json")).read_text())["max_tier"] == 2
    await dev.set_control("owner", t2_enabled=False)                            # closing T2 again stops it
    with pytest.raises(dev.DevError, match="ditutup"):
        await dev.propose("jarvis/rekonstruksi-b", "B", "x", design_id=d["design_id"])


async def test_v4_f0_the_approval_shows_what_the_runner_found(pool, monkeypatch, tmp_path):
    import json
    from app import dev
    await pool.execute("TRUNCATE approvals, dev_changes CASCADE")
    monkeypatch.setattr(dev, "ROOT", tmp_path)
    cid = await pool.fetchval("INSERT INTO dev_changes (branch, title, why) VALUES ('jarvis/a', 'A', 'kata Jarvis: aman sekali') RETURNING id")
    (tmp_path / "results").mkdir()
    (tmp_path / "results" / f"{cid}-test.json").write_text(json.dumps({
        "id": cid, "action": "test", "status": "passed", "commit": "abc123", "files": ["core/app/charts.py", "core/tests/test_unit.py"],
        "diffstat": "2 files changed", "tests": "server: 160 passed", "verdict": {"ok": True, "tier": 1, "changed_lines": 40}, "log": "ok"}))
    assert await dev.poll() == 1
    a = await pool.fetchrow("SELECT kind, detail, title FROM approvals ORDER BY id DESC LIMIT 1")
    d = a["detail"]
    assert a["kind"] == "code_change" and "(T1)" in a["title"]
    assert d["file_dari_diff_nyata"] == ["core/app/charts.py", "core/tests/test_unit.py"] and d["hasil_tes_dari_penjalan"] == "server: 160 passed"
    assert d["alasan_dari_jarvis_tidak_diverifikasi"] == "kata Jarvis: aman sekali"
    assert (await pool.fetchrow("SELECT tier, tests FROM dev_changes WHERE id = $1", cid))["tests"] == "server: 160 passed"


# ---------- Blueprint v4, Fase 1: Company Federation (ADR-042, ADR-046) ----------

async def _two_companies(pool, monkeypatch):
    from app import companies, gm
    monkeypatch.setenv("VAULT_KEY", "33" * 32)  # company credentials are encrypted with the vault key
    await pool.execute("TRUNCATE companies, company_vault, decision_vault, entity_relations, gm_directives, approvals, reports CASCADE")
    companies.forget()
    monkeypatch.setattr(gm.MockDGM, "behaviour", {})
    monkeypatch.setattr(gm.MockDGM, "sent", [])
    monkeypatch.setattr(gm.MockDGM, "delay_s", 0.01)
    r = await companies.create("PT Renature", "owner", ["renature"])
    j = await companies.create("Jack Healer", "owner", ["jh store"])
    await companies.configure("jack-healer", "owner", dgm_token="token-rahasia-jack-healer")
    await companies.configure("renature", "owner", dgm_token="token-rahasia-renature")
    return r["id"], j["id"]


async def test_v4_f1_renature_never_reads_jack_healer(pool, monkeypatch):
    from app import companies
    _fake_embed(monkeypatch)
    r, j = await _two_companies(pool, monkeypatch)
    await companies.vault_add(r, "kpi", "Omzet", "owner", data={"metric": "Omzet", "value": 120, "unit": "juta IDR", "period": "Okt"})
    await companies.vault_add(r, "core_constraint", "Tidak boleh pakai influencer politik", "owner")
    await companies.vault_add(j, "kpi", "Omzet", "owner", data={"metric": "Omzet", "value": 999, "unit": "juta IDR", "period": "Okt"})
    await companies.vault_add(j, "validated_finding", "Pelanggan JH suka bundling vitamin", "owner")
    await companies.decision_add("company", j, "correction_pivot", "JH pindah ke B2B", "owner")
    ctx = await companies.context_block(r)
    assert "120 juta" in ctx and "influencer" in ctx and "999" not in ctx and "bundling" not in ctx and "B2B" not in ctx
    assert all(e["company_id"] == r for e in await companies.vault_list(r))
    hits = await companies.search(r, "omzet penjualan pelanggan bundling vitamin")
    assert hits and all(h["company_id"] == r for h in hits)                       # Qdrant filter + re-read under r's scope
    assert (await companies.credentials(r))["token"] == "token-rahasia-renature"   # each company decrypts only its own key
    with pytest.raises(companies.CompanyError):
        await companies.vault_list("")                                              # no company → refused
    with pytest.raises(companies.CompanyError):
        await companies.vault_list("perusahaan-hantu")
    # Postgres itself, as a role that does NOT bypass row-level security (production's jarvis_core is such a role)
    await pool.execute("DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'rls_probe') THEN CREATE ROLE rls_probe NOLOGIN; END IF; END $$")
    await pool.execute("GRANT SELECT, INSERT ON company_vault, decision_vault, gm_directives TO rls_probe")
    await pool.execute("GRANT USAGE ON SEQUENCE company_vault_id_seq TO rls_probe")
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute("SET LOCAL ROLE rls_probe")
            assert await conn.fetchval("SELECT count(*) FROM company_vault") == 0      # no company set: nothing visible
            await conn.execute("SELECT set_config('jarvis.company', $1, true)", r)
            rows = await conn.fetch("SELECT company_id FROM company_vault")
            assert rows and {x["company_id"] for x in rows} == {r}                     # even without a WHERE: only Renature
            assert await conn.fetchval("SELECT count(*) FROM decision_vault WHERE company_id = $1", j) == 0
        with pytest.raises(Exception):
            async with conn.transaction():
                await conn.execute("SET LOCAL ROLE rls_probe")
                await conn.execute("SELECT set_config('jarvis.company', $1, true)", r)
                await conn.execute("INSERT INTO company_vault (company_id, kind, title) VALUES ($1, 'note', 'menyusup')", j)


async def test_v4_f1_a_company_task_sees_only_its_company(pool, monkeypatch):
    from app import companies, hermes, memory, workers
    _fake_embed(monkeypatch)
    monkeypatch.setattr(memory, "search", _no_memory)
    r, j = await _two_companies(pool, monkeypatch)
    await companies.vault_add(r, "core_constraint", "Anggaran iklan maksimal 10 juta per bulan", "owner")
    await companies.vault_add(j, "core_constraint", "JH tidak menjual ke luar Jawa", "owner")
    prompts = []

    async def stream(text, session_id, image=None, **kw):
        prompts.append(text)
        yield {"type": "done", "reply": hermes.HermesReply("ok", 1, 1, 1)}
    monkeypatch.setattr(hermes, "stream", stream)
    await workers.spawn("Riset Renature", "Riset kompetitor skincare untuk Renature", "s-c", "owner", company_id=r)
    assert await _wait(lambda: _prompted(prompts))
    assert "KONTEKS PERUSAHAAN: PT Renature" in prompts[0] and "10 juta" in prompts[0] and "luar Jawa" not in prompts[0]


async def test_v4_f1_same_task_key_never_runs_twice(pool, monkeypatch):
    from app import gm
    r, _ = await _two_companies(pool, monkeypatch)
    key = "9b2f6a2e-3a9c-4c7f-9a7e-2f0d3c1b4a55"
    a = await gm.create(r, "laporan", "Rekap penjualan minggu ini per kanal", "owner", task_key=key)
    b = await gm.create(r, "laporan", "Rekap penjualan minggu ini per kanal", "owner", task_key=key)
    assert a["id"] == b["id"] and b.get("duplicate") and len(gm.MockDGM.sent) == 1


async def test_v4_f1_no_callback_means_limited_resends_then_the_owner_is_told(pool, monkeypatch):
    from app import companies, gm
    r, _ = await _two_companies(pool, monkeypatch)
    await companies.configure(r, "owner", max_retries=1, callback_timeout_s=60)
    gm.MockDGM.behaviour[r] = "silent"
    d = await gm.create(r, "laporan", "Rekap stok gudang hari ini", "owner")
    assert d["status"] == "sent" and d["attempts"] == 1
    await pool.execute("UPDATE gm_directives SET deadline = now() - interval '1 second' WHERE id = $1", d["id"])
    assert (await gm.tick())["retried"] == 1
    assert (await gm.get(r, d["id"]))["attempts"] == 2
    assert {x["task_id"] for x in gm.MockDGM.sent} == {str(d["task_key"])}         # the resend carries the SAME key
    await pool.execute("UPDATE gm_directives SET deadline = now() - interval '1 second' WHERE id = $1", d["id"])
    assert (await gm.tick())["timed_out"] == 1
    assert (await gm.get(r, d["id"]))["status"] == "timed_out"
    assert "tidak membalas" in await pool.fetchval("SELECT text FROM reports ORDER BY id DESC LIMIT 1")


async def test_v4_f1_anything_that_changes_the_outside_world_stops_at_approval(pool, monkeypatch):
    from app import approvals, gm
    r, _ = await _two_companies(pool, monkeypatch)
    d = await gm.create(r, "keluarkan_anggaran", "Jalankan iklan Meta untuk produk serum baru", "owner", constraints={"budget_usd": 300})
    assert d["status"] == "awaiting_owner" and d["approval_id"] and gm.MockDGM.sent == []   # nothing went out
    sneaky = await gm.create(r, "rencana", "Susun rencana lalu posting ke Instagram resmi", "owner")
    assert sneaky["status"] == "awaiting_owner"                                     # the words give it away
    await approvals.decide(d["approval_id"], True, "device:HP")                     # the owner's phone may approve company work
    assert (await gm.get(r, d["id"]))["status"] == "sent" and len(gm.MockDGM.sent) == 1


async def test_v4_f1_callbacks_are_signed_deduplicated_and_company_bound(pool, monkeypatch):
    import json
    import time
    from app import approvals, companies, gm
    r, j = await _two_companies(pool, monkeypatch)
    gm.MockDGM.behaviour[r] = "silent"
    d = await gm.create(r, "laporan", "Rekap penjualan minggu ini per kanal", "owner")
    secret_r = (await companies.credentials(r))["callback_secret"]
    secret_j = (await companies.credentials(j))["callback_secret"]
    body = json.dumps({"task_id": str(d["task_key"]), "callback_id": "cb-1", "status": "needs_approval",
                       "result": "Draf siap", "approval_request": {"title": "Bayar vendor foto Rp3 juta"}}).encode()
    ts = str(int(time.time()))
    with pytest.raises(gm.GMError, match="tanda tangan"):
        await gm.callback(r, body, ts, gm.sign(secret_j, ts, body))                # Jack Healer's key cannot speak for Renature
    with pytest.raises(gm.GMError, match="tidak dikenal"):
        await gm.callback(j, body, ts, gm.sign(secret_j, ts, body))                # nor reach Renature's directive via its own URL
    ok = await gm.callback(r, body, ts, gm.sign(secret_r, ts, body))
    assert ok["status"] == "awaiting_owner_result"
    assert (await gm.callback(r, body, ts, gm.sign(secret_r, ts, body)))["duplicate"]   # replay: ignored
    ap = await pool.fetchrow("SELECT id, kind FROM approvals WHERE kind = 'company_action'")
    await approvals.decide(ap["id"], True, "device:HP")
    assert gm.MockDGM.sent[-1] == {"decision": True, "task_id": str(d["task_key"])}   # the decision went back to Hermes-DGM


async def test_v4_f1_mock_dgm_round_trip_and_the_fast_lane(pool, monkeypatch):
    from app import assistant, chat, companies, gm
    r, j = await _two_companies(pool, monkeypatch)
    await companies.vault_add(r, "kpi", "Omzet", "owner", data={"metric": "Omzet", "value": 120, "unit": "juta IDR", "period": "Okt"})
    d = await gm.create(r, "rekap_kpi", "Kirimkan rekap KPI bulan Oktober", "owner")

    async def done():
        return (await gm.get(r, d["id"]))["status"] == "completed"
    assert await _wait(done)                                                       # sent → signed callback → completed → reported
    assert "SIMULASI" in await pool.fetchval("SELECT text FROM reports ORDER BY id DESC LIMIT 1")

    async def never(*a, **k):
        raise AssertionError("the fast lane uses stored data, not a model")
    monkeypatch.setattr(assistant.llm, "stream_chat", never, raising=False)
    t = await chat.handle("berapa KPI Renature sekarang?", "s-kpi", actor="test")
    assert "Omzet: 120 juta IDR (Okt)" in t.reply and "rekap kpi — selesai" in t.reply
    from app import company_lane
    cid, block = await company_lane.situation("bandingkan Renature dengan JH Store")
    assert cid is None and "SATU perusahaan" in block and "120" not in block       # two companies: no data at all


# ---------- Blueprint v4 Fase 3: voice complements (ADR-048) ----------

TTS_MODELS = [{"id": "elevenlabs/eleven-flash-v2.5", "name": "ElevenLabs Flash v2.5", "provider": "elevenlabs", "free": False,
               "price_in": 0.00004, "price_out": 0.0, "price_text": "±$0.040 per 1000 huruf", "voices": ["george", "sarah"],
               "multilingual": True, "expires": None, "description": ""}]
STT_MODELS = [{"id": "openai/whisper-large-v3-turbo", "name": "Whisper turbo", "provider": "openai", "free": False,
               "price_in": 0.0000033, "price_out": 0.0, "price_text": "±$0.012 per jam audio", "voices": [],
               "multilingual": True, "expires": None, "description": ""}]


async def _voice(pool, monkeypatch, tmp_path):
    from app import openrouter, voice
    await pool.execute("TRUNCATE voice_events, voice_data, companies CASCADE")

    async def catalog(kind="speech", force=False):
        return TTS_MODELS if kind == "speech" else STT_MODELS
    monkeypatch.setattr(openrouter, "speech_catalog", catalog)
    monkeypatch.setattr(voice, "VOICE_DIR", tmp_path)
    voice.forget()
    voice._spoken.clear()
    return voice


def _heard(text, engine="whisper", confidence=0.8, stt_ms=3000):
    return {"text": text, "engine": engine, "confidence": confidence, "stt_ms": stt_ms}


async def test_v4_f3_the_baseline_is_measured_per_engine_and_secrets_are_never_stored(pool, monkeypatch, tmp_path):
    voice = await _voice(pool, monkeypatch, tmp_path)
    for h in (_heard("putar lagu santai"), _heard("cek cuaca besok", stt_ms=3400), _heard("ketemu uat jam tiga", "groq", 0.35, 500)):
        out = await voice.process(h, b"\0" * 3200, "s-v1")
        assert out["voice_event"] and out["text"] == h["text"]                       # nothing changes while complements are in shadow
    out = await voice.process(_heard("password: rahasia123 simpan ya"), b"\0" * 3200, "s-v1")
    assert await pool.fetchval("SELECT raw_text FROM voice_events WHERE id = $1", out["voice_event"]) == "[disensor]"
    b = await voice.baseline()
    whisper = next(e for e in b["engines"] if e["engine"] == "whisper")
    groq = next(e for e in b["engines"] if e["engine"] == "groq")
    assert whisper["utterances"] == 3 and whisper["stt_ms_p50"] >= 3000 and groq["low_confidence"] == 1
    assert b["keep_samples"] is False and not list(tmp_path.glob("*.pcm"))          # no consent (K3) → no audio kept
    # the owner's correction labels the utterance and is classified (Fase 3.1 taxonomy)
    fixed = await voice.correct(session_id="s-v1", heard="uat", meant="Ashar", source="owner_chat", actor="device:HP")
    assert fixed["reference"] == "ketemu Ashar jam tiga" and fixed["error_kind"] == "nama"
    assert fixed["learned"] == {"kind": "lexicon", "key": "uat", "value": "Ashar"}
    assert (await voice.baseline())["error_kinds"] == {"nama": 1}


async def test_v4_f3_a_complement_runs_in_shadow_until_the_gate_passes_then_reverts_by_itself(pool, monkeypatch, tmp_path):
    voice = await _voice(pool, monkeypatch, tmp_path)
    first = await voice.process(_heard("rapat sama uat"), b"", "s-v2")
    await voice.correct(event_id=first["voice_event"], heard="uat", meant="Ashar", source="owner_chat", actor="device:HP")
    voice.forget()
    ids = []
    for _ in range(20):                                                              # the dictionary would fix these …
        out = await voice.process(_heard("rapat sama uat"), b"", "s-v2")
        assert out["text"] == "rapat sama uat"                                       # … but in shadow it changes nothing
        ids.append(out["voice_event"])
    shadow = await pool.fetchval("SELECT shadow FROM voice_events WHERE id = $1", ids[0])
    assert shadow == [{"complement": "kamus", "after": "rapat sama Ashar"}]
    for i in ids:
        await voice.correct(event_id=i, full="rapat sama Ashar", source="admin", actor="admin")
    r = await voice.evaluate("test")
    assert "kamus: shadow → on" in r["changed"]
    k = r["complements"]["kamus"]["eval"]
    assert k["passes"] and k["wer_after"] < k["wer_before"] and k["false_corrections"] == 0
    # the utterance the pair was learned from is NOT counted as fixed by it (leave-one-out)
    assert k["fixed"] == 20 and k["samples"] == 21
    live = await voice.process(_heard("rapat sama uat"), b"", "s-v2")
    assert live["text"] == "rapat sama Ashar" and live["raw_text"] == "rapat sama uat"   # now ON: the fix is live, raw kept
    # a bad dictionary entry makes correct utterances wrong → the gate takes the complement back to shadow by itself
    for _ in range(3):
        ok = await voice.process(_heard("putar lagu"), b"", "s-v2")
        await voice.correct(event_id=ok["voice_event"], full="putar lagu", source="admin", actor="admin")
    await voice.data_add("lexicon", "putar", "Pertamina", "admin", "admin")
    r = await voice.evaluate("test")
    assert "kamus: on → shadow" in r["changed"] and r["complements"]["kamus"]["eval"]["false_corrections"] >= 3
    assert await pool.fetchval("SELECT count(*) FROM audit_events WHERE action = 'voice.gate'") == 2
    voice.forget()
    assert (await voice.process(_heard("putar lagu"), b"", "s-v2"))["text"] == "putar lagu"


async def test_v4_f3_echo_of_jarvis_itself_and_learned_hallucinations(pool, monkeypatch, tmp_path):
    voice = await _voice(pool, monkeypatch, tmp_path)
    said = await voice.prepare({"type": "say", "text": "Baik, aku putar lagunya sekarang."})
    out = await voice.process(_heard("baik aku putar lagunya sekarang"), b"", "s-v3")
    assert out["text"] and await pool.fetchval("SELECT shadow FROM voice_events WHERE id = $1", out["voice_event"]) == \
        [{"complement": "gema", "after": ""}]
    await voice.set_mode("gema", "on", "admin")
    out = await voice.process(_heard("baik aku putar lagunya sekarang"), b"", "s-v3")
    assert out["text"] == "" and out["dropped"] == "gema" and said["text"].startswith("Baik")
    assert (await voice.process(_heard("putar lagu jazz"), b"", "s-v3"))["text"] == "putar lagu jazz"   # the owner is still heard
    # the owner disowns the same short phrase twice → it is learned as a hallucination (data, versioned, undoable)
    for _ in range(2):
        await voice.process(_heard("terima kasih semuanya"), b"", "s-v3")
        await voice.correct(session_id="s-v3", not_me=True, source="owner_chat", actor="device:HP")
    rows = await voice.data_list("hallucination")
    assert [r["key"] for r in rows] == ["terima kasih semuanya"] and rows[0]["source"] == "learned"
    assert await voice.data_remove(rows[0]["id"], "admin") and not await voice.data_list("hallucination")
    assert len(await voice.data_list("hallucination", include_removed=True)) == 1           # history kept


async def test_v4_f3_cloud_voice_never_reads_private_text_respects_the_budget_and_records_cost(pool, monkeypatch, tmp_path):
    import httpx
    voice = await _voice(pool, monkeypatch, tmp_path)
    from app import budget, config
    monkeypatch.setattr(config.settings, "openrouter_api_key", "sk-or-test")
    monkeypatch.setattr(voice, "GEN_DELAY_S", 0)
    calls = []

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append(req.url.path)
        if req.url.path.endswith("/audio/speech"):
            import json as _j
            body = _j.loads(req.content)
            assert body["voice"] == "george" and "rupiah" in body["input"]       # the normalised copy is what gets spoken
            return httpx.Response(200, content=b"ID3fake-mp3", headers={"content-type": "audio/mpeg", "x-generation-id": "gen-1"})
        return httpx.Response(200, json={"data": {"total_cost": 0.0012}})
    monkeypatch.setattr(voice, "_client", lambda timeout: httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    with pytest.raises(voice.VoiceError):
        await voice.set_settings({"tts": {"engine": "openrouter", "model": "elevenlabs/eleven-flash-v2.5", "voice": "darth"}}, "device:HP")
    opts = await voice.set_settings({"tts": {"engine": "openrouter", "model": "elevenlabs/eleven-flash-v2.5", "voice": "george"}}, "device:HP")
    assert opts["tts"]["engine"] == "openrouter" and opts["tts"]["models"][0]["voices"] == ["george", "sarah"]
    ev = await voice.prepare({"type": "reply", "text": "Saldo Rp 1.500.000"})
    assert ev["text"] == "Saldo Rp 1.500.000" and ev["speech"] == "Saldo satu juta lima ratus ribu rupiah" and "local_voice" not in ev
    audio = await voice.synthesize(ev["speech"])
    assert audio == b"ID3fake-mp3"
    assert await voice.synthesize(ev["speech"]) == audio and calls.count("/api/v1/audio/speech") == 1   # cached
    assert await _wait(lambda: pool.fetchval("SELECT cost_usd = 0.0012 FROM llm_usage WHERE category = 'suara'"))
    for private in ("/privat saldo rekeningku", "password: rahasia123"):
        with pytest.raises(voice.VoiceError) as e:
            await voice.synthesize(private)
        assert e.value.status == 409
    assert (await voice.prepare({"type": "say", "text": "password: rahasia123"}))["local_voice"] is True
    assert (await voice.prepare({"type": "reply", "text": "isi lampiran"}, local_voice=True))["local_voice"] is True
    await pool.execute("INSERT INTO settings_kv (key, value) VALUES ('budget:total', '1')")
    await pool.execute("INSERT INTO llm_usage (category, caller, provider, model, cost_usd, ok) VALUES ('ngobrol', 't', 'openrouter', 'm', 5, true)")
    budget.forget()
    with pytest.raises(voice.VoiceError) as e:
        await voice.synthesize("kalimat baru yang belum ada di cache")
    assert e.value.status == 402


async def test_v4_f3_owner_controls_voice_by_chat_and_consent_is_admin_page_only(pool, monkeypatch, tmp_path):
    import httpx
    voice = await _voice(pool, monkeypatch, tmp_path)
    from app import assistant, config, devices, main
    out = await assistant._voice_tool("voice_settings", {"query": "eleven"}, "device:HP", "s-v5", None, None, False)
    assert out["pilihan"][0]["id"] == "elevenlabs/eleven-flash-v2.5" and out["sekarang"]["engine"] == "android"
    out = await assistant._voice_tool("voice_settings", {"model": "elevenlabs/eleven-flash-v2.5", "voice": "sarah"},
                                      "device:HP", "s-v5", None, None, False)
    assert out["suara_sekarang"]["engine"] == "openrouter" and out["suara_sekarang"]["voice"] == "sarah"
    refused = await assistant._voice_tool("voice_settings", {"engine": "android"}, "device:HP", "s-v5", None, {"is_owner": False}, False)
    assert "pemilik" in refused["error"]
    out = await assistant._voice_tool("voice_pronounce", {"word": "Renature", "say_as": "ri-ne-cer"}, "device:HP", "s-v5", None, None, False)
    assert "ri-ne-cer" in out["dipelajari"]
    voice.forget()
    assert (await voice.prepare({"type": "say", "text": "Renature naik 7%"}))["text"] == "ri-ne-cer naik tujuh persen"
    assert "MENYANGKUT UANG" in assistant._user_content("transfer lima juta ke Budi", None, stt={"confidence": 0.9})
    assert "MENYANGKUT UANG" not in assistant._user_content("putar lagu jam 5", None, stt={"confidence": 0.9})
    # K3 consent and the complements' switches belong to the admin page, never the app console
    _, token = await devices.create("HP pemilik", "test", scope="owner")
    monkeypatch.setattr(config.settings, "admin_token", "admin-secret")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url="http://t") as c:
        app_h, admin_h = {"Authorization": f"Bearer {token}"}, {"X-Admin-Token": "admin-secret"}
        assert (await c.post("/api/v1/console/voice/settings", json={"keep_samples": True}, headers=app_h)).status_code == 403
        assert (await c.post("/api/v1/console/voice/complements/kamus", json={"mode": "on"}, headers=app_h)).status_code == 403
        assert (await c.post("/admin/voice/settings", json={"keep_samples": True}, headers=admin_h)).status_code == 200
        r = await c.get("/api/v1/voice", headers=app_h)
        assert r.status_code == 200 and r.json()["tts"]["voice"] == "sarah"
        r = await c.put("/api/v1/voice", json={"tts": {"engine": "android"}}, headers=app_h)
        assert r.status_code == 200 and r.json()["tts"]["engine"] == "android"
        r = await c.post("/api/v1/voice/speak", json={"text": "halo"}, headers=app_h)
        assert r.status_code == 422                                                   # android chosen → the phone speaks itself
    assert await voice.keep_samples()
    out = await voice.process(_heard("ketemu uat", confidence=0.3), b"\1" * 3200, "s-v5")
    assert (tmp_path / f"{out['voice_event']}.pcm").exists()                          # with consent, doubtful audio is kept here
