"""Who is calling the app API (ADR-087): the owner's device — and, for what moves money or acts on the phone from a chat, his approval as
well (the owner's rule, ADR-077): the admin password, or — since 2026-10-31 ("Approval dibikin dari apps saja pakai pin/konfirmasi hp") —
the phone's own lock: the app signs a one-time code with a Keystore key usable only after the phone's PIN / fingerprint, registered once
with the admin password. Shared by the app's routers so they need nothing from main.py."""

import base64
import secrets
import time

import httpx
from fastapi import HTTPException, Request

from . import audit, devices
from .config import settings

ADMIN_URL = "http://jarvis-admin:8000"
_failures: dict[str, list[float]] = {}
_nonces: dict[str, tuple[str, float]] = {}   # one-time code → (device id, valid until)
NONCE_S = 120
PHONE_PREFIX = "hp1:"   # "hp1:<code>:<signature>" travels where the password would


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


def new_nonce(device: dict) -> str:
    now = time.time()
    for k in [k for k, (_, until) in _nonces.items() if until < now]:
        _nonces.pop(k, None)
    n = secrets.token_hex(16)
    _nonces[n] = (str(device["id"]), now + NONCE_S)
    return n


def approval_message(nonce: str) -> bytes:
    """What the phone signs for one approval (approval/DeviceApproval.message). Pure."""
    return f"jarvis-approve:{nonce}".encode()


def verify_signature(public_key_b64: str, nonce: str, signature_b64: str) -> bool:
    """An ECDSA P-256 / SHA-256 signature of the approval message by the registered key. Pure."""
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    try:
        key = serialization.load_der_public_key(base64.b64decode(public_key_b64))
        if not isinstance(key, ec.EllipticCurvePublicKey):
            return False
        key.verify(base64.b64decode(signature_b64), approval_message(nonce), ec.ECDSA(hashes.SHA256()))
        return True
    except (InvalidSignature, ValueError, TypeError):
        return False


async def _phone_approval(device: dict, token: str) -> bool:
    """"hp1:<code>:<signature>": the code this device was given (once, unexpired) signed by its registered key."""
    from . import db
    try:
        nonce, sig = token[len(PHONE_PREFIX):].split(":", 1)
    except ValueError:
        return False
    holder = _nonces.pop(nonce, None)
    if not holder or holder[0] != str(device["id"]) or holder[1] < time.time():
        return False
    pub = await db.pool().fetchval("SELECT public_key FROM device_keys WHERE device_id = $1", device["id"])
    if not pub or not verify_signature(pub, nonce, sig):
        return False
    await db.pool().execute("UPDATE device_keys SET last_used = now() WHERE device_id = $1", device["id"])
    return True


async def require_password(device: dict, password: str, target: str) -> None:
    """The owner's approval: the phone's lock (a signed one-time code), or the admin password checked by the web admin (it alone holds it).
    5 wrong ones per device per 15 minutes."""
    key, now = str(device["id"]), time.time()
    recent = [t for t in _failures.get(key, []) if now - t < 900]
    _failures[key] = recent
    if len(recent) >= 5:
        raise HTTPException(429, "Terlalu banyak persetujuan salah. Coba lagi dalam 15 menit.")
    if (password or "").startswith(PHONE_PREFIX):
        if await _phone_approval(device, password):
            _failures.pop(key, None)
            await audit.record(actor(device), "app.approved_by_phone_lock", target)
            return
        recent.append(now)
        await audit.record(actor(device), "app.bad_phone_approval", target)
        raise HTTPException(422, "Persetujuan dari HP tidak sah atau kedaluwarsa — coba lagi")
    code = await _check(password or "")
    if code == 401:
        recent.append(now)
        await audit.record(actor(device), "app.bad_password", target)
        raise HTTPException(422, "Password admin salah")   # not 401: the app would take it for a lost login
    if code != 200:
        raise HTTPException(429 if code == 429 else 502, "Gagal memeriksa password")
    _failures.pop(key, None)
