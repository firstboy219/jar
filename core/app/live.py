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
import base64
import json
import logging
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

import httpx

from . import db, hub, n8n, sensitive

log = logging.getLogger("jarvis-core.live")
BROWSER = "http://jarvis-browser-gw:9222"
FRAME_EVERY_S = 0.9
BROWSER_IDLE_S = 25          # no browser tool for this long → stop taking screenshots
KEEP_DONE_S = 600            # a finished station stays this long (its card leaves the board: only work in progress is shown, ADR-067)
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
    view: tuple[float, float] = (0.0, 0.0)   # the page's size in CSS pixels, from the screencast (a click at 0.5/0.5 lands in its middle)
    control_until: float = 0.0               # the owner has taken the wheel until this moment (every input renews it)
    control_by: str = ""
    driver: "Driver | None" = None
    driver_checked: float = 0.0
    marked_at: float = 0.0
    paused: bool = False                     # the worker was told to keep its hands off the browser until the owner hands it back


stations: dict[int, Station] = {}
subscribers: list[tuple[str | None, asyncio.Queue]] = []   # live viewers: (company or None, queue of (task_id, seq, jpeg))


def subscribe(context: str) -> tuple[asyncio.Queue, "callable"]:
    """A viewer's live feed of frames for the stations of its galaxy (newest wins: a slow viewer skips frames, never lags behind)."""
    q: asyncio.Queue = asyncio.Queue(maxsize=3)
    entry = (context_company(context), q)
    subscribers.append(entry)
    return q, lambda: subscribers.remove(entry) if entry in subscribers else None


def _publish(st: "Station", jpeg: bytes) -> None:
    st.frame, st.frame_seq, st.frame_at = jpeg, st.frame_seq + 1, time.time()
    for company, q in subscribers:
        if company == st.company_id:
            if q.full():
                q.get_nowait()
            q.put_nowait((st.task_id, st.frame_seq, jpeg))


def step_text(name: str, label: str) -> tuple[str, str]:
    """(icon, text) of one tool call. Pure; unit-tested."""
    icon, verb = ACTIONS.get(name, ("🔧", name.replace("_", " ").capitalize()))
    label = re.sub(r"\s+", " ", label or "").strip()
    return icon, (f"{verb}: {label[:110]}" if label else verb)


def host_of(text: str) -> str:
    m = URL.search(text or "")
    return (urlparse(m.group()).hostname or "") if m else ""


tab_activity: dict[str, float] = {}   # DevTools target id → when the worker last did something in that tab (a mouse move, a click, typing, a navigation)
ACTIVE_S = 90.0                       # a tab touched this recently is "the one being worked in"
KEEP_TABS, IDLE_CLOSE_S = 8, 1800.0   # past 8 open tabs, those idle for 30 minutes are closed (workers leave tabs behind)


def pick_target(targets: list[dict], hint_host: str, last_url: str, activity: dict | None = None, now: float | None = None) -> dict | None:
    """Which browser tab is the station's. The tab the worker is touching right now (its hands moved there in the last 90 s), preferring the
    one on the host it was told to open; else the tab on that host, else where it was last seen, else the first real page. Pure; unit-tested."""
    pages = [t for t in targets if t.get("type") == "page" and not str(t.get("url", "")).startswith(("devtools://", "chrome-extension://"))]
    if not pages:
        return None
    host = lambda t: urlparse(t.get("url", "")).hostname or ""   # noqa: E731
    if activity:
        now = time.time() if now is None else now
        hot = sorted((t for t in pages if now - activity.get(t.get("id"), 0) < ACTIVE_S), key=lambda t: -activity[t["id"]])
        if hot:
            return next((t for t in hot if hint_host and host(t) == hint_host), hot[0])
    if hint_host:
        for t in pages:
            if host(t) == hint_host:
                return t
    if last_url:
        for t in pages:
            if t.get("url") == last_url:
                return t
    if activity is not None:
        return None   # nothing the worker touched lately: show nothing rather than a forgotten tab
    real = [t for t in pages if t.get("url") not in ("", "about:blank")]
    return (real or pages)[0]


