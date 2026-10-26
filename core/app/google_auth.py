"""The owner's Google account, connected by logging in from the phone (ADR-057).

The owner taps "Hubungkan akun Google" on the desk (or in the app); Google's own sign-in page opens in the phone's browser, the owner
picks the account and allows Gmail + Calendar, and Google sends them back to /api/v1/google/callback. Core then:
  1. trades the one-time code for tokens (the refresh token is kept encrypted with the vault key),
  2. writes them into two n8n credentials (Gmail, Google Calendar) — n8n refreshes the access token itself from then on,
  3. puts those credentials on the inbox flows (inbox_flows.py) and switches the flows on: the login is the owner's consent.
Sending an email or creating an event still waits for the owner's approval of that exact email / event (inbox.py).

Google needs a registered OAuth client (Google Cloud Console → Credentials → "Web application", redirect URI below). Its id and secret
come from the environment (GOOGLE_OAUTH_CLIENT_ID / _SECRET) or are pasted once by the owner (set_client); the secret is stored encrypted.
"""

import os
import secrets
import time
from urllib.parse import urlencode

import httpx

from . import audit, db, n8n, vault

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"
REVOKE_URL = "https://oauth2.googleapis.com/revoke"
SCOPES = ("openid", "email", "https://www.googleapis.com/auth/gmail.modify", "https://www.googleapis.com/auth/calendar.events")
CLIENT_KEY, ACCOUNT_KEY = "google:client", "google:account"
STATE_TTL_S = 900
_states: dict[str, float] = {}   # login attempts in flight: state → when it was made (one use each)


class GoogleError(RuntimeError):
    pass


def redirect_uri() -> str:
    return f"{os.getenv('PUBLIC_ORIGIN', '').rstrip('/')}/api/v1/google/callback"


async def _get(key: str) -> dict:
    v = await db.pool().fetchval("SELECT value FROM settings_kv WHERE key = $1", key)
    return v if isinstance(v, dict) else {}


async def _put(key: str, value: dict | None) -> None:
    if value is None:
        await db.pool().execute("DELETE FROM settings_kv WHERE key = $1", key)
    else:
        await db.pool().execute("INSERT INTO settings_kv (key, value) VALUES ($1, $2) ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value",
                                key, value)


async def client() -> tuple[str, str]:
    """(client id, client secret) — from the environment, else what the owner pasted. ('', '') when there is none yet."""
    cid, sec = os.getenv("GOOGLE_OAUTH_CLIENT_ID", "").strip(), os.getenv("GOOGLE_OAUTH_CLIENT_SECRET", "").strip()
    if cid and sec:
        return cid, sec
    c = await _get(CLIENT_KEY)
    if c.get("id") and c.get("secret"):
        return c["id"], vault.decrypt(bytes.fromhex(c["secret"]))
    return "", ""


def check_client(client_id: str, client_secret: str) -> tuple[str, str]:
    """What a Google web client looks like (pure; unit-tested). Raises GoogleError with a plain reason."""
    cid, sec = (client_id or "").strip(), (client_secret or "").strip()
    if not cid.endswith(".apps.googleusercontent.com") or len(cid) > 200:
        raise GoogleError("Client ID Google berakhiran .apps.googleusercontent.com")
    if not 10 <= len(sec) <= 200 or any(c.isspace() for c in sec):
        raise GoogleError("Client secret tidak valid")
    return cid, sec


async def set_client(client_id: str, client_secret: str, actor: str) -> dict:
    cid, sec = check_client(client_id, client_secret)
    await _put(CLIENT_KEY, {"id": cid, "secret": vault.encrypt(sec).hex(), "at": time.time()})
    await audit.record(actor, "google.client_set", None)
    return await status()


async def status() -> dict:
    cid, _ = await client()
    acc = await _get(ACCOUNT_KEY)
    return {"configured": bool(cid), "connected": bool(acc.get("email")), "email": acc.get("email", ""),
            "connected_at": acc.get("at"), "redirect_uri": redirect_uri(), "flows_on": bool(acc.get("flows_on")),
            "error": acc.get("error", "")}


def login_url(client_id: str, state: str, redirect: str) -> str:
    """Google's sign-in page for this client (pure; unit-tested). offline + consent: Google gives a refresh token every time."""
    return AUTH_URL + "?" + urlencode({"client_id": client_id, "redirect_uri": redirect, "response_type": "code",
                                       "scope": " ".join(SCOPES), "access_type": "offline", "prompt": "consent",
                                       "include_granted_scopes": "true", "state": state})


async def start(actor: str) -> dict:
    cid, _ = await client()
    if not cid:
        raise GoogleError("Client Google belum diisi — tempel Client ID dan secret dulu")
    now = time.time()
    for s, t in list(_states.items()):
        if now - t > STATE_TTL_S:
            del _states[s]
    state = secrets.token_urlsafe(24)
    _states[state] = now
    await audit.record(actor, "google.login_started", None)
    return {"url": login_url(cid, state, redirect_uri())}


