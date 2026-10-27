"""The canvas — JARVIS's workspace as a board (Blueprint v4 Fase 4, ADR-049; a 3D galaxy first, a 2D Miro/Figma-style board since Fase 11, ADR-055).
The plane of the board is x (right) and z (down); y is kept as the old 3D height and ignored by the viewer.

One galaxy per context: "utama" (everyday), "project:<name>", and "company:<id>" for each company. Each galaxy has
constellations, one per kind of card (tugas, dokumen, tampilan, rapat, memori, …), laid out on spiral arms; the owner and
JARVIS can move cards anywhere in 3D space (it is infinite), link them, and fly to them.

A canvas stores LAYOUT, never knowledge: a card is a reference '<type>:<id>' resolved when the canvas is read —
  shown:<stage_history id>   doc:<document uuid>   meeting:<id>   playlist:<id>   music:<id>   memory:<uuid>
  task:<id>   goal:<id>   vault:<company_vault id>   directive:<gm_directives id>   decision:<decision_vault id>
  obj:<token>   a free object the owner drew on the board — note, text, shape or frame; it lives in the node itself (props)
Isolation (§4.4): a card may only reference things of its canvas's owner — a company's galaxy only that company's
vault, directives, decisions, tasks and their documents; a personal galaxy never anything of a company. Checked when a
card is added AND again when the canvas is read; company galaxies are read inside the company's row-level-security scope.
The canvas can navigate, select, place, move, resize, link and hide cards — it can never approve, delete (other than the owner's own notes and
shapes), send or pay.
"""

import contextlib
import json
import math
import re

from . import audit, companies, db

KINDS = {  # constellation → (title, colour) — the viewer draws them
    "tampilan": ("Yang ditampilkan", "#38bdf8"), "dokumen": ("Dokumen", "#a78bfa"), "rapat": ("Rapat", "#f472b6"),
    "musik": ("Musik", "#fb923c"), "memori": ("Memori", "#34d399"), "tugas": ("Tugas", "#facc15"),
    "tujuan": ("Tujuan", "#f87171"), "perusahaan": ("Data perusahaan", "#2dd4bf"), "arahan": ("Arahan tim", "#60a5fa"),
    "keputusan": ("Keputusan", "#e879f9"), "papan": ("Catatan & bentuk", "#94a3b8"),
}
REF = re.compile(r"^(shown|doc|meeting|playlist|music|memory|task|goal|vault|directive|decision|obj):([0-9A-Za-z-]{1,64})$")
KIND_OF = {"shown": "tampilan", "doc": "dokumen", "meeting": "rapat", "playlist": "musik", "music": "musik",
           "memory": "memori", "task": "tugas", "goal": "tujuan", "vault": "perusahaan", "directive": "arahan",
           "decision": "keputusan", "obj": "papan"}
COMPANY_ONLY = {"vault", "directive"}          # these exist only inside a company
PERSONAL_ONLY = {"memory", "goal", "playlist", "music", "shown", "meeting"}   # personal things never go to a company galaxy
PERSONAL_KINDS = ["tugas", "tampilan", "dokumen", "rapat", "memori", "musik", "tujuan", "keputusan"]
COMPANY_KINDS = ["tugas", "perusahaan", "arahan", "dokumen", "keputusan"]   # a company galaxy has no personal constellations (free objects, kind "papan", have no zone: they sit where the owner puts them)
GALAXY_R = 2700.0                      # the ring the areas sit on, in board units
GRID_COLS, CELL_W, CELL_H = 4, 340, 230   # a card is about 300 × 160: this leaves a gutter
KEEP_VERSIONS = 60


class CanvasError(ValueError):
    pass


# ---------- pure geometry ----------

def constellation_center(kind: str, company: bool = False) -> tuple[float, float, float]:
    """Each kind has its own area of the board, on a ring around the middle (where the desk panels sit), one angle per kind. Pure."""
    order = COMPANY_KINDS if company else PERSONAL_KINDS
    i = order.index(kind) if kind in order else len(order)
    angle = i * (2 * math.pi / len(order))
    return (round(GALAXY_R * math.cos(angle), 2), 0.0, round(GALAXY_R * math.sin(angle), 2))


def place(kind: str, index: int, company: bool = False) -> tuple[float, float, float]:
    """The index-th card of an area: rows of GRID_COLS cards under the area's name, left to right, then down. Pure."""
    cx, _, cz = constellation_center(kind, company)
    col, row = index % GRID_COLS, index // GRID_COLS
    return (round(cx - GRID_COLS * CELL_W / 2 + col * CELL_W + 20, 2), 0.0, round(cz + 90 + row * CELL_H, 2))


_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)
_UUID_KINDS = {"doc", "memory", "meeting"}
_INT_KINDS = {"task", "goal", "shown", "playlist", "vault", "directive", "decision"}


def parse_ref(ref: str) -> tuple[str, str]:
    """'<type>:<id>' with an id of the right shape (a bad id never reaches SQL, where it would abort the transaction)."""
    m = REF.match(ref or "")
    if not m or (m.group(1) in _UUID_KINDS and not _UUID.match(m.group(2))) or (m.group(1) in _INT_KINDS and not m.group(2).isdigit()):
        raise CanvasError(f"rujukan kartu tidak dikenal: {ref!r}")
    return m.group(1), m.group(2)


