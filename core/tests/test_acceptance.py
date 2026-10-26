"""Blueprint v2 §15 acceptance criteria, one test each, with fake providers (the living specification of "adaptive").
Heavier mechanics have their own unit/integration tests; these check the CRITERION as the owner would state it."""

import asyncio
import json
import os
import time

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
    assert (await gm.get(r, d["id"]))["status"] in ("sent", "completed") and len(gm.MockDGM.sent) == 1   # the mock may already have answered


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


# ---------- Blueprint v4 Fase 4: the 3D canvas (ADR-049) ----------

async def _task(pool, title, company=None, status="completed", result="hasil"):
    return await pool.fetchval("""INSERT INTO tasks (session_id, title, instruction, status, result, company_id)
                                  VALUES ('s', $1, $1, $2, $3, $4) RETURNING id""", title, status, result, company)


async def test_v4_f4_each_context_is_its_own_galaxy_and_companies_never_mix(pool, monkeypatch):
    from app import canvas, companies
    await pool.execute("TRUNCATE canvases CASCADE")
    r, j = await _two_companies(pool, monkeypatch)
    rv = await companies.vault_add(r, "kpi", "Omzet Renature", "owner", data={"metric": "Omzet", "value": 120, "unit": "juta", "period": "Okt"})
    jv = await companies.vault_add(j, "validated_finding", "Rahasia dagang JH", "owner")
    rt = await _task(pool, "Riset pasar Renature", company=r)
    mine = await _task(pool, "Cari resep rendang")
    mem = await pool.fetchval("INSERT INTO memories (text, category, source) VALUES ('Aku suka kopi tubruk', 'personal', 'owner') RETURNING id")
    await canvas.add(f"company:{r}", f"vault:{rv['id']}", "owner")
    await canvas.add(f"company:{r}", f"task:{rt}", "owner")
    await canvas.add("utama", f"task:{mine}", "owner")
    await canvas.add("utama", f"memory:{mem}", "owner")
    refused = [(f"company:{r}", f"vault:{jv['id']}"), (f"company:{r}", f"memory:{mem}"), (f"company:{r}", f"task:{mine}"),
               ("utama", f"vault:{rv['id']}"), ("utama", f"task:{rt}"), (f"company:{j}", f"task:{rt}")]
    for ctx, ref in refused:
        with pytest.raises(canvas.CanvasError):
            await canvas.add(ctx, ref, "owner")
    rc, uc = await canvas.ensure(f"company:{r}"), await canvas.ensure("utama")
    rview, uview = await canvas.view(rc["id"]), await canvas.view(uc["id"])
    assert {c["ref"] for c in rview["cards"]} == {f"vault:{rv['id']}", f"task:{rt}"}
    assert {c["ref"] for c in uview["cards"]} == {f"task:{mine}", f"memory:{mem}"}
    assert "120" in next(c for c in rview["cards"] if c["ref"].startswith("vault"))["snippet"]
    assert "Rahasia" not in json.dumps(rview, default=str) and "Renature" not in json.dumps(uview, default=str)
    assert {c["kind"] for c in rview["constellations"]} == {"tugas", "perusahaan", "arahan", "dokumen", "keputusan"}
    assert "memori" in {c["kind"] for c in uview["constellations"]} and "arahan" not in {c["kind"] for c in uview["constellations"]}
    titles = {c["context"]: c for c in await canvas.contexts()}
    assert set(titles) >= {"utama", f"company:{r}", f"company:{j}"} and titles[f"company:{r}"]["cards"] == 2
    # Postgres itself: as a role without the RLS bypass, Jack Healer's scope sees none of Renature's canvas
    await pool.execute("DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'rls_probe') THEN CREATE ROLE rls_probe NOLOGIN; END IF; END $$")
    await pool.execute("GRANT SELECT, INSERT ON canvases, canvas_nodes TO rls_probe")
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute("SET LOCAL ROLE rls_probe")
            await conn.execute("SELECT set_config('jarvis.company', $1, true)", j)
            assert await conn.fetchval("SELECT count(*) FROM canvas_nodes WHERE company_id = $1", r) == 0
            assert await conn.fetchval("SELECT count(*) FROM canvases WHERE company_id = $1", r) == 0
            assert await conn.fetchval("SELECT count(*) FROM canvas_nodes WHERE company_id IS NULL") == 2   # personal cards are not a company's
        with pytest.raises(Exception):
            async with conn.transaction():
                await conn.execute("SET LOCAL ROLE rls_probe")
                await conn.execute("SELECT set_config('jarvis.company', $1, true)", j)
                await conn.execute("INSERT INTO canvas_nodes (canvas_id, company_id, kind, ref) VALUES ($1, $2, 'tugas', 'task:999')", rc["id"], r)


async def test_v4_f4_jarvis_places_its_work_and_the_canvas_holds_layout_not_knowledge(pool, monkeypatch):
    from app import canvas, stage, workers
    await pool.execute("TRUNCATE canvases, stage_history CASCADE")
    await stage.show("text", {"text": "Ringkasan cuaca minggu ini"}, "Cuaca minggu ini")
    shown = await pool.fetchval("SELECT id FROM stage_history ORDER BY id DESC LIMIT 1")
    tid = await _task(pool, "Bandingkan harga laptop")
    await canvas.auto(f"task:{tid}")
    await canvas.auto(f"task:{tid}")                                                   # idempotent: one card
    doc = await pool.fetchval("""INSERT INTO documents (title, format, filename, size, task_id, created_by)
                                 VALUES ('Perbandingan laptop', 'docx', 'x.docx', 10, $1, 'jarvis') RETURNING id""", tid)
    await canvas.auto(f"doc:{doc}")
    c = await canvas.ensure("utama")
    v = await canvas.view(c["id"])
    assert {x["ref"] for x in v["cards"]} == {f"shown:{shown}", f"task:{tid}", f"doc:{doc}"}
    assert next(x for x in v["cards"] if x["ref"] == f"doc:{doc}")["url"] == f"/api/v1/documents/{doc}"
    # the canvas stores references only; the text comes from where it lives, and follows it
    cols = {r["column_name"] for r in await pool.fetch("SELECT column_name FROM information_schema.columns WHERE table_name = 'canvas_nodes'")}
    assert not cols & {"text", "title", "body", "content", "snippet"}
    await pool.execute("UPDATE tasks SET title = 'Bandingkan harga laptop gaming' WHERE id = $1", tid)
    assert any(x["title"] == "Bandingkan harga laptop gaming" for x in (await canvas.view(c["id"]))["cards"])
    # a private task never becomes a card
    priv = await pool.fetchval("INSERT INTO tasks (session_id, title, instruction, status, private) VALUES ('s', 'rahasia', 'x', 'queued', true) RETURNING id")
    assert priv and "rahasia" not in json.dumps(await canvas.view(c["id"]), default=str)
    # end to end: a worker finishing an owner task puts its card on the galaxy by itself
    _hermes(monkeypatch, lambda n, text, sid: _done("Laptop A paling hemat."))
    t = await workers.spawn("Cek harga SSD", "Cek harga SSD 1TB", "s-f4", "test")
    assert await _wait(lambda: pool.fetchval("SELECT status = 'completed' FROM tasks WHERE id = $1", t["id"]))
    assert await _wait(lambda: pool.fetchval("SELECT count(*) = 1 FROM canvas_nodes WHERE ref = $1", f"task:{t['id']}"))


async def test_v4_f4_moves_links_focus_versions_and_hiding_never_deletes_data(pool, monkeypatch):
    from app import canvas
    await pool.execute("TRUNCATE canvases CASCADE")
    a, b = await _task(pool, "Tugas A"), await _task(pool, "Tugas B")
    na = await canvas.add("utama", f"task:{a}", "owner")
    nb = await canvas.add("utama", f"task:{b}", "owner")
    c = await canvas.ensure("utama")
    moved = await canvas.move(na["id"], "owner", x=12345.5, y=-300, z=88)
    assert (moved["x"], moved["y"]) == (12345.5, -300)                                 # anywhere in the infinite space
    with pytest.raises(canvas.CanvasError):
        await canvas.move(na["id"], "owner", x=float("inf"))
    e = await canvas.link(na["id"], nb["id"], "owner", "lanjutan")
    v1 = await canvas.view(c["id"])
    assert v1["edges"] == [{"id": e["id"], "a": na["id"], "b": nb["id"], "label": "lanjutan", "style": {}}]
    assert (await canvas.view(c["id"], since=v1["version"]))["unchanged"]
    f = await canvas.focus("utama", f"task:{b}", "jarvis")
    assert (await canvas.view(c["id"]))["focus"] == nb["id"] and f["version"] > v1["version"]
    before_hide = (await canvas.versions(c["id"]))[0]["version"]
    assert await canvas.hide(nb["id"], "owner")
    assert await pool.fetchval("SELECT count(*) FROM tasks WHERE id = $1", b) == 1     # the task itself is untouched
    v2 = await canvas.view(c["id"])
    assert [x["ref"] for x in v2["cards"]] == [f"task:{a}"] and v2["edges"] == []
    r = await canvas.restore(c["id"], before_hide, "owner")
    v3 = await canvas.view(c["id"])
    assert r["cards"] == 2 and {x["ref"] for x in v3["cards"]} == {f"task:{a}", f"task:{b}"} and len(v3["edges"]) == 1
    assert next(x for x in v3["cards"] if x["ref"] == f"task:{a}")["x"] == 12345.5


