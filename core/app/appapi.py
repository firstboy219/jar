"""The app's own API (ADR-087): what the screens of the new app need that the older endpoints did not already give.

Everything here is for the owner's device (owner scope). Screens that only show what an older endpoint returns call that endpoint
directly (/api/v1/notes/…, /api/v1/workers/…, /api/v1/console/… for what the web admin has)."""

import json
from pathlib import Path

from fastapi import APIRouter, Body, Depends, HTTPException
from fastapi.responses import FileResponse, RedirectResponse
from pydantic import BaseModel, Field

from . import audit, db, home, needs, places, workers
from .appauth import actor, owner, require_password
from .location import Location, remember_last

router = APIRouter()
API = "/api/v1/app"

from . import features  # noqa: E402  each feature's own endpoints (/api/v1/app/<feature>/…), providers, checks and ticks
for _r in features.ROUTERS:
    router.include_router(_r)


def jsonable(obj):
    return json.loads(json.dumps(obj, default=str))


# ---------- the app itself: /app/ (the phone's main screen and a page of its own on the web) ----------

WEB = Path(__file__).parent / "web" / "app"
CSP = ("default-src 'self'; script-src 'self'; connect-src 'self' wss: ws:; img-src 'self' https: data: blob:; media-src 'self' https: blob:; "
       "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; font-src 'self' https://fonts.gstatic.com; frame-src 'self' https://www.youtube-nocookie.com; "
       "frame-ancestors 'none'")


@router.get("/app")
async def app_root():
    return RedirectResponse("/app/")


@router.get("/app/{path:path}")
async def app_static(path: str):
    target = (WEB / (path or "index.html")).resolve()
    if not str(target).startswith(str(WEB.resolve())) or not target.is_file():
        raise HTTPException(404)
    return FileResponse(target, headers={"Content-Security-Policy": CSP, "X-Content-Type-Options": "nosniff", "Cache-Control": "no-cache",
                                         "Permissions-Policy": "camera=(self), microphone=(self), display-capture=(self), geolocation=(self)"})


# ---------- front page, catalog, usage ----------

@router.get(API + "/home")
async def app_home(slot: str | None = None, device: dict = Depends(owner)):
    return jsonable(await home.feed(slot))


class OpenedIn(BaseModel):
    feature: str = Field(max_length=40)


@router.post(API + "/opened")
async def app_opened(body: OpenedIn, device: dict = Depends(owner)):
    return {"ok": await home.opened(body.feature)}


@router.get(API + "/features")
async def app_features(device: dict = Depends(owner)):
    from . import setup_status
    status = await setup_status.all_status()
    return jsonable({"groups": home.GROUPS, "features": [{**f, **status.get(f["id"], {})} for f in home.FEATURES]})


# ---------- what waits for the owner ----------

@router.get(API + "/needs")
async def app_needs(device: dict = Depends(owner)):
    return jsonable({"items": await needs.listing()})


class AnswerIn(BaseModel):
    approve: bool | None = None
    option: int | None = None
    text: str = Field(default="", max_length=2000)
    password: str = Field(default="", max_length=200)


@router.post(API + "/needs/{kind}/{item_id}")
async def app_need_answer(kind: str, item_id: int, body: AnswerIn, device: dict = Depends(owner)):
    who = actor(device)
    if kind == "phone" and body.approve:
        from . import phone_agent
        await require_password(device, body.password, f"phone_run:{item_id}")
        try:
            return jsonable({"ok": True, "run": await phone_agent.approve(item_id, who)})
        except phone_agent.PhoneError as e:
            raise HTTPException(409, str(e))
    if kind == "web" and body.approve:   # a web review asked from the chat: sending it is his decision with the admin password
        detail = await db.pool().fetchval("SELECT detail FROM web_waits WHERE id = $1 AND kind = 'tinjau'", item_id) or {}
        if detail.get("password"):
            await require_password(device, body.password, f"web_wait:{item_id}")
    try:
        return jsonable(await needs.answer(kind, item_id, who, approve=body.approve, option=body.option, text=body.text))
    except needs.NeedError as e:
        raise HTTPException(409, str(e))


