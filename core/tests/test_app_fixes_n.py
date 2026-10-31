"""Owner 2026-10-31: approvals from the app with the phone's own lock (a Keystore key signs a one-time code; registered once with the admin
password), and the news check as an analysis (situation, themes with indicators and reasons, opportunities) by the heavy brain."""
import base64
import os

import httpx
import pytest

from tests.test_integration import pool  # noqa: F401  (fixture)

needs_db = pytest.mark.skipif(not os.getenv("TEST_DATABASE_URL"), reason="needs TEST_DATABASE_URL")


def _key():
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    k = ec.generate_private_key(ec.SECP256R1())
    pub = base64.b64encode(k.public_key().public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)).decode()
    sign = lambda msg: base64.b64encode(k.sign(msg, ec.ECDSA(hashes.SHA256()))).decode()   # noqa: E731
    return pub, sign


def test_only_the_registered_key_signing_this_code_counts():
    from app import appauth
    pub, sign = _key()
    other_pub, other_sign = _key()
    sig = sign(appauth.approval_message("abc"))
    assert appauth.verify_signature(pub, "abc", sig)
    assert not appauth.verify_signature(pub, "abd", sig)                       # another code
    assert not appauth.verify_signature(other_pub, "abc", sig)                 # another phone's key
    assert not appauth.verify_signature(pub, "abc", "bm90IGEgc2lnbmF0dXJl") and not appauth.verify_signature("xx", "abc", sig)


@needs_db
async def test_an_approval_is_the_phone_lock_after_one_registration(pool, monkeypatch):
    from app import appauth, composition, devices, main
    await pool.execute("TRUNCATE device_keys")

    async def check(pw):
        return 200 if pw == "pw-admin" else 401
    monkeypatch.setattr(appauth, "_check", check)
    changed = []

    async def update(changes, actor):
        changed.append(changes)
        return {}
    monkeypatch.setattr(composition, "update", update)
    _, token = await devices.create("HP pemilik", "test", scope="owner")
    _, token2 = await devices.create("Tablet", "test", scope="owner")
    h, h2 = {"Authorization": f"Bearer {token}"}, {"Authorization": f"Bearer {token2}"}
    pub, sign = _key()
    body = {"category": "ringan", "models": ["a/b"]}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url="http://t") as c:
        assert (await c.get("/api/v1/app/approval/key", headers=h)).json()["enrolled"] is False
        assert (await c.post("/api/v1/app/approval/nonce", headers=h)).status_code == 409            # not registered yet
        assert (await c.post("/api/v1/app/approval/key", json={"public_key": pub, "password": "salah"}, headers=h)).status_code == 422
        assert (await c.post("/api/v1/app/approval/key", json={"public_key": pub, "password": "pw-admin"}, headers=h)).json() == {"enrolled": True}
        nonce = (await c.post("/api/v1/app/approval/nonce", headers=h)).json()["nonce"]
        approval = f"hp1:{nonce}:{sign(appauth.approval_message(nonce))}"
        assert (await c.put("/api/v1/app/brain/routes", json={**body, "password": approval}, headers=h)).status_code == 200
        assert len(changed) == 1
        r = await c.put("/api/v1/app/brain/routes", json={**body, "password": approval}, headers=h)
        assert r.status_code == 422 and "HP tidak sah" in r.json()["detail"] and len(changed) == 1          # a code is good once
        nonce = (await c.post("/api/v1/app/approval/nonce", headers=h)).json()["nonce"]
        stolen = f"hp1:{nonce}:{sign(appauth.approval_message(nonce))}"
        assert (await c.put("/api/v1/app/brain/routes", json={**body, "password": stolen}, headers=h2)).status_code == 422   # another device
        _, forged = _key()
        nonce = (await c.post("/api/v1/app/approval/nonce", headers=h)).json()["nonce"]
        assert (await c.put("/api/v1/app/brain/routes", json={**body, "password": f"hp1:{nonce}:{forged(appauth.approval_message(nonce))}"},
                            headers=h)).status_code == 422                                             # signed by a key never registered
        assert (await c.post("/api/v1/app/approval/key", json={"public_key": pub, "password": approval}, headers=h)).status_code == 422
        assert (await c.get("/api/v1/app/approval/key", headers=h)).json()["enrolled"] is True
    assert await pool.fetchval("SELECT last_used IS NOT NULL FROM device_keys") is True