def idle_to_close(targets: list[dict], activity: dict, now: float) -> list[str]:
    """Ids of old idle tabs to close so the shared browser does not grow without end. Keeps the newest KEEP_TABS and anything touched lately. Pure."""
    pages = [t for t in targets if t.get("type") == "page" and not str(t.get("url", "")).startswith(("devtools://", "chrome-extension://"))]
    if len(pages) <= KEEP_TABS:
        return []
    ranked = sorted(pages, key=lambda t: -activity.get(t.get("id"), 0))
    return [t["id"] for t in ranked[KEEP_TABS:] if now - activity.get(t["id"], 0) > IDLE_CLOSE_S]


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
    t = pick_target(targets, st.hint_host, st.url, tab_activity)
    if not t or not t.get("webSocketDebuggerUrl"):
        return False
    st.url, st.page_title = str(t.get("url") or "")[:300], str(t.get("title") or "")[:160]
    jpeg = await _screenshot(t["webSocketDebuggerUrl"])
    if not jpeg:
        return False
    _publish(st, jpeg)
    return True


async def _pick(st: Station) -> dict | None:
    try:
        async with _client(4) as c:
            targets = (await c.get(f"{BROWSER}/json/list")).json()
    except (httpx.HTTPError, ValueError):
        return None
    t = pick_target(targets, st.hint_host, st.url, tab_activity)
    if t:
        st.url, st.page_title = str(t.get("url") or "")[:300], str(t.get("title") or "")[:160]
    return t


async def _cast_target(st: Station, t: dict) -> None:
    """Live video of one tab: Chromium pushes a frame whenever the page changes (about 10–30 a second while the cursor glides, a page
    scrolls or a form fills in) and we relay each one to the viewers. Returns when the worker moves to another tab or goes idle."""
    async with _ws_connect(t["webSocketDebuggerUrl"]) as ws:
        n = 0

        async def send(method: str, params: dict | None = None) -> None:
            nonlocal n
            n += 1
            await ws.send(json.dumps({"id": n, "method": method, "params": params or {}}))
        await send("Page.startScreencast", {"format": "jpeg", "quality": 55, "maxWidth": 1100, "maxHeight": 700, "everyNthFrame": 1})
        last_pick = time.time()
        try:
            while time.time() < st.browser_until:
                try:
                    msg = json.loads(await asyncio.wait_for(ws.recv(), 1.0))
                except asyncio.TimeoutError:
                    msg = {}
                if msg.get("method") == "Page.screencastFrame":
                    p = msg["params"]
                    md = p.get("metadata") or {}
                    if md.get("deviceWidth") and md.get("deviceHeight"):
                        st.view = (float(md["deviceWidth"]), float(md["deviceHeight"]))
                    _publish(st, base64.b64decode(p["data"]))
                    await send("Page.screencastFrameAck", {"sessionId": p["sessionId"]})
                if time.time() - last_pick > 1.5:   # is the worker still in this tab? the hands keep the station awake
                    last_pick = time.time()
                    if tab_activity.get(t.get("id"), 0) > time.time() - 12 or controlled(st):
                        st.browser_until = max(st.browser_until, time.time() + 8)
                    now_tab = await _pick(st)
                    if now_tab is None or now_tab.get("id") != t.get("id"):
                        return
        finally:
            try:
                await send("Page.stopScreencast")
            except Exception:
                pass


async def _capture_loop(st: Station) -> None:
    try:
        while time.time() < st.browser_until:
            t = await _pick(st)
            if t is None or not t.get("webSocketDebuggerUrl"):
                await asyncio.sleep(0.6)
                continue
            try:
                await _cast_target(st, t)
            except asyncio.CancelledError:
                raise
            except Exception as e:  # the tab closed or the socket dropped: look for the worker's tab again
                log.debug("screencast: %s", type(e).__name__)
                await asyncio.sleep(0.6)
        await grab(st)   # and one last look, so the final page stays on the station
    except asyncio.CancelledError:
        raise
    except Exception:
        log.exception("capture loop failed")