# ---------- approvals with the phone's own lock (owner 2026-10-31) ----------

class ApprovalKeyIn(BaseModel):
    public_key: str = Field(min_length=60, max_length=400)
    password: str = Field(min_length=1, max_length=200)


@router.get(API + "/approval/key")
async def api_approval_key_state(device: dict = Depends(owner)):
    row = await db.pool().fetchrow("SELECT created_at, last_used FROM device_keys WHERE device_id = $1", device["id"])
    return jsonable({"enrolled": bool(row), "since": row["created_at"] if row else None, "last_used": row["last_used"] if row else None})


@router.post(API + "/approval/key")
async def api_approval_key_register(body: ApprovalKeyIn, device: dict = Depends(owner)):
    """Once per phone: the admin password, then approvals are signed with the phone's PIN / fingerprint."""
    from . import appauth
    if body.password.startswith(appauth.PHONE_PREFIX):
        raise HTTPException(422, "pendaftaran pertama butuh password admin")
    try:
        __import__("base64").b64decode(body.public_key, validate=True)
    except ValueError:
        raise HTTPException(422, "kunci HP tidak valid")
    await require_password(device, body.password, "approval_key")
    await db.pool().execute("""INSERT INTO device_keys (device_id, public_key) VALUES ($1, $2)
                               ON CONFLICT (device_id) DO UPDATE SET public_key = EXCLUDED.public_key, created_at = now(), last_used = NULL""",
                            device["id"], body.public_key)
    await audit.record(actor(device), "app.approval_key", f"device:{device['id']}")
    return {"enrolled": True}


@router.post(API + "/approval/nonce")
async def api_approval_nonce(device: dict = Depends(owner)):
    from . import appauth
    if not await db.pool().fetchval("SELECT 1 FROM device_keys WHERE device_id = $1", device["id"]):
        raise HTTPException(409, "HP ini belum didaftarkan untuk persetujuan")
    return {"nonce": appauth.new_nonce(device)}


# ---------- missions ----------

@router.get(API + "/missions")
async def app_missions(done: bool = False, device: dict = Depends(owner)):
    """The missions (running first); done=true: the finished ones with a look at what each produced (Hasil & laporan)."""
    rows = await db.pool().fetch(
        """SELECT id, title, status, kind, category, runtime, model_used, cost_usd::float AS cost, phase, progress, created_at, finished_at,
                  EXTRACT(EPOCH FROM (COALESCE(finished_at, now()) - COALESCE(started_at, created_at)))::int AS seconds,
                  CASE WHEN $1 THEN left(coalesce(result::text, ''), 220) END AS preview,
                  (EXISTS (SELECT 1 FROM web_waits w JOIN web_tasks wt ON wt.id = w.web_task_id WHERE wt.task_id = tasks.id AND w.status = 'open')
                   OR EXISTS (SELECT 1 FROM owner_questions q WHERE q.task_id = tasks.id AND q.status = 'open')) AS waiting
           FROM tasks WHERE company_id IS NULL AND dev_role IS NULL AND kind NOT IN ('flowcheck') AND (NOT $1 OR status = 'completed')
           ORDER BY (status IN ('queued', 'running')) DESC, id DESC LIMIT 40""", done)
    return jsonable({"missions": [dict(r) for r in rows]})


