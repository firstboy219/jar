"""ADR-087 wave 7: the live flow (stations, live runs, steps, effectiveness per job) and the brain workshop — a version of a job (lane,
extra prompt rule, length, temperature) or of the global thresholds, written from the owner's words by the heavy brain, tried on real
past inputs (judged blind), rolled out to 10% first, rolled back automatically when worse, promoted when not; every run records its version."""
import json
import os

import httpx
import pytest

from tests.test_integration import pool  # noqa: F401  (fixture)

needs_db = pytest.mark.skipif(not os.getenv("TEST_DATABASE_URL"), reason="needs TEST_DATABASE_URL")


def reply(content):
    return {"choices": [{"message": {"content": content if isinstance(content, str) else json.dumps(content)}}]}


# ---------- pure ----------

def test_versions_rules_canary_and_verdicts():
    from app import bengkel, master
    assert bengkel.clean_config({"lane": "aneh", "instruction": "  sebut tenggat  ", "max_tokens": 99999, "temperature": 3}, "inbox:draf") == \
        {"lane": "auto", "instruction": "sebut tenggat", "max_tokens": 6000, "temperature": 1.2}
    assert bengkel.clean_config({"light_min_ok": 0.75}, "")["light_min_ok"] == 0.75
    with pytest.raises(bengkel.BrainError):
        bengkel.clean_config({"learn_min_runs": 0}, "")
    msgs = bengkel.with_rule([{"role": "system", "content": "Tulis draf."}, {"role": "user", "content": "x"}], "Selalu formal.")
    assert msgs[0]["content"].endswith("ATURAN TAMBAHAN DARI PEMILIK (utamakan):\nSelalu formal.") and msgs[1]["content"] == "x"
    assert bengkel.with_rule([{"role": "user", "content": "x"}], "R")[0]["role"] == "system"
    a, c = {"id": 1, "canary_pct": 10}, {"id": 2, "canary_pct": 10}
    assert bengkel.pick(a, c, 0.05)["id"] == 2 and bengkel.pick(a, c, 0.5)["id"] == 1 and bengkel.pick(None, None, 0.1) is None
    assert bengkel.verdict((20, 19), (4, 0)) == "wait" and bengkel.verdict((20, 19), (5, 2)) == "rollback"
    assert bengkel.verdict((20, 18), (8, 7)) == "wait" and bengkel.verdict((20, 18), (15, 14)) == "promote"
    # the workshop's lane and thresholds reach Hermes' choice
    base = dict(has_skill=False, skill_streak=0, tools=False, phone=False, routine=False, heavy=False, has_prompt=True, light_on=True, stats={})
    assert master.choose(**base)[0] == "ringan" and master.choose(**base, forced="berat") == ("berat", "diatur pemilik di Bengkel otak: otak berat")
    assert master.choose(**{**base, "has_prompt": False, "has_skill": True}, forced="ringan")[0] == "skill"      # no prompt: cannot be forced to AI
    assert master.choose(**{**base, "stats": {"ringan": (3, 1)}})[0] == "ringan"
    assert master.choose(**{**base, "stats": {"ringan": (3, 1)}}, learn_min_runs=3)[0] == "berat"                 # a lower global threshold


# ---------- the workshop end to end ----------

@needs_db
async def test_a_change_in_words_is_tried_rolled_out_to_ten_percent_and_rolled_back_when_worse(pool, monkeypatch):
    import random
    from app import bengkel, gateway, hub, master
    await pool.execute("TRUNCATE flow_runs, flow_samples, brain_versions RESTART IDENTITY CASCADE")
    bengkel.invalidate()
    seen = []

    async def fake(lane, body, **kw):
        sysmsg = body["messages"][0]["content"]
        seen.append((lane, sysmsg))
        if "insinyur" in sysmsg:
            return reply({"lane": "auto", "instruction": "Selalu sebut tenggat di kalimat pertama.", "alasan": "pemilik minta tenggat disebut"})
        if "juri" in sysmsg:
            return reply({"pemenang": "1", "alasan": "lebih jelas"})
        if "ATURAN TAMBAHAN" in sysmsg:
            return reply("Tenggat Jumat. Draf baru.")
        return reply("Draf lama.")
    monkeypatch.setattr(gateway, "complete", fake)

    def job():
        return master.Job("inbox", "draf", "tulis draf balasan email", messages=[{"role": "system", "content": "Tulis balasan email."}, {"role": "user", "content": "Email dari Sari"}])
    for _ in range(3):
        assert (await master.run(job()))["result"] == "Draf lama."                                         # the job as built; its inputs kept
    assert await pool.fetchval("SELECT count(*) FROM flow_samples WHERE feature = 'inbox'") == 3
    p = await bengkel.propose("inbox:draf", "selalu sebut tenggat di awal", "owner")
    assert p["config"]["instruction"].startswith("Selalu sebut tenggat") and p["lane"] == "berat"
    assert "Prompt sistemnya sekarang" not in next(s for l, s in seen if "insinyur" in s)   # the job prompt goes in the user part
    ev = await bengkel.evaluate(p["id"], limit=2)
    assert len(ev["samples"]) == 2 and ev["score"]["A"] + ev["score"]["B"] == 2 and all(s["b"].startswith("Tenggat") for s in ev["samples"])
    await bengkel.deploy(p["id"], "canary", "owner", 10)
    hub.reset()
    told = []

    async def listen(e):
        told.append(e)
    hub.register(listen)
    monkeypatch.setattr(random, "random", lambda: 0.01)                                                 # every run lands in the canary
    for _ in range(4):
        r = await master.run(job())
        assert r["result"] == "Tenggat Jumat. Draf baru."
    assert await pool.fetchval("SELECT count(*) FROM flow_runs WHERE brain_version = $1", p["id"]) == 4

    async def broken(lane, body, **kw):
        raise gateway.GatewayError("model rusak")
    monkeypatch.setattr(gateway, "complete", broken)
    for _ in range(3):
        await master.run(job())                                                                         # the canary now fails …
    assert await pool.fetchval("SELECT status FROM brain_versions WHERE id = $1", p["id"]) == "rolled_back"   # … and is rolled back by itself
    assert any(e.get("title") == "Perubahan otak dibatalkan otomatis" for e in told)
    assert (await bengkel.config_for("inbox:draf")) is None                                              # the job runs as built again
    hub.reset()