async def test_v4_f4_viewer_is_served_safely_and_the_api_needs_the_owner(pool, monkeypatch):
    import httpx
    from app import devices, main
    await pool.execute("TRUNCATE canvases CASCADE")
    _, token = await devices.create("HP pemilik", "test", scope="owner")
    _, guest = await devices.create("Tamu", "test", scope="device")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url="http://t") as c:
        r = await c.get("/canvas/")
        assert r.status_code == 200 and "Papan JARVIS" in r.text
        csp = r.headers["content-security-policy"]
        assert "default-src 'self'" in csp and "frame-ancestors 'none'" in csp and "unsafe-eval'" not in csp.replace("wasm-unsafe-eval'", "")
        for f in ("app.js", "lib.js", "board.js", "chrome.js", "gestures.js", "gesture.html"):
            assert (await c.get(f"/canvas/{f}")).status_code == 200
        assert (await c.get("/canvas/../main.py")).status_code == 404 and (await c.get("/canvas/%2e%2e/main.py")).status_code == 404
        assert (await c.get("/api/v1/canvases")).status_code == 401
        h, g = {"Authorization": f"Bearer {token}"}, {"Authorization": f"Bearer {guest}"}
        opened = (await c.post("/api/v1/canvases", json={"context": "project:Toko Online"}, headers=h)).json()
        assert opened["context"] == "project:toko-online"
        tid = await _task(pool, "Desain logo toko")
        assert (await c.post(f"/api/v1/canvases/{opened['id']}/cards", json={"ref": f"task:{tid}"}, headers=g)).status_code == 403
        card = (await c.post(f"/api/v1/canvases/{opened['id']}/cards", json={"ref": f"task:{tid}"}, headers=h)).json()
        found = (await c.get(f"/api/v1/canvases/{opened['id']}/search?q=logo", headers=h)).json()
        assert found[0]["ref"] == f"task:{tid}"
        assert (await c.patch(f"/api/v1/canvas/cards/{card['id']}", json={"x": 1, "y": 2, "z": 3}, headers=h)).json()["z"] == 3
        view = (await c.get(f"/api/v1/canvases/{opened['id']}", headers=g)).json()      # anyone paired may look
        assert view["cards"][0]["title"] == "Desain logo toko" and view["constellations"]


async def test_v4_f2_spike_keys_reach_only_the_spike_model_and_stop_at_its_budget(pool, monkeypatch):
    import hashlib

    import httpx
    from app import billing, config, main, spike
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")
    monkeypatch.setattr(billing, "_last_notified", 0.0)
    monkeypatch.setattr(config.settings, "llm_gateway_key", "hermes-key")
    seen = []

    def handler(request):
        seen.append(json.loads(request.content)["model"])
        return httpx.Response(200, content=_sse("ok", cost=0.3), headers={"content-type": "text/event-stream"})
    # what migration 025 seeds (the test fixture points every category at the local model)
    await pool.execute("""UPDATE llm_categories SET budget_usd = 1.00,
                          routes = '[{"provider": "openrouter", "model": "deepseek/deepseek-v4.1-flash"}]' WHERE name = 'spike'""")
    _fake_providers(monkeypatch, handler)
    for rt, key in (("hermes", "k-h"), ("openjarvis", "k-oj")):
        await pool.execute("INSERT INTO settings_kv (key, value) VALUES ($1, to_jsonb($2::text)) ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value",
                           f"spike:key:{rt}", hashlib.sha256(key.encode()).hexdigest())
    spike.forget_keys()
    body = {"model": "jarvis-spike", "stream": True, "messages": [{"role": "user", "content": "halo"}]}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url="http://t") as c:
        r = await c.post("/llm/v1/chat/completions", json=body, headers={"Authorization": "Bearer salah"})
        assert r.status_code == 401
        r = await c.post("/llm/v1/chat/completions", json={**body, "model": "jarvis-web"}, headers={"Authorization": "Bearer k-oj"})
        assert r.status_code == 403                                            # a spike key is good for the spike only
        r = await c.get("/llm/v1/models", headers={"Authorization": "Bearer k-oj"})
        assert [m["id"] for m in r.json()["data"]] == ["jarvis-spike"]
        r = await c.post("/llm/v1/chat/completions", json=body, headers={"Authorization": "Bearer k-oj"})
        assert r.status_code == 200 and "ok" in r.text
        assert seen == ["deepseek/deepseek-v4.1-flash"]                      # the spike model, nothing else in front
        row = await pool.fetchrow("SELECT caller, category FROM llm_usage ORDER BY id DESC LIMIT 1")
        assert (row["caller"], row["category"]) == ("spike-openjarvis", "spike")   # cost is attributed per runtime
        # past the $1 cap: no safety model, no local fallback — the call is refused
        await pool.execute("INSERT INTO llm_usage (category, caller, provider, model, cost_usd, ok) VALUES ('spike', 'spike-hermes', 'openrouter', 'x', 1.5, true)")
        r = await c.post("/llm/v1/chat/completions", json=body, headers={"Authorization": "Bearer k-h"})
        assert r.status_code == 502 and "anggaran" in r.text
        assert seen == ["deepseek/deepseek-v4.1-flash"]
        # the real Hermes key still works for everything
        r = await c.post("/llm/v1/chat/completions", json={**body, "model": "jarvis-web"}, headers={"Authorization": "Bearer hermes-key"})
        assert r.status_code == 200
    spike.forget_keys()


async def _openjarvis_env(pool, monkeypatch, on=True, answer=None, error=None):
    from app import hermes, memory, openjarvis
    monkeypatch.setattr(memory, "search", _no_memory)
    sent, prompts = [], []

    async def run(text, category, session_id):
        sent.append((text, category, session_id))
        if error:
            raise openjarvis.OpenJarvisError(error)
        return answer
    monkeypatch.setattr(openjarvis, "run", run)

    async def hermes_stream(text, session_id, image=None, **kw):
        prompts.append(text)
        yield {"type": "done", "reply": hermes.HermesReply("Hasil dari Hermes.", 1, 1, 1)}
    monkeypatch.setattr(hermes, "stream", hermes_stream)
    await openjarvis.set_enabled(on)
    return sent, prompts


async def _heavy_task(workers, **kw):
    return await workers.spawn("Analisis besar", "Analisis pemakaian AI seminggu dan beri saran konkret.", "s-oj", "test",
                               heavy=True, category="analisis", **kw)


async def test_v4_f2_a_heavy_task_goes_to_openjarvis_when_it_is_on(pool, monkeypatch):
    from app import workers
    sent, prompts = await _openjarvis_env(pool, monkeypatch, answer="Kategori web paling lambat; pindahkan ke model cepat untuk menghemat waktu.")
    t = await _heavy_task(workers)
    assert await _wait(lambda: _status(pool, t["id"], "completed"))
    row = await pool.fetchrow("SELECT runtime, runtime_note, result FROM tasks WHERE id = $1", t["id"])
    assert row["runtime"] == "openjarvis" and row["runtime_note"] is None and "Kategori web" in row["result"]
    assert prompts == []                                                               # Hermes was never asked
    assert sent[0][1] == "analisis" and sent[0][0].startswith(f"[tugas #{t['id']}]")   # the number ties the gateway's cost to the task
    assert "capability_search" not in sent[0][0] and "task_plan" not in sent[0][0]      # no Hermes-only instructions leak to it


async def test_v4_f2_a_failed_openjarvis_hands_the_task_to_hermes(pool, monkeypatch):
    from app import workers
    sent, prompts = await _openjarvis_env(pool, monkeypatch, error="model mengirim panggilan alat sebagai teks mentah, tidak dijalankan")
    t = await _heavy_task(workers)
    assert await _wait(lambda: _status(pool, t["id"], "completed"))
    row = await pool.fetchrow("SELECT runtime, runtime_note, result FROM tasks WHERE id = $1", t["id"])
    assert row["runtime"] == "hermes" and "teks mentah" in row["runtime_note"] and "Hasil dari Hermes." in row["result"]
    assert len(prompts) == 1 and len(sent) == 1                                         # one try, then Hermes — the owner gets an answer
    assert await pool.fetchval("SELECT count(*) FROM audit_events WHERE action = 'task.openjarvis_fallback'") >= 1


async def test_v4_f2_openjarvis_is_off_by_default_and_never_gets_private_or_normal_tasks(pool, monkeypatch):
    from app import openjarvis, workers
    sent, prompts = await _openjarvis_env(pool, monkeypatch, on=False, answer="x" * 40)
    t = await _heavy_task(workers)                                                      # heavy, but the owner has not switched it on
    assert await _wait(lambda: _status(pool, t["id"], "completed"))
    assert (await pool.fetchval("SELECT runtime FROM tasks WHERE id = $1", t["id"])) == "hermes" and sent == []
    await openjarvis.set_enabled(True)
    t = await _heavy_task(workers, private=True)                                        # /privat never leaves the local model
    n = await workers.spawn("Biasa", "Cek harga emas hari ini dan ringkas.", "s-oj", "test")   # not marked heavy
    for task in (t, n):
        assert await _wait(lambda task=task: _status(pool, task["id"], "completed"))
        assert (await pool.fetchval("SELECT runtime FROM tasks WHERE id = $1", task["id"])) == "hermes"
    assert sent == []