@router.get(API + "/missions/{task_id}")
async def app_mission(task_id: int, device: dict = Depends(owner)):
    from . import live, results
    r = await db.pool().fetchrow(
        """SELECT id, title, instruction, status, kind, category, runtime, runtime_note, model_used, cost_usd::float AS cost,
                  budget_usd::float AS budget, phase, progress, goal, criteria, plan, result, error, hermes_run, created_at, started_at, finished_at,
                  EXTRACT(EPOCH FROM (COALESCE(finished_at, now()) - COALESCE(started_at, created_at)))::int AS seconds
           FROM tasks WHERE id = $1 AND company_id IS NULL""", task_id)
    if not r:
        raise HTTPException(404, "misi tidak ditemukan")
    t = dict(r)
    data, text = results.split(t.pop("result") or "")
    st = live.stations.get(task_id)
    t["station"] = live.station_view(st) if st else None
    t["result"] = {"data": data, "text": text}
    t["can_say"] = t["status"] == "running" and bool(t.pop("hermes_run"))
    t["can_stop"] = t["status"] in ("queued", "running")
    t["can_start"] = t["status"] in ("stopped", "failed", "cancelled")
    ep = await db.pool().fetchrow("SELECT success, approach, lesson, model FROM episodes WHERE task_id = $1 ORDER BY id DESC LIMIT 1", task_id)
    t["episode"] = dict(ep) if ep else None
    t.update(await _mission_extra(task_id, t))
    return jsonable(t)


async def _mission_extra(task_id: int, t: dict) -> dict:
    """What a mission shows beyond the worker's own fields (owner 2026-10-30: "lg buka halaman misi … tidak ada tanda2 hasilnya"): who does
    it, what it is waiting for from the owner (answered right on the mission page), and — for the web agent — its steps and result."""
    from . import needs, workers
    producer = workers.core_producer(t.pop("instruction", "") or "")
    out: dict = {"producer": producer, "needs": [], "web": None}
    for q in await db.pool().fetch("SELECT q.id, q.question, q.task_id, t.title FROM owner_questions q LEFT JOIN tasks t ON t.id = q.task_id "
                                   "WHERE q.task_id = $1 AND q.status = 'open' ORDER BY q.id", task_id):
        out["needs"].append(needs.question_item(dict(q)))
    w = await db.pool().fetchrow("SELECT id, goal, site, status, backend, trace, result FROM web_tasks WHERE task_id = $1", task_id)
    if w:
        trace = w["trace"] or []
        out["web"] = {"id": w["id"], "site": w["site"], "status": w["status"], "backend": w["backend"], "result": w["result"],
                      "steps": [webstep_text(s) for s in trace][-12:], "step_count": len(trace)}
        for row in await db.pool().fetch("SELECT w.*, t.goal, t.origin, t.site FROM web_waits w JOIN web_tasks t ON t.id = w.web_task_id "
                                         "WHERE w.web_task_id = $1 AND w.status = 'open' ORDER BY w.id", w["id"]):
            out["needs"].append(needs.web_item(dict(row)))
    return out


def webstep_text(s: dict) -> str:
    """One step of the web agent in words. Pure."""
    op, label = s.get("op") or "", ((s.get("sig") or {}).get("l") or "")[:80]
    return {"klik": f"klik “{label}”" + (" (ditinjau dulu)" if s.get("commit") else ""), "isi": f"isi {len(s.get('fields') or [])} kolom",
            "buka": f"buka {str(s.get('url') or '')[:80]}", "gulir": "gulir halaman", "kembali": "kembali ke halaman sebelumnya"}.get(op, op or "langkah")


@router.post(API + "/missions/{task_id}/pause")
async def app_mission_pause(task_id: int, device: dict = Depends(owner)):
    """Jeda: the worker is told to keep its hands off the browser (the owner's wheel) until he lets it carry on."""
    from . import live
    try:
        return await live.take(task_id, "utama", actor(device))
    except live.ControlError as e:
        raise HTTPException(409, str(e))


@router.post(API + "/missions/{task_id}/resume")
async def app_mission_resume(task_id: int, device: dict = Depends(owner)):
    from . import live
    try:
        return await live.release(task_id, "utama", actor(device), False)
    except live.ControlError as e:
        raise HTTPException(409, str(e))


# ---------- what is open on the desk: the "Halaman aktif" ----------

