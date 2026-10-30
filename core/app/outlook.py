"""Outlook through Microsoft Graph (ADR-087): the owner's office mail and calendar.

Signing in: the owner registers an app once in Microsoft Entra (Azure) — "Mobile and desktop", public client flows on, delegated permissions
Mail.ReadWrite, Mail.Send, Calendars.ReadWrite, User.Read, offline_access — and puts its client id in the app. Then a device-code sign-in:
the app shows a short code, he enters it at microsoft.com/devicelogin on his phone, and JARVIS keeps a refresh token, encrypted with the
vault key. JARVIS reads, flags, categorises and drafts; it SENDS only what the owner sent from the app (an approval he decided)."""

import base64
import logging
import time
from datetime import datetime, timedelta, timezone

import httpx

from . import approvals, audit, db, vault

log = logging.getLogger("jarvis-core")
GRAPH = "https://graph.microsoft.com/v1.0"
LOGIN = "https://login.microsoftonline.com"
SCOPES = "offline_access User.Read Mail.ReadWrite Mail.Send Calendars.ReadWrite"
CATEGORY = "JARVIS: Penting"
_access: dict = {"token": "", "until": 0.0}


class OutlookError(RuntimeError):
    pass


def _client(timeout: float = 20) -> httpx.AsyncClient:  # seam for tests
    return httpx.AsyncClient(timeout=timeout)


async def _kv(key: str) -> dict:
    return await db.pool().fetchval("SELECT value FROM settings_kv WHERE key = $1", key) or {}


async def _put(key: str, value: dict | None) -> None:
    if value is None:
        await db.pool().execute("DELETE FROM settings_kv WHERE key = $1", key)
    else:
        await db.pool().execute("INSERT INTO settings_kv (key, value) VALUES ($1, $2) ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value", key, value)


async def status() -> dict:
    c, t = await _kv("outlook:client"), await _kv("outlook:token")
    pending = await _kv("outlook:device")
    return {"client_id": c.get("client_id", ""), "tenant": c.get("tenant", "common"), "connected": bool(t.get("refresh")), "account": t.get("account", ""),
            "pending": {"user_code": pending.get("user_code"), "uri": pending.get("verification_uri")} if pending.get("device_code") and pending.get("until", 0) > time.time() else None,
            "last_sync": t.get("last_sync")}


async def set_client(client_id: str, tenant: str, actor: str) -> dict:
    client_id, tenant = client_id.strip(), (tenant or "common").strip() or "common"
    if len(client_id) != 36 or client_id.count("-") != 4:
        raise OutlookError("client id harus GUID (xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx) dari pendaftaran aplikasi di Entra")
    try:
        vault.encrypt("check")   # the refresh token is kept encrypted: no vault key, no sign-in
    except vault.VaultError as e:
        raise OutlookError(str(e))
    await _put("outlook:client", {"client_id": client_id, "tenant": tenant})
    await audit.record(actor, "outlook.client", None, tenant=tenant)
    return await status()


async def start_login() -> dict:
    """Step 1 of the device-code sign-in: a code for the owner to enter at microsoft.com/devicelogin."""
    c = await _kv("outlook:client")
    if not c.get("client_id"):
        raise OutlookError("isi client id aplikasi Entra dulu")
    async with _client() as h:
        r = await h.post(f"{LOGIN}/{c.get('tenant', 'common')}/oauth2/v2.0/devicecode", data={"client_id": c["client_id"], "scope": SCOPES})
    js = r.json()
    if r.status_code != 200:
        raise OutlookError(js.get("error_description") or js.get("error") or f"HTTP {r.status_code}")
    await _put("outlook:device", {"device_code": js["device_code"], "user_code": js["user_code"], "verification_uri": js["verification_uri"],
                                  "interval": int(js.get("interval", 5)), "until": time.time() + int(js.get("expires_in", 900))})
    return {"user_code": js["user_code"], "uri": js["verification_uri"], "expires_in": js.get("expires_in"), "message": js.get("message")}


