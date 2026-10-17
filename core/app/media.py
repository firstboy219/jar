"""Pictures and videos JARVIS shows the owner on the phone ("menampilkan maksud mereka").

Workers find media (jarvis-tools: find_images / find_videos, or any image they met while browsing) and
call show_media; jarvis-tools forwards it here and the hub pushes it to the owner's devices. URLs are
checked before reaching the phone: https only, images must really be images of sane size.
"""

import re

import httpx

from . import audit, hub

YOUTUBE = re.compile(r"^https://(www\.|m\.)?(youtube\.com/watch\?v=|youtu\.be/)([A-Za-z0-9_-]{11})")
MAX_IMAGE_BYTES = 15_000_000


def youtube_thumbnail(url: str) -> str | None:
    m = YOUTUBE.match(url)
    return f"https://i.ytimg.com/vi/{m.group(3)}/hqdefault.jpg" if m else None


async def _image_ok(client: httpx.AsyncClient, url: str) -> bool:
    try:
        r = await client.head(url, follow_redirects=True)
        if r.status_code >= 400 or "image/" not in r.headers.get("content-type", ""):
            # some hosts reject HEAD: fall back to a tiny ranged GET
            r = await client.get(url, headers={"Range": "bytes=0-1023"}, follow_redirects=True)
        size = int(r.headers.get("content-length") or 0)
        return r.status_code < 400 and r.headers.get("content-type", "").startswith("image/") and size <= MAX_IMAGE_BYTES
    except (httpx.HTTPError, ValueError):
        return False


async def clean(items: list[dict]) -> list[dict]:
    """Keep valid items only, normalised to {kind, url, title, thumbnail, source}."""
    out = []
    async with httpx.AsyncClient(timeout=8, headers={"User-Agent": "JARVIS/1.0"}) as client:
        for it in items[:12]:
            url = str(it.get("url", "")).strip()
            if not url.startswith("https://"):
                continue
            kind = it.get("kind") if it.get("kind") in ("image", "video", "link") else "image"
            item = {"kind": kind, "url": url, "title": str(it.get("title") or "")[:160],
                    "source": str(it.get("source") or "")[:120], "thumbnail": None}
            if kind == "video":
                item["thumbnail"] = youtube_thumbnail(url) or it.get("thumbnail")
            elif kind == "image" and not await _image_ok(client, url):
                continue
            if item["thumbnail"] and not str(item["thumbnail"]).startswith("https://"):
                item["thumbnail"] = None
            out.append(item)
    return out


async def show(items: list[dict], caption: str, actor: str) -> dict:
    good = await clean(items)
    if not good:
        return {"shown": 0, "reason": "tidak ada URL media yang valid (harus https dan benar-benar gambar/video)"}
    devices = await hub.broadcast({"type": "media", "caption": caption[:300], "items": good})
    await audit.record(actor, "media.shown", None, count=len(good), caption=caption[:120])
    return {"shown": len(good), "devices": devices,
            "note": "Tampil di layar HP pemilik." if devices else "Tidak ada perangkat yang terhubung saat ini."}
