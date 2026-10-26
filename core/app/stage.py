"""The phone's contextual front screen ("Panggung"): JARVIS shows what fits the conversation.

Panels: music, audio, video, image, gallery, map, web (read an article / let the owner log in), doc, text,
draft — and board: several of these stacked (anything at once). show_any() picks the panel from what it
is given (a URL's type, a text, a place). The 3D brain is always the background of the phone's home. Events go to every connected device:
  {"type": "stage", "id", "panel", "mode": "show"|"update"|"close", "payload", "caption"}
The last open panel is kept so a phone that reconnects sees the same thing.
"""

import re
import time
import uuid
from urllib.parse import urlparse

from . import audit, hub

PANELS = {"music", "audio", "video", "image", "map", "web", "gallery", "doc", "text", "draft", "board"}
BOARD_BLOCKS = PANELS - {"board", "draft"}  # a board never holds drafts or another board
MAX_TEXT = 20_000
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


def validate(panel: str, payload: dict, drafts: bool = False) -> dict:
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
    if panel in ("audio", "image") and not payload.get("url"):
        raise StageError(f"{panel} butuh url")
    if panel == "text":
        if not str(payload.get("text") or "").strip():
            raise StageError("text butuh isi")
        payload = {**payload, "text": str(payload["text"])[:MAX_TEXT]}
    if panel == "board":
        blocks = payload.get("blocks") or []
        if not (1 <= len(blocks) <= 12) or not all(isinstance(b, dict) for b in blocks):
            raise StageError("board butuh 1–12 blok")
        checked = []
        for b in blocks:
            kind = b.get("kind")
            if kind not in BOARD_BLOCKS and not (drafts and kind == "draft"):  # core's writer: draft + its file
                raise StageError(f"blok tidak dikenal: {kind}")
            if kind == "web" and b.get("mode", "read") != "read":
                raise StageError("login web hanya sebagai panel sendiri")
            checked.append({**validate(kind, {k: v for k, v in b.items() if k != "kind"}), "kind": kind})
        payload = {**payload, "blocks": checked}
    if panel == "draft":
        variants = payload.get("variants") or []
        if not (1 <= len(variants) <= 4) or not all(isinstance(v, dict) and v.get("text") for v in variants):
            raise StageError("draf butuh 1–4 varian berisi text")
    return payload


_EXT = {"audio": (".mp3", ".m4a", ".aac", ".ogg", ".oga", ".opus", ".wav", ".flac"),
        "video": (".mp4", ".webm", ".m3u8", ".mov", ".mkv"),
        "image": (".jpg", ".jpeg", ".png", ".webp", ".gif", ".avif"),
        "doc": (".pdf", ".docx", ".xlsx", ".pptx")}
_YOUTUBE = re.compile(r"^https://(www\.|m\.)?(youtube\.com/(watch|shorts)|youtu\.be/)", re.IGNORECASE)


def guess(item: dict) -> tuple[str, dict]:
    """What panel fits one thing to show (pure, unit-tested): {"url"} by type, {"text"}, or {"lat","lon"}."""
    if item.get("text") and not item.get("url"):
        return "text", {"title": item.get("title", ""), "text": item["text"]}
    if "lat" in item and "lon" in item:
        return "map", {"title": item.get("title") or item.get("label", ""),
                       "markers": [{"lat": item["lat"], "lon": item["lon"], "label": item.get("label") or item.get("title", "")}]}
    url = str(item.get("url") or "")
    path = urlparse(url).path.lower()
    title = item.get("title", "")
    if url.startswith("/api/v1/media/"):
        return ("video" if item.get("kind") == "video" else "audio"), {"url": url, "title": title}
    if url.startswith("/api/v1/documents/"):
        return "doc", {"url": url, "title": title, "format": item.get("format", "")}
    if _YOUTUBE.match(url):
        return "video", {"url": url, "title": title}
    for kind, exts in _EXT.items():
        if path.endswith(exts):
            return kind, {"url": url, "title": title, **({"format": path.rsplit(".", 1)[-1]} if kind == "doc" else {})}
    return "web", {"url": url, "mode": "read", "title": title}


