"""ADR-087 wave 9: the app as one contract — every API path a screen calls exists on the server (method and shape), every feature in the
front page's catalog has a screen, no feature module calls a model except through the master flow, every GET endpoint of the app answers
on an empty database, and every recurring job is registered and survives a run with no network at all."""
import os
import re
from pathlib import Path

import httpx
import pytest

from tests.test_integration import pool  # noqa: F401  (fixture)

needs_db = pytest.mark.skipif(not os.getenv("TEST_DATABASE_URL"), reason="needs TEST_DATABASE_URL")
APP = Path(__file__).resolve().parent.parent / "app"
WEB = APP / "web" / "app"
CALL = re.compile(r"\b(get|post|put|del|patch)\(\s*[`'\"](/api/v1/[^`'\"]*)[`'\"]")
API_CALL = re.compile(r"\bapi\(\s*'(GET|POST|PUT|DELETE|PATCH)',\s*[`'\"](/api/v1/[^`'\"]*)[`'\"]")


def _calls() -> list[tuple[str, str, str]]:
    out = []
    for f in sorted([*WEB.glob("views/*.js"), *WEB.glob("*.js")]):
        src = f.read_text()
        for m in CALL.finditer(src):
            out.append((f.name, {"get": "GET", "post": "POST", "put": "PUT", "del": "DELETE", "patch": "PATCH"}[m.group(1)], m.group(2)))
        for m in API_CALL.finditer(src):
            out.append((f.name, m.group(1), m.group(2)))
    return out


def all_routes(routes, prefix: str = ""):
    """(path, methods) of every route, through included routers (FastAPI keeps those as one lazy entry)."""
    for r in routes:
        if hasattr(r, "original_router"):
            yield from all_routes(r.original_router.routes, prefix + (r.include_context.prefix or ""))
        elif hasattr(r, "methods") and getattr(r, "path", None):
            yield prefix + r.path, set(r.methods or ())


def _route_regex(path: str) -> re.Pattern:
    return re.compile("^" + re.sub(r"\{[^/}]+\}", "[^/]+", path) + "$")


def test_every_api_call_of_every_screen_has_a_server_route():
    from app import main
    routes = [(methods, _route_regex(path)) for path, methods in all_routes(main.app.routes) if path.startswith("/api/")]
    calls = _calls()
    assert len(calls) > 120                                                                   # the screens really talk to the server
    missing = []
    for file, method, raw in calls:
        path = re.sub(r"\$\{[^{}`]*\}", "X", raw)
        path = path.split("${")[0].split("?")[0].rstrip("/") or raw   # an optional query built inline: the path before it
        path = re.sub(r"X[^/]*", "X", path)
        if not any(method in methods and rx.match(path) for methods, rx in routes):
            missing.append(f"{file}: {method} {raw}")
    assert missing == [], "screens call paths the server does not have:\n" + "\n".join(missing)


def test_every_catalog_feature_has_a_screen_or_a_phone_feature():
    from app import home
    index = (WEB / "views" / "index.js").read_text()
    views = set(re.findall(r"\b(\w+)(?:\s*:\s*\w+)?\s*[,}]", index.split("export const VIEWS = {")[1]))
    native = {"talk", "desk", "notes", "tasks", "meetings", "measure", "guide"}   # MainActivity's open() targets
    for f in home.FEATURES:
        r = f["route"]
        if r.startswith("native:"):
            assert r[7:] in native, f"{f['id']}: the phone has no {r}"
        else:
            name = r.lstrip("#/").split("/")[0].split("?")[0] or "beranda"
            assert name in views, f"{f['id']}: no screen for {r}"


def test_the_quran_fallback_has_every_verse():
    from app import quran
    assert len(quran.AYAT) == len(quran.LATIN) == 114 and sum(quran.AYAT) == 6236 and quran.LATIN[17] == "Al-Kahf"