def context_company(context: str) -> str | None:
    return context.split(":", 1)[1] if context.startswith("company:") else None


def context_of(value: str) -> str:
    """'utama' / 'project:Toko Online' → 'project:toko-online' / 'company:renature'. Pure."""
    v = (value or "utama").strip()
    if v.lower() in ("utama", "regular", ""):
        return "utama"
    if v.startswith("company:"):
        return "company:" + companies._check_id(v.split(":", 1)[1])
    name = v.split(":", 1)[1] if v.startswith("project:") else v
    s = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:60]
    if not s:
        raise CanvasError("nama proyek kosong")
    return "project:" + s


# ---------- connections ----------

@contextlib.asynccontextmanager
async def _conn(company_id: str | None):
    if company_id:
        async with companies.scope(company_id) as conn:
            yield conn
    else:
        async with db.pool().acquire() as conn, conn.transaction():
            yield conn


async def _canvas_row(canvas_id: int) -> dict:
    """Personal canvases are visible without a scope; for a company one, find its company first (not secret)."""
    row = await db.pool().fetchrow("SELECT * FROM canvases WHERE id = $1", canvas_id)
    if row:
        return dict(row)
    for c in await companies.all_(True):
        async with companies.scope(c["id"]) as conn:
            if row := await conn.fetchrow("SELECT * FROM canvases WHERE id = $1", canvas_id):
                return dict(row)
    raise CanvasError("kanvas tidak ada")


# ---------- contexts ----------

async def contexts() -> list[dict]:
    """Every galaxy the owner can open: utama, projects that have one, each active company."""
    rows = [dict(r) for r in await db.pool().fetch(
        "SELECT id, context, title, version, (SELECT count(*) FROM canvas_nodes n WHERE n.canvas_id = c.id) AS cards "
        "FROM canvases c WHERE company_id IS NULL ORDER BY context = 'utama' DESC, title")]
    if not any(r["context"] == "utama" for r in rows):
        rows.insert(0, {"id": None, "context": "utama", "title": "Utama", "version": 0, "cards": 0})
    for c in await companies.all_():
        async with companies.scope(c["id"]) as conn:
            r = await conn.fetchrow("SELECT id, version, (SELECT count(*) FROM canvas_nodes n WHERE n.canvas_id = c.id) AS cards "
                                    "FROM canvases c WHERE context = $1", f"company:{c['id']}")
        rows.append({"id": r["id"] if r else None, "context": f"company:{c['id']}", "title": c["name"],
                     "version": r["version"] if r else 0, "cards": r["cards"] if r else 0, "company_id": c["id"]})
    return rows


async def ensure(context: str, title: str | None = None) -> dict:
    context = context_of(context)
    company = context_company(context)
    if company:
        title = title or (await companies.get(company))["name"]
    async with _conn(company) as conn:
        row = await conn.fetchrow("SELECT * FROM canvases WHERE context = $1", context)
        if not row:
            row = await conn.fetchrow(
                """INSERT INTO canvases (context, title, company_id) VALUES ($1, $2, $3)
                   ON CONFLICT (context) DO UPDATE SET context = EXCLUDED.context RETURNING *""",
                context, (title or ("Utama" if context == "utama" else context.split(":", 1)[1].replace("-", " ").title()))[:80],
                company)
    return dict(row)


# ---------- whose is a reference ----------

async def owner_of(ref: str) -> tuple[bool, str | None]:
    """(exists, company_id or None) of the thing a card points at."""
    kind, ident = parse_ref(ref)
    p = db.pool()
    try:
        match kind:
            case "obj":
                return (True, None)   # the node row is the object; the viewer drops it when the row is gone
            case "task":
                row = await p.fetchrow("SELECT company_id FROM tasks WHERE id = $1", int(ident))
                return (row is not None, row["company_id"] if row else None)
            case "doc":
                row = await p.fetchrow("SELECT t.company_id FROM documents d LEFT JOIN tasks t ON t.id = d.task_id WHERE d.id = $1::uuid", ident)
                return (row is not None, row["company_id"] if row else None)
            case "memory":
                return (await p.fetchval("SELECT 1 FROM memories WHERE id = $1::uuid", ident) is not None, None)
            case "goal":
                return (await p.fetchval("SELECT 1 FROM goals WHERE id = $1", int(ident)) is not None, None)
            case "shown":
                return (await p.fetchval("SELECT 1 FROM stage_history WHERE id = $1", int(ident)) is not None, None)
            case "meeting":
                return (await p.fetchval("SELECT 1 FROM meetings WHERE id = $1::uuid", ident) is not None, None)
            case "playlist":
                return (await p.fetchval("SELECT 1 FROM playlists WHERE id = $1", int(ident)) is not None, None)
            case "music":
                from . import musiclib
                return (bool(musiclib.find(ident)), None)
            case "vault" | "directive" | "decision":
                table = {"vault": "company_vault", "directive": "gm_directives", "decision": "decision_vault"}[kind]
                for c in await companies.all_(True):   # each company only within its own scope
                    async with companies.scope(c["id"]) as conn:
                        row = await conn.fetchrow(f"SELECT company_id FROM {table} WHERE id = $1", int(ident))
                    if row and (row["company_id"] is not None or kind != "decision"):
                        return (True, row["company_id"])
                if kind == "decision":
                    row = await p.fetchrow("SELECT company_id FROM decision_vault WHERE id = $1 AND company_id IS NULL", int(ident))
                    return (row is not None, None)
                return (False, None)
    except (ValueError, TypeError):
        return (False, None)
    return (False, None)


