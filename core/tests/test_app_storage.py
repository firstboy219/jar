"""Owner 2026-10-31: "manager storage sehingga saya tahu mana saja yg bisa dihapus atau dizip" — the host measures (infra/scripts/storage.py),
the app shows it grouped, and only the host's whitelisted cleanups run, after the phone's lock, through the master flow."""
import base64
import json
import os
import time

import httpx
import pytest

from tests.test_integration import pool  # noqa: F401  (fixture)

needs_db = pytest.mark.skipif(not os.getenv("TEST_DATABASE_URL"), reason="needs TEST_DATABASE_URL")

STATE = {"at": 0, "disk": {"total": 100 * 1024 ** 3, "used": 92 * 1024 ** 3, "free": 8 * 1024 ** 3}, "last": None, "items": [
    {"id": "docker-cache", "label": "Cache build Docker", "group": "Docker", "bytes": 20 * 1024 ** 3, "action": "hapus", "note": "Aman."},
    {"id": "docker-images-used", "label": "Image Docker yang dipakai", "group": "Docker", "bytes": 15 * 1024 ** 3, "action": None, "note": "Dipakai."},
    {"id": "logs-zip", "label": "Log Hermes", "group": "Hermes", "bytes": 10 * 1024 ** 2, "action": "zip", "note": "Dipadatkan."},
    {"id": "postgres", "label": "Database", "group": "Data JARVIS", "bytes": 1024 ** 3, "action": None, "note": "Seluruh data."}]}


def test_the_screen_groups_biggest_first_and_says_what_can_go():
    from app import diskspace
    s = diskspace.summary(STATE)
    assert [g["name"] for g in s["groups"]] == ["Docker", "Data JARVIS", "Hermes"]
    assert s["groups"][0]["items"][0]["id"] == "docker-cache"                     # removable first within a group
    assert s["can_free"] == 20 * 1024 ** 3 and s["can_zip"] == 10 * 1024 ** 2
    assert diskspace.low(STATE) and not diskspace.low({**STATE, "disk": {**STATE["disk"], "free": 30 * 1024 ** 3}})
    assert diskspace.summary(None) == {"groups": [], "can_free": 0, "can_zip": 0}


def test_the_host_script_only_knows_its_own_cleanups():
    import importlib.util
    path = os.path.join(os.path.dirname(__file__), "..", "..", "infra", "scripts", "storage.py")
    if not os.path.exists(path):
        pytest.skip("infra not in this checkout")
    spec = importlib.util.spec_from_file_location("storage_host", path)
    host = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(host)
    assert host.size_of("22.98GB (76%)") == 22_980_000_000 and host.size_of("65.54kB") == 65_540 and host.size_of("0B") == 0
    assert {"docker-cache", "docker-volumes", "apk-old", "gradle", "pip"} <= set(host.CLEAN) and host.ZIP <= set(host.CLEAN)
    assert not {"postgres", "media", "whisper", "documents"} & set(host.CLEAN)    # his data is never a cleanup


@needs_db
async def test_cleaning_needs_the_phone_lock_and_hands_only_known_ids_to_the_host(pool, monkeypatch, tmp_path):
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from app import appauth, appclock, devices, diskspace, features, main, reports  # noqa: F401
    monkeypatch.setattr(diskspace, "ROOT", tmp_path)
    await pool.execute("TRUNCATE device_keys, flow_runs, music_library RESTART IDENTITY CASCADE")

    async def check(pw):
        return 401
    monkeypatch.setattr(appauth, "_check", check)
    said = []

    async def report(task_id, session, text):
        said.append(text)
        return {}
    monkeypatch.setattr(reports, "_create", report)
    assert "storage.watch" in appclock._every
    dev, token = await devices.create("HP", "test", scope="owner")
    h = {"Authorization": f"Bearer {token}"}
    k = ec.generate_private_key(ec.SECP256R1())
    pub = base64.b64encode(k.public_key().public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)).decode()
    await pool.execute("INSERT INTO device_keys (device_id, public_key) VALUES ($1, $2)", dev["id"], pub)

    await diskspace._tick()                                                          # nothing measured yet: ask the host
    assert json.loads((tmp_path / "storage.request").read_text())["action"] == "scan" and not said
    (tmp_path / "storage.request").unlink()
    (tmp_path / "storage.json").write_text(json.dumps({**STATE, "at": time.time()}))
    await diskspace._tick()                                                          # fresh: no new scan; low disk: told once a day
    await diskspace._tick()
    assert not (tmp_path / "storage.request").exists() and len(said) == 1 and "8 GB" in said[0]

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url="http://t") as c:
        d = (await c.get("/api/v1/app/storage", headers=h)).json()
        assert d["can_free"] == 20 * 1024 ** 3 and d["low"] and d["music"]["ready"] == 0 and d["pending"] is None
        body = {"items": ["docker-cache", "postgres", "rm -rf /", "logs-zip"]}
        assert (await c.post("/api/v1/app/storage/clean", json=body, headers=h)).status_code == 422             # no PIN, nothing
        assert not (tmp_path / "storage.request").exists()
        nonce = (await c.post("/api/v1/app/approval/nonce", headers=h)).json()["nonce"]
        sig = base64.b64encode(k.sign(appauth.approval_message(nonce), ec.ECDSA(hashes.SHA256()))).decode()
        r = await c.post("/api/v1/app/storage/clean", json={**body, "password": f"hp1:{nonce}:{sig}"}, headers=h)
        assert r.status_code == 200 and r.json()["items"] == ["docker-cache", "logs-zip"]                   # only what the host offers
        req = json.loads((tmp_path / "storage.request").read_text())
        assert req["action"] == "clean" and req["items"] == ["docker-cache", "logs-zip"]
        assert (await c.get("/api/v1/app/storage", headers=h)).json()["pending"]["action"] == "clean"
    run = await pool.fetchrow("SELECT feature, action, status FROM flow_runs ORDER BY id DESC LIMIT 1")
    assert (run["feature"], run["action"], run["status"]) == ("sistem", "bersihkan-disk", "done")             # through the master flow
