"""The desk (Blueprint v4 Fase 7, ADR-051): the 3D canvas as the main table where everything JARVIS is doing can be seen.

What it shows, live: every worker task as a station (what it is doing, step by step, and — when it browses — what the page looks
like), what n8n is running, the owner's latest requests and JARVIS' answers, and the storage (the library) as it grows.
Nothing here acts: it only watches. It listens to the same events the phone gets (hub.tap), keeps a short window in memory, and — for
a task that uses the browser — takes screenshots of the shared Chromium (the browser Hermes works in; core attaches to it over
DevTools) about once a second while the task is browsing, so the owner sees the page open, scroll and fill in, as it happens.
Privacy: private tasks never appear; a company's tasks only in that company's galaxy; frames live in memory only (never on disk, gone
10 minutes after the task ends), are served to paired devices only, and what the owner typed in a request is masked when it looks
sensitive (OTP, card, password).
"""

import asyncio
import json
import logging
import re
import time
from dataclasses import dataclass, field
from urllib.parse import urlparse

import httpx

from . import db, hub, n8n, sensitive

log = logging.getLogger("jarvis-core.live")
BROWSER = "http://jarvis-browser-gw:9222"
FRAME_EVERY_S = 0.9
BROWSER_IDLE_S = 25          # no browser tool for this long → stop taking screenshots
KEEP_DONE_S = 600            # a finished station stays on the desk this long (its card stays on the canvas for good)
MAX_STEPS = 14
FINAL = {"completed", "failed", "cancelled", "stopped"}
URL = re.compile(r"https?://[^\s'\"<>)]+")

# Hermes' browser tools → (icon, verb) the owner reads on the station
ACTIONS = {
    "browser_navigate": ("🌐", "Membuka"), "browser_snapshot": ("👁", "Membaca halaman"), "browser_click": ("👆", "Mengklik"),
    "browser_type": ("⌨️", "Mengetik"), "browser_scroll": ("↕️", "Menggulir"), "browser_back": ("◀️", "Kembali"),
    "browser_press": ("⏎", "Menekan tombol"), "browser_vision": ("📷", "Melihat halaman"), "browser_get_images": ("🖼", "Mengambil gambar"),
    "browser_console": ("🧾", "Membaca konsol halaman"), "browser_vault": ("🔐", "Mengisi login dari brankas"),
    "browser_exec": ("⚙️", "Menjalankan di halaman"), "browser_cdp": ("⚙️", "Mengendalikan browser"), "browser_dialog": ("💬", "Menjawab dialog"),
    "web_search": ("🔎", "Mencari"), "web_extract": ("📄", "Membaca situs"), "read_file": ("📂", "Membaca berkas"),
    "write_file": ("💾", "Menulis berkas"), "patch": ("🩹", "Mengubah berkas"), "search_files": ("🗂", "Mencari berkas"),
    "terminal": ("💻", "Menjalankan perintah"), "execute_code": ("🧮", "Menghitung"), "delegate_task": ("🧑‍🤝‍🧑", "Menugaskan sub-pekerja"),
    "memory_search": ("🧠", "Mengingat"), "create_document": ("📝", "Membuat dokumen"), "ask_owner": ("❓", "Bertanya padamu"),
}


@dataclass
class Station:
    task_id: int
    title: str
    kind: str
    status: str
    company_id: str | None
    started: float = field(default_factory=time.time)
    finished: float = 0.0
    steps: list[dict] = field(default_factory=list)
    thought: str = ""
    url: str = ""
    page_title: str = ""
    hint_host: str = ""
    browser_until: float = 0.0
    frame: bytes = b""
    frame_seq: int = 0
    frame_at: float = 0.0
    capture: asyncio.Task | None = None


stations: dict[int, Station] = {}


def step_text(name: str, label: str) -> tuple[str, str]:
    """(icon, text) of one tool call. Pure; unit-tested."""
    icon, verb = ACTIONS.get(name, ("🔧", name.replace("_", " ").capitalize()))
    label = re.sub(r"\s+", " ", label or "").strip()
    return icon, (f"{verb}: {label[:110]}" if label else verb)


def host_of(text: str) -> str:
    m = URL.search(text or "")
    return (urlparse(m.group()).hostname or "") if m else ""


def pick_target(targets: list[dict], hint_host: str, last_url: str) -> dict | None:
    """Which browser tab is the station's: the one on the host it was told to open, else the one it was last seen on, else the newest
    real page. Pure; unit-tested."""
    pages = [t for t in targets if t.get("type") == "page" and not str(t.get("url", "")).startswith(("devtools://", "chrome-extension://"))]
    if not pages:
        return None
    if hint_host:
        for t in pages:
            if (urlparse(t.get("url", "")).hostname or "") == hint_host:
                return t
    if last_url:
        for t in pages:
            if t.get("url") == last_url:
                return t
    real = [t for t in pages if t.get("url") not in ("", "about:blank")]
    return (real or pages)[0]