@router.get(API + "/pages")
async def app_pages(device: dict = Depends(owner)):
    pages = await _open_pages()
    hidden = set((await db.pool().fetchval("SELECT value FROM settings_kv WHERE key = 'pages:hidden'") or {}).get("ids", []))
    return jsonable({"pages": [p for p in pages if _sig(p) not in hidden], "hidden": len([p for p in pages if _sig(p) in hidden])})


def _sig(p: dict) -> str:
    """A closed page stays closed until what it shows changes (a new video in the same slot comes back)."""
    return f"{p['id']}|{p['title']}"


async def _open_pages() -> list[dict]:
    from . import live, meetings, stage
    pages = []
    if p := stage.desk_player():
        pages.append({"id": "player", "kind": "musik", "title": p.get("title") or "Musik", "sub": p.get("artist") or "Memutar", "route": "#/musik",
                      "image": p.get("cover_url")})
    for slot, card in (stage.desk_cards() or {}).items():
        if not card:
            continue
        item = (card.get("items") or [{}])[0]
        route = {"video": "#/video", "doc": "#/berkas", "draft": "#/inbox", "map": "#/perjalanan"}.get(slot, "#/obrolan")
        pages.append({"id": f"card:{slot}", "kind": slot, "title": str(item.get("title") or card.get("caption") or slot)[:80],
                      "sub": live.SLOT_WORD.get(slot, slot), "route": route, "image": item.get("thumbnail_url") or item.get("url") if slot == "image" else item.get("thumbnail_url")})
    if m := await meetings.desk_card():
        pages.append({"id": "meeting", "kind": "rapat", "title": m.get("title") or "Rapat", "sub": {"recording": "Merekam", "processing": "Diproses"}.get(m["state"], m["state"]),
                      "route": "#/rapat", **({"since": m["started_at"]} if m["state"] == "recording" and m.get("started_at") else {})})
    from . import commute
    if t := await commute.active():
        chosen = t["chosen"] or {}
        drv = next((e.get("data") for e in reversed(t["events"] or []) if e.get("kind") == "driver"), None) or {}
        pages.append({"id": f"trip:{t['id']}", "kind": "perjalanan", "title": "Berangkat ke kantor" if t["direction"] == "out" else "Pulang ke rumah",
                      "sub": (f"{drv.get('driver') or 'Driver'} {drv.get('plate') or ''} · {drv['eta_min']} mnt" if drv.get("eta_min") is not None
                              else f"tiba ±{chosen.get('arrive', '')}" if chosen.get("arrive") else "berjalan").strip(), "route": "#/perjalanan"})
    for s in (await live.snapshot()).get("stations", []):
        if s["status"] in ("queued", "running"):
            pages.append({"id": f"task:{s['task_id']}", "kind": "misi", "title": s["title"], "sub": s.get("page_title") or s.get("thought") or "berjalan",
                          "route": f"#/misi/{s['task_id']}", "frame": s["task_id"] if s.get("has_frame") else None})
    return pages


class PagesHideIn(BaseModel):
    ids: list[str] = Field(default_factory=list, max_length=50)


@router.post(API + "/pages/hide")
async def app_pages_hide(body: PagesHideIn, device: dict = Depends(owner)):
    """Close pages on the Halaman aktif list (the music stops; other pages just leave the list until they change)."""
    from . import stage
    if "player" in body.ids and (cur := stage.current()) and cur.get("panel") in ("music", "audio", "video"):
        await stage.close(cur["id"])
    keep = (await db.pool().fetchval("SELECT value FROM settings_kv WHERE key = 'pages:hidden'") or {}).get("ids", [])
    want = set(body.ids) - {"player"}
    ids = list(dict.fromkeys([*keep, *[_sig(p) for p in await _open_pages() if p["id"] in want]]))[-200:]
    await db.pool().execute("INSERT INTO settings_kv (key, value) VALUES ('pages:hidden', $1) ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value", {"ids": ids})
    return {"hidden": len(ids)}


