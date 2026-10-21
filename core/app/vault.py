"""Password manager (ADR-023): the owner's logins, so JARVIS never asks for them twice.

- Stored here, encrypted at rest with AES-GCM under VAULT_KEY (.env); the database alone reveals nothing.
- The owner's phone (owner-scope device, fingerprint in the app) lists, adds, reveals and deletes them,
  and the web panel fills a login page from them and offers to save new ones after the owner signs in.
- Entries marked allow_agent are synced into Hermes' browser vault, which fills the password field
  server-side without the model ever seeing it (Hermes `browser_vault`, model-blind by design).
- Passwords never go to an AI model, to memory, to logs, or to the audit trail (only "who used which").
"""

import os
import uuid
from urllib.parse import urlsplit

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from . import audit, db


class VaultError(ValueError):
    pass


def _key() -> bytes:
    raw = os.getenv("VAULT_KEY", "").strip()
    try:
        key = bytes.fromhex(raw)
    except ValueError:
        key = b""
    if len(key) != 32:
        raise VaultError("brankas belum dikonfigurasi (VAULT_KEY)")
    return key


def encrypt(password: str) -> bytes:
    nonce = os.urandom(12)
    return nonce + AESGCM(_key()).encrypt(nonce, password.encode(), b"jarvis-vault")


def decrypt(blob: bytes) -> str:
    return AESGCM(_key()).decrypt(bytes(blob[:12]), bytes(blob[12:]), b"jarvis-vault").decode()


def normalize_origin(url: str) -> str:
    """'https://Login.Example.com/path?x' → 'https://login.example.com'. https only. Pure; unit-tested."""
    url = (url or "").strip()
    if "://" not in url:
        url = "https://" + url
    p = urlsplit(url)
    if p.scheme != "https" or not p.hostname:
        raise VaultError("alamat harus https://…")
    port = f":{p.port}" if p.port and p.port != 443 else ""
    return f"https://{p.hostname.lower()}{port}"


def base_domain(host: str) -> str:
    parts = host.lower().strip(".").split(".")
    second = {"co.id", "go.id", "ac.id", "or.id", "web.id", "my.id", "sch.id", "co.uk", "com.au", "com.sg", "com.my"}
    if len(parts) > 2 and ".".join(parts[-2:]) in second:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:])


def _public(r) -> dict:
    return {"id": str(r["id"]), "origin": r["origin"], "label": r["label"], "username": r["username"],
            "note": r["note"], "allow_agent": r["allow_agent"], "created_at": r["created_at"],
            "updated_at": r["updated_at"], "last_used": r["last_used"]}


async def list_() -> list[dict]:
    rows = await db.pool().fetch("SELECT * FROM vault_entries ORDER BY origin, username")
    return [_public(r) for r in rows]


async def save(url: str, username: str, password: str, actor: str, label: str = "", note: str = "",
               allow_agent: bool = False) -> dict:
    origin = normalize_origin(url)
    username = username.strip()
    if not username or not password:
        raise VaultError("username dan password wajib diisi")
    if len(password) > 500 or len(username) > 200:
        raise VaultError("terlalu panjang")
    host = urlsplit(origin).hostname
    existing = await db.pool().fetchrow(
        "SELECT id FROM vault_entries WHERE origin = $1 AND username = $2", origin, username)
    if existing:  # same site + same account: update the password instead of duplicating
        row = await db.pool().fetchrow(
            """UPDATE vault_entries SET secret = $2, note = coalesce(nullif($3, ''), note), allow_agent = $4,
                   label = coalesce(nullif($5, ''), label), updated_at = now() WHERE id = $1 RETURNING *""",
            existing["id"], encrypt(password), note.strip()[:500], allow_agent, label.strip()[:100])
        action = "vault.updated"
    else:
        row = await db.pool().fetchrow(
            """INSERT INTO vault_entries (origin, label, username, secret, note, allow_agent)
               VALUES ($1, $2, $3, $4, $5, $6) RETURNING *""",
            origin, label.strip()[:100] or host, username, encrypt(password), note.strip()[:500], allow_agent)
        action = "vault.saved"
    await audit.record(actor, action, f"vault:{row['id']}", origin=origin, allow_agent=allow_agent)
    return _public(row)


async def update(entry_id: str, actor: str, **fields) -> dict:
    row = await db.pool().fetchrow("SELECT * FROM vault_entries WHERE id = $1", uuid.UUID(entry_id))
    if not row:
        raise VaultError("entri tidak ditemukan")
    password = fields.get("password")
    row = await db.pool().fetchrow(
        """UPDATE vault_entries SET label = coalesce($2, label), username = coalesce($3, username),
               secret = coalesce($4, secret), note = coalesce($5, note), allow_agent = coalesce($6, allow_agent),
               updated_at = now() WHERE id = $1 RETURNING *""",
        row["id"], fields.get("label"), (fields.get("username") or None),
        encrypt(password) if password else None, fields.get("note"), fields.get("allow_agent"))
    await audit.record(actor, "vault.updated", f"vault:{entry_id}", changed=sorted(k for k, v in fields.items() if v is not None and k != "password") + (["password"] if password else []))
    return _public(row)


async def delete(entry_id: str, actor: str) -> bool:
    done = await db.pool().execute("DELETE FROM vault_entries WHERE id = $1", uuid.UUID(entry_id))
    if done.endswith("1"):
        await audit.record(actor, "vault.deleted", f"vault:{entry_id}")
        return True
    return False


async def reveal(entry_id: str, actor: str) -> dict:
    row = await db.pool().fetchrow("SELECT * FROM vault_entries WHERE id = $1", uuid.UUID(entry_id))
    if not row:
        raise VaultError("entri tidak ditemukan")
    await audit.record(actor, "vault.revealed", f"vault:{entry_id}")
    return _public(row) | {"password": decrypt(row["secret"])}


async def match(url: str, actor: str) -> list[dict]:
    """Logins for the page the owner is on: exact origin first, then the same site (login.x.com ↔ www.x.com)."""
    origin = normalize_origin(url)
    host = urlsplit(origin).hostname
    rows = await db.pool().fetch("SELECT * FROM vault_entries ORDER BY updated_at DESC")
    same = [r for r in rows if r["origin"] == origin] + \
           [r for r in rows if r["origin"] != origin and base_domain(urlsplit(r["origin"]).hostname) == base_domain(host)]
    if same:
        await db.pool().execute("UPDATE vault_entries SET last_used = now() WHERE id = ANY($1::uuid[])", [r["id"] for r in same[:3]])
        await audit.record(actor, "vault.autofill", None, origin=origin, count=len(same[:3]))
    return [_public(r) | {"password": decrypt(r["secret"])} for r in same[:3]]


async def agent_entries() -> list[dict]:
    """For Hermes' model-blind browser vault (internal network, MCP token)."""
    rows = await db.pool().fetch("SELECT * FROM vault_entries WHERE allow_agent ORDER BY origin")
    return [{"id": str(r["id"]), "origin": r["origin"], "label": r["label"], "username": r["username"],
             "password": decrypt(r["secret"])} for r in rows]