async def _last_frame(st: Station) -> None:
    if st.browser_until and time.time() < st.browser_until + 60:
        await grab(st)


# ---------- the hands: a cursor, clicks and typing drawn inside the shared browser ----------

CURSOR_JS = (Path(__file__).parent / "live_cursor.js").read_text()


def _ws_connect(url: str):  # seam for tests
    import websockets
    return websockets.connect(url, max_size=2**24, open_timeout=5)


async def _decorate_once() -> None:
    """Attach to the shared browser and put the overlay script into every page, now and when a page is opened later."""
    async with _client(4) as c:
        ws_url = (await c.get(f"{BROWSER}/json/version")).json()["webSocketDebuggerUrl"]
    seen: set[str] = set()
    started = time.time()
    session_tab: dict[str, str] = {}
    last_sweep = [time.time()]
    async with _ws_connect(ws_url) as ws:
        n = 0

        async def send(method: str, params: dict | None = None, session: str | None = None) -> None:
            nonlocal n
            n += 1
            await ws.send(json.dumps({"id": n, "method": method, "params": params or {}, **({"sessionId": session} if session else {})}))
        await send("Target.setDiscoverTargets", {"discover": True})
        async for raw in ws:
            m = json.loads(raw)
            method, p = m.get("method"), m.get("params") or {}
            if method in ("Target.targetCreated", "Target.targetInfoChanged"):
                t = p.get("targetInfo") or {}
                if t.get("type") == "page" and not str(t.get("url", "")).startswith("devtools://"):
                    # opened or navigated: someone is working in it — except tabs that were already there when we started (they are
                    # remembered as "a while ago": neither hot nor yet closable)
                    tab_activity[t["targetId"]] = time.time() if time.time() - started > 2 else tab_activity.get(t["targetId"], time.time() - IDLE_CLOSE_S / 2)
                    if t["targetId"] not in seen:
                        seen.add(t["targetId"])
                        await send("Target.attachToTarget", {"targetId": t["targetId"], "flatten": True})
            elif method == "Target.targetDestroyed":
                seen.discard(p.get("targetId"))
                tab_activity.pop(p.get("targetId"), None)
            elif method == "Runtime.bindingCalled" and p.get("name") == "jarvisHands":   # the hands moved in a tab: that is where the worker is
                if tid := session_tab.get(m.get("sessionId")):
                    tab_activity[tid] = time.time()
            elif method == "Target.attachedToTarget" and p.get("sessionId"):
                session_tab[p["sessionId"]] = (p.get("targetInfo") or {}).get("targetId", "")
                await send("Runtime.enable", None, p["sessionId"])
                await send("Runtime.addBinding", {"name": "jarvisHands"}, p["sessionId"])
                await send("Page.enable", None, p["sessionId"])   # without it Chromium keeps the script for the page that is open, not for the next one
                await send("Page.addScriptToEvaluateOnNewDocument", {"source": CURSOR_JS}, p["sessionId"])   # every later page of this tab
                await send("Runtime.evaluate", {"expression": CURSOR_JS}, p["sessionId"])                    # the page that is open now
            if time.time() - last_sweep[0] > 60:
                last_sweep[0] = time.time()
                try:
                    async with _client(4) as c:
                        listing = (await c.get(f"{BROWSER}/json/list")).json()
                    for tid in idle_to_close(listing, tab_activity, time.time()):
                        await send("Target.closeTarget", {"targetId": tid})
                        tab_activity.pop(tid, None)
                except (httpx.HTTPError, ValueError):
                    pass


async def decorate_forever() -> None:
    delay = 3.0
    while True:
        try:
            await _decorate_once()
            delay = 3.0
        except asyncio.CancelledError:
            raise
        except Exception as e:  # browser down or restarting: try again, quietly
            log.debug("hands: %s", type(e).__name__)
        await asyncio.sleep(delay)
        delay = min(delay * 2, 60.0)


# ---------- what the viewer asks for ----------

def context_company(context: str) -> str | None:
    return context.split(":", 1)[1] if context.startswith("company:") else None