# ---------- location in the background, and the owner's places ----------

@router.post(API + "/location")
async def app_location(loc: Location, device: dict = Depends(owner)):
    await remember_last(loc)
    return jsonable({"place": (await places.current()).get("place")})


@router.get(API + "/places")
async def app_places(device: dict = Depends(owner)):
    return jsonable({"places": await places.listing(), "now": await places.current()})


class PlaceIn(BaseModel):
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    label: str = Field(default="", max_length=200)
    radius_m: int = Field(default=200, ge=50, le=5000)


@router.put(API + "/places/{name}")
async def app_place_set(name: str, body: PlaceIn, device: dict = Depends(owner)):
    try:
        return jsonable(await places.set_place(name, body.lat, body.lon, body.label, body.radius_m))
    except ValueError as e:
        raise HTTPException(422, str(e))


@router.delete(API + "/places/{name}")
async def app_place_delete(name: str, device: dict = Depends(owner)):
    return {"ok": await places.remove(name)}


# ---------- settings the screens keep (one JSON per feature) ----------

SETTING_KEYS = {"ibadah", "alarm", "money", "coffee", "invest", "commute", "brief", "story", "jobs", "music", "home", "quran", "bisnis", "cinema", "inbox"}


def loosens_invest(cur: dict, new: dict) -> bool:
    """Does this change make investing less guarded (a higher limit, a wider price guard, no password)? Pure."""
    def more(k):
        return isinstance(new.get(k), (int, float)) and new[k] > cur.get(k, 0)
    return more("limit") or more("price_guard_pct") or new.get("password") is False


@router.get(API + "/settings/{key}")
async def app_setting(key: str, device: dict = Depends(owner)):
    if key not in SETTING_KEYS:
        raise HTTPException(404)
    from . import appsettings
    return jsonable(await appsettings.get(key))


@router.put(API + "/settings/{key}")
async def app_setting_put(key: str, body: dict = Body(...), device: dict = Depends(owner)):
    if key not in SETTING_KEYS:
        raise HTTPException(404)
    from . import appsettings, hub
    body = dict(body)
    password = str(body.pop("admin_password", "") or "")
    if key == "invest" and loosens_invest(await appsettings.get("invest"), body):
        await require_password(device, password, "settings:invest")   # a higher limit or a looser guard is his decision, like a trade
    try:
        out = await appsettings.put(key, body, actor(device))
    except appsettings.SettingError as e:
        raise HTTPException(422, str(e))
    await hub.broadcast({"type": "settings", "key": key})   # the phone re-reads what it keeps itself (the alarm)
    return jsonable(out)


# ---------- the conversation shown in Obrolan ----------

@router.get(API + "/chat/history")
async def app_chat_history(session_id: str, limit: int = 40, device: dict = Depends(owner)):
    rows = await db.pool().fetch(
        """SELECT role, content, route, created_at FROM messages WHERE session_id = $1 AND role IN ('user', 'assistant')
           AND route IS DISTINCT FROM 'silent' ORDER BY id DESC LIMIT $2""", session_id[:128], max(1, min(limit, 100)))
    return jsonable({"messages": [dict(r) for r in reversed(rows)]})


# ---------- Ingatan: what JARVIS learned (skills, phone routines) and knows about the owner ----------