async def test_v4_f2_the_openjarvis_gateway_key_reaches_worker_categories_only(pool, monkeypatch):
    import hashlib

    import httpx
    from app import billing, config, main
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")
    monkeypatch.setattr(billing, "_last_notified", 0.0)
    monkeypatch.setattr(config.settings, "llm_gateway_key", "hermes-key")
    seen = []

    def handler(request):
        seen.append(json.loads(request.content)["model"])
        return httpx.Response(200, content=_sse("ok", cost=0.001), headers={"content-type": "text/event-stream"})
    _fake_providers(monkeypatch, handler)
    await pool.execute("UPDATE llm_categories SET routes = '[{\"provider\":\"openrouter\",\"model\":\"m/work\"}]' WHERE name IN ('analisis', 'ngobrol', 'privat')")
    await pool.execute("INSERT INTO settings_kv (key, value) VALUES ('worker:key:openjarvis', to_jsonb($1::text)) ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value",
                       hashlib.sha256(b"oj-key").hexdigest())
    body = {"stream": True, "messages": [{"role": "user", "content": "[tugas #7] halo"}]}
    hdr = {"Authorization": "Bearer oj-key"}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url="http://t") as c:
        assert (await c.post("/llm/v1/chat/completions", json={**body, "model": "jarvis-analisis"}, headers=hdr)).status_code == 200
        assert (await c.post("/llm/v1/chat/completions", json={**body, "model": "jarvis-privat"}, headers=hdr)).status_code == 403
        assert (await c.post("/llm/v1/chat/completions", json={**body, "model": "jarvis-ngobrol"}, headers=hdr)).status_code == 403
        assert (await c.post("/llm/v1/chat/completions", json={**body, "model": "jarvis-spike"}, headers=hdr)).status_code == 200  # worker category too
        assert (await c.post("/llm/v1/chat/completions", json={**body, "model": "jarvis-analisis"}, headers={"Authorization": "Bearer lain"})).status_code == 401
        ids = [m["id"] for m in (await c.get("/llm/v1/models", headers=hdr)).json()["data"]]
        assert "jarvis-analisis" in ids and "jarvis-privat" not in ids and "jarvis-ngobrol" not in ids
    row = await pool.fetchrow("SELECT caller, category FROM llm_usage WHERE category = 'analisis' ORDER BY id DESC LIMIT 1")
    assert row["caller"] == "openjarvis"                                                  # cost is attributed to the worker


async def _mail_env(pool, monkeypatch, items=None):
    from app import inbox, llm, memory
    monkeypatch.setattr(memory, "search", _no_memory)
    posts, llm_calls = [], []

    async def post(kind, payload):
        posts.append((kind, payload))
        if kind == "list":
            return {"items": items or []}
        return {"sent": True, "id": f"g-{len(posts)}"}
    monkeypatch.setattr(inbox, "_post", post)

    async def complete(messages, category="cepat", **kw):
        llm_calls.append((category, kw.get("private"), messages[-1]["content"]))
        if category == "privat":
            return '[{"importance": "penting", "summary": "Budi minta konfirmasi rapat"}, {"importance": "abaikan", "summary": "Promosi"}]'
        return "Baik Pak Budi, saya hadir Senin jam 10. Terima kasih."
    monkeypatch.setattr(llm, "complete", complete)
    return posts, llm_calls


async def test_v4_f6_mail_is_sorted_by_the_local_model_and_a_reply_leaves_only_after_approval(pool, monkeypatch):
    from app import approvals, inbox
    posts, llm_calls = await _mail_env(pool, monkeypatch, items=[
        {"id": "m1", "threadId": "t1", "from": "Budi <budi@kantor.co.id>", "subject": "Rapat Senin", "snippet": "Bisa konfirmasi hadir?"},
        {"id": "m2", "threadId": "t2", "from": "Toko <promo@toko.id>", "subject": "Diskon 50%", "snippet": "Hanya hari ini"},
        {"id": "m3", "from": "Bank <no-reply@bank.id>", "subject": "Kode verifikasi", "snippet": "OTP 482913"}])
    r = await inbox.check()
    assert r["baru"] == 3 and [m["dari"] for m in r["penting"]] == ["Budi"]
    sorted_by = [c for c in llm_calls if c[0] == "privat"]
    assert len(sorted_by) == 1 and sorted_by[0][1] is True                       # mail text only ever reached the LOCAL model
    assert "482913" not in sorted_by[0][2] and "482913" not in str(await pool.fetch("SELECT * FROM mail_items"))   # the OTP is not even kept
    assert await pool.fetchval("SELECT count(*) FROM reports WHERE session_id = 'inbox' AND text LIKE '%email penting%'") == 1
    assert (await inbox.check())["baru"] == 0                                    # the same mail is not told twice (ext_id is unique)
    assert await pool.fetchval("SELECT count(*) FROM mail_items") == 3

    mid = await pool.fetchval("SELECT id FROM mail_items WHERE ext_id = 'm1'")
    d = await inbox.draft_reply(mid, "bilang saya hadir")
    assert d["status"].startswith("draf") and d["subjek"] == "Re: Rapat Senin"
    assert [p for p in posts if p[0] == "send"] == []                              # a draft is not sent
    p = await inbox.propose(d["outbox_id"])
    assert p["status"].startswith("menunggu persetujuanmu") and [x for x in posts if x[0] == "send"] == []   # proposed is not sent either
    assert await pool.fetchval("SELECT status FROM approvals WHERE id = $1", p["persetujuan"]) == "awaiting_approval"
    await approvals.decide(p["persetujuan"], True, "device:HP")                    # the owner's phone approves THIS email
    sends = [x for x in posts if x[0] == "send"]
    assert len(sends) == 1 and sends[0][1]["to"] == "budi@kantor.co.id" and "hadir Senin" in sends[0][1]["body"] and sends[0][1]["threadId"] == "t1"
    assert await pool.fetchval("SELECT status FROM outbox WHERE id = $1", d["outbox_id"]) == "sent"
    assert await pool.fetchval("SELECT status FROM mail_items WHERE id = $1", mid) == "replied"
    assert (await inbox.execute(d["outbox_id"])) == {"already_sent": True} and len([x for x in posts if x[0] == "send"]) == 1   # never twice
    with __import__("pytest").raises(inbox.InboxError):                            # an edit after it went out is refused
        await inbox.edit_draft(d["outbox_id"], "lain")


async def test_v4_f6_a_refused_or_failed_send_never_goes_out_and_the_calendar_needs_approval_too(pool, monkeypatch):
    import pytest
    from app import approvals, inbox
    posts, _ = await _mail_env(pool, monkeypatch, items=[{"id": "m9", "from": "Ani <ani@x.id>", "subject": "Halo", "snippet": "Apa kabar"}])
    await inbox.check(notify=False)
    mid = await pool.fetchval("SELECT id FROM mail_items WHERE ext_id = 'm9'")
    d = await inbox.draft_reply(mid, "jawab singkat")
    p = await inbox.propose(d["outbox_id"])
    await approvals.decide(p["persetujuan"], False, "device:HP")                   # the owner says no
    assert await pool.fetchval("SELECT status FROM outbox WHERE id = $1", d["outbox_id"]) == "rejected"
    with pytest.raises(inbox.InboxError):
        await inbox.execute(d["outbox_id"])
    assert [x for x in posts if x[0] == "send"] == []

    with pytest.raises(inbox.InboxError):                                          # an event needs a time zone and an end after the start
        await inbox.propose_event("Rapat", "2026-11-03T14:00:00", "2026-11-03T15:00:00")
    e = await inbox.propose_event("Rapat proyek", "2026-11-03T14:00:00+07:00", "2026-11-03T15:00:00+07:00", ["budi@kantor.co.id"], "Zoom")
    assert [x for x in posts if x[0] == "calendar"] == []                          # proposed, not written
    await approvals.decide(e["persetujuan"], True, "device:HP")
    cal = [x for x in posts if x[0] == "calendar"]
    assert len(cal) == 1 and cal[0][1]["title"] == "Rapat proyek" and cal[0][1]["attendees"] == ["budi@kantor.co.id"]

    async def broken(kind, payload):
        raise inbox.InboxError("alur n8n belum aktif")
    monkeypatch.setattr(inbox, "_post", broken)
    d2 = await inbox.draft_reply(mid, "coba lagi")
    p2 = await inbox.propose(d2["outbox_id"])
    done = await approvals.decide(p2["persetujuan"], True, "device:HP")
    assert done["status"] == "failed" and await pool.fetchval("SELECT status FROM outbox WHERE id = $1", d2["outbox_id"]) == "failed"


async def test_v4_f6_the_flows_are_created_inactive_once_and_the_owner_activates_them(pool, monkeypatch):
    from app import inbox, n8n
    created = []

    async def create_inactive(wf):
        created.append(wf)
        return {"id": f"wf{len(created)}", "name": wf["name"], "active": False}
    monkeypatch.setattr(n8n, "create_inactive", create_inactive)

    async def list_workflows():
        return [{"id": "wf1", "name": "x", "active": True}]
    monkeypatch.setattr(n8n, "list_workflows", list_workflows)
    st = await inbox.install()
    assert len(created) == 3 and all(f["installed"] for f in st["flows"]) and [f["active"] for f in st["flows"]] == [True, False, False]
    assert (await pool.fetchval("SELECT count(*) FROM approvals WHERE kind = 'n8n_activate_workflow' AND status = 'awaiting_approval'")) == 3
    await inbox.install()                                                          # repeating creates nothing new
    assert len(created) == 3
    paths = [h["path"] for h in (await inbox.hooks()).values()]
    assert len(set(paths)) == 3 and all(len(p.split("-")[-1]) == 32 for p in paths)    # a random secret in each address