def test_no_feature_module_calls_a_model_outside_the_master_flow():
    feat = (APP / "features.py").read_text()
    mods = set(re.findall(r"\b([a-z_]+)\b", feat.split("from . import")[1].split(")")[0]))
    extra = {"meetings", "notifications", "inbox", "appapi", "home", "needs", "places", "commute", "krl", "weather"}
    offenders = []
    for m in sorted(mods | extra):
        p = APP / f"{m}.py"
        if not p.exists():
            continue
        for i, line in enumerate(p.read_text().splitlines(), 1):
            if re.search(r"\b(llm|gateway)\.complete\(", line):
                offenders.append(f"{m}.py:{i}: {line.strip()[:90]}")
    assert offenders == [], "model calls outside master.run:\n" + "\n".join(offenders)
    assert len(mods) >= 25


@needs_db
async def test_every_app_get_endpoint_answers_on_an_empty_database(pool, monkeypatch):
    from app import devices, main

    monkeypatch.setattr(httpx.AsyncClient, "send", _offline_unless_asgi(httpx.AsyncClient.send))   # the app is reached; the internet is not
    _, token = await devices.create("HP", "test", scope="owner")
    h = {"Authorization": f"Bearer {token}"}
    paths = sorted({p for p, m in all_routes(main.app.routes) if "GET" in m and p.startswith("/api/v1/app/") and "{" not in p})
    assert len(paths) > 40
    bad = []
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app, raise_app_exceptions=False), base_url="http://t") as c:
        for p in paths:
            r = await c.get(p, headers=h)
            explained = r.status_code in (502, 503) and "detail" in (r.headers.get("content-type", "") and r.json() or {})   # an outside source down, said so
            if r.status_code >= 500 and not explained:
                bad.append(f"{p} → {r.status_code} {r.text[:120]}")
    assert bad == [], "\n".join(bad)


def _offline_unless_asgi(real):
    async def send(self, request, **kw):
        if isinstance(self._transport, httpx.ASGITransport):
            return await real(self, request, **kw)
        raise httpx.ConnectError("offline in tests")
    return send


EXPECTED_EVERY = {"habits.time", "commute.watch", "ibadah.reminders", "quran.routines", "inbox.sync", "outlook.login", "bisnis.poll", "money.ingest",
                  "jobs.replies", "jobs.mail", "music.download", "storage.watch"}
EXPECTED_DAILY = {"habits.learn", "bisnis.strategy", "bisnis.opportunities", "money.label", "invest.weekly", "flow.thin", "jobs.round1", "jobs.round2"}


@needs_db
async def test_every_recurring_job_is_registered_and_survives_a_pass_without_network(pool, monkeypatch, caplog):
    import logging
    from app import appclock, attention, features  # noqa: F401
    await pool.execute("TRUNCATE flow_runs, notifications, mail_items, biz_sources, job_applications, job_replies, inbox_items, music_library RESTART IDENTITY CASCADE")
    attention._seen["mark"] = (None, None)
    assert EXPECTED_EVERY <= set(appclock._every), EXPECTED_EVERY - set(appclock._every)
    assert EXPECTED_DAILY <= set(appclock._daily), EXPECTED_DAILY - set(appclock._daily)
    assert any(n.startswith("brief") for n in appclock._daily)                                  # the morning brief

    async def offline(self, request, **kw):
        raise httpx.ConnectError("offline in tests")
    monkeypatch.setattr(httpx.AsyncClient, "send", offline)
    failed = []
    for name, (secs, fn) in appclock._every.items():
        try:
            await fn()
        except Exception as e:   # each tick must cope with an empty database and no network on its own
            failed.append(f"{name}: {type(e).__name__}: {e}"[:200])
    assert failed == [], "\n".join(failed)
    idle = await pool.fetch("SELECT feature, action FROM flow_runs WHERE feature IN ('inbox', 'bisnis', 'uang', 'karier')")
    assert [dict(x) for x in idle] == []                                                       # nothing to do → no run started
    caplog.set_level(logging.ERROR)
    appclock._last.clear()
    ran = await appclock.run_once()
    assert set(appclock._every) <= set(ran)                                                     # one pass runs every periodic job