async def show_any(items: list[dict], caption: str = "", actor: str = "jarvis") -> dict:
    """Show anything: one item → its own panel; several → a board with one block each."""
    if not items:
        raise StageError("tidak ada yang ditampilkan")
    parts = [guess(i) for i in items[:12]]
    if len(parts) == 1:
        return await show(parts[0][0], parts[0][1], caption, actor)
    return await show("board", {"title": caption, "blocks": [{"kind": k, **p} for k, p in parts]}, caption, actor)


async def show(panel: str, payload: dict, caption: str = "", actor: str = "jarvis", drafts: bool = False) -> dict:
    global _current
    payload = validate(panel, payload, drafts)
    event = {"type": "stage", "id": uuid.uuid4().hex[:12], "panel": panel, "mode": "show",
             "payload": payload, "caption": caption[:200], "at": time.time()}
    _current = event
    delivered = await hub.broadcast(event)
    from . import library
    shown = await library.record(panel, payload, caption)  # Simpanan: shown again later
    if shown and actor != "owner":  # what JARVIS shows also lands on the galaxy (ADR-049); a re-show from Simpanan does not
        from . import canvas
        await canvas.auto(f"shown:{shown}")
    await audit.record(actor, "stage.show", None, panel=panel, delivered=delivered)
    return {"id": event["id"], "delivered": delivered}


async def update(stage_id: str, payload: dict) -> dict:
    global _current
    if not _current or _current["id"] != stage_id:
        raise StageError("panel itu sudah tidak tampil")
    drafts = any(b.get("kind") == "draft" for b in _current["payload"].get("blocks") or [])
    payload = validate(_current["panel"], {**_current["payload"], **payload}, drafts)
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


def desk_player() -> dict | None:
    """What the desk's player card shows (ADR-054): the music / sound / video panel that is up, else nothing. The id changes with each
    song, so a viewer builds a new player only then; the rest of the fields describe it."""
    cur = _current
    if not cur or cur["panel"] not in ("music", "audio", "video"):
        return None
    p = cur["payload"] or {}
    pl = p.get("playlist") if isinstance(p.get("playlist"), dict) else None
    return {"id": cur["id"], "panel": cur["panel"], "title": str(p.get("title") or "")[:200],
            "artist": str(p.get("artist") or p.get("channel") or "")[:200], "url": str(p.get("url") or ""),
            "cover_url": str(p.get("cover_url") or ""), "caption": cur.get("caption", ""), "playlist": pl,
            "license": str(p.get("license") or ""), "at": cur.get("at")}


def describe() -> str | None:
    """For the main agent's prompt: what the owner is looking at."""
    if not _current:
        return None
    p = _current["payload"]
    what = {"music": f"memutar musik: {p.get('title', '')}", "audio": f"memutar suara: {p.get('title', '')}",
            "video": f"video: {p.get('title', '')}", "image": f"gambar: {p.get('title', '')}",
            "map": f"peta: {p.get('title', '')}", "web": f"halaman web {p.get('domain', '')}",
            "gallery": "galeri gambar", "doc": f"dokumen: {p.get('title', '')}", "text": f"catatan: {p.get('title', '')}",
            "draft": "draf balasan pesan",
            "board": "beberapa hal sekaligus (" + ", ".join(b.get("kind", "") for b in p.get("blocks", [])) + ")"
            }[_current["panel"]]
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
    if (_current["payload"] or {}).get("playlist") and event in ("ended", "next", "prev"):
        from . import playlists
        playlists.on_stage_event(event)  # a playlist is playing: the following (or previous) song comes next
    _current = {**_current, "last_event": {"event": event[:40], "detail": detail or {}, "at": time.time()}}
    if event == "route_selected" and isinstance((detail or {}).get("index"), int):
        _current["payload"] = {**_current["payload"], "selected": detail["index"]}
    await audit.record("owner", "stage.event", None, panel=_current["panel"], event=event[:40])