async def test_v4_f6_watchers_notify_once_never_buy_and_never_advise(pool, monkeypatch):
    from app import ops, reports, watchers, workers
    prices = iter([1_050_000.0, 990_000.0, 985_000.0, None])

    async def coingecko(coin):
        return next(prices)
    monkeypatch.setattr(watchers, "_coingecko", coingecko)
    monkeypatch.setattr(reports, "push", lambda *a, **k: __import__("asyncio").sleep(0, False))
    w = await watchers.add("kripto", "Bitcoin", "bitcoin", "<=", 1_000_000)
    assert w["every_min"] == 15                                                    # not faster than every 15 minutes
    with __import__("pytest").raises(watchers.WatchError):
        await watchers.add("kripto", "x", "Bitcoin; DROP", "<=", 1)

    async def due():
        await pool.execute("UPDATE watchers SET last_checked = now() - interval '1 day' WHERE id = $1", w["id"])
        await watchers.tick()
    texts = lambda: pool.fetch("SELECT text FROM reports WHERE session_id = 'watcher' ORDER BY id")   # noqa: E731
    await due()
    assert await texts() == []                                                     # 1.05 M is above the line: silent
    await due()
    t = await texts()
    assert len(t) == 1 and "Rp 990.000" in t[0]["text"] and "bukan nasihat investasi" in t[0]["text"]
    await due()
    assert len(await texts()) == 1                                                 # still below: no second message within 6 hours
    await due()                                                                    # the source failed: nothing breaks, nothing is said
    assert len(await texts()) == 1 and "tidak menjawab" in (await pool.fetchrow("SELECT last_note FROM watchers WHERE id = $1", w["id"]))["last_note"]

    spawned = []

    async def spawn(title, instruction, session_id, actor, **kw):
        spawned.append((instruction, kw))
        tid = await pool.fetchval("""INSERT INTO tasks (session_id, title, instruction, kind, category, status)
                                     VALUES ('watcher', $1, $2, 'watcher', 'web', 'running') RETURNING id""", title, instruction)
        spawned[-1] = (instruction, kw, tid)
        return {"id": tid}
    monkeypatch.setattr(workers, "spawn", spawn)

    async def ok():
        return True, ""
    monkeypatch.setattr(ops, "background_ok", ok)
    t = await watchers.add("tiket", "KA Argo Bromo", "tiket KA Argo Bromo Anggrek Gambir-Surabaya 20 Nov 2026", "<=", 600_000)
    assert t["every_min"] == 120                                                   # web checks cost AI: rarer
    await watchers.tick()
    instruction, kw, task_id = spawned[0]
    assert kw == {"kind": "watcher"} and "JANGAN membeli" in instruction and "berhenti sebelum pembayaran" in instruction
    assert "JANGAN memberi saran membeli" in instruction
    assert (await pool.fetchval("SELECT pending_task FROM watchers WHERE id = $1", t["id"])) == task_id
    await watchers.tick()
    assert len(spawned) == 1                                                       # one check at a time per watcher
    await watchers.on_result(task_id, 'Harga terendah Rp 575.000 di kai.id.\nHASIL: {"value": 575000, "note": "kai.id, kelas eksekutif"}')
    last = (await texts())[-1]["text"]
    assert "Rp 575.000" in last and "belum membeli atau memesan" in last and "kamu yang memutuskan dan membayar" in last
    assert await pool.fetchval("SELECT pending_task FROM watchers WHERE id = $1", t["id"]) is None


async def test_v4_f6_the_agent_can_read_draft_and_propose_but_has_no_way_to_send(pool, monkeypatch):
    from app import assistant
    posts, _ = await _mail_env(pool, monkeypatch, items=[{"id": "m5", "from": "Cici <cici@x.id>", "subject": "Tanya harga", "snippet": "Berapa?"}])
    names = {t["function"]["name"] for t in assistant.TOOLS}
    assert {"inbox", "watch"} <= names and not {"send_email", "send_mail", "send_whatsapp", "buy_ticket", "pay"} & names
    actions = next(t for t in assistant.TOOLS if t["function"]["name"] == "inbox")["function"]["parameters"]["properties"]["action"]["enum"]
    assert "send" in actions                                                       # 'send' only PROPOSES (an approval); the executor is the approval
    await assistant._inbox_tool("inbox", {"action": "check"})
    mid = await pool.fetchval("SELECT id FROM mail_items WHERE ext_id = 'm5'")
    d = await assistant._inbox_tool("inbox", {"action": "draft_reply", "mail_id": mid, "instruction": "kasih tahu Rp 100 ribu"})
    p = await assistant._inbox_tool("inbox", {"action": "send", "outbox_id": d["outbox_id"]})
    assert "menunggu persetujuanmu" in p["status"] and [x for x in posts if x[0] == "send"] == []
    w = await assistant._inbox_tool("watch", {"action": "add", "kind": "emas", "label": "Emas", "query": "harga emas Antam 1 gram", "op": ">=", "threshold": 1_600_000})
    assert w["cek_tiap_menit"] == 60 and "tidak membeli" in w["catatan"]
    assert (await assistant._inbox_tool("inbox", {"action": "event", "title": "x", "start": "besok", "end": "lusa"}))["error"]


async def _station_env(pool, monkeypatch):
    """The desk with a fake shared browser: one tab the worker's hands are in, and a screencast that pushes a frame whenever 'the page changes'."""
    import asyncio
    import base64
    import time

    import httpx
    from app import hub, live
    live.stations.clear()
    live.subscribers.clear()
    live.tab_activity.clear()
    live.tab_activity["P1"] = time.time()                                   # the hands moved in this tab a moment ago
    looks = {"frames": 0, "acks": [], "started": 0, "sent": []}

    class FakeBrowser:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url):
            return httpx.Response(200, json=[{"id": "P1", "type": "page", "url": "https://www.jostreet.com/produk", "title": "Produk Jostreet",
                                              "webSocketDebuggerUrl": "ws://fake/page"},
                                             {"id": "OLD", "type": "page", "url": "https://iana.org/", "title": "forgotten", "webSocketDebuggerUrl": "ws://fake/old"}])
    monkeypatch.setattr(live, "_client", lambda timeout: FakeBrowser())

    class FakePage:
        def __init__(self, url):
            self.url, self.q, self.resp = url, asyncio.Queue(), asyncio.Queue()

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            if getattr(self, "pusher", None):
                self.pusher.cancel()
            return False

        def __aiter__(self):                                             # a second connection (the owner's hands) reads answers like this
            return self

        async def __anext__(self):
            return await self.resp.get()

        async def send(self, raw):
            m = json.loads(raw)
            if m["method"].startswith(("Input.", "Runtime.", "Page.getLayout")):
                looks["sent"].append(m)
            if m["method"] == "Page.getLayoutMetrics":
                self.resp.put_nowait(json.dumps({"id": m["id"], "result": {"cssVisualViewport": {"clientWidth": 1280, "clientHeight": 800}}}))
            if m["method"] == "Page.startScreencast" and self.url.endswith("/page"):
                looks["started"] += 1

                async def push():                                        # Chromium keeps pushing while something moves: ~100 frames a second here
                    for i in range(1, 400):
                        looks["frames"] += 1
                        self.q.put_nowait(json.dumps({"method": "Page.screencastFrame", "params": {
                            "data": base64.b64encode(b"\xff\xd8JPEG" + bytes([i % 250])).decode(), "sessionId": i,
                            "metadata": {"deviceWidth": 1280, "deviceHeight": 800}}}))
                        await asyncio.sleep(0.01)
                self.pusher = asyncio.create_task(push())
            elif m["method"] == "Page.screencastFrameAck":
                looks["acks"].append(m["params"]["sessionId"])

        async def recv(self):
            return await self.q.get()
    monkeypatch.setattr(live, "_ws_connect", lambda url: FakePage(url))

    async def screenshot(ws_url):
        return b"\xff\xd8JPEG-final"
    monkeypatch.setattr(live, "_screenshot", screenshot)
    hub.reset()
    live.start()
    return looks