@router.get(API + "/memory")
async def app_memory(device: dict = Depends(owner)):
    from . import master, memory, routines, skills_pipeline
    rts = await routines.listing()
    skills = await skills_pipeline.listing()
    mems = [m for m in await memory.list_(limit=400) if not m.get("stale")]
    prefs = [{"id": str(m["id"]), "text": m["text"], "kind": m.get("kind"), "category": m.get("category")} for m in mems
             if m.get("category") == "personal"][:60]
    auto = sum(r["auto_steps"] or 0 for r in rts)
    ai = sum(r["ai_steps"] or 0 for r in rts)
    flow = await master.summary(30)
    from datetime import datetime, timedelta, timezone
    week = datetime.now(timezone.utc) - timedelta(days=7)
    new = [{"kind": "rutin", "id": r["id"], "name": r["name"], "app": r["app"], "steps": r["steps"], "params": r["params"]} for r in rts
           if r["updated_at"] > week and (r["runs"] or 0) <= 3]
    new += [{"kind": "skill", "id": s["id"], "name": s["name"], "status": s["status"], "approval_id": s["approval_id"]} for s in skills if s["created_at"] > week]
    return jsonable({"routines": rts, "skills": skills, "prefs": prefs, "new": new[:6],
                     "counts": {"skills": len([s for s in skills if s.get("cap_status") == "active" or s["status"] == "published"]) + len([r for r in rts if r["status"] == "active"]),
                                "memories": len(mems)},
                     "no_ai_pct": flow.get("no_ai_pct"), "routine_auto_pct": round(100 * auto / (auto + ai)) if auto + ai else None,
                     "flow": flow, "saved_usd": await saved_this_month()})


async def saved_this_month() -> float:
    """What the work done without AI this month would have cost with it: each job's runs as a skill × what that job costs when it
    thinks (its own average, else the average thinking run)."""
    r = await db.pool().fetchrow(
        """WITH ai AS (SELECT feature, action, avg(cost_usd) AS c FROM flow_runs WHERE lane IN ('ringan', 'berat') AND cost_usd > 0
                                                                        AND started_at > now() - interval '60 days' GROUP BY 1, 2),
                avg_all AS (SELECT coalesce(avg(cost_usd), 0) AS c FROM flow_runs WHERE lane = 'ringan' AND cost_usd > 0 AND started_at > now() - interval '60 days')
           SELECT coalesce(sum(coalesce(ai.c, (SELECT c FROM avg_all))), 0)::float AS saved
           FROM flow_runs f LEFT JOIN ai ON ai.feature = f.feature AND ai.action = f.action
           WHERE f.lane = 'skill' AND f.status = 'done' AND f.started_at > date_trunc('month', now())""")
    return round(r["saved"] or 0, 4)


@router.get(API + "/memory/routine/{routine_id}")
async def app_routine_steps(routine_id: int, device: dict = Depends(owner)):
    """A learned phone routine, step by step, in words (what it opens, taps, types — the parts that change are named)."""
    row = await db.pool().fetchrow("SELECT id, name, app, params, steps, runs, ok_runs, status FROM routines WHERE id = $1", routine_id)
    if not row:
        raise HTTPException(404)
    words = {"open": "Buka", "tap": "Ketuk", "type": "Ketik", "wait": "Tunggu", "scroll": "Gulir", "back": "Kembali", "read": "Baca", "if": "Bila",
             "goto": "Lompat ke", "ai": "Tanya AI", "ask": "Tanya pemilik", "done": "Selesai"}
    steps = [{"n": i + 1, "op": st.get("op"), "text": f"{words.get(st.get('op'), st.get('op'))} {st.get('target') or st.get('text') or st.get('app') or st.get('value') or ''}".strip()}
             for i, st in enumerate(row["steps"] or []) if isinstance(st, dict)]
    return jsonable({**{k: row[k] for k in ("id", "name", "app", "params", "runs", "ok_runs", "status")}, "steps": steps})


# ---------- Kontrol: health, budget, where the owner is, the brains ----------

@router.get(API + "/control")
async def app_control(device: dict = Depends(owner)):
    from . import budget, hub, lanes, master, phone_agent, status
    return jsonable({"health": await status.check_all(), "budget": await budget.state(), "places": await places.listing(),
                     "here": await places.current(), "phone_online": phone_agent.phone_online(), "lanes": await lanes.view(),
                     "flow": await master.summary(7), "devices": [{"device": c.get("device"), "caps": c.get("caps"), "app_version": c.get("app_version")} for c in hub.clients()]})