async def poll_login() -> str:
    """Step 2, run by the clock while a sign-in waits: 'waiting' | 'done' | 'expired' | 'none'."""
    d = await _kv("outlook:device")
    if not d.get("device_code"):
        return "none"
    if d["until"] < time.time():
        await _put("outlook:device", None)
        return "expired"
    c = await _kv("outlook:client")
    async with _client() as h:
        r = await h.post(f"{LOGIN}/{c.get('tenant', 'common')}/oauth2/v2.0/token",
                         data={"grant_type": "urn:ietf:params:oauth:grant-type:device_code", "client_id": c["client_id"], "device_code": d["device_code"]})
    js = r.json()
    if r.status_code != 200:
        if js.get("error") in ("authorization_pending", "slow_down"):
            return "waiting"
        await _put("outlook:device", None)
        return "expired"
    await _save_tokens(js)
    await _put("outlook:device", None)
    me = await graph("GET", "/me?$select=mail,userPrincipalName,displayName")
    t = await _kv("outlook:token")
    t["account"] = me.get("mail") or me.get("userPrincipalName") or me.get("displayName") or ""
    await _put("outlook:token", t)
    await audit.record("owner", "outlook.connected", None, account=t["account"])
    return "done"


async def _save_tokens(js: dict) -> None:
    t = await _kv("outlook:token")
    if js.get("refresh_token"):
        t["refresh"] = base64.b64encode(vault.encrypt(js["refresh_token"])).decode()
    await _put("outlook:token", t)
    _access.update(token=js["access_token"], until=time.time() + int(js.get("expires_in", 3600)) - 120)


async def logout(actor: str) -> None:
    await _put("outlook:token", None)
    _access.update(token="", until=0.0)
    await audit.record(actor, "outlook.disconnected", None)


async def _token() -> str:
    if _access["token"] and _access["until"] > time.time():
        return _access["token"]
    t, c = await _kv("outlook:token"), await _kv("outlook:client")
    if not t.get("refresh") or not c.get("client_id"):
        raise OutlookError("Outlook belum disambungkan")
    refresh = vault.decrypt(base64.b64decode(t["refresh"]))
    async with _client() as h:
        r = await h.post(f"{LOGIN}/{c.get('tenant', 'common')}/oauth2/v2.0/token",
                         data={"grant_type": "refresh_token", "client_id": c["client_id"], "refresh_token": refresh, "scope": SCOPES})
    js = r.json()
    if r.status_code != 200:
        raise OutlookError(f"login Outlook kedaluwarsa — sambungkan lagi ({js.get('error', r.status_code)})")
    await _save_tokens(js)
    return _access["token"]


async def graph(method: str, path: str, json: dict | None = None) -> dict:
    async with _client(30) as h:
        r = await h.request(method, path if path.startswith("http") else GRAPH + path, json=json,
                            headers={"Authorization": f"Bearer {await _token()}", "Prefer": 'outlook.body-content-type="text"'})
    if r.status_code == 401:
        _access.update(token="", until=0.0)
        raise OutlookError("akses Outlook ditolak — sambungkan lagi")
    if r.status_code >= 400:
        raise OutlookError(f"Graph HTTP {r.status_code}: {r.text[:200]}")
    return r.json() if r.content else {}


def mail_row(m: dict) -> dict:
    """A Graph message → the fields the inbox keeps. Pure."""
    frm = ((m.get("from") or {}).get("emailAddress") or {})
    return {"ext_id": m["id"], "thread": m.get("conversationId") or m["id"], "sender": frm.get("name") or frm.get("address") or "",
            "sender_addr": frm.get("address") or "", "subject": m.get("subject") or "(tanpa judul)", "snippet": (m.get("bodyPreview") or "")[:500],
            "received_at": m.get("receivedDateTime"), "flagged": ((m.get("flag") or {}).get("flagStatus") == "flagged"),
            "importance": m.get("importance"), "link": m.get("webLink") or "", "read": bool(m.get("isRead"))}


async def recent_mail(since: datetime, top: int = 50) -> list[dict]:
    q = (f"/me/mailFolders/inbox/messages?$top={top}&$orderby=receivedDateTime desc&$filter=receivedDateTime ge {since.astimezone(timezone.utc):%Y-%m-%dT%H:%M:%SZ}"
         "&$select=id,conversationId,subject,from,receivedDateTime,bodyPreview,isRead,flag,importance,webLink")
    return [mail_row(m) for m in (await graph("GET", q)).get("value", [])]