OTP = re.compile(r"\b(otp|kode (verifikasi|otp|keamanan)|verification code|one[- ]time|kode rahasia|pin|cvv|password|kata sandi)\b", re.IGNORECASE)


def mask(text: str) -> str:
    """A request shown on the desk: hidden when it looks sensitive (OTP, password, card, a /privat message)."""
    return "(berisi data sensitif — disembunyikan)" if sensitive.scan(text) or OTP.search(text) or sensitive.is_private(text) else text


# ---------- the events the phone also gets ----------

async def on_event(ev: dict) -> None:
    kind = ev.get("type")
    if kind == "task":
        await _on_task(ev)
    elif kind == "task_event":
        st = stations.get(int(ev.get("task_id") or 0))
        if st:
            _on_step(st, ev.get("event") or {})


async def _on_task(ev: dict) -> None:
    tid = int(ev["id"])
    st = stations.get(tid)
    if st is None:
        if ev.get("status") in FINAL:
            return  # finished before we ever saw it: nothing to show live
        row = await db.pool().fetchrow("SELECT private, company_id FROM tasks WHERE id = $1", tid)
        if not row or row["private"]:
            return  # a private task never appears on the desk
        st = stations[tid] = Station(tid, str(ev.get("title") or "Tugas")[:120], str(ev.get("kind") or "owner"), "queued", row["company_id"])
    st.status = str(ev.get("status") or st.status)
    if st.status in FINAL and not st.finished:
        st.finished = time.time()
        if st.capture is None or st.capture.done():
            st.capture = asyncio.create_task(_last_frame(st))   # one more look at where it ended
    _prune()


def _on_step(st: Station, e: dict) -> None:
    if e.get("type") == "thought":
        st.thought = str(e.get("text") or "")[:240]
    elif e.get("type") == "tool":
        name, status = str(e.get("name") or ""), e.get("status")
        icon, text = step_text(name, str(e.get("label") or ""))
        sid = str(e.get("id") or "")
        known = next((s for s in st.steps if sid and s["id"] == sid), None)
        if not known and status != "running":  # Hermes numbers every event, so a completion has its own id: it ends the latest call of that tool
            known = next((s for s in reversed(st.steps) if s["name"] == name and s["status"] == "running"), None)
            if known is None:
                return  # a completion whose start we never saw: its label is a result, not an action
        last = st.steps[-1] if st.steps else None
        if known is None and last and status == "running" and last["name"] == name and last["text"] == text:
            last["n"] = last.get("n", 1) + 1   # the same call again (a retry, a poll): one line with a count, not five identical ones
            last["at"] = time.time()
        elif known:
            known["status"] = status
        else:
            st.steps.append({"id": sid, "name": name, "icon": icon, "text": text, "status": status, "at": time.time()})
            del st.steps[:-MAX_STEPS]
        if name.startswith("browser_"):
            st.browser_until = time.time() + BROWSER_IDLE_S
            if name == "browser_navigate" and (h := host_of(str(e.get("label") or ""))):
                st.hint_host = h
            if st.capture is None or st.capture.done():
                st.capture = asyncio.create_task(_capture_loop(st))


def _prune() -> None:
    now = time.time()
    for tid in [t for t, s in stations.items() if s.finished and now - s.finished > KEEP_DONE_S]:
        stations.pop(tid, None)


# ---------- screenshots of the shared browser ----------

def _client(timeout: float) -> httpx.AsyncClient:  # seam for tests
    return httpx.AsyncClient(timeout=httpx.Timeout(timeout, connect=3))


async def _screenshot(ws_url: str) -> bytes | None:
    import base64

    import websockets
    try:
        async with websockets.connect(ws_url, max_size=8 * 2**20, open_timeout=4) as ws:
            await ws.send(json.dumps({"id": 1, "method": "Page.captureScreenshot", "params": {"format": "jpeg", "quality": 55}}))
            for _ in range(20):
                msg = json.loads(await asyncio.wait_for(ws.recv(), 6))
                if msg.get("id") == 1:
                    data = (msg.get("result") or {}).get("data")
                    return base64.b64decode(data) if data else None
    except Exception as e:
        log.debug("screenshot failed: %s", type(e).__name__)
    return None