@needs_db
async def test_a_good_canary_is_promoted_and_global_thresholds_and_rollback_work(pool, monkeypatch):
    import random
    from app import bengkel, gateway, master
    await pool.execute("TRUNCATE flow_runs, flow_samples, brain_versions RESTART IDENTITY CASCADE")
    bengkel.invalidate()

    async def ok(lane, body, **kw):
        return reply("baik")
    monkeypatch.setattr(gateway, "complete", ok)
    v = await bengkel.save_manual("brief:compose", {"lane": "berat", "instruction": "Mulai dengan cuaca."}, "test", "owner")
    await bengkel.deploy(v["id"], "canary", "owner", 50)
    monkeypatch.setattr(random, "random", lambda: 0.1)
    for _ in range(bengkel.PROMOTE_RUNS):
        r = await master.run(master.Job("brief", "compose", "tulis brief", messages=[{"role": "user", "content": "x"}]))
    assert r["lane"] == "berat" and "Bengkel otak" in r["why"]                                           # the forced lane is honoured
    assert await pool.fetchval("SELECT status FROM brain_versions WHERE id = $1", v["id"]) == "active"       # promoted
    view = await bengkel.rollback("brief:compose", "owner")
    assert view["active"] is None and await pool.fetchval("SELECT status FROM brain_versions WHERE id = $1", v["id"]) == "rolled_back"
    g = await bengkel.save_manual("", {"learn_min_runs": 3}, "lebih cepat", "owner")
    await bengkel.deploy(g["id"], "all", "owner")
    assert (await bengkel.global_cfg())["learn_min_runs"] == 3
    with pytest.raises(bengkel.BrainError):
        await bengkel.evaluate(g["id"])                                                                 # globals are not replayed


@needs_db
async def test_the_live_flow_view_and_run_detail(pool, monkeypatch):
    from app import alur, bengkel, devices, gateway, main, master
    await pool.execute("TRUNCATE flow_runs, flow_samples, brain_versions RESTART IDENTITY CASCADE")
    bengkel.invalidate()

    async def ok(lane, body, **kw):
        return reply("hasil")
    monkeypatch.setattr(gateway, "complete", ok)

    async def skill():
        return {"n": 3}
    await master.run(master.Job("bisnis", "sinkron", "ambil angka", skill=skill))
    r = await master.run(master.Job("brief", "compose", "tulis brief", messages=[{"role": "user", "content": "x"}]))
    await pool.execute("INSERT INTO flow_runs (feature, action, goal, lane, status) VALUES ('kopi', 'pesan', 'pesan kopi', 'hermes', 'waiting')")
    v = await alur.view(24)
    assert v["total"] == 3 and v["stations"]["skill"]["runs"] == 1 and v["stations"]["hermes"]["runs"] == 1 and [x["feature"] for x in v["live"]] == ["kopi"]
    assert {(j["feature"], j["ok_pct"]) for j in v["jobs"]} >= {("bisnis", 100), ("brief", 100)}
    d = await alur.run_detail(r["run_id"])
    assert [s["stage"] for s in d["steps"]][:2] == ["router", "hermes"] and d["has_sample"] and d["result_preview"] == "hasil"
    _, token = await devices.create("HP", "test", scope="owner")
    h = {"Authorization": f"Bearer {token}"}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url="http://t") as c:
        assert (await c.get("/api/v1/app/flow", headers=h)).json()["total"] == 3
        assert (await c.get(f"/api/v1/app/flow/{r['run_id']}", headers=h)).json()["feature"] == "brief"
        assert (await c.get("/api/v1/app/flow/999999", headers=h)).status_code == 404
        b = (await c.get("/api/v1/app/brain", headers=h)).json()
        assert any(j["job"] == "brief:compose" for j in b["jobs"]) and b["global"]["global"]["learn_min_runs"] == 5
        assert (await c.get("/api/v1/app/brain/brief:compose", headers=h)).json()["samples"] == 1
        assert (await c.post("/api/v1/app/brain/brief:compose/rollback", headers=h)).status_code == 409
        assert (await c.post("/api/v1/app/brain/global/manual", json={"config": {"learn_min_runs": 0}}, headers=h)).status_code == 422
        assert (await c.get("/api/v1/app/flow")).status_code in (401, 403)
    await pool.execute("UPDATE flow_runs SET started_at = now() - interval '40 days' WHERE lane = 'skill'")
    assert await alur.thin() == 1