async def test_v4_f7_a_worker_task_is_a_station_on_the_desk_with_steps_and_the_page_it_browses(pool, monkeypatch):
    import asyncio

    import httpx
    from app import devices, hub, live, main
    looks = await _station_env(pool, monkeypatch)
    watcher_q, unsubscribe = live.subscribe("utama")                                  # a viewer with the desk open
    tid = await pool.fetchval("""INSERT INTO tasks (session_id, title, instruction, kind, category, status)
                                 VALUES ('s-f7', 'Cek web Jostreet', 'cek jostreet', 'owner', 'web', 'running') RETURNING id""")
    await hub.broadcast({"type": "task", "id": tid, "title": "Cek web Jostreet", "status": "running", "kind": "owner"})
    for i, (name, label) in enumerate([("browser_navigate", "https://www.jostreet.com/produk"), ("browser_scroll", "bawah"),
                                       ("browser_type", "kolom pencarian: sepatu")]):
        await hub.broadcast({"type": "task_event", "task_id": tid, "event": {"type": "tool", "id": f"c{i}", "name": name, "label": label, "status": "running"}})
    await hub.broadcast({"type": "task_event", "task_id": tid, "event": {"type": "thought", "text": "mencari sepatu lari"}})
    await hub.broadcast({"type": "task_event", "task_id": tid, "event": {"type": "tool", "id": "c2", "name": "browser_type", "label": "", "status": "completed"}})
    for _ in range(100):
        if live.stations[tid].frame_seq >= 2:
            break
        await asyncio.sleep(0.02)
    snap = await live.snapshot("utama")
    st = next(s for s in snap["stations"] if s["task_id"] == tid)
    assert st["status"] == "running" and st["browsing"] and st["ref"] == f"task:{tid}"
    assert [x["text"] for x in st["steps"]] == ["Membuka: https://www.jostreet.com/produk", "Menggulir: bawah", "Mengetik: kolom pencarian: sepatu"]
    assert st["steps"][2]["status"] == "completed" and st["thought"] == "mencari sepatu lari"   # a finished call updates its step, not a new one
    await hub.broadcast({"type": "task_event", "task_id": tid, "event": {"type": "tool", "id": "browser_scroll-9", "name": "browser_scroll",
                                                                          "label": '{"success": true, "output": "hasil mentah"}', "status": "completed"}})
    await hub.broadcast({"type": "task_event", "task_id": tid, "event": {"type": "tool", "id": "x-77", "name": "browser_click",
                                                                          "label": '{"output": "tak pernah dimulai"}', "status": "completed"}})
    steps = (await live.snapshot("utama"))["stations"][0]["steps"]
    assert len(steps) == 3 and steps[1]["status"] == "completed" and "hasil mentah" not in str(steps)   # paired by tool, results never shown as actions
    for _ in range(3):                                                                         # the same call again and again: one line, counted
        await hub.broadcast({"type": "task_event", "task_id": tid, "event": {"type": "tool", "id": f"e{_}", "name": "browser_exec", "label": "ambil teks halaman", "status": "running"}})
    steps = (await live.snapshot("utama"))["stations"][0]["steps"]
    assert len(steps) == 4 and steps[3]["n"] == 3 and steps[3]["text"] == "Menjalankan di halaman: ambil teks halaman"
    assert st["page_title"] == "Produk Jostreet" and st["has_frame"] and st["frame_seq"] >= 2
    assert looks["started"] >= 1 and len(looks["acks"]) >= 2                              # a live screencast on the worker's tab, every frame acknowledged
    got = []
    while not watcher_q.empty():
        got.append(watcher_q.get_nowait())
    assert got and all(g[0] == tid for g in got) and [g[1] for g in got] == sorted(g[1] for g in got)   # pushed to the viewer, in order, for its task
    unsubscribe()
    assert {"n8n", "prompts", "storage"} <= set(snap)                                          # the owner's desk also has the panels

    _, token = await devices.create("HP", "test", scope="owner")
    hdr = {"Authorization": f"Bearer {token}"}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url="http://t") as c:
        assert (await c.get("/api/v1/canvas/live")).status_code == 401                           # only paired devices
        assert (await c.get(f"/api/v1/canvas/live/{tid}/frame")).status_code == 401
        r = await c.get(f"/api/v1/canvas/live/{tid}/frame", headers=hdr)
        assert r.status_code == 200 and r.headers["content-type"] == "image/jpeg" and r.content.startswith(b"\xff\xd8JPEG")
        assert r.headers["cache-control"] == "no-store"
        assert (await c.get(f"/api/v1/canvas/live/{tid}/frame?context=company:renature", headers=hdr)).status_code == 404   # not another galaxy's
        assert len((await c.get("/api/v1/canvas/live", headers=hdr)).json()["stations"]) == 1
    await hub.broadcast({"type": "task", "id": tid, "title": "Cek web Jostreet", "status": "completed", "kind": "owner"})
    assert live.stations[tid].finished and (await live.snapshot("utama"))["stations"][0]["status"] == "completed"


async def test_v4_f7_private_and_company_work_never_leaks_onto_the_wrong_desk_and_requests_are_masked(pool, monkeypatch):
    from app import hub, live
    await _station_env(pool, monkeypatch)
    private = await pool.fetchval("""INSERT INTO tasks (session_id, title, instruction, kind, category, status, private)
                                     VALUES ('s-p', 'Rahasia', 'x', 'owner', 'privat', 'running', true) RETURNING id""")
    await hub.broadcast({"type": "task", "id": private, "title": "Rahasia", "status": "running", "kind": "owner"})
    assert private not in live.stations                                                         # a private task is never on the desk
    r, _ = await _two_companies(pool, monkeypatch)
    ctask = await pool.fetchval("""INSERT INTO tasks (session_id, title, instruction, kind, category, status, company_id)
                                   VALUES ('s-c', 'Iklan Renature', 'x', 'owner', 'web', 'running', $1) RETURNING id""", r)
    await hub.broadcast({"type": "task", "id": ctask, "title": "Iklan Renature", "status": "running", "kind": "owner"})
    assert [s["task_id"] for s in (await live.snapshot(f"company:{r}"))["stations"]] == [ctask]
    assert (await live.snapshot("utama"))["stations"] == []                                     # the personal desk does not show company work
    assert "n8n" not in await live.snapshot(f"company:{r}")                                      # nor the owner's panels on a company desk
    await pool.execute("INSERT INTO messages (session_id, role, content, route) VALUES ('s1', 'user', 'tolong cek harga emas', 'hermes')")
    await pool.execute("INSERT INTO messages (session_id, role, content, route) VALUES ('s1', 'assistant', 'Emas Rp 1,5 juta', 'hermes')")
    await pool.execute("INSERT INTO messages (session_id, role, content, route) VALUES ('s2', 'user', 'kode OTP saya 482913', 'hermes')")
    await pool.execute("INSERT INTO messages (session_id, role, content, route) VALUES ('s3', 'user', '/privat catatan pribadi', 'hermes')")
    shown = await live.prompts()
    asked = [p["asked"] for p in shown]
    assert "tolong cek harga emas" in asked and not any("482913" in a for a in asked) and not any("catatan pribadi" in a for a in asked)
    assert next(p for p in shown if p["asked"] == "tolong cek harga emas")["answer"] == "Emas Rp 1,5 juta"


async def test_v4_f7_a_new_task_is_on_the_canvas_at_once_and_storage_can_be_laid_out(pool, monkeypatch):
    from app import canvas, memory, workers
    monkeypatch.setattr(memory, "search", _no_memory)
    t = await workers.spawn("Cari sepatu", "Cari sepatu lari di jostreet dan bandingkan harga.", "s-f7b", "test")
    c = await canvas.ensure("utama")
    v = await canvas.view(c["id"])
    assert f"task:{t['id']}" in [x["ref"] for x in v["cards"]]                                  # a card from the moment the task exists
    before = v["version"]
    await canvas.touch(f"task:{t['id']}")
    assert (await canvas.view(c["id"]))["version"] == before + 1                                # a finished task makes open viewers re-read it
    first = await canvas.fill("utama", "owner")
    assert (await canvas.fill("utama", "owner"))["added"] == 0                                              # idempotent
    r, _ = await _two_companies(pool, monkeypatch)
    assert (await canvas.fill(f"company:{r}", "owner"))["added"] == 0                            # a company galaxy takes none of the personal library


class _FakeSocket:
    """What a browser's WebSocket looks like to main.ws(): first-message auth (browsers cannot set headers), text frames in and out."""
    def __init__(self):
        import asyncio
        self.headers, self.inbox, self.out = {}, asyncio.Queue(), []

    async def accept(self):
        pass

    async def receive_text(self):
        item = await self.inbox.get()
        if isinstance(item, Exception):
            raise item
        return item

    async def send_text(self, text):
        self.out.append(json.loads(text))

    async def close(self, code=1000):
        self.out.append({"type": "closed", "code": code})