def test_the_previous_stage_list_becomes_items():
    from app import projects
    items = projects.clean_items({"item": [
        {"judul": "Head of IT", "perusahaan": "Humana", "lokasi": "Jakarta", "gaji": "Rp 30 jt", "link": "https://x/1"},
        {"judul": "head of it", "perusahaan": "humana"}, {"perusahaan": "tanpa judul"}, "bukan objek",
        {"judul": "IT Manager", "perusahaan": "Pharos"}]})
    assert [(i["judul"], i["perusahaan"]) for i in items] == [("Head of IT", "Humana"), ("IT Manager", "Pharos")]
    assert projects.clean_items(None) == [] and len(projects.clean_items([{"judul": f"J{i}"} for i in range(30)])) == projects.MAX_ITEMS


@needs_db
async def test_the_apply_stage_opens_jobstreet_once_per_job_with_what_he_answered_before(pool, monkeypatch):
    from app import gateway, phone_agent, projects, workers
    await pool.execute("TRUNCATE phone_runs, flow_runs, settings_kv RESTART IDENTITY CASCADE")
    monkeypatch.setattr(workers, "_start", lambda *a, **k: None)
    await phone_agent.remember_answer("jobstreet", "Berapa ekspektasi gaji Anda?", "25 juta")
    await phone_agent.remember_answer("jobstreet", "berapa ekspektasi gaji anda?", "27 juta")       # the same question again: the newer answer
    await phone_agent.remember_answer("jobstreet", "Kapan bisa mulai?", "(pemilik belum menjawab dalam 10 menit — putuskan yang paling aman)")
    assert await phone_agent.remembered_answers("jobstreet") == "- berapa ekspektasi gaji anda? → 27 juta"

    async def fake(category, body, **kw):
        return {"choices": [{"message": {"content": '{"item": [{"judul": "IT Manager", "perusahaan": "Pharos", "gaji": "20-24 jt"},'
                                                     ' {"judul": "Head of IT", "perusahaan": "Humana"}]}'}}], "jarvis_route": {"model": "m/x"}}
    monkeypatch.setattr(gateway, "complete", fake)
    p = {"id": None, "name": "Apply job di jobstreet", "goal": "apply job sesuai CV, gaji min 20jt"}
    role = {"id": None, "role": "Melakukan apply job", "brief": "Lamar lewat aplikasi JobStreet", "app": "jobstreet", "per_item": True, "model": None, "workers": 1}
    spawned, asked = await projects.spawn_roles(p, 3, [role], "proyek", "chain", context="HASIL TAHAP SEBELUMNYA:\n1. IT Manager — Pharos …")
    goals = [r["goal"] for r in await pool.fetch("SELECT goal FROM phone_runs ORDER BY id")]
    assert len(goals) == 2 and len(spawned) == 2 and not asked                                  # one JobStreet run per job, no password (a project)
    assert "item 1/2" in goals[0] and "ITEM INI: IT Manager · Pharos · 20-24 jt" in goals[0] and "27 juta" in goals[0]
    assert await pool.fetchval("SELECT count(*) FROM phone_runs WHERE app = 'jobstreet' AND scheduled") == 2
    assert await projects.item_goals(p, 3, role, "") == []                                      # nothing found before: nothing to apply to


@needs_db
async def test_the_allocation_can_be_edited_by_hand(pool, monkeypatch):
    from app import appsettings, devices, main
    await pool.execute("TRUNCATE settings_kv, money_tx RESTART IDENTITY CASCADE")
    await appsettings.put("money", {"salary": 10_000_000, "payday": 25, "pots": [{"name": "Makan", "amount": 3_000_000, "categories": ["makan"]}]}, "owner")
    _, token = await devices.create("HP", "test", scope="owner")
    h = {"Authorization": f"Bearer {token}"}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url="http://t") as c:
        pots = [{"name": "Makan & kopi", "amount": "2.500.000", "categories": ["makan", "kopi"]}, {"name": "Investasi", "amount": 1_500_000, "categories": ["investasi"]},
                {"name": "", "amount": 5}, {"name": "Rusak", "amount": -1}]
        r = (await c.put("/api/v1/app/money/pots", json={"pots": pots}, headers=h)).json()
        assert [(p["name"], p["amount"], p["categories"]) for p in r["settings"]["pots"]] == [("Makan & kopi", 2_500_000, ["makan", "kopi"]), ("Investasi", 1_500_000, ["investasi"])]
        dup = await c.put("/api/v1/app/money/pots", json={"pots": [{"name": "A", "amount": 1}, {"name": "a", "amount": 2}]}, headers=h)
        assert dup.status_code == 409 and "kembar" in dup.json()["detail"]
    assert [p["name"] for p in (await appsettings.get("money"))["pots"]] == ["Makan & kopi", "Investasi"]