def allowed(ref: str, canvas_company: str | None, ref_company: str | None) -> bool:
    """Isolation rule for one card. Pure; unit-tested."""
    kind, _ = parse_ref(ref)
    if kind == "obj":   # the owner's own drawing: any board may hold it, it points at no one's data
        return True
    if canvas_company:
        return kind not in PERSONAL_ONLY and ref_company == canvas_company
    return kind not in COMPANY_ONLY and ref_company is None


# ---------- changes ----------

async def _bump(conn, canvas: dict, actor: str, change: str) -> int:
    v = await conn.fetchval("UPDATE canvases SET version = version + 1, updated_at = now() WHERE id = $1 RETURNING version", canvas["id"])
    nodes = await conn.fetch("SELECT id, kind, ref, x, y, z, size, pinned, w, h, props FROM canvas_nodes WHERE canvas_id = $1", canvas["id"])
    edges = await conn.fetch("SELECT a, b, label, style FROM canvas_edges WHERE canvas_id = $1", canvas["id"])
    await conn.execute("""INSERT INTO canvas_versions (canvas_id, version, company_id, snapshot, actor, change)
                          VALUES ($1, $2, $3, $4, $5, $6)""", canvas["id"], v, canvas["company_id"],
                       {"nodes": [dict(n) for n in nodes], "edges": [dict(e) for e in edges]}, actor, change[:120])
    await conn.execute("DELETE FROM canvas_versions WHERE canvas_id = $1 AND version <= $2", canvas["id"], v - KEEP_VERSIONS)
    return v


async def add(context: str, ref: str, actor: str, pos: tuple[float, float, float] | None = None, *, quiet: bool = False) -> dict:
    """Put a card on a galaxy (idempotent: the same thing twice is one card)."""
    kind_key, _ = parse_ref(ref)
    canvas = await ensure(context)
    exists, ref_company = await owner_of(ref)
    if not exists:
        raise CanvasError("yang dirujuk tidak ada")
    if not allowed(ref, canvas["company_id"], ref_company):
        raise CanvasError("kartu ini bukan milik kanvas ini (kanvas tiap perusahaan dan kanvas pribadi terpisah penuh)")
    kind = KIND_OF[kind_key]
    async with _conn(canvas["company_id"]) as conn:
        found = await conn.fetchrow("SELECT * FROM canvas_nodes WHERE canvas_id = $1 AND ref = $2", canvas["id"], ref)
        if found:
            return dict(found) | {"existing": True}
        n = await conn.fetchval("SELECT count(*) FROM canvas_nodes WHERE canvas_id = $1 AND kind = $2", canvas["id"], kind)
        x, y, z = pos or place(kind, n, bool(canvas["company_id"]))
        row = await conn.fetchrow(
            """INSERT INTO canvas_nodes (canvas_id, company_id, kind, ref, x, y, z, created_by)
               VALUES ($1, $2, $3, $4, $5, $6, $7, $8) RETURNING *""", canvas["id"], canvas["company_id"], kind, ref, x, y, z, actor)
        await _bump(conn, canvas, actor, f"kartu {ref}")
    if not quiet:
        await audit.record(actor, "canvas.card_added", f"canvas:{canvas['id']}", ref=ref)
    return dict(row)


async def auto(ref: str, company_id: str | None = None) -> None:
    """JARVIS places what it made (a task's result, a document, something shown). Never fails the caller."""
    import logging
    try:
        await add(f"company:{company_id}" if company_id else "utama", ref, "jarvis", quiet=True)
    except Exception as e:
        logging.getLogger("jarvis-core.canvas").info("card %s not placed: %s", ref, e)


async def touch(ref: str, company_id: str | None = None) -> None:
    """What a card shows changed (a task finished): bump the version of every galaxy holding it, so open viewers re-read it."""
    try:
        async with _conn(company_id) as conn:
            await conn.execute("UPDATE canvases SET version = version + 1 WHERE id IN (SELECT canvas_id FROM canvas_nodes WHERE ref = $1)", ref)
    except Exception as e:
        import logging
        logging.getLogger("jarvis-core.canvas").info("touch %s failed: %s", ref, e)


async def fill(context: str, actor: str, limit: int = 300) -> dict:
    """Put what is in storage (the library: documents, drafts, songs, playlists, meetings, what was shown) on this galaxy.
    Idempotent; only what this galaxy may hold (a company galaxy takes none of the personal library)."""
    from . import library
    canvas = await ensure(context)
    if canvas["company_id"]:
        return {"added": 0, "note": "galaksi perusahaan hanya memuat data perusahaannya"}
    added = 0
    for i in await library.items(limit=limit):
        if not REF.match(i["key"]):
            continue
        try:
            n = await add(context, i["key"], actor, quiet=True)
        except CanvasError:
            continue
        added += 0 if n.get("existing") else 1
    return {"added": added}