async def test_v4_f8_the_desk_is_the_front_door_and_its_chat_voice_camera_and_screen_reach_the_same_brain(pool, monkeypatch):
    import asyncio
    import base64
    from types import SimpleNamespace

    import httpx
    from fastapi import WebSocketDisconnect
    from app import chat, devices, main, stt, voice
    # the front door: / opens the desk, and the desk may use this origin's microphone, camera and screen sharing (nothing else, nobody else)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url="http://t") as c:
        r = await c.get("/", follow_redirects=False)
        assert r.status_code in (302, 307) and r.headers["location"] == "/canvas/"
        pp = (await c.get("/canvas/")).headers["permissions-policy"]
        assert "camera=(self)" in pp and "microphone=(self)" in pp and "display-capture=(self)" in pp and "geolocation=()" in pp
        for f in ("deskcards.js", "dock.js", "worklet.js"):
            assert (await c.get(f"/canvas/{f}")).status_code == 200
    seen = {}

    async def handle(text, session_id, actor, device_id=None, emit=None, **kw):
        seen.update(text=text, session=session_id, screen=kw.get("screen"), source=kw.get("image_source"))
        await emit({"type": "delta", "text": "Ha"})
        return SimpleNamespace(reply=f"Dengar: {text}", route="assistant", spoken=False)
    monkeypatch.setattr(chat, "handle", handle)

    async def hear(pcm):
        return {"text": "cek harga emas", "engine": "test", "confidence": 0.9}
    monkeypatch.setattr(stt, "transcribe_with_voice", hear)

    async def process(heard, pcm, sid):
        return heard
    monkeypatch.setattr(voice, "process", process)
    _, token = await devices.create("Browser meja", "test", scope="owner")
    sock = _FakeSocket()
    server = asyncio.create_task(main.ws(sock))

    async def until(pred, tries=200):
        for _ in range(tries):
            if any(pred(e) for e in sock.out):
                return True
            await asyncio.sleep(0.02)
        return False
    await sock.inbox.put(json.dumps({"type": "auth", "token": "salah"}))
    assert await until(lambda e: e.get("type") == "closed" and e["code"] == 4401)               # a wrong token is refused
    server = asyncio.create_task(main.ws(sock := _FakeSocket()))
    await sock.inbox.put(json.dumps({"type": "auth", "token": token}))
    assert await until(lambda e: e["type"] == "auth_ok")
    frame = base64.b64encode(b"\xff\xd8fakejpeg").decode()
    await sock.inbox.put(json.dumps({"user_command": "tolong lihat ini", "session_id": "meja-1", "screen": frame, "image_source": "camera"}))
    assert await until(lambda e: e["type"] == "reply" and e["text"] == "Dengar: tolong lihat ini")
    assert seen["screen"] == frame and seen["source"] == "camera" and seen["session"] == "meja-1"   # the camera frame goes along with the words
    assert any(e["type"] == "delta" and e["session_id"] == "meja-1" for e in sock.out)               # and the answer streams back to the same session
    pcm = base64.b64encode(b"\x01\x00" * 16000).decode()                                              # one second of 16 kHz PCM16, as dock.js sends
    await sock.inbox.put(json.dumps({"type": "utterance", "audio": pcm, "seq": 7, "session_id": "meja-1", "screen": frame, "image_source": "screen"}))
    assert await until(lambda e: e["type"] == "transcript" and e["text"] == "cek harga emas" and e["seq"] == 7)
    assert await until(lambda e: e["type"] == "reply" and e["text"] == "Dengar: cek harga emas")
    assert seen["source"] == "screen"                                                                  # a shared screen is sent with what is said
    await sock.inbox.put(json.dumps({"type": "utterance", "audio": base64.b64encode(b"\x00" * 100).decode(), "seq": 8, "session_id": "meja-1"}))
    assert await until(lambda e: e["type"] == "error" and "tidak valid" in e["message"])               # audio that is too short is refused
    await sock.inbox.put(WebSocketDisconnect())
    await asyncio.wait_for(server, 3)


async def test_v4_f7_the_shared_browser_gets_the_hands_overlay_in_every_page(pool, monkeypatch):
    import asyncio
    import httpx
    from app import live
    sent = []

    class FakeWS:
        """A browser-level DevTools socket: announces one page, then (after the attach request) the session for it, then a second page."""
        def __init__(self):
            self.q = asyncio.Queue()
            for m in ({"method": "Target.targetCreated", "params": {"targetInfo": {"targetId": "T1", "type": "page", "url": "about:blank"}}},
                      {"method": "Target.targetCreated", "params": {"targetInfo": {"targetId": "X1", "type": "service_worker", "url": "https://x/sw.js"}}},
                      {"method": "Target.targetCreated", "params": {"targetInfo": {"targetId": "D1", "type": "page", "url": "devtools://devtools/x"}}}):
                self.q.put_nowait(json.dumps(m))

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def send(self, raw):
            m = json.loads(raw)
            sent.append(m)
            if m["method"] == "Target.attachToTarget":
                self.q.put_nowait(json.dumps({"method": "Target.attachedToTarget", "params": {"sessionId": "S-" + m["params"]["targetId"],
                                                                                   "targetInfo": {"targetId": m["params"]["targetId"]}}}))
                if m["params"]["targetId"] == "T1":   # a page opened later by the worker
                    self.q.put_nowait(json.dumps({"method": "Target.targetCreated", "params": {"targetInfo": {"targetId": "T2", "type": "page", "url": "https://jobstreet.co.id/"}}}))
                    self.q.put_nowait(json.dumps({"method": "Target.targetInfoChanged", "params": {"targetInfo": {"targetId": "T2", "type": "page", "url": "https://jobstreet.co.id/id"}}}))
                if m["params"]["targetId"] == "T2":   # the worker's hands move in the second tab
                    self.q.put_nowait(json.dumps({"method": "Runtime.bindingCalled", "sessionId": "S-T2", "params": {"name": "jarvisHands", "payload": "1"}}))
                    self.q.put_nowait(None)

        def __aiter__(self):
            return self

        async def __anext__(self):
            item = await asyncio.wait_for(self.q.get(), 2)
            if item is None:
                raise StopAsyncIteration
            return item

    class Browser:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url):
            return httpx.Response(200, json={"webSocketDebuggerUrl": "ws://fake/devtools/browser/1"})
    monkeypatch.setattr(live, "_client", lambda timeout: Browser())
    monkeypatch.setattr(live, "_ws_connect", lambda url: FakeWS())
    live.tab_activity.clear()
    await live._decorate_once()
    attached = [m["params"]["targetId"] for m in sent if m["method"] == "Target.attachToTarget"]
    assert attached == ["T1", "T2"]                                  # real pages only, each once (not workers, not devtools, not a repeat)
    for sid in ("S-T1", "S-T2"):
        mine = [m for m in sent if m.get("sessionId") == sid]
        assert [m["method"] for m in mine] == ["Runtime.enable", "Runtime.addBinding", "Page.enable", "Page.addScriptToEvaluateOnNewDocument", "Runtime.evaluate"]
        assert mine[1]["params"] == {"name": "jarvisHands"}                # the hands tell core where they are (DevTools only, not the network)
        assert "__jarvisHands" in mine[3]["params"]["source"]
    assert live.tab_activity["T2"] > live.tab_activity["T1"] - 1 and time.time() - live.tab_activity["T2"] < 5   # the tab the hands moved in is the live one
    js = live.CURSOR_JS
    assert "mode: 'closed'" in js and "pointer-events:none" in js and "aria-hidden" in js     # draws, never touches or answers the page
    assert "fetch(" not in js and "XMLHttpRequest" not in js and "sendBeacon" not in js        # and sends nothing anywhere


async def test_v4_f7_live_video_reaches_a_viewer_over_a_websocket_only_for_its_own_galaxy(pool, monkeypatch):
    import asyncio

    from app import devices, hub, live, main
    looks = await _station_env(pool, monkeypatch)
    _, token = await devices.create("Browser meja", "test", scope="owner")
    tid = await pool.fetchval("""INSERT INTO tasks (session_id, title, instruction, kind, category, status)
                                 VALUES ('s-v', 'Cek web', 'x', 'owner', 'web', 'running') RETURNING id""")
    await hub.broadcast({"type": "task", "id": tid, "title": "Cek web", "status": "running", "kind": "owner"})

    class Sock(_FakeSocket):
        def __init__(self):
            super().__init__()
            self.bytes = []

        async def send_bytes(self, data):
            self.bytes.append(data)
    stranger, viewer = Sock(), Sock()
    srv1 = asyncio.create_task(main.canvas_live_ws(stranger))
    await stranger.inbox.put(json.dumps({"type": "auth", "token": "salah"}))
    await asyncio.wait_for(srv1, 3)
    assert {"type": "closed", "code": 4401} in stranger.out and not stranger.bytes                # a wrong token never gets video
    srv2 = asyncio.create_task(main.canvas_live_ws(viewer))
    await viewer.inbox.put(json.dumps({"type": "auth", "token": token}))
    await viewer.inbox.put(json.dumps({"type": "watch", "context": "utama"}))
    await hub.broadcast({"type": "task_event", "task_id": tid, "event": {"type": "tool", "id": "c1", "name": "browser_navigate",
                                                                          "label": "https://www.jostreet.com/produk", "status": "running"}})
    for _ in range(150):
        if len(viewer.bytes) >= 3:
            break
        await asyncio.sleep(0.02)
    assert len(viewer.bytes) >= 3                                                                   # frames pushed as they happen, not polled
    task_id, seq = int.from_bytes(viewer.bytes[0][:4], "big"), int.from_bytes(viewer.bytes[0][4:8], "big")
    assert task_id == tid and seq >= 1 and viewer.bytes[0][8:].startswith(b"\xff\xd8JPEG")         # task id + frame number + the JPEG
    assert {"type": "auth_ok"} in viewer.out
    await viewer.inbox.put(json.dumps({"type": "watch", "context": "company:renature"}))             # another galaxy: this task's frames stop
    await asyncio.sleep(0.2)
    n = len(viewer.bytes)
    await asyncio.sleep(0.4)
    assert len(viewer.bytes) == n
    srv2.cancel()
    await asyncio.gather(srv2, return_exceptions=True)
    assert live.subscribers == []                                                                    # a closed viewer leaves nothing behind


