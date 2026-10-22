"""Simpanan: one list of everything JARVIS made or showed the owner (ADR-036).

Sources, each keyed '<source>:<id>':
  doc      documents (docx/xlsx/pdf: drafts, minutes, reports)      — documents table
  playlist the owner's playlists                                    — playlists table
  music    songs fetched as MP3 (purged after 30 days unless kept) — /data/media/<id>.json
  meeting  finished meetings with minutes                           — meetings table
  shown    pictures, videos, web pages, maps, notes, drafts, boards — stage_history (stage.show records them)
'kind' is what the app filters on: musik, playlist, dokumen, draf, gambar, video, web, peta, teks, rapat.
"""

import json
import logging
import re

from . import audit, db, documents, musiclib, playlists, stage

log = logging.getLogger("jarvis-core.library")
HISTORY_KEEP = 500
KINDS = ("musik", "playlist", "dokumen", "draf", "gambar", "video", "web", "peta", "teks", "rapat", "lainnya")
_PANEL_KIND = {"image": "gambar", "gallery": "gambar", "video": "video", "web": "web", "map": "peta", "text": "teks",
               "draft": "draf", "doc": "dokumen"}
_KEY = re.compile(r"^(doc|playlist|music|meeting|shown):([0-9A-Za-z-]{1,64})$")
_NOT_RECORDED = {"music", "audio"}  # songs are listed from the media folder; a song panel is not a new item


class LibraryError(ValueError):
    pass


def kind_of_panel(panel: str, payload: dict) -> str:
    """What the app calls a shown panel. A board is named by its most telling block. Pure; unit-tested."""
    if panel == "board":
        kinds = [_PANEL_KIND.get(b.get("kind"), "lainnya") for b in payload.get("blocks") or []]
        for k in ("draf", "dokumen", "video", "gambar", "peta", "web", "teks"):
            if k in kinds:
                return k
        return "lainnya"
    return _PANEL_KIND.get(panel, "lainnya")


def title_of(panel: str, payload: dict, caption: str = "") -> str:
    """A readable title for a shown panel. Pure."""
    for t in (caption, payload.get("title"), payload.get("subject"), payload.get("query"), payload.get("to"),
              payload.get("domain"), payload.get("url")):
        if isinstance(t, str) and t.strip():
            return re.sub(r"\s+", " ", t.strip())[:160]
    return {"text": "Catatan", "map": "Peta", "image": "Gambar", "draft": "Draf"}.get(panel, panel.capitalize())


def parse_key(key: str) -> tuple[str, str]:
    m = _KEY.match(key or "")
    if not m:
        raise LibraryError("item tidak dikenal")
    return m.group(1), m.group(2)


async def record(panel: str, payload: dict, caption: str = "") -> None:
    """Called by stage.show: remember what was shown so it can be shown again. Never fails the show."""
    if panel in _NOT_RECORDED:
        return
    try:
        await db.pool().execute("INSERT INTO stage_history (panel, title, payload) VALUES ($1, $2, $3)",
                                panel, title_of(panel, payload, caption), json.dumps(payload, ensure_ascii=False))
        await db.pool().execute(
            """DELETE FROM stage_history WHERE id IN (
                 SELECT id FROM stage_history ORDER BY id DESC OFFSET $1)
               AND 'shown:' || id NOT IN (SELECT key FROM library_kept)""", HISTORY_KEEP)
    except Exception as e:
        log.warning("stage history not saved: %s", e)


async def kept() -> set[str]:
    return {r["key"] for r in await db.pool().fetch("SELECT key FROM library_kept")}


def _songs() -> list[dict]:
    out = []
    if not musiclib.ROOT.is_dir():
        return out
    for meta_path in musiclib.ROOT.glob("*.json"):
        try:
            m = json.loads(meta_path.read_text())
            if not (musiclib.ROOT / m["file"]).is_file():
                continue
        except (OSError, ValueError, KeyError):
            continue
        mid = meta_path.stem
        out.append({"key": f"music:{mid}", "kind": "musik", "title": m.get("title") or "Lagu",
                    "subtitle": m.get("artist") or "", "at": meta_path.stat().st_mtime,
                    "url": f"/api/v1/media/{mid}", "format": "mp3"})
    return out