def _n8n_data(cid: str, sec: str, tokens: dict) -> dict:
    """What an n8n Google OAuth2 credential holds after a login (pure; unit-tested)."""
    token = {"access_token": tokens["access_token"], "refresh_token": tokens["refresh_token"], "token_type": tokens.get("token_type", "Bearer"),
             "expires_in": tokens.get("expires_in", 3599), "scope": tokens.get("scope", " ".join(SCOPES))}
    return {"clientId": cid, "clientSecret": sec, "oauthTokenData": token}


async def _exchange(code: str, cid: str, sec: str) -> dict:
    async with httpx.AsyncClient(timeout=20) as c:
        r = await c.post(TOKEN_URL, data={"code": code, "client_id": cid, "client_secret": sec, "redirect_uri": redirect_uri(),
                                          "grant_type": "authorization_code"})
        if r.status_code != 200:
            raise GoogleError(f"Google menolak kode login ({r.status_code}: {r.text[:160]})")
        tokens = r.json()
        u = await c.get(USERINFO_URL, headers={"Authorization": f"Bearer {tokens['access_token']}"})
    tokens["email"] = (u.json() if u.status_code == 200 else {}).get("email", "")
    return tokens


async def finish(code: str, state: str) -> dict:
    """Google sent the owner back: tokens → n8n credentials → the inbox flows on. Returns the new status."""
    from . import inbox
    made = _states.pop(state or "", None)
    if not made or time.time() - made > STATE_TTL_S:
        raise GoogleError("Tautan login ini sudah tidak berlaku — mulai lagi dari JARVIS")
    cid, sec = await client()
    tokens = await _exchange(code, cid, sec)
    if not tokens.get("refresh_token"):
        raise GoogleError("Google tidak memberi izin jangka panjang — coba lagi dan centang semua izin")
    granted = set(str(tokens.get("scope", "")).split())
    missing = [s.rsplit("/", 1)[-1] for s in SCOPES[2:] if s not in granted]
    acc = await _get(ACCOUNT_KEY)
    data = _n8n_data(cid, sec, tokens)
    gmail = await n8n.put_credential(acc.get("gmail_cred"), f"JARVIS · Google ({tokens['email']})", "gmailOAuth2", data)
    cal = await n8n.put_credential(acc.get("calendar_cred"), f"JARVIS · Kalender ({tokens['email']})", "googleCalendarOAuth2Api", data)
    acc = {"email": tokens["email"], "at": time.time(), "gmail_cred": gmail["id"], "calendar_cred": cal["id"],
           "refresh": vault.encrypt(tokens["refresh_token"]).hex(), "scope": tokens.get("scope", ""), "flows_on": False, "error": ""}
    await _put(ACCOUNT_KEY, acc)
    try:
        await inbox.install({"gmailOAuth2": gmail, "googleCalendarOAuth2Api": cal})
        acc["flows_on"] = True
    except inbox.InboxError as e:
        acc["error"] = f"Akun terhubung, tetapi alur n8n gagal dipasang: {e}"[:300]
    await _put(ACCOUNT_KEY, acc)
    await audit.record("owner", "google.connected", None, email=tokens["email"], missing=missing)
    out = await status()
    out["missing"] = missing
    return out


async def disconnect(actor: str) -> dict:
    """Forget the account: Google revokes the token, n8n's credentials go, the inbox flows stop."""
    from . import inbox
    acc = await _get(ACCOUNT_KEY)
    if acc.get("refresh"):
        try:
            async with httpx.AsyncClient(timeout=15) as c:
                await c.post(REVOKE_URL, data={"token": vault.decrypt(bytes.fromhex(acc["refresh"]))})
        except httpx.HTTPError:
            pass
    for f in (await inbox.hooks()).values():
        try:
            await n8n.deactivate(f["workflow_id"])
        except n8n.N8nError:
            pass
    for k in ("gmail_cred", "calendar_cred"):
        if acc.get(k):
            try:
                await n8n.delete_credential(acc[k])
            except n8n.N8nError:
                pass
    await _put(ACCOUNT_KEY, None)
    await audit.record(actor, "google.disconnected", None)
    return await status()


def page(title: str, text: str, ok: bool) -> str:
    """The small page the phone's browser shows after Google sends the owner back."""
    esc = lambda s: s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")  # noqa: E731
    color = "#4ade80" if ok else "#f87171"
    return ("<!doctype html><html lang=id><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>"
            f"<title>{esc(title)}</title><body style='margin:0;font:16px system-ui;background:#080c18;color:#e6edff;display:grid;"
            "place-items:center;min-height:100vh'><div style='max-width:420px;padding:24px'>"
            f"<h2 style='color:{color}'>{esc(title)}</h2><p>{esc(text)}</p>"
            "<p style='color:#8fa0c4'>Halaman ini boleh ditutup. Kembali ke aplikasi JARVIS.</p></div></body></html>")