async def test_v4_f9_the_owner_can_take_the_wheel_of_a_workers_browser_and_hand_it_back(pool, monkeypatch):
    import asyncio

    from app import audit, devices, hub, live, main, questions
    looks = await _station_env(pool, monkeypatch)
    _, owner = await devices.create("HP pemilik", "test", scope="owner")
    _, basic = await devices.create("Tamu", "test", scope="basic")
    tid = await pool.fetchval("""INSERT INTO tasks (session_id, title, instruction, kind, category, status)
                                 VALUES ('s-t', 'Apply Jobstreet', 'x', 'owner', 'web', 'running') RETURNING id""")
    await hub.broadcast({"type": "task", "id": tid, "title": "Apply Jobstreet", "status": "running", "kind": "owner"})
    await hub.broadcast({"type": "task_event", "task_id": tid, "event": {"type": "tool", "id": "c1", "name": "browser_navigate",
                                                                          "label": "https://www.jostreet.com/produk", "status": "running"}})
    q = await questions.ask("Ada captcha di halaman login. Buka Meja dan klik Ambil alih.", tid)
    snap = await live.snapshot("utama")
    assert snap["stations"][0]["asking"].startswith("Ada captcha")                      # the card says what the worker needs
    assert snap["stations"][0]["controlled"] is False

    async def run(token, msgs):
        sock = _FakeSocket()
        srv = asyncio.create_task(main.canvas_live_ws(sock))
        await sock.inbox.put(json.dumps({"type": "auth", "token": token}))
        await sock.inbox.put(json.dumps({"type": "watch", "context": "utama"}))
        for m in msgs:
            await sock.inbox.put(json.dumps(m))
            await asyncio.sleep(0.05)
        return sock, srv
    guest, srv0 = await run(basic, [{"type": "take", "task": tid}])
    assert any(m.get("what") == "take" and m.get("ok") is False for m in guest.out) and not looks["sent"]       # only the owner's own device may steer
    srv0.cancel()

    sock, srv = await run(owner, [
        {"type": "take", "task": tid},
        {"type": "input", "task": tid, "ev": {"t": "mouse", "k": "down", "x": 0.5, "y": 0.25, "b": "left"}},
        {"type": "input", "task": tid, "ev": {"t": "mouse", "k": "up", "x": 0.5, "y": 0.25, "b": "left"}},
        {"type": "input", "task": tid, "ev": {"t": "text", "text": "kode-rahasia-123"}},
        {"type": "input", "task": tid, "ev": {"t": "key", "k": "down", "key": "Enter", "code": "Enter"}},
        {"type": "input", "task": tid, "ev": {"t": "wheel", "x": 0.5, "y": 0.5, "dx": 0, "dy": 240}},
    ])
    assert {"type": "control", "task": tid, "what": "take", "ok": True, "ttl": live.CONTROL_TTL_S} in sock.out
    snap = await live.snapshot("utama")
    assert snap["stations"][0]["controlled"] is True and snap["stations"][0]["control_by"].startswith("device:")
    sent = [m for m in looks["sent"] if m["method"].startswith("Input.")]
    press = next(m for m in sent if m["params"].get("type") == "mousePressed")
    assert (press["params"]["x"], press["params"]["y"]) == (640.0, 200.0)               # a click at 50%/25% of the 1280x800 page
    assert any(m["method"] == "Input.insertText" and m["params"]["text"] == "kode-rahasia-123" for m in sent)
    assert any(m["params"].get("type") == "mouseWheel" and m["params"]["deltaY"] == 240 for m in sent)
    assert any("__jarvisOwner" in json.dumps(m) for m in looks["sent"])                  # the page draws the pointer as the owner's ("ANDA")
    trail = json.dumps([dict(r) for r in await pool.fetch("SELECT * FROM audit_events WHERE action LIKE 'live.%'")], default=str)
    assert "live.takeover" in trail and "kode-rahasia" not in trail                      # taking over is audited; what was typed never is

    await sock.inbox.put(json.dumps({"type": "release", "task": tid, "done": True}))
    await asyncio.sleep(0.1)
    assert any(m.get("what") == "release" and m.get("told") == 1 for m in sock.out)
    row = await questions.get(q["id"])
    assert row["status"] == "answered" and "sudah membantu" in row["answer"]              # the waiting worker is told to go on
    assert (await live.snapshot("utama"))["stations"][0]["controlled"] is False
    n = len(looks["sent"])
    await sock.inbox.put(json.dumps({"type": "input", "task": tid, "ev": {"t": "text", "text": "x"}}))
    await asyncio.sleep(0.1)
    assert len(looks["sent"]) == n and any(m.get("what") == "input" and m.get("ok") is False for m in sock.out)   # once handed back, no more input gets in
    srv.cancel()
    await asyncio.gather(srv, srv0, return_exceptions=True)


async def test_v4_f9_a_viewer_that_vanishes_hands_the_wheel_back(pool, monkeypatch):
    import asyncio

    from app import devices, hub, live, main
    from starlette.websockets import WebSocketDisconnect
    await _station_env(pool, monkeypatch)
    _, owner = await devices.create("HP pemilik", "test", scope="owner")
    tid = await pool.fetchval("""INSERT INTO tasks (session_id, title, instruction, kind, category, status)
                                 VALUES ('s-t2', 'Cek', 'x', 'owner', 'web', 'running') RETURNING id""")
    await hub.broadcast({"type": "task", "id": tid, "title": "Cek", "status": "running", "kind": "owner"})
    sock = _FakeSocket()
    srv = asyncio.create_task(main.canvas_live_ws(sock))
    for m in ({"type": "auth", "token": owner}, {"type": "watch", "context": "utama"}, {"type": "take", "task": tid}):
        await sock.inbox.put(json.dumps(m))
    await asyncio.sleep(0.15)
    assert live.controlled(live.stations[tid])
    await sock.inbox.put(WebSocketDisconnect())                                           # the tab was closed with the wheel in hand
    await asyncio.wait_for(srv, 3)
    assert not live.controlled(live.stations[tid])


# ---------- Fase 10 / ADR-054: the player and the meeting recorder are cards on the desk ----------

async def test_v4_f10_a_song_on_the_stage_is_a_player_card_on_the_desk_and_leaves_with_it(pool, monkeypatch):
    from app import hub, live, stage
    monkeypatch.setattr(hub, "_clients", {})
    assert (await live.snapshot("utama"))["player"] is None                                          # nothing playing, nothing on the desk
    await stage.show("music", {"title": "Bunga", "artist": "BCL", "url": "/api/v1/media/abc", "playlist": {"name": "Playlist saya", "index": 1, "total": 5}},
                     "Memutar Bunga", "jarvis")
    p = (await live.snapshot("utama"))["player"]
    assert p["title"] == "Bunga" and p["panel"] == "music" and p["url"] == "/api/v1/media/abc" and p["playlist"]["total"] == 5
    first = p["id"]
    await stage.show("video", {"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ", "title": "Klip"}, "Klip", "jarvis")
    assert (await live.snapshot("utama"))["player"]["id"] != first                                     # a new song is a new player
    await stage.show("map", {"title": "Rute", "markers": [{"lat": -6.2, "lon": 106.8, "label": "x"}]}, "Rute", "jarvis")
    assert (await live.snapshot("utama"))["player"] is None                                          # a map is not a player
    await stage.show("audio", {"url": "https://cdn.example.com/a.mp3", "title": "Suara"}, "Suara", "jarvis")
    await stage.on_event(stage.current()["id"], "closed")
    assert (await live.snapshot("utama"))["player"] is None
    r, _ = await _two_companies(pool, monkeypatch)
    assert "player" not in await live.snapshot(f"company:{r}")                                         # a company galaxy has no personal player


async def test_v4_f10_start_a_meeting_by_voice_opens_the_card_and_recording_waits_for_consent(pool, monkeypatch, tmp_path):
    from app import assistant, hub, meetings, router
    monkeypatch.setattr(meetings, "ROOT", tmp_path / "meetings")
    await pool.execute("DELETE FROM meetings")
    meetings.forget_want()
    seen = []

    async def tap(ev):
        seen.append(ev)
    monkeypatch.setattr(hub, "_taps", [tap])
    assert await meetings.desk_card() is None
    intent = router.parse_action("Jarvis, mulai rapat tentang anggaran 2027")
    assert intent.name == "meeting_start" and intent.args["title"] == "anggaran 2027"
    said = await assistant._meeting("start", {"title": intent.args["title"]})
    assert "Mulai rekam" in said["say"]
    card = await meetings.desk_card()
    assert card["state"] == "waiting" and card["title"] == "anggaran 2027"                           # a card, not a recording: everyone must agree first
    assert not await pool.fetchval("SELECT count(*) FROM meetings") and not [e for e in seen if e.get("type") == "meeting_cmd"]
    # the owner ticks consent on the card inside the app: the phone is told to record (consent is required)
    out = await meetings.request_start("Rapat anggaran", True, ["Bu Rina"], "Q3", "device:HP")
    cmd = [e for e in seen if e.get("type") == "meeting_cmd"][0]
    assert cmd["cmd"] == "start" and cmd["title"] == "Rapat anggaran" and cmd["confidential"] is True and cmd["participants"] == ["Bu Rina"]
    assert out["delivered"] == 0 and (await meetings.desk_card()) is None                              # the want is spent
    # the phone creates the meeting (the usual API) → the card follows the row
    m = await meetings.create("Rapat anggaran", True, True)
    rec = await meetings.desk_card()
    assert rec["state"] == "recording" and rec["id"] == str(m["id"]) and rec["started_at"] > 0 and rec["confidential"] is True
    stop_before = rec["stop_seq"]
    assert (await assistant._meeting("stop", {}))["ok"] is True                                           # "selesai rapat"
    assert (await meetings.desk_card())["stop_seq"] == stop_before + 1
    assert [e for e in seen if e.get("type") == "meeting_cmd" and e["cmd"] == "stop"]
    await meetings.add_chunk(str(m["id"]), 0, b"RIFF" + b"\0" * 100, "webm")                        # a browser recorder uploads WebM
    await meetings.finish(str(m["id"]), 61, 1, "test")
    assert (await meetings.desk_card())["state"] == "processing"
    await pool.execute("UPDATE meetings SET status = 'done', done_at = now() WHERE id = $1", m["id"])
    assert (await meetings.desk_card())["state"] == "done"
    await pool.execute("UPDATE meetings SET done_at = now() - interval '2 hours' WHERE id = $1", m["id"])
    assert await meetings.desk_card() is None                                                          # a finished meeting leaves the desk after a while
    assert (await assistant._meeting("stop", {}))["error"]                                              # nothing is recording any more