async def message_body(ext_id: str) -> str:
    m = await graph("GET", f"/me/messages/{ext_id}?$select=body,subject,from,toRecipients,ccRecipients")
    return ((m.get("body") or {}).get("content") or "")[:12000]


async def sent_samples(n: int = 8) -> list[str]:
    """How the owner writes (for drafts in his style): his last sent mails' openings."""
    try:
        js = await graph("GET", f"/me/mailFolders/sentitems/messages?$top={n}&$select=bodyPreview,subject")
        return [m.get("bodyPreview", "")[:400] for m in js.get("value", []) if m.get("bodyPreview")]
    except OutlookError:
        return []


async def flag(ext_id: str) -> None:
    await graph("PATCH", f"/me/messages/{ext_id}", {"flag": {"flagStatus": "flagged"}, "categories": [CATEGORY]})


async def create_reply_draft(ext_id: str, body: str) -> str:
    d = await graph("POST", f"/me/messages/{ext_id}/createReply", {})
    await graph("PATCH", f"/me/messages/{d['id']}", {"body": {"contentType": "Text", "content": body}})
    return d["id"]


async def add_attachment(draft_id: str, name: str, data: bytes, content_type: str = "") -> None:
    """A file on a draft (≤ 3 MB: Graph's simple upload)."""
    if len(data) > 3_000_000:
        raise OutlookError(f"{name} lebih dari 3 MB — lampirkan dari Outlook")
    await graph("POST", f"/me/messages/{draft_id}/attachments", {"@odata.type": "#microsoft.graph.fileAttachment", "name": name[:150],
                                                                  "contentType": content_type or "application/octet-stream",
                                                                  "contentBytes": base64.b64encode(data).decode()})


async def send_draft(draft_id: str) -> None:
    await graph("POST", f"/me/messages/{draft_id}/send")


async def calendar(start: datetime, end: datetime) -> list[dict]:
    q = (f"/me/calendarView?startDateTime={start.astimezone(timezone.utc):%Y-%m-%dT%H:%M:%SZ}&endDateTime={end.astimezone(timezone.utc):%Y-%m-%dT%H:%M:%SZ}"
         "&$orderby=start/dateTime&$top=50&$select=id,subject,start,end,location,attendees,isOnlineMeeting,onlineMeeting,organizer,isCancelled")
    out = []
    for e in (await graph("GET", q)).get("value", []):
        if e.get("isCancelled"):
            continue
        out.append({"ext_id": e["id"], "title": e.get("subject") or "(tanpa judul)", "start": e["start"]["dateTime"][:19] + "Z",
                    "end": e["end"]["dateTime"][:19] + "Z", "location": (e.get("location") or {}).get("displayName", ""),
                    "attendees": [((a.get("emailAddress") or {}).get("name") or "") for a in e.get("attendees") or []][:20],
                    "online": bool(e.get("isOnlineMeeting"))})
    return out


async def create_event(title: str, start: datetime, end: datetime, location: str = "", body: str = "") -> dict:
    return await graph("POST", "/me/events", {"subject": title, "start": {"dateTime": start.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S"), "timeZone": "UTC"},
                                               "end": {"dateTime": end.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S"), "timeZone": "UTC"},
                                               "location": {"displayName": location}, "body": {"contentType": "Text", "content": body}})


async def update_event_location(event_id: str, location: str) -> dict:
    """A meeting moved to another room: only its location changes (the attendees get Outlook's own update)."""
    return await graph("PATCH", f"/me/events/{event_id}", {"location": {"displayName": location[:200]}})


async def _exec_send(detail: dict) -> dict:
    """The approval executor: the owner pressed Kirim on a draft in the app."""
    await send_draft(detail["draft_id"])
    await db.pool().execute("UPDATE inbox_items SET status = 'done', draft = draft || '{\"sent\": true}'::jsonb WHERE id = $1", int(detail["item_id"]))
    return {"sent": True}


approvals.EXECUTORS.setdefault("outlook_send", _exec_send)


async def mark_synced() -> None:
    t = await _kv("outlook:token")
    if t:
        t["last_sync"] = datetime.now(timezone.utc).isoformat()
        await _put("outlook:token", t)


def since_default() -> datetime:
    return datetime.now(timezone.utc) - timedelta(days=2)