async def _node(node_id: int) -> tuple[dict, dict]:
    row = await db.pool().fetchrow("SELECT canvas_id FROM canvas_nodes WHERE id = $1", node_id)
    if row:
        canvas = await _canvas_row(row["canvas_id"])
    else:
        canvas = None
        for c in await companies.all_(True):
            async with companies.scope(c["id"]) as conn:
                if r := await conn.fetchrow("SELECT canvas_id FROM canvas_nodes WHERE id = $1", node_id):
                    canvas = await _canvas_row(r["canvas_id"])
                    break
        if not canvas:
            raise CanvasError("kartu tidak ada")
    async with _conn(canvas["company_id"]) as conn:
        node = await conn.fetchrow("SELECT * FROM canvas_nodes WHERE id = $1", node_id)
    return dict(node), canvas


def _coord(v) -> float:
    f = float(v)
    if not math.isfinite(f) or abs(f) > 1e6:
        raise CanvasError("posisi tidak valid")
    return f


def _extent(v, lo: float, hi: float) -> float:
    f = float(v)
    if not math.isfinite(f):
        raise CanvasError("ukuran tidak valid")
    return min(max(f, lo), hi)


async def move(node_id: int, actor: str, x=None, y=None, z=None, size=None, pinned=None, w=None, h=None, props=None) -> dict:
    node, canvas = await _node(node_id)
    vals = {k: _coord(v) for k, v in (("x", x), ("y", y), ("z", z)) if v is not None}
    if size is not None:
        vals["size"] = min(max(float(size), 0.3), 4.0)
    if pinned is not None:
        vals["pinned"] = bool(pinned)
    if w is not None:
        vals["w"] = _extent(w, 60, 4000)
    if h is not None:
        vals["h"] = _extent(h, 40, 4000)
    if props is not None:
        if not node["ref"].startswith("obj:"):
            raise CanvasError("hanya catatan, teks, bentuk dan bingkai yang punya properti")
        vals["props"] = {**(node["props"] if isinstance(node["props"], dict) else json.loads(node["props"] or "{}")), **clean_props(props, creating=False)}
    if not vals:
        return node
    sets = ", ".join(f"{k} = ${i + 2}" for i, k in enumerate(vals))
    async with _conn(canvas["company_id"]) as conn:
        row = await conn.fetchrow(f"UPDATE canvas_nodes SET {sets}, updated_at = now() WHERE id = $1 RETURNING *", node_id, *vals.values())
        await _bump(conn, canvas, actor, f"pindah #{node_id}")
    return dict(row)


OBJECT_TYPES = ("note", "text", "shape", "frame")
SHAPES = ("rect", "round", "ellipse", "diamond")
_COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")
MAX_OBJECT_TEXT = 4000


def clean_props(props: dict, creating: bool = True) -> dict:
    """What a free object may carry: only these keys, only these shapes of value. Pure; unit-tested."""
    if not isinstance(props, dict):
        raise CanvasError("properti harus berupa objek")
    out: dict = {}
    if creating or "type" in props:
        if props.get("type") not in OBJECT_TYPES:
            raise CanvasError(f"jenis objek: {', '.join(OBJECT_TYPES)}")
        if not creating:
            raise CanvasError("jenis objek tidak bisa diganti")
        out["type"] = props["type"]
    if "text" in props:
        out["text"] = str(props["text"] or "")[:MAX_OBJECT_TEXT]
    for key in ("color", "stroke"):
        if props.get(key) is not None:
            if not _COLOR.match(str(props[key])):
                raise CanvasError(f"{key}: warna harus #rrggbb")
            out[key] = str(props[key]).lower()
    if "shape" in props:
        if props["shape"] not in SHAPES:
            raise CanvasError(f"bentuk: {', '.join(SHAPES)}")
        out["shape"] = props["shape"]
    if "font" in props:
        out["font"] = int(_extent(props["font"], 10, 96))
    if "align" in props:
        if props["align"] not in ("left", "center", "right"):
            raise CanvasError("rata teks: left, center, right")
        out["align"] = props["align"]
    for flag in ("bold", "locked", "filled"):
        if flag in props:
            out[flag] = bool(props[flag])
    return out


def object_content(props) -> dict:
    """The viewer's card for a free object (what _resolve does for things that live elsewhere). Pure."""
    p = props if isinstance(props, dict) else json.loads(props or "{}")
    text = str(p.get("text") or "")
    first = text.strip().splitlines()[0] if text.strip() else ""
    return {"title": _short(first, 80) or {"note": "Catatan", "text": "Teks", "shape": "Bentuk", "frame": "Bingkai"}.get(p.get("type"), "Objek"),
            "subtitle": p.get("type", "objek"), "snippet": _short(text, 600), "type": p.get("type", "note"), "props": p}


DEFAULT_SIZE = {"note": (220, 180), "text": (240, 60), "shape": (180, 120), "frame": (560, 380)}