async def items(kind: str = "", query: str = "", limit: int = 200) -> list[dict]:
    """Newest first. kind: one of KINDS or '' for all; query matches the title/subtitle."""
    if kind and kind not in KINDS:
        raise LibraryError("jenis tidak dikenal")
    out: list[dict] = []
    for d in await documents.list_(limit=300):
        is_draft = d["title"].lower().startswith("draf")
        out.append({"key": f"doc:{d['id']}", "kind": "draf" if is_draft else "dokumen", "title": d["title"],
                    "subtitle": d["format"].upper(), "at": d["created_at"].timestamp(), "url": d["url"],
                    "format": d["format"]})
    for p in await playlists.all_():
        out.append({"key": f"playlist:{p['id']}", "kind": "playlist", "title": p["name"],
                    "subtitle": f"{p.get('songs', 0)} lagu", "at": p["created_at"].timestamp()})
    out += _songs()
    for r in await db.pool().fetch(
            "SELECT id, title, started_at, done_at, document_id FROM meetings WHERE status = 'done' ORDER BY id DESC LIMIT 200"):
        out.append({"key": f"meeting:{r['id']}", "kind": "rapat", "title": r["title"] or f"Rapat #{r['id']}",
                    "subtitle": "notulen", "at": (r["done_at"] or r["started_at"]).timestamp(),
                    **({"url": f"/api/v1/documents/{r['document_id']}", "format": "docx"} if r["document_id"] else {})})
    for r in await db.pool().fetch("SELECT id, panel, title, payload, created_at FROM stage_history ORDER BY id DESC LIMIT 500"):
        payload = json.loads(r["payload"]) if isinstance(r["payload"], str) else r["payload"]
        out.append({"key": f"shown:{r['id']}", "kind": kind_of_panel(r["panel"], payload), "title": r["title"],
                    "subtitle": "ditampilkan", "at": r["created_at"].timestamp(), "panel": r["panel"],
                    **({"url": payload["url"]} if str(payload.get("url") or "").startswith("https://") else {})})
    stars = await kept()
    for i in out:
        i["kept"] = i["key"] in stars
    q = query.strip().lower()
    out = [i for i in out if (not kind or i["kind"] == kind)
           and (not q or q in i["title"].lower() or q in str(i.get("subtitle", "")).lower())]
    out.sort(key=lambda i: i["at"], reverse=True)
    return out[:limit]


async def show(key: str) -> dict:
    """Show an item again on the phone's front screen."""
    source, ident = parse_key(key)
    match source:
        case "shown":
            r = await db.pool().fetchrow("SELECT panel, title, payload FROM stage_history WHERE id = $1", int(ident))
            if not r:
                raise LibraryError("sudah tidak ada")
            payload = json.loads(r["payload"]) if isinstance(r["payload"], str) else r["payload"]
            return await stage.show(r["panel"], payload, r["title"], "owner",
                                    drafts=any(b.get("kind") == "draft" for b in payload.get("blocks") or []))
        case "music":
            found = musiclib.find(ident)
            if not found:
                raise LibraryError("lagunya sudah terhapus")
            m = json.loads((musiclib.ROOT / f"{ident}.json").read_text())
            return await stage.show("music", {"title": m.get("title") or "Lagu", "artist": m.get("artist") or "",
                                              "url": f"/api/v1/media/{ident}", "cover_url": m.get("cover_url") or ""},
                                    m.get("title") or "Lagu", "owner")
        case "playlist":
            p = next((p for p in await playlists.all_() if str(p["id"]) == ident), None)
            if not p:
                raise LibraryError("playlist sudah tidak ada")
            return await playlists.play(p["name"])
        case "doc" | "meeting":
            if source == "meeting":
                ident = str(await db.pool().fetchval("SELECT document_id FROM meetings WHERE id = $1", int(ident)) or "")
            found = await documents.get(ident) if ident else None
            if not found:
                raise LibraryError("dokumennya sudah tidak ada")
            row, _ = found
            return await stage.show("doc", {"title": row["title"], "url": f"/api/v1/documents/{row['id']}",
                                            "format": row["format"]}, row["title"], "owner")
    raise LibraryError("item tidak dikenal")


async def keep(key: str, on: bool, actor: str) -> bool:
    parse_key(key)
    if on:
        await db.pool().execute("INSERT INTO library_kept (key) VALUES ($1) ON CONFLICT DO NOTHING", key)
    else:
        await db.pool().execute("DELETE FROM library_kept WHERE key = $1", key)
    await audit.record(actor, "library.keep" if on else "library.unkeep", key)
    return on


async def delete(key: str, actor: str) -> bool:
    """Remove an item for good (the file too). Meetings are deleted from the Rapat menu, not here."""
    source, ident = parse_key(key)
    done = False
    match source:
        case "shown":
            done = (await db.pool().execute("DELETE FROM stage_history WHERE id = $1", int(ident))).endswith(" 1")
        case "music":
            found = musiclib.find(ident)
            if found:
                found[0].unlink(missing_ok=True)
                (musiclib.ROOT / f"{ident}.json").unlink(missing_ok=True)
                done = True
        case "doc":
            found = await documents.get(ident)
            if found:
                row, path = found
                await db.pool().execute("DELETE FROM documents WHERE id = $1", row["id"])
                path.unlink(missing_ok=True)
                done = True
        case "playlist":
            p = next((p for p in await playlists.all_() if str(p["id"]) == ident), None)
            if p:
                await db.pool().execute("DELETE FROM playlists WHERE id = $1", p["id"])
                done = True
        case "meeting":
            raise LibraryError("rapat dihapus dari menu Rapat")
    if done:
        await db.pool().execute("DELETE FROM library_kept WHERE key = $1", key)
        await audit.record(actor, "library.delete", key)
    return done


async def purge_media() -> int:
    """musiclib.purge_old, sparing starred songs."""
    stars = {k.split(":", 1)[1] for k in await kept() if k.startswith("music:")}
    return musiclib.purge_old(keep=stars)


async def find(query: str, kind: str = "") -> list[dict]:
    """For the main agent / Hermes: the best matches, short."""
    found = await items(kind if kind in KINDS else "", query, limit=8)
    return [{k: i[k] for k in ("key", "kind", "title", "subtitle") if k in i} for i in found]