def station_view(st: Station) -> dict:
    return {"task_id": st.task_id, "ref": f"task:{st.task_id}", "title": st.title, "kind": st.kind, "status": st.status,
            "seconds": int((st.finished or time.time()) - st.started), "steps": st.steps[-MAX_STEPS:], "thought": st.thought,
            "url": st.url, "page_title": st.page_title, "frame_seq": st.frame_seq, "has_frame": bool(st.frame),
            "browsing": time.time() < st.browser_until and not st.finished,
            "controlled": controlled(st), "control_by": st.control_by if controlled(st) else "",
            "paused": controlled(st) and st.paused}


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


PANEL_OF_SLOT = {"music": "player"}   # the stage's slot → the desk panel that shows it (the rest share the name)
SLOT_WORD = {"music": "musik", "video": "video", "image": "gambar", "doc": "dokumen", "map": "peta", "web": "halaman web", "text": "catatan",
             "draft": "draf balasan"}


async def last_activity() -> dict | None:
    """Where the owner's latest request left its mark on the main board (ADR-072): the newest of the latest task card still on the board
    and the feature cards (player, video, picture, document, map, web, notes, draft); with the request itself."""
    from . import stage
    ask = await db.pool().fetchrow(
        """SELECT content, created_at FROM messages WHERE role = 'user' AND route NOT IN ('blocked', 'silent')
           AND session_id NOT IN ('flowwatch', 'system') AND session_id NOT LIKE 'devteam%' ORDER BY id DESC LIMIT 1""")
    places = []
    t = await db.pool().fetchrow(
        """SELECT t.id, t.title, t.created_at, n.id AS node FROM tasks t
           JOIN canvas_nodes n ON n.ref = 'task:' || t.id JOIN canvases c ON c.id = n.canvas_id AND c.context = 'utama'
           WHERE t.kind = 'owner' AND t.company_id IS NULL ORDER BY t.id DESC LIMIT 1""")
    if t:
        places.append({"at": t["created_at"].timestamp(), "where": "card", "node": t["node"], "title": t["title"], "what": "tugas"})
    for slot, card in list(stage._desk.items()):
        first = (card.get("items") or [{}])[0]
        places.append({"at": card.get("at") or 0, "where": "panel", "panel": PANEL_OF_SLOT.get(slot, slot), "what": SLOT_WORD.get(slot, slot),
                       "title": str(first.get("title") or card.get("caption") or SLOT_WORD.get(slot, slot))[:120]})
    if not places and not ask:
        return None
    best = max(places, key=lambda p: p["at"]) if places else {"where": "none"}
    asked = {"asked": mask(ask["content"])[:160], "asked_at": ask["created_at"].timestamp()} if ask and not sensitive.is_private(ask["content"]) else {}
    return best | asked


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
    if mine:   # a worker that waits for the owner (a login, a captcha) says what it needs, so the card can ask for a hand
        asks = await db.pool().fetch("SELECT task_id, question FROM owner_questions WHERE status = 'open' AND task_id = ANY($1::int[])",
                                     [v["task_id"] for v in mine])
        said = {a["task_id"]: a["question"] for a in asks}
        for v in mine:
            v["asking"] = mask(said.get(v["task_id"], ""))[:240]
    mine.sort(key=lambda s: (s["status"] in FINAL, -s["task_id"]))
    out = {"now": time.time(), "stations": mine}
    if company is None:  # the owner's own desk; a company galaxy shows only that company's tasks
        from . import devteam, meetings, stage, workers
        out |= {"n8n": await n8n_recent(), "prompts": await prompts(), "storage": await storage(),
                "player": stage.desk_player(), "cards": stage.desk_cards(), "meeting": await meetings.desk_card(),
                "workers": await workers.overview(), "devteam": await devteam.overview(), "last_activity": await last_activity()}
    return out


def frame(task_id: int, context: str = "utama") -> tuple[bytes, int] | None:
    st = stations.get(task_id)
    if not st or not st.frame or st.company_id != context_company(context):
        return None
    return st.frame, st.frame_seq


def start() -> None:
    hub.tap(on_event)