async def create_object(context: str, props: dict, actor: str, x: float = 0, z: float = 0, w=None, h=None) -> dict:
    """The owner draws a note / text / shape / frame on the board."""
    import secrets
    props = clean_props(props)
    canvas = await ensure(context)
    dw, dh = DEFAULT_SIZE[props["type"]]
    ref = f"obj:{secrets.token_hex(5)}"
    async with _conn(canvas["company_id"]) as conn:
        row = await conn.fetchrow(
            """INSERT INTO canvas_nodes (canvas_id, company_id, kind, ref, x, y, z, w, h, props, created_by)
               VALUES ($1, $2, 'papan', $3, $4, 0, $5, $6, $7, $8, $9) RETURNING *""",
            canvas["id"], canvas["company_id"], ref, _coord(x), _coord(z),
            _extent(w if w is not None else dw, 60, 4000), _extent(h if h is not None else dh, 40, 4000), props, actor)
        await _bump(conn, canvas, actor, f"buat {props['type']}")
    await audit.record(actor, "canvas.object_added", f"canvas:{canvas['id']}", type=props["type"])
    return dict(row)


async def move_many(canvas_id: int, items: list[dict], actor: str, note: str = "") -> dict:
    """Several cards at once (a multi-selection dragged, aligned or resized): one change, one history entry."""
    if not items or len(items) > 500:
        raise CanvasError("1–500 kartu sekaligus")
    canvas = await _canvas_row(canvas_id)
    async with _conn(canvas["company_id"]) as conn:
        have = {r["id"] for r in await conn.fetch("SELECT id FROM canvas_nodes WHERE canvas_id = $1 AND id = ANY($2::bigint[])",
                                                 canvas_id, [int(i["id"]) for i in items])}
        for it in items:
            if int(it["id"]) not in have:
                raise CanvasError("kartu bukan milik kanvas ini")
        for it in items:
            vals = {k: _coord(it[k]) for k in ("x", "y", "z") if it.get(k) is not None}
            if it.get("w") is not None:
                vals["w"] = _extent(it["w"], 60, 4000)
            if it.get("h") is not None:
                vals["h"] = _extent(it["h"], 40, 4000)
            if vals:
                sets = ", ".join(f"{k} = ${i + 2}" for i, k in enumerate(vals))
                await conn.execute(f"UPDATE canvas_nodes SET {sets}, updated_at = now() WHERE id = $1", int(it["id"]), *vals.values())
        v = await _bump(conn, canvas, actor, (note or f"atur {len(items)} kartu")[:120])
    return {"version": v, "moved": len(items)}


def clean_style(style: dict) -> dict:
    out: dict = {}
    if not isinstance(style, dict):
        raise CanvasError("gaya garis tidak valid")
    if "to" in style:   # null / 0 takes the arrow away
        out["to"] = int(style["to"]) if style["to"] else None
    if "dash" in style:
        out["dash"] = bool(style["dash"])
    if style.get("color") is not None:
        if not _COLOR.match(str(style["color"])):
            raise CanvasError("warna garis harus #rrggbb")
        out["color"] = str(style["color"]).lower()
    return out


async def update_edge(edge_id: int, canvas_id: int, actor: str, label: str | None = None, style: dict | None = None) -> dict:
    canvas = await _canvas_row(canvas_id)
    async with _conn(canvas["company_id"]) as conn:
        row = await conn.fetchrow("SELECT * FROM canvas_edges WHERE id = $1 AND canvas_id = $2", edge_id, canvas_id)
        if not row:
            raise CanvasError("garis tidak ada")
        merged = {**(row["style"] if isinstance(row["style"], dict) else json.loads(row["style"] or "{}")), **clean_style(style or {})}
        merged = {k: v for k, v in merged.items() if v is not None}
        if merged.get("to") not in (None, row["a"], row["b"]):
            raise CanvasError("panah harus menunjuk salah satu ujung garis")
        out = await conn.fetchrow("UPDATE canvas_edges SET label = $2, style = $3 WHERE id = $1 RETURNING *", edge_id,
                                  row["label"] if label is None else label.strip()[:60], merged)
        await _bump(conn, canvas, actor, f"ubah garis #{edge_id}")
    return dict(out)


async def arrange(canvas_id: int, actor: str) -> dict:
    """Put every card that points at something (not the owner's own drawings, not locked ones) back in the grid of its area."""
    canvas = await _canvas_row(canvas_id)
    async with _conn(canvas["company_id"]) as conn:
        rows = await conn.fetch("SELECT id, kind FROM canvas_nodes WHERE canvas_id = $1 AND NOT pinned AND ref NOT LIKE 'obj:%' ORDER BY kind, id", canvas_id)
        count: dict[str, int] = {}
        for r in rows:
            i = count[r["kind"]] = count.get(r["kind"], -1) + 1
            x, y, z = place(r["kind"], i, bool(canvas["company_id"]))
            await conn.execute("UPDATE canvas_nodes SET x = $2, y = $3, z = $4, updated_at = now() WHERE id = $1", r["id"], x, y, z)
        v = await _bump(conn, canvas, actor, f"rapikan {len(rows)} kartu")
    await audit.record(actor, "canvas.arranged", f"canvas:{canvas_id}", cards=len(rows))
    return {"version": v, "arranged": len(rows)}


