"""ADR-087 phase J: receipts from a photo (camera or gallery) become spending without double counting; the YouTube player page takes speed,
subtitles and autoplay; the brains' models are changed from the app with the admin password (the same rules as Komposisi AI)."""
import base64
import io
import json
import os

import httpx
import pytest

from tests.test_integration import pool  # noqa: F401  (fixture)

needs_db = pytest.mark.skipif(not os.getenv("TEST_DATABASE_URL"), reason="needs TEST_DATABASE_URL")


def reply(content):
    return {"choices": [{"message": {"content": content if isinstance(content, str) else json.dumps(content)}}]}


def test_receipt_reading_is_kept_to_what_was_read():
    from app import money
    r = money.clean_receipt({"toko": "Indomaret Sudirman", "total": "Rp 45.300", "tanggal": "2026-10-30", "jam": "18:05", "item": ["Aqua", "Roti"], "bayar": "QRIS"})
    assert r == {"merchant": "Indomaret Sudirman", "total": 45300, "day": "2026-10-30", "time": "18:05", "items": ["Aqua", "Roti"], "method": "QRIS"}
    assert money.clean_receipt({"toko": "X", "total": None}) is None and money.clean_receipt({"total": "-5"}) is None
    assert money.clean_receipt({"total": 1000, "tanggal": "kemarin", "jam": "sore"})["day"] == ""


@needs_db
async def test_receipt_photos_embed_controls_and_model_editor(pool, monkeypatch, tmp_path):
    from PIL import Image
    from app import appauth, attachments, composition, devices, gateway, main, money, openrouter
    monkeypatch.setattr(attachments, "ROOT", tmp_path / "att")
    await pool.execute("TRUNCATE money_tx, flow_runs, settings_kv RESTART IDENTITY CASCADE")
    b = io.BytesIO()
    Image.new("RGB", (400, 600), "white").save(b, "JPEG")
    a1 = await attachments.save("struk1.jpg", "image/jpeg", base64.b64encode(b.getvalue()).decode())
    a2 = await attachments.save("struk2.jpg", "image/jpeg", base64.b64encode(b.getvalue()).decode())
    answers = iter([{"toko": "Indomaret", "total": 45300, "tanggal": "2026-10-30", "jam": "18:05", "item": ["Aqua"]},
                    {"toko": "Kopi Kenangan", "total": 28000, "tanggal": "2026-10-30", "jam": "15:00"}])
    cats = []

    async def fake(category, body, **kw):
        cats.append(category)
        return reply(next(answers))
    monkeypatch.setattr(gateway, "complete", fake)
    await pool.execute("INSERT INTO money_tx (at, amount, direction, merchant, category, source) VALUES ('2026-10-30 15:02+07', 28000, 'out', 'GoPay Kopi', 'kopi', 'notif')")

    async def check(pw):
        return 200 if pw == "pw-admin" else 401
    monkeypatch.setattr(appauth, "_check", check)
    _, token = await devices.create("HP", "test", scope="owner")
    h = {"Authorization": f"Bearer {token}"}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url="http://t") as c:
        r = (await c.post("/api/v1/app/money/receipts", json={"attachment_ids": [a1["id"], a2["id"], "0" * 32]}, headers=h)).json()["receipts"]
        assert r[0]["id"] and r[0]["total"] == 45300 and r[1]["duplicate"]["source"] == "notif" and r[2]["error"]
        assert cats[:2] == ["penglihatan", "penglihatan"]
        row = await pool.fetchrow("SELECT merchant, source, category, at FROM money_tx WHERE source = 'struk'")
        assert row["merchant"] == "Indomaret" and row["category"] == "belanja" and row["at"].hour == 11   # 18:05 WIB
        assert await pool.fetchval("SELECT count(*) FROM money_tx WHERE amount = 28000") == 1                 # the coffee was not counted twice

        page = (await c.get("/embed/youtube/dQw4w9WgXcQ?autoplay=1&rate=1.5&cc=id")).text
        assert "if(1)e.target.playVideo()" in page and "RATE=1.5" in page and 'CC="id"' in page and "function jv(c)" in page
        page = (await c.get("/embed/youtube/dQw4w9WgXcQ?cc=<script>&rate=9")).text
        assert 'CC=""' in page and "RATE=2.0" in page and "if(0)" in page                               # bad values dropped, speed capped, no autoplay

        async def catalog(force=False):
            return [{"id": "deepseek/deepseek-v4-flash", "name": "DeepSeek V4 Flash", "context": 128000, "price_in": 0.1, "price_out": 0.3, "free": False,
                     "tools": True, "vision": False, "created": 1, "description": ""},
                    {"id": "google/gemini-3-flash", "name": "Gemini 3 Flash", "context": 1000000, "price_in": 0.2, "price_out": 0.8, "free": False,
                     "tools": True, "vision": True, "created": 2, "description": ""}]
        monkeypatch.setattr(openrouter, "catalog", catalog)
        cat = (await c.get("/api/v1/app/brain/catalog?q=gemini&vision=true", headers=h)).json()
        assert [m["id"] for m in cat["models"]] == ["google/gemini-3-flash"]
        comp = (await c.get("/api/v1/app/brain/composition", headers=h)).json()
        assert [x["name"] for x in comp["categories"]][:3] == ["ringan", "berat", "penglihatan"]

        calls = []

        async def set_model(category, model, actor, *, provider="openrouter", role="utama", confirmed=False):
            calls.append((category, model, role, confirmed))
            return {"category": category, "main": model, "chain": [model], "price": {}} if confirmed or "flash" in model else {"needs_confirmation": True, "say": "mahal"}
        monkeypatch.setattr(composition, "set_model", set_model)
        assert (await c.put("/api/v1/app/brain/model", json={"category": "ringan", "model": "google/gemini-3-flash"}, headers=h)).status_code == 422
        r = (await c.put("/api/v1/app/brain/model", json={"category": "ringan", "model": "google/gemini-3-flash", "password": "pw-admin"}, headers=h)).json()
        assert r["main"] == "google/gemini-3-flash" and calls[-1] == ("ringan", "google/gemini-3-flash", "utama", False)
        r = (await c.put("/api/v1/app/brain/model", json={"category": "berat", "model": "anthropic/opus", "password": "pw-admin"}, headers=h)).json()
        assert r["needs_confirmation"]

        updates = []

        async def update(changes, actor):
            updates.append(changes)
            return {}
        monkeypatch.setattr(composition, "update", update)
        assert (await c.put("/api/v1/app/brain/routes", json={"category": "ringan", "models": ["a/b", "c/d"]}, headers=h)).status_code == 422
        await c.put("/api/v1/app/brain/routes", json={"category": "ringan", "models": ["a/b", "c/d"], "password": "pw-admin"}, headers=h)
        assert updates[-1] == {"categories": {"ringan": {"routes": [{"provider": "openrouter", "model": "a/b"}, {"provider": "openrouter", "model": "c/d"}]}}}
    assert money