async def test_v4_f10_the_meeting_endpoints_need_consent_and_an_owner_device(pool, monkeypatch):
    from fastapi import HTTPException

    from app import main
    with pytest.raises(HTTPException) as e:
        await main.meeting_start_request(main.MeetingStartIn(title="x", consent=False), device={"name": "HP"})
    assert e.value.status_code == 422
    assert (await main.meeting_start_request(main.MeetingStartIn(title="x", consent=True), device={"name": "HP"}))["delivered"] == 0
    assert (await main.meeting_stop_request(device={"name": "HP"}))["stopping"] is False


# ---------- Fase 11 / ADR-055: the canvas is a 2D board ----------

async def test_v4_f11_the_owner_draws_notes_shapes_and_frames_resizes_them_and_undoes_by_the_history(pool, monkeypatch):
    from app import canvas
    c = await canvas.ensure("utama")
    note = await canvas.create_object("utama", {"type": "note", "text": "Beli tinta printer\nbesok", "color": "#fde68a"}, "owner", 100, -50)
    frame = await canvas.create_object("utama", {"type": "frame", "text": "Minggu ini"}, "owner", 0, 0, 800, 500)
    v = await canvas.view(c["id"])
    got = {x["id"]: x for x in v["cards"]}
    n = got[note["id"]]
    assert n["ref"].startswith("obj:") and n["kind"] == "papan" and n["type"] == "note" and n["title"] == "Beli tinta printer"
    assert (n["x"], n["z"], n["w"], n["h"]) == (100, -50, 220, 180)                                   # a note arrives with a default size
    assert got[frame["id"]]["w"] == 800 and got[frame["id"]]["props"]["text"] == "Minggu ini"
    # resize + edit text + colour: only known keys, only well-formed values
    await canvas.move(note["id"], "owner", w=300, h=240, props={"text": "Beli tinta", "color": "#bbf7d0", "font": 20})
    n = {x["id"]: x for x in (await canvas.view(c["id"]))["cards"]}[note["id"]]
    assert (n["w"], n["h"], n["props"]["color"], n["props"]["font"], n["props"]["type"]) == (300, 240, "#bbf7d0", 20, "note")
    for bad in ({"color": "merah"}, {"shape": "bintang"}, {"type": "frame"}, {"align": "tengah"}):
        with pytest.raises(canvas.CanvasError):
            await canvas.move(note["id"], "owner", props=bad)
    with pytest.raises(canvas.CanvasError):
        await canvas.create_object("utama", {"type": "script", "text": "x"}, "owner")
    with pytest.raises(canvas.CanvasError):
        await canvas.move(0, "owner", w=100)                                                           # a card that does not exist
    # several at once = one version
    before = (await canvas.view(c["id"]))["version"]
    out = await canvas.move_many(c["id"], [{"id": note["id"], "x": 0, "z": 600}, {"id": frame["id"], "x": -50, "z": 520, "w": 900}], "owner", "geser dua")
    assert out["version"] == before + 1
    assert {x["id"]: x for x in (await canvas.view(c["id"]))["cards"]}[frame["id"]]["w"] == 900
    # connectors keep an arrow and a style, and the history brings back sizes, props and arrows
    e = await canvas.link(note["id"], frame["id"], "owner", "ada di", {"to": frame["id"], "dash": True, "color": "#38bdf8"})
    edge = (await canvas.view(c["id"]))["edges"][0]
    assert edge["label"] == "ada di" and edge["style"] == {"to": frame["id"], "dash": True, "color": "#38bdf8"}
    await canvas.update_edge(e["id"], c["id"], "owner", label="di dalam", style={"dash": False})
    assert (await canvas.view(c["id"]))["edges"][0]["style"]["dash"] is False
    with pytest.raises(canvas.CanvasError):
        await canvas.update_edge(e["id"], c["id"], "owner", style={"to": 999999})
    ver = (await canvas.view(c["id"]))["version"]
    await canvas.hide(note["id"], "owner")                                                            # deleting the owner's own note is allowed
    assert note["id"] not in {x["id"] for x in (await canvas.view(c["id"]))["cards"]}
    r = await canvas.restore(c["id"], ver, "owner")
    back = (await canvas.view(c["id"]))
    notes = [x for x in back["cards"] if x["type"] == "note"]
    assert r["dropped"] == 0 and len(notes) == 1 and notes[0]["w"] == 300 and notes[0]["props"]["text"] == "Beli tinta"
    assert back["edges"][0]["style"].get("to") in {x["id"] for x in back["cards"]}                        # the arrow follows the restored node's new id


async def test_v4_f11_a_company_board_can_hold_drawings_but_never_another_boards_cards(pool, monkeypatch):
    from app import canvas
    r, _ = await _two_companies(pool, monkeypatch)
    mine = await canvas.create_object(f"company:{r}", {"type": "shape", "shape": "ellipse", "text": "Target Q4"}, "owner", 10, 10)
    assert {x["ref"] for x in (await canvas.view((await canvas.ensure(f"company:{r}"))["id"]))["cards"]} == {mine["ref"]}
    other = await canvas.create_object("utama", {"type": "note", "text": "pribadi"}, "owner")
    with pytest.raises(canvas.CanvasError):
        await canvas.link(mine["id"], other["id"], "owner")                                          # different boards stay apart
    c2 = await canvas.ensure(f"company:{r}")
    with pytest.raises(canvas.CanvasError):
        await canvas.move_many(c2["id"], [{"id": other["id"], "x": 1, "z": 1}], "owner")                # and a batch cannot reach across


async def test_v4_f11_the_board_endpoints_need_an_owner_and_reject_nonsense(pool, monkeypatch):
    from fastapi import HTTPException

    from app import canvas, main
    c = await canvas.ensure("utama")
    dev = {"name": "HP"}
    made = await main.canvases_add_object(c["id"], main.ObjectIn(props={"type": "text", "text": "Halo", "bold": True}, x=5, z=6), device=dev)
    assert made["props"]["bold"] is True and made["w"] == 240
    with pytest.raises(HTTPException) as e:
        await main.canvases_add_object(c["id"], main.ObjectIn(props={"type": "note", "color": "<script>"}), device=dev)
    assert e.value.status_code == 422
    await main.canvases_layout(c["id"], main.LayoutIn(items=[main.LayoutItem(id=made["id"], x=50, z=60)], note="uji"), device=dev)
    moved = {x["id"]: x for x in (await canvas.view(c["id"]))["cards"]}[made["id"]]
    assert (moved["x"], moved["z"]) == (50, 60)
    with pytest.raises(HTTPException):
        await main.canvases_layout(c["id"], main.LayoutIn(items=[main.LayoutItem(id=987654321, x=1)]), device=dev)


async def test_v4_f11_arrange_puts_pointing_cards_back_in_their_grid_and_leaves_drawings_and_locked_cards(pool, monkeypatch):
    from app import canvas
    t = [await pool.fetchval("INSERT INTO tasks (session_id, title, instruction, kind, category, status) VALUES ('s-ar', $1, 'x', 'owner', 'web', 'completed') RETURNING id", f"T{i}") for i in range(3)]
    c = await canvas.ensure("utama")
    nodes = [await canvas.add("utama", f"task:{i}", "owner", (123.0 + n, 5.0, 456.0)) for n, i in enumerate(t)]
    note = await canvas.create_object("utama", {"type": "note", "text": "tetap"}, "owner", 7, 8)
    await canvas.move(nodes[2]["id"], "owner", pinned=True)
    r = await canvas.arrange(c["id"], "owner")
    assert r["arranged"] == 2
    got = {x["id"]: x for x in (await canvas.view(c["id"]))["cards"]}
    a, b = got[nodes[0]["id"]], got[nodes[1]["id"]]
    assert (a["x"], a["z"]) == (canvas.place("tugas", 0)[0], canvas.place("tugas", 0)[2]) and b["x"] == canvas.place("tugas", 1)[0]
    assert (got[nodes[2]["id"]]["x"], got[note["id"]]["x"]) == (125.0, 7)                                  # locked and drawn things stay where they are
