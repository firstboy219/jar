"""The phone's contextual front screen ("Panggung"): JARVIS shows what fits the conversation.

Panels: music, video, map, web (read an article / let the owner log in), gallery, doc, draft. With no
panel open the phone shows the 3D brain. Events go to every connected device:
  {"type": "stage", "id", "panel", "mode": "show"|"update"|"close", "payload", "caption"}
The last open panel is kept so a phone that reconnects sees the same thing.
"""

import re
import time
import uuid
from urllib.parse import urlparse

from . import audit, hub

PANELS = {"music", "video", "map", "web", "gallery", "doc", "draft"}
MAX_PAYLOAD = 64_000
_HTTPS = re.compile(r"^https://", re.IGNORECASE)
_current: dict | None = None


class StageError(ValueError):
    pass


def _check_urls(obj, path: str = "") -> None:
    """Every URL JARVIS sends to the phone must be https (no file:, javascript:, intent:, plain http)."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(v, str) and (k.endswith("url") or k in ("src", "href", "stream")):
                if v and not (_HTTPS.match(v) or v.startswith("/api/v1/media/") or v.startswith("/api/v1/documents/")):
                    raise StageError(f"{path}{k}: hanya https yang diizinkan")
                if v.startswith("https://") and not urlparse(v).hostname:
                    raise StageError(f"{path}{k}: URL tidak valid")
            else:
                _check_urls(v, f"{path}{k}.")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            _check_urls(v, f"{path}{i}.")


def validate(panel: str, payload: dict) -> dict:
    if panel not in PANELS:
        raise StageError(f"panel tidak dikenal: {panel}")
    if not isinstance(payload, dict):
        raise StageError("payload harus object")
    import json
    if len(json.dumps(payload, ensure_ascii=False)) > MAX_PAYLOAD:
        raise StageError("payload terlalu besar")
    _check_urls(payload)
    if panel == "web":
        mode = payload.get("mode", "read")
        if mode not in ("read", "login"):
            raise StageError("mode web: read | login")
        if not payload.get("url"):
            raise StageError("web butuh url")
        payload = {**payload, "domain": urlparse(payload["url"]).hostname}
    if panel == "map" and not (payload.get("routes") or payload.get("markers")):
        raise StageError("peta butuh routes atau markers")
    if panel == "draft":
        variants = payload.get("variants") or []
        if not (1 <= len(variants) <= 4) or not all(isinstance(v, dict) and v.get("text") for v in variants):
            raise StageError("draf butuh 1–4 varian berisi text")
    return payload


async def show(panel: str, payload: dict, caption: str = "", actor: str = "jarvis") -> dict:
    global _current
    payload = validate(panel, payload)
    event = {"type": "stage", "id": uuid.uuid4().hex[:12], "panel": panel, "mode": "show",
             "payload": payload, "caption": caption[:200], "at": time.time()}
    _current = event
    delivered = await hub.broadcast(event)
    await audit.record(actor, "stage.show", None, panel=panel, delivered=delivered)
    return {"id": event["id"], "delivered": delivered}


async def update(stage_id: str, payload: dict) -> dict:
    global _current
    if not _current or _current["id"] != stage_id:
        raise StageError("panel itu sudah tidak tampil")
    payload = validate(_current["panel"], {**_current["payload"], **payload})
    _current = {**_current, "payload": payload, "mode": "update"}
    return {"delivered": await hub.broadcast(_current)}


async def close(stage_id: str | None = None) -> dict:
    global _current
    if _current and (stage_id is None or _current["id"] == stage_id):
        event = {"type": "stage", "id": _current["id"], "panel": _current["panel"], "mode": "close"}
        _current = None
        return {"delivered": await hub.broadcast(event)}
    return {"delivered": 0}


def current() -> dict | None:
    return _current


def describe() -> str | None:
    """For the main agent's prompt: what the owner is looking at."""
    if not _current:
        return None
    p = _current["payload"]
    what = {"music": f"memutar musik: {p.get('title', '')}", "video": f"video: {p.get('title', '')}",
            "map": f"peta: {p.get('title', '')}", "web": f"halaman web {p.get('domain', '')}",
            "gallery": "galeri gambar", "doc": f"dokumen: {p.get('title', '')}",
            "draft": "draf balasan pesan"}[_current["panel"]]
    last = _current.get("last_event") or {}
    happened = {"login_done": " Pemilik sudah selesai login di halaman itu.",
                "route_selected": f" Pemilik memilih rute ke-{(last.get('detail') or {}).get('index', 0) + 1}.",
                "draft_copied": " Pemilik sudah menyalin draf.", "draft_sent": " Pemilik sudah mengirim draf.",
                "paused": " Musik/video dijeda."}.get(last.get("event"), "")
    return f"LAYAR HP SEKARANG (Panggung): {what}. {_current.get('caption', '')}{happened}".strip()


async def on_event(stage_id: str, event: str, detail: dict | None = None) -> None:
    """The owner acted on a panel: closed it, finished logging in, picked a route, paused the music."""
    global _current
    if not _current or _current["id"] != stage_id:
        return
    if event == "closed":
        _current = None
        return
    _current = {**_current, "last_event": {"event": event[:40], "detail": detail or {}, "at": time.time()}}
    if event == "route_selected" and isinstance((detail or {}).get("index"), int):
        _current["payload"] = {**_current["payload"], "selected": detail["index"]}
    await audit.record("owner", "stage.event", None, panel=_current["panel"], event=event[:40])