# ---------- the owner takes the wheel (ADR-053) ----------
# When the worker is stuck on a login or a captcha the owner clicks "Ambil alih" on the station: mouse, wheel, keys and pasted text from
# the desk go to the very tab the video shows, through DevTools (Input.*). Nothing the owner types is stored, logged or sent anywhere
# but into that page; only "took over" / "handed back" and how long is audited.

CONTROL_TTL_S = 90          # no input for this long → the wheel goes back by itself
KEYS = {  # keys that are not characters → Windows virtual key code
    "Backspace": 8, "Tab": 9, "Enter": 13, "Escape": 27, "Delete": 46, "Home": 36, "End": 35, "PageUp": 33, "PageDown": 34,
    "ArrowLeft": 37, "ArrowUp": 38, "ArrowRight": 39, "ArrowDown": 40,
}
BUTTONS = {"left": 1, "right": 2, "middle": 4}
MAX_TEXT = 500


def controlled(st: Station) -> bool:
    return st.control_until > time.time() and not st.finished


def _unit(v) -> float:
    try:
        return min(1.0, max(0.0, float(v)))
    except (TypeError, ValueError):
        return 0.0


def input_commands(ev: dict, view: tuple[float, float]) -> list[tuple[str, dict]]:
    """One thing the owner did on the video → the DevTools commands that do it in the page. Anything unexpected → nothing."""
    w, h = view
    kind = ev.get("t")
    if kind in ("mouse", "wheel"):
        if w <= 0 or h <= 0:
            return []
        x, y = round(_unit(ev.get("x")) * w, 1), round(_unit(ev.get("y")) * h, 1)
        if kind == "wheel":
            dx, dy = (max(-1500.0, min(1500.0, float(ev.get(k) or 0))) for k in ("dx", "dy"))
            return [("Input.dispatchMouseEvent", {"type": "mouseWheel", "x": x, "y": y, "deltaX": dx, "deltaY": dy})]
        ty = {"move": "mouseMoved", "down": "mousePressed", "up": "mouseReleased"}.get(ev.get("k"))
        if not ty:
            return []
        button = ev.get("b") if ev.get("b") in BUTTONS else "none"
        held = BUTTONS.get(button, 0) if ev.get("k") != "up" else 0
        cmd = {"type": ty, "x": x, "y": y, "button": button if ev.get("k") != "move" else "none", "buttons": held}
        if ev.get("k") != "move":
            cmd["clickCount"] = max(1, min(3, int(ev.get("c") or 1)))
        return [("Input.dispatchMouseEvent", cmd)]
    if kind == "text":
        text = str(ev.get("text") or "")[:MAX_TEXT]
        return [("Input.insertText", {"text": text})] if text else []
    if kind == "key":
        key = str(ev.get("key") or "")
        down = ev.get("k") != "up"
        mods = (1 if ev.get("alt") else 0) | (8 if ev.get("shift") else 0)
        if ev.get("ctrl") or ev.get("meta"):   # no shortcuts, but select-all so a field can be replaced (pasting goes through "text")
            if key.lower() == "a" and down:
                return [("Input.dispatchKeyEvent", {"type": "rawKeyDown", "key": "a", "code": "KeyA", "windowsVirtualKeyCode": 65,
                                                    "modifiers": 2, "commands": ["selectAll"]}),
                        ("Input.dispatchKeyEvent", {"type": "keyUp", "key": "a", "code": "KeyA", "windowsVirtualKeyCode": 65, "modifiers": 2})]
            return []
        if key in KEYS:
            cmd = {"type": ("rawKeyDown" if key != "Enter" else "keyDown") if down else "keyUp", "key": key, "code": str(ev.get("code") or key)[:20],
                   "windowsVirtualKeyCode": KEYS[key], "modifiers": mods}
            if key == "Enter" and down:
                cmd["text"] = "\r"
            return [("Input.dispatchKeyEvent", cmd)]
        if len(key) == 1:
            cmd = {"type": "keyDown" if down else "keyUp", "key": key, "code": str(ev.get("code") or "")[:20], "modifiers": mods,
                   "windowsVirtualKeyCode": ord(key.upper()) if key.isalnum() else 0}
            if down:
                cmd["text"] = key
            return [("Input.dispatchKeyEvent", cmd)]
    return []