async def hide(node_id: int, actor: str) -> bool:
    """Take a card off the canvas. The thing it points at is untouched (the canvas never deletes data)."""
    node, canvas = await _node(node_id)
    async with _conn(canvas["company_id"]) as conn:
        await conn.execute("DELETE FROM canvas_nodes WHERE id = $1", node_id)
        await _bump(conn, canvas, actor, f"lepas {node['ref']}")
    await audit.record(actor, "canvas.card_hidden", f"canvas:{canvas['id']}", ref=node["ref"])
    return True


async def link(a: int, b: int, actor: str, label: str = "", style: dict | None = None) -> dict:
    na, ca = await _node(a)
    nb, cb = await _node(b)
    if ca["id"] != cb["id"]:
        raise CanvasError("dua kartu harus di kanvas yang sama")
    async with _conn(ca["company_id"]) as conn:
        row = await conn.fetchrow(
            """INSERT INTO canvas_edges (canvas_id, company_id, a, b, label, style) VALUES ($1, $2, $3, $4, $5, $6)
               ON CONFLICT (a, b) DO UPDATE SET label = EXCLUDED.label, style = EXCLUDED.style RETURNING *""",
            ca["id"], ca["company_id"], min(a, b), max(a, b), label.strip()[:60], {k: v for k, v in clean_style(style or {}).items() if v is not None})
        await _bump(conn, ca, actor, f"hubung #{a}–#{b}")
    return dict(row)


async def unlink(edge_id: int, canvas_id: int, actor: str) -> bool:
    canvas = await _canvas_row(canvas_id)
    async with _conn(canvas["company_id"]) as conn:
        done = await conn.fetchval("DELETE FROM canvas_edges WHERE id = $1 AND canvas_id = $2 RETURNING id", edge_id, canvas_id)
        if done:
            await _bump(conn, canvas, actor, f"putus #{edge_id}")
    return bool(done)


async def focus(context: str, ref_or_node: str, actor: str) -> dict:
    """JARVIS (or the owner) asks every open viewer to fly to a card."""
    canvas = await ensure(context)
    async with _conn(canvas["company_id"]) as conn:
        node = await conn.fetchrow("SELECT id FROM canvas_nodes WHERE canvas_id = $1 AND (ref = $2 OR id::text = $2)",
                                   canvas["id"], ref_or_node)
        if not node:
            raise CanvasError("kartu itu belum ada di kanvas ini")
        await conn.execute("UPDATE canvases SET focus_node = $2 WHERE id = $1", canvas["id"], node["id"])
        v = await _bump(conn, canvas, actor, f"fokus #{node['id']}")
    return {"canvas_id": canvas["id"], "node": node["id"], "version": v}


async def versions(canvas_id: int) -> list[dict]:
    canvas = await _canvas_row(canvas_id)
    async with _conn(canvas["company_id"]) as conn:
        rows = await conn.fetch("""SELECT version, actor, change, at, jsonb_array_length(snapshot->'nodes') AS cards
                                   FROM canvas_versions WHERE canvas_id = $1 ORDER BY version DESC LIMIT 60""", canvas_id)
    return [dict(r) for r in rows]


async def restore(canvas_id: int, version: int, actor: str) -> dict:
    """Bring back the layout of an earlier version: positions, sizes, links. Cards whose thing is gone stay gone."""
    canvas = await _canvas_row(canvas_id)
    async with _conn(canvas["company_id"]) as conn:
        snap = await conn.fetchval("SELECT snapshot FROM canvas_versions WHERE canvas_id = $1 AND version = $2", canvas_id, version)
        if snap is None:
            raise CanvasError("versi itu tidak ada (disimpan 60 terakhir)")
        snap = json.loads(snap) if isinstance(snap, str) else snap
    keep = []
    for n in snap["nodes"]:
        exists, ref_company = await owner_of(n["ref"])
        if exists and allowed(n["ref"], canvas["company_id"], ref_company):
            keep.append(n)
    async with _conn(canvas["company_id"]) as conn:
        await conn.execute("DELETE FROM canvas_nodes WHERE canvas_id = $1", canvas_id)
        ids = {}
        for n in keep:
            ids[n["id"]] = await conn.fetchval(
                """INSERT INTO canvas_nodes (canvas_id, company_id, kind, ref, x, y, z, size, pinned, w, h, props, created_by)
                   VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13) RETURNING id""", canvas_id, canvas["company_id"], n["kind"], n["ref"],
                n["x"], n["y"], n["z"], n["size"], n["pinned"], n.get("w"), n.get("h"), _as_dict(n.get("props")), actor)
        for e in snap["edges"]:
            if e["a"] in ids and e["b"] in ids:
                style = _as_dict(e.get("style"))
                if style.get("to") in ids:   # the arrow follows the node it pointed at, which has a new id now
                    style["to"] = ids[style["to"]]
                else:
                    style.pop("to", None)
                await conn.execute("INSERT INTO canvas_edges (canvas_id, company_id, a, b, label, style) VALUES ($1, $2, $3, $4, $5, $6)",
                                   canvas_id, canvas["company_id"], min(ids[e["a"]], ids[e["b"]]), max(ids[e["a"]], ids[e["b"]]), e["label"], style)
        v = await _bump(conn, canvas, actor, f"pulihkan versi {version}")
    await audit.record(actor, "canvas.restored", f"canvas:{canvas_id}", version=version)
    return {"version": v, "cards": len(keep), "dropped": len(snap["nodes"]) - len(keep)}


