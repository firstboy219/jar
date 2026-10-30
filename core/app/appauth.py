"""Who is calling the app API (ADR-087): the owner's device — and, for what moves money or acts on the phone from a chat, the admin
password as well (the owner's rule, ADR-077). Shared by the app's routers so they need nothing from main.py."""

import time

import httpx
from fastapi import HTTPException, Request

from . import audit, devices
from .config import settings

ADMIN_URL = "http://jarvis-admin:8000"
_failures: dict[str, list[float]] = {}


def _bearer(value: str | None) -> str | None:
    if value and value.lower().startswith("bearer "):
        return value[7:].strip()
    return None


async def owner(request: Request) -> dict:
    """FastAPI dependency: an owner-scope device token."""
    device = await devices.authenticate(_bearer(request.headers.get("authorization")))
    if not device:
        raise HTTPException(401, "token perangkat tidak valid")
    if device.get("scope") != "owner":
        raise HTTPException(403, "perangkat ini tidak punya akses pemilik")
    return device


def actor(device: dict) -> str:
    return f"device:{device['name']}"


async def _check(password: str) -> int:   # seam for tests
    try:
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.post(ADMIN_URL + "/internal/check-admin-password", json={"password": password},
                             headers={"X-Admin-Token": settings.admin_token})
            return r.status_code
    except httpx.HTTPError:
        return 502


async def require_password(device: dict, password: str, target: str) -> None:
    """The admin password, checked by the web admin (it alone holds it). 5 wrong ones per device per 15 minutes."""
    key, now = str(device["id"]), time.time()
    recent = [t for t in _failures.get(key, []) if now - t < 900]
    _failures[key] = recent
    if len(recent) >= 5:
        raise HTTPException(429, "Terlalu banyak password salah. Coba lagi dalam 15 menit.")
    code = await _check(password or "")
    if code == 401:
        recent.append(now)
        await audit.record(actor(device), "app.bad_password", target)
        raise HTTPException(422, "Password admin salah")   # not 401: the app would take it for a lost login
    if code != 200:
        raise HTTPException(429 if code == 429 else 502, "Gagal memeriksa password")
    _failures.pop(key, None)