class Driver:
    """One DevTools connection to the tab the owner drives; the answers are read and dropped (only layout metrics are waited for)."""

    def __init__(self, ws_cm, target_id: str):
        self.cm, self.ws, self.target_id, self.n = ws_cm, None, target_id, 0
        self.waiting: dict[int, asyncio.Future] = {}
        self.reader: asyncio.Task | None = None

    async def open(self) -> "Driver":
        self.ws = await self.cm.__aenter__()
        self.reader = asyncio.create_task(self._read())
        return self

    async def _read(self) -> None:
        try:
            async for raw in self.ws:
                m = json.loads(raw)
                if (f := self.waiting.pop(m.get("id"), None)) and not f.done():
                    f.set_result(m.get("result") or {})
        except Exception:
            pass
        finally:
            for f in self.waiting.values():
                if not f.done():
                    f.cancel()

    async def call(self, method: str, params: dict | None = None, wait: float = 0.0) -> dict:
        self.n += 1
        fut = asyncio.get_running_loop().create_future() if wait else None
        if fut:
            self.waiting[self.n] = fut
        await self.ws.send(json.dumps({"id": self.n, "method": method, "params": params or {}}))
        return await asyncio.wait_for(fut, wait) if fut else {}

    async def close(self) -> None:
        if self.reader:
            self.reader.cancel()
        try:
            await self.cm.__aexit__(None, None, None)
        except Exception:
            pass


class ControlError(Exception):
    pass


def _station_for(task_id: int, context: str) -> Station:
    st = stations.get(task_id)
    if not st or st.company_id != context_company(context) or st.finished:
        raise ControlError("tugas ini tidak sedang dikerjakan di meja")
    return st


async def take(task_id: int, context: str, actor: str) -> dict:
    """The owner takes the wheel of the station's browser tab."""
    from . import audit
    st = _station_for(task_id, context)
    fresh = not controlled(st)
    if fresh:
        await audit.record(actor, "live.takeover", f"task:{task_id}")
    st.control_until, st.control_by = time.time() + CONTROL_TTL_S, actor
    if fresh:   # the owner never has to wait for the worker to ask: the worker is told to stand still right away
        st.paused = await pause_worker(task_id)
    st.browser_until = max(st.browser_until, time.time() + CONTROL_TTL_S)
    if st.capture is None or st.capture.done():
        st.capture = asyncio.create_task(_capture_loop(st))
    return {"ok": True, "ttl": CONTROL_TTL_S}


async def _driver_for(st: Station) -> Driver:
    now = time.time()
    if st.driver and now - st.driver_checked < 2.0:
        return st.driver
    t = await _pick(st)
    if not t or not t.get("webSocketDebuggerUrl"):
        raise ControlError("belum ada halaman yang terbuka")
    st.driver_checked = now
    if st.driver and st.driver.target_id == t.get("id") and not st.driver.reader.done():
        return st.driver
    if st.driver:
        await st.driver.close()
    st.driver = await Driver(_ws_connect(t["webSocketDebuggerUrl"]), t.get("id", "")).open()
    return st.driver


async def send_input(task_id: int, context: str, ev: dict) -> bool:
    """Do what the owner just did on the video in the page. False when the wheel is not theirs (not taken, or handed back)."""
    st = stations.get(task_id)
    if not st or st.company_id != context_company(context) or not controlled(st):
        return False
    st.control_until = time.time() + CONTROL_TTL_S
    st.browser_until = max(st.browser_until, time.time() + 20)
    if ev.get("t") == "hold":
        return True
    drv = await _driver_for(st)
    if st.view[0] <= 0 and ev.get("t") in ("mouse", "wheel"):   # a picture from before the first screencast frame: ask the page how big it is
        m = (await drv.call("Page.getLayoutMetrics", wait=3)).get("cssVisualViewport") or {}
        st.view = (float(m.get("clientWidth") or 0), float(m.get("clientHeight") or 0))
    for method, params in input_commands(ev, st.view):
        await drv.call(method, params)
    if ev.get("t") != "mouse" or ev.get("k") != "move":
        if time.time() - st.marked_at > 0.5:   # the page's overlay shows the pointer as the owner's ("ANDA"), not the worker's
            st.marked_at = time.time()
            await drv.call("Runtime.evaluate", {"expression": "window.__jarvisOwner=Date.now()"})
    return True