# ---------- reading ----------

def _as_dict(v) -> dict:
    return v if isinstance(v, dict) else (json.loads(v) if v else {})


def _short(text: str | None, n: int = 280) -> str:
    t = re.sub(r"\s+", " ", str(text or "")).strip()
    return t if len(t) <= n else t[:n - 1] + "…"


async def _resolve(conn, ref: str) -> dict | None:
    """What a card shows, read from where the thing lives. None when it is gone."""
    kind, ident = parse_ref(ref)
    try:
        match kind:
            case "task":
                r = await conn.fetchrow("SELECT title, status, result, phase, created_at FROM tasks WHERE id = $1", int(ident))
                return r and {"title": r["title"], "subtitle": f"tugas #{ident} · {r['status']}", "snippet": _short(r["result"]),
                              "status": r["status"], "at": r["created_at"]}
            case "doc":
                r = await conn.fetchrow("SELECT title, format, created_at FROM documents WHERE id = $1::uuid", ident)
                return r and {"title": r["title"], "subtitle": r["format"].upper(), "url": f"/api/v1/documents/{ident}", "at": r["created_at"]}
            case "memory":
                r = await conn.fetchrow("SELECT text, category, kind, created_at FROM memories WHERE id = $1::uuid", ident)
                return r and {"title": _short(r["text"], 80), "subtitle": f"memori · {r['category']}", "snippet": _short(r["text"]),
                              "at": r["created_at"]}
            case "goal":
                r = await conn.fetchrow("SELECT text, status, priority, due, created_at FROM goals WHERE id = $1", int(ident))
                return r and {"title": _short(r["text"], 80), "subtitle": f"tujuan · {r['status']} · prioritas {r['priority']}",
                              "status": r["status"], "at": r["created_at"]}
            case "shown":
                r = await conn.fetchrow("SELECT panel, title, payload, created_at FROM stage_history WHERE id = $1", int(ident))
                if not r:
                    return None
                payload = json.loads(r["payload"]) if isinstance(r["payload"], str) else r["payload"]
                url = payload.get("url") if str(payload.get("url") or "").startswith("https://") else None
                return {"title": r["title"], "subtitle": f"ditampilkan · {r['panel']}", "panel": r["panel"],
                        "snippet": _short(payload.get("text") or payload.get("body") or ""), "url": url,
                        "image": payload.get("url") if r["panel"] == "image" and url else None, "at": r["created_at"]}
            case "meeting":
                r = await conn.fetchrow("SELECT title, status, started_at, document_id FROM meetings WHERE id = $1::uuid", ident)
                return r and {"title": r["title"] or f"Rapat #{ident}", "subtitle": f"rapat · {r['status']}", "at": r["started_at"],
                              "url": f"/api/v1/documents/{r['document_id']}" if r["document_id"] else None}
            case "playlist":
                r = await conn.fetchrow("SELECT name, created_at FROM playlists WHERE id = $1", int(ident))
                return r and {"title": r["name"], "subtitle": "playlist", "at": r["created_at"]}
            case "music":
                from . import musiclib
                if not musiclib.find(ident):
                    return None
                m = json.loads((musiclib.ROOT / f"{ident}.json").read_text())
                return {"title": m.get("title") or "Lagu", "subtitle": m.get("artist") or "lagu", "url": f"/api/v1/media/{ident}"}
            case "vault":
                r = await conn.fetchrow("SELECT kind, title, body, data, created_at FROM company_vault WHERE id = $1", int(ident))
                return r and {"title": r["title"], "subtitle": r["kind"], "at": r["created_at"],
                              "snippet": _short(companies.kpi_line(dict(r)) if r["kind"] in ("kpi", "cashflow") else r["body"])}
            case "directive":
                r = await conn.fetchrow("SELECT action, instruction, status, created_at FROM gm_directives WHERE id = $1", int(ident))
                return r and {"title": f"#{ident} {r['action'].replace('_', ' ')}", "subtitle": f"arahan · {r['status']}",
                              "snippet": _short(r["instruction"]), "status": r["status"], "at": r["created_at"]}
            case "decision":
                r = await conn.fetchrow("SELECT kind, text, entity_id, created_at FROM decision_vault WHERE id = $1", int(ident))
                return r and {"title": _short(r["text"], 80), "subtitle": f"keputusan · {r['kind']} · {r['entity_id']}",
                              "snippet": _short(r["text"]), "at": r["created_at"]}
    except (ValueError, TypeError, OSError):
        return None
    return None