async def grab(st: Station) -> bool:
    """One look at the station's tab. False when there is nothing to look at (browser down, no page yet)."""
    try:
        async with _client(4) as c:
            targets = (await c.get(f"{BROWSER}/json/list")).json()
    except (httpx.HTTPError, ValueError):
        return False
    t = pick_target(targets, st.hint_host, st.url)
    if not t or not t.get("webSocketDebuggerUrl"):
        return False
    st.url, st.page_title = str(t.get("url") or "")[:300], str(t.get("title") or "")[:160]
    jpeg = await _screenshot(t["webSocketDebuggerUrl"])
    if not jpeg:
        return False
    st.frame, st.frame_seq, st.frame_at = jpeg, st.frame_seq + 1, time.time()
    return True


async def _capture_loop(st: Station) -> None:
    try:
        while time.time() < st.browser_until and not st.finished:
            await grab(st)
            await asyncio.sleep(FRAME_EVERY_S)
        await grab(st)   # and one last look, so the final page stays on the station
    except asyncio.CancelledError:
        raise
    except Exception:
        log.exception("capture loop failed")


async def _last_frame(st: Station) -> None:
    if st.browser_until and time.time() < st.browser_until + 60:
        await grab(st)


# ---------- what the viewer asks for ----------

def context_company(context: str) -> str | None:
    return context.split(":", 1)[1] if context.startswith("company:") else None


def station_view(st: Station) -> dict:
    return {"task_id": st.task_id, "ref": f"task:{st.task_id}", "title": st.title, "kind": st.kind, "status": st.status,
            "seconds": int((st.finished or time.time()) - st.started), "steps": st.steps[-MAX_STEPS:], "thought": st.thought,
            "url": st.url, "page_title": st.page_title, "frame_seq": st.frame_seq, "has_frame": bool(st.frame),
            "browsing": time.time() < st.browser_until and not st.finished}


_n8n_cache: dict = {"at": 0.0, "value": []}


async def n8n_recent() -> list[dict]:
    """What n8n ran lately (cached 10 s); nothing when n8n is not set up."""
    if time.time() - _n8n_cache["at"] < 10:
        return _n8n_cache["value"]
    out: list[dict] = []
    try:
        names = {w["id"]: w["name"] for w in await n8n.list_workflows()}
        for e in await n8n.executions(12):
            out.append({"id": e["id"], "workflow": names.get(e["workflow_id"], "workflow"), "status": e["status"],
                        "started_at": e["started_at"], "stopped_at": e["stopped_at"]})
    except n8n.N8nError:
        out = []
    _n8n_cache.update(at=time.time(), value=out)
    return out


async def prompts(limit: int = 6) -> list[dict]:
    """The owner's latest requests and what JARVIS answered (not private ones; sensitive words masked)."""
    rows = await db.pool().fetch(
        """SELECT id, session_id, role, content, created_at FROM messages
           WHERE role IN ('user', 'assistant') AND route <> 'blocked' ORDER BY id DESC LIMIT 60""")
    out: list[dict] = []
    answers: dict[str, str] = {}
    for r in rows:  # newest first: remember the answer that followed each request
        if r["role"] == "assistant":
            answers.setdefault(r["session_id"], r["content"])
        elif not sensitive.is_private(r["content"]):
            out.append({"id": r["id"], "asked": mask(r["content"])[:160], "at": r["created_at"],
                        "answer": mask(answers.pop(r["session_id"], ""))[:160]})
        if len(out) >= limit:
            break
    return out


async def storage(limit: int = 8) -> dict:
    from . import library
    items = await library.items(limit=400)
    counts: dict[str, int] = {}
    for i in items:
        counts[i["kind"]] = counts.get(i["kind"], 0) + 1
    return {"total": len(items), "counts": counts,
            "latest": [{"key": i["key"], "kind": i["kind"], "title": i["title"], "kept": i.get("kept", False)} for i in items[:limit]]}


async def snapshot(context: str = "utama") -> dict:
    _prune()
    company = context_company(context)
    mine = [station_view(s) for s in stations.values() if s.company_id == company]
    mine.sort(key=lambda s: (s["status"] in FINAL, -s["task_id"]))
    out = {"now": time.time(), "stations": mine}
    if company is None:  # the owner's own desk; a company galaxy shows only that company's tasks
        out |= {"n8n": await n8n_recent(), "prompts": await prompts(), "storage": await storage()}
    return out


def frame(task_id: int, context: str = "utama") -> tuple[bytes, int] | None:
    st = stations.get(task_id)
    if not st or not st.frame or st.company_id != context_company(context):
        return None
    return st.frame, st.frame_seq


def start() -> None:
    hub.tap(on_event)