PAUSE_TEXT = ("PEMILIK SEDANG MENGAMBIL ALIH BROWSER untuk [tugas #{n}]. Berhenti memakai browser SEKARANG (jangan klik, ketik, "
              "pindah halaman atau ambil alih tab). Panggil tool wait_for_owner(task_id={n}) dan tunggu sampai hasilnya 'handed_back'; "
              "setelah itu ambil dulu pandangan halaman yang sekarang terbuka, lalu lanjutkan tugasnya.")


async def pause_worker(task_id: int) -> bool:
    """Tell the worker's running Hermes turn to keep its hands off the browser (a steer: read before its next step). False when the task
    has no live Hermes run (OpenJarvis, finished, or Hermes refused) — the owner still has the wheel, the worker just was not told."""
    from . import hermes
    try:
        run_id = await db.pool().fetchval("SELECT hermes_run FROM tasks WHERE id = $1", task_id)
    except Exception:
        return False
    return bool(run_id) and await hermes.steer(run_id, PAUSE_TEXT.format(n=task_id))


def hold_state(task_id: int) -> dict:
    """What wait_for_owner sees: is the owner still driving this task's browser?"""
    st = stations.get(task_id)
    if st and controlled(st):
        return {"status": "owner_driving", "seconds_left": int(st.control_until - time.time())}
    return {"status": "handed_back", "note": HANDED_BACK}


EDITABLE_JS = ("(() => { let a = document.activeElement; while (a && a.shadowRoot && a.shadowRoot.activeElement) a = a.shadowRoot.activeElement;"
               " if (a && a.tagName === 'IFRAME') { try { a = a.contentDocument.activeElement; } catch (e) { return true; } }"
               " return !!a && (a.isContentEditable || a.tagName === 'TEXTAREA' || (a.tagName === 'INPUT' &&"
               " !['button','checkbox','radio','submit','reset','image','file','range','color'].includes((a.type || '').toLowerCase()))); })()")


async def focus_editable(task_id: int, context: str) -> bool:
    """After the owner's tap: is the page's focus now in a field one types into? Then the phone opens its keyboard by itself."""
    st = stations.get(task_id)
    if not st or st.company_id != context_company(context) or not controlled(st):
        return False
    await asyncio.sleep(0.12)   # let the page move its focus first
    drv = await _driver_for(st)
    r = await drv.call("Runtime.evaluate", {"expression": EDITABLE_JS, "returnByValue": True}, wait=2)
    return bool((r.get("result") or {}).get("value"))


HANDED_BACK = ("Pemilik sudah membantu langsung di browser (login / captcha / langkah yang kamu tunggu). "
               "Lanjutkan dari halaman yang sekarang terbuka; ambil dulu pandangan halamannya.")


async def release(task_id: int, context: str, actor: str, done: bool) -> dict:
    """The wheel goes back to the worker. With done=True the worker's open question about this task is answered, so it carries on."""
    from . import audit, questions
    st = stations.get(task_id)
    if not st or st.company_id != context_company(context):
        raise ControlError("tugas ini tidak ada di meja")
    was = controlled(st)
    st.control_until, st.paused = 0.0, False
    if st.driver:
        await st.driver.close()
        st.driver = None
    told = 0
    if done:
        for q in await db.pool().fetch("SELECT id FROM owner_questions WHERE status = 'open' AND task_id = $1", task_id):
            told += 1 if await questions.answer(q["id"], HANDED_BACK, actor) else 0
    if was:
        await audit.record(actor, "live.handback", f"task:{task_id}", told_worker=bool(told))
    return {"ok": True, "told": told}