async def view(canvas_id: int, since: int | None = None) -> dict:
    """The whole galaxy for the viewer, or {"version", "unchanged": True} when nothing moved since `since`."""
    canvas = await _canvas_row(canvas_id)
    if since is not None and since == canvas["version"]:
        return {"id": canvas_id, "version": canvas["version"], "unchanged": True}
    async with _conn(canvas["company_id"]) as conn:
        nodes = [dict(n) for n in await conn.fetch("SELECT * FROM canvas_nodes WHERE canvas_id = $1 ORDER BY id", canvas_id)]
        edges = [dict(e) | {"style": _as_dict(e["style"])} for e in
                 await conn.fetch("SELECT id, a, b, label, style FROM canvas_edges WHERE canvas_id = $1", canvas_id)]
        cards = []
        for n in nodes:
            exists, ref_company = await owner_of(n["ref"])
            if not exists or not allowed(n["ref"], canvas["company_id"], ref_company):
                continue   # gone, or (never expected) not this canvas's — never shown
            content = object_content(n["props"]) if n["ref"].startswith("obj:") else await _resolve(conn, n["ref"])
            if content is None:
                continue
            cards.append({"id": n["id"], "ref": n["ref"], "kind": n["kind"], "x": n["x"], "y": n["y"], "z": n["z"],
                          "size": n["size"], "pinned": n["pinned"], "w": n["w"], "h": n["h"], **content})
    shown = {c["id"] for c in cards}
    return {"id": canvas_id, "context": canvas["context"], "title": canvas["title"], "version": canvas["version"],
            "focus": canvas["focus_node"] if canvas["focus_node"] in shown else None,
            "constellations": [{"kind": k, "title": KINDS[k][0], "color": KINDS[k][1], "center": constellation_center(k, bool(canvas["company_id"]))}
                               for k in (COMPANY_KINDS if canvas["company_id"] else PERSONAL_KINDS)],
            "cards": cards, "edges": [e for e in edges if e["a"] in shown and e["b"] in shown]}


async def search_refs(context: str, query: str, limit: int = 20) -> list[dict]:
    """Things that could be put on this galaxy, for the viewer's 'Tambah kartu' box."""
    context = context_of(context)
    company = context_company(context)
    q = f"%{query.strip()}%"
    out = []
    if company:
        async with companies.scope(company) as conn:
            for r in await conn.fetch("SELECT id, kind, title FROM company_vault WHERE company_id = $1 AND title ILIKE $2 ORDER BY id DESC LIMIT $3", company, q, limit):
                out.append({"ref": f"vault:{r['id']}", "title": r["title"], "kind": "perusahaan"})
            for r in await conn.fetch("SELECT id, action, instruction FROM gm_directives WHERE company_id = $1 AND instruction ILIKE $2 ORDER BY id DESC LIMIT $3", company, q, limit):
                out.append({"ref": f"directive:{r['id']}", "title": f"#{r['id']} {r['action']}: {_short(r['instruction'], 60)}", "kind": "arahan"})
        for r in await db.pool().fetch("SELECT id, title FROM tasks WHERE company_id = $1 AND title ILIKE $2 ORDER BY id DESC LIMIT $3", company, q, limit):
            out.append({"ref": f"task:{r['id']}", "title": r["title"], "kind": "tugas"})
        return out[:limit]
    for r in await db.pool().fetch("SELECT id, title FROM tasks WHERE company_id IS NULL AND title ILIKE $1 ORDER BY id DESC LIMIT $2", q, limit):
        out.append({"ref": f"task:{r['id']}", "title": r["title"], "kind": "tugas"})
    for r in await db.pool().fetch("SELECT d.id, d.title FROM documents d LEFT JOIN tasks t ON t.id = d.task_id "
                                   "WHERE t.company_id IS NULL AND d.title ILIKE $1 ORDER BY d.created_at DESC LIMIT $2", q, limit):
        out.append({"ref": f"doc:{r['id']}", "title": r["title"], "kind": "dokumen"})
    for r in await db.pool().fetch("SELECT id, text FROM memories WHERE NOT stale AND text ILIKE $1 ORDER BY updated_at DESC LIMIT $2", q, limit):
        out.append({"ref": f"memory:{r['id']}", "title": _short(r["text"], 80), "kind": "memori"})
    for r in await db.pool().fetch("SELECT id, title FROM stage_history WHERE title ILIKE $1 ORDER BY id DESC LIMIT $2", q, limit):
        out.append({"ref": f"shown:{r['id']}", "title": r["title"], "kind": "tampilan"})
    return out[:limit]


# ---------- the desk's areas (ADR-062): the size and lock the owner gave each one, shared by every device ----------

AREAS_KEY = "desk:areas"
_AREA = re.compile(r"^[a-z][a-z0-9_-]{0,31}$")


def clean_area(name: str, layout: dict) -> dict:
    """One area's layout as stored (pure; unit-tested): width 220–2600, height 140–2600 or none (grows with its content), locked."""
    if not _AREA.match(name or ""):
        raise CanvasError("nama area tidak dikenal")
    def num(v, lo, hi):
        try:
            return int(min(hi, max(lo, round(float(v)))))
        except (TypeError, ValueError):
            return None
    w = num(layout.get("w"), 220, 2600)
    h = None if layout.get("h") in (None, "") else num(layout.get("h"), 140, 2600)
    return {"w": w, "h": h, "locked": bool(layout.get("locked"))}


async def areas() -> dict:
    v = await db.pool().fetchval("SELECT value FROM settings_kv WHERE key = $1", AREAS_KEY)
    return v if isinstance(v, dict) else {}


async def set_area(name: str, layout: dict, actor: str) -> dict:
    clean = clean_area(name, layout)
    have = await areas()
    if len(have) >= 60 and name not in have:
        raise CanvasError("terlalu banyak area")
    have[name] = clean
    await db.pool().execute("INSERT INTO settings_kv (key, value) VALUES ($1, $2) ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value",
                            AREAS_KEY, have)
    return clean
