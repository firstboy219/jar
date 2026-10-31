"""JARVIS Web Admin (FS-105): dashboard, approval queue, memory, devices, usage, audit, settings, chat.

Settings are written to the stack's .env; a host systemd path unit
(infra/systemd/jarvis-apply.*) notices the change and runs `docker compose up -d`.
Everything else goes through jarvis-core's internal /admin API (X-Admin-Token from .env).
This container has no Docker socket and no database access.
"""

import json
import os
import re
from pathlib import Path

import httpx
from fastapi import FastAPI, Form, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .auth import Throttle, check_session, hash_password, make_session, verify_password
from .envfile import EnvFile

ENV = EnvFile(os.getenv("JARVIS_ENV_FILE", "/config/.env"))
APPLY_LOG = Path(os.getenv("JARVIS_APPLY_LOG", "/status/apply.log"))
RELEASES = Path(os.getenv("JARVIS_RELEASES", "/releases"))  # written by infra/scripts/build-apk.sh
APK_NAME = re.compile(r"^jarvis-\d+\.\d+\.\d+\.apk$")
PUBLIC_ORIGIN = os.getenv("ADMIN_PUBLIC_ORIGIN", "")
COOKIE = "jarvis_admin"
CORE = "http://jarvis-core:8000"

OR_KEY = r"^sk-or-[A-Za-z0-9_-]{10,}$"
# key, label, is_secret, validation pattern, help text. Which AI handles what is NOT here: it is the
# owner's composition, changed only from the APK (Komposisi AI) — decision 2026-10-21.
SETTINGS = [
    ("OPENROUTER_API_KEY", "OpenRouter API key", True, OR_KEY,
     "Opsional. Dari openrouter.ai/keys. Tanpa kunci, semua AI berjalan lokal di server (lambat tapi jalan)."),
    ("OPENROUTER_KEY_CHAT", "OpenRouter key — ngobrol", True, OR_KEY,
     "Opsional: kunci terpisah untuk agen utama, supaya bisa diberi limit bulanan sendiri di openrouter.ai."),
    ("OPENROUTER_KEY_HERMES", "OpenRouter key — Hermes", True, OR_KEY,
     "Opsional: kunci terpisah untuk pekerjaan Hermes (limit sendiri)."),
    ("OPENROUTER_KEY_LATAR", "OpenRouter key — latar belakang", True, OR_KEY,
     "Opsional: kunci untuk tugas kecil & latar belakang (situasi, cek diri, laporan)."),
    ("GROQ_API_KEY", "Groq API key", True, r"^gsk_[A-Za-z0-9]{20,}$",
     "Opsional. Pengenalan suara cepat (Whisper turbo, gratis ±8 jam audio/hari). console.groq.com/keys."),
    ("HERMES_PROFILE", "Profil Hermes", False, r"^(lean|full)?$",
     "lean: prompt ramping untuk model lokal (cepat di CPU). full: semua alat & skill langsung (untuk model cloud). "
     "Diatur otomatis saat Komposisi AI berganti."),
    ("MP3_CONVERTER_URL", "Converter YouTube → MP3 (alamat API)", False, r"^(https://[A-Za-z0-9.-]+(:[0-9]+)?(/[A-Za-z0-9._/-]*)?)?$",
     "Opsional. API converter kompatibel cobalt (mis. https://<instance>/). Link YouTube dikirim ke sini, hasil MP3 diputar di HP."),
    ("MP3_CONVERTER_KEY", "Converter YouTube → MP3 (API key)", True, r"^[A-Za-z0-9._-]{8,200}$",
     "Opsional. API key dari pengelola converter itu. Tanpa converter, lagu diambil dari SoundCloud (MP3)."),
    ("TOMTOM_API_KEY", "TomTom API key (peta)", True, r"^[A-Za-z0-9]{20,}$",
     "Opsional. Waktu tempuh dengan kondisi macet (gratis 2.500 rute/hari). developer.tomtom.com."),
    ("ORS_API_KEY", "OpenRouteService key (peta)", True, r"^[A-Za-z0-9=]{20,}$",
     "Opsional. Rute alternatif tanpa data macet (gratis 2.000/hari). openrouteservice.org."),
    ("JARVIS_BUDGET_USD", "Anggaran AI per bulan (USD)", False, r"^([0-9]|[1-9][0-9]|100)(\.[0-9]{1,2})?$",
     "Batas lunak: 80% → tugas latar ke model gratis/lokal, 100% → model berbayar berhenti (lokal tetap jalan)."),
    ("QUIET_HOURS", "Jam tenang notifikasi (WIB)", False, r"^(([01][0-9]|2[0-3]):[0-5][0-9]-([01][0-9]|2[0-3]):[0-5][0-9])?$",
     "Format 22:00-06:00. Di jam ini hanya notifikasi penting yang disampaikan. Kosongkan untuk mematikan."),
    ("WORKER_CONCURRENCY", "Worker berjalan bersamaan", False, r"^([1-9]|1[0-9]|20)$",
     "Jumlah tugas tak terbatas (antre); ini berapa yang dikerjakan sekaligus (1–20)."),
    ("WHISPER_LIVE_MODEL", "Whisper lokal — ucapan", False, r"^(base|small|medium|large-v3-turbo)$",
     "small: ±3,5 dtk/ucapan, salah ±19%. large-v3-turbo: salah ±10% tapi ±15 dtk/ucapan."),
    ("WHISPER_FILE_MODEL", "Whisper lokal — rekaman rapat", False, r"^(base|small|medium|large-v3-turbo)$",
     "small: 1 jam rapat ≈ 25 menit. large-v3-turbo: lebih akurat, ±3 jam per jam rapat."),
    ("N8N_API_KEY", "n8n API key", True, r"^[A-Za-z0-9._-]{20,}$",
     "Buat di https://flow1.cosger.online → Settings → n8n API."),
    ("DEEPGRAM_API_KEY", "Deepgram API key", True, r"^[A-Za-z0-9]{20,}$",
     "Opsional (mesin suara Deepgram). APK hanya menerima token berumur pendek dari server."),
    ("DEEPGRAM_MODEL", "Model Deepgram", False, r"^[a-z0-9-]+$",
     "nova-2 terbukti paling akurat untuk bahasa Indonesia (WER ±12%)."),
    ("DEEPGRAM_KEYWORDS", "Kosakata khusus suara", False, r"^[A-Za-z0-9 ,._-]{0,500}$",
     "Nama/istilah yang sering kamu ucapkan, pisahkan dengan koma. Dipakai juga oleh Whisper."),
]
TABS = [("dashboard", "Dasbor"), ("approvals", "Persetujuan"), ("memory", "Memori"), ("ai", "Model AI"),
        ("studio", "Hermes Studio"), ("companies", "Perusahaan"), ("voice", "Suara"), ("worker", "Pekerja berat"), ("inbox", "Inbox & Pantau"), ("docs", "Dokumen"), ("password", "Password"), ("self", "Diri JARVIS"), ("devices", "Perangkat"),
        ("app", "Aplikasi"), ("audit", "Audit"), ("settings", "Pengaturan")]
CATEGORIES = ["personal", "project", "knowledge", "experience", "operational"]
KINDS = ["fact", "assumption", "preference"]

app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
app.mount("/static", StaticFiles(directory=Path(__file__).parent / "static"), name="static")
templates = Jinja2Templates(directory=Path(__file__).parent / "templates")
throttle = Throttle()


class CoreError(RuntimeError):
    pass


async def core(method: str, path: str, **kw):
    token = ENV.read().get("CORE_ADMIN_TOKEN", "")
    try:
        async with httpx.AsyncClient(base_url=CORE, timeout=200, headers={"X-Admin-Token": token}) as c:
            r = await c.request(method, path, **kw)
    except httpx.HTTPError as e:
        raise CoreError(f"jarvis-core tidak dapat dihubungi ({type(e).__name__})")
    if r.status_code >= 400:
        try:
            detail = r.json().get("detail")
        except ValueError:
            detail = r.text[:200]
        raise CoreError(f"{detail or 'HTTP ' + str(r.status_code)}")
    return r.json()


def client_ip(request: Request) -> str:
    return request.headers.get("x-real-ip") or (request.client.host if request.client else "?")


def authed(request: Request) -> bool:
    env = ENV.read()
    return check_session(request.cookies.get(COOKIE), env["ADMIN_SESSION_SECRET"], env["ADMIN_PASSWORD_HASH"])


def same_origin(request: Request) -> bool:
    # CSRF guard on top of SameSite=Strict cookies.
    origin = request.headers.get("origin")
    return origin is None or not PUBLIC_ORIGIN or origin == PUBLIC_ORIGIN


def mask(value: str) -> str:
    return f"••••{value[-4:]}" if len(value) > 8 else ("••••" if value else "")


def load_releases() -> list[dict]:
    try:
        releases = json.loads((RELEASES / "releases.json").read_text())
    except (OSError, ValueError):
        return []
    # old APK files may be removed by the storage manager (the index keeps them so versionCodes never repeat)
    return [r for r in releases if APK_NAME.match(r.get("file", "")) and (RELEASES / r["file"]).is_file()]


def apply_log_tail(lines: int = 8) -> str:
    try:
        return "\n".join(APPLY_LOG.read_text().splitlines()[-lines:])
    except OSError:
        return ""


async def _tab_data(tab: str, request: Request) -> dict:
    q = request.query_params
    if tab == "dashboard":
        return {"status": await core("GET", "/admin/status"), "usage": await core("GET", "/admin/usage"),
                "pending": await core("GET", "/admin/approvals", params={"status_": "awaiting_approval"}),
                "apply_log": apply_log_tail()}
    if tab == "approvals":
        return {"approvals": await core("GET", "/admin/approvals")}
    if tab == "memory":
        params = {k: q[k] for k in ("q", "category") if q.get(k)}
        return {"memories": await core("GET", "/admin/memories", params=params), "q": q.get("q", ""),
                "category": q.get("category", ""), "categories": CATEGORIES, "kinds": KINDS}
    if tab == "devices":
        return {"devices": await core("GET", "/admin/devices")}
    if tab == "audit":
        return {"events": await core("GET", "/admin/audit")}
    if tab == "app":
        return {"releases": load_releases()}
    if tab == "companies":
        listing = await core("GET", "/admin/companies")
        chosen = q.get("c") or next((c["id"] for c in listing["companies"]), None)
        return listing | {"chosen": chosen, "detail": await core("GET", f"/admin/companies/{chosen}") if chosen else None}
    if tab == "inbox":
        return await core("GET", "/admin/inbox")
    if tab == "voice":
        return await core("GET", "/admin/voice")
    if tab == "worker":
        return await core("GET", "/admin/openjarvis")
    if tab == "self":
        return await core("GET", "/admin/self") | {"errors_log": await core("GET", "/admin/errors"),
                                                    "flow_issues": await core("GET", "/admin/flow-issues"),
                                                    "dev_changes": await core("GET", "/admin/dev-changes"),
                                                    "selfdev": await core("GET", "/admin/selfdev/control")}
    if tab == "password":
        return {"vault": await core("GET", "/admin/vault")}
    if tab == "ai":
        return {"composition": await core("GET", "/admin/composition"), "llm": await core("GET", "/admin/llm-usage")}
    if tab == "studio":
        return {"studio": await core("GET", "/admin/hermes-studio")}
    if tab == "docs":
        return {"documents": await core("GET", "/admin/documents")}
    if tab == "settings":
        env = ENV.read()
        return {"fields": [{"key": k, "label": label, "secret": secret, "help": help_,
                            "display": mask(env.get(k, "")) if secret else env.get(k, "")}
                           for k, label, secret, _, help_ in SETTINGS],
                "apply_log": apply_log_tail()}
    return {}


async def render(request: Request, tab: str, **extra) -> HTMLResponse:
    tab = tab if tab in dict(TABS) else "dashboard"
    try:
        data = await _tab_data(tab, request)
    except CoreError as e:
        data, extra["errors"] = {}, [*extra.get("errors", []), str(e)]
    return templates.TemplateResponse(request, "dashboard.html", {
        "tab": tab, "tabs": TABS, "backend_url": f"https://{ENV.read().get('BACKEND_DOMAIN', '')}",
        **data, **extra})


def back(tab: str, **params) -> RedirectResponse:
    qs = "&".join(f"{k}={v}" for k, v in params.items() if v)
    return RedirectResponse(f"/?tab={tab}" + (f"&{qs}" if qs else ""), status_code=303)


def guard(request: Request) -> RedirectResponse | None:
    if not authed(request) or not same_origin(request):
        return RedirectResponse("/login", status_code=303)
    return None


# ---------- pages ----------

@app.get("/", response_class=HTMLResponse)
async def index(request: Request, tab: str = "dashboard"):
    if not authed(request):
        return RedirectResponse("/login", status_code=303)
    return await render(request, tab)


@app.get("/login", response_class=HTMLResponse)
async def login_form(request: Request):
    return templates.TemplateResponse(request, "login.html", {})


@app.post("/login")
async def login(request: Request, password: str = Form(...)):
    ip = client_ip(request)
    if not same_origin(request):
        return HTMLResponse("Forbidden", status_code=403)
    if throttle.blocked(ip):
        return templates.TemplateResponse(request, "login.html",
                                          {"error": "Terlalu banyak percobaan. Coba lagi 15 menit lagi."},
                                          status_code=429)
    env = ENV.read()
    if not verify_password(password, env["ADMIN_PASSWORD_HASH"]):
        throttle.fail(ip)
        return templates.TemplateResponse(request, "login.html", {"error": "Password salah."}, status_code=401)
    throttle.reset(ip)
    response = RedirectResponse("/", status_code=303)
    response.set_cookie(COOKIE, make_session(env["ADMIN_SESSION_SECRET"], env["ADMIN_PASSWORD_HASH"]),
                        httponly=True, secure=True, samesite="strict", max_age=12 * 3600)
    return response


@app.post("/logout")
async def logout():
    response = RedirectResponse("/login", status_code=303)
    response.delete_cookie(COOKIE)
    return response


# ---------- actions ----------

@app.post("/approvals/{approval_id}", response_class=HTMLResponse)
async def decide(request: Request, approval_id: int, decision: str = Form(...), tab: str = Form("approvals")):
    if r := guard(request):
        return r
    try:
        a = await core("POST", f"/admin/approvals/{approval_id}", json={"approve": decision == "approve"})
    except CoreError as e:
        return await render(request, tab, errors=[str(e)])
    msg = f"Persetujuan #{a['id']} → {a['status']}" + (f": {a['error']}" if a.get("error") else "")
    return await render(request, tab, notice=msg)


@app.post("/memory", response_class=HTMLResponse)
async def memory_create(request: Request, text: str = Form(...), category: str = Form(...), kind: str = Form(...)):
    if r := guard(request):
        return r
    try:
        await core("POST", "/admin/memories", json={"text": text, "category": category, "kind": kind})
    except CoreError as e:
        return await render(request, "memory", errors=[str(e)])
    return await render(request, "memory", notice="Memori disimpan.")


@app.post("/memory/{mem_id}", response_class=HTMLResponse)
async def memory_edit(request: Request, mem_id: str, action: str = Form(...), text: str = Form(""),
                      category: str = Form(""), kind: str = Form("")):
    if r := guard(request):
        return r
    try:
        if action == "delete":
            await core("DELETE", f"/admin/memories/{mem_id}")
            msg = "Memori dihapus (termasuk dari indeks)."
        elif action in ("stale", "fresh"):
            await core("PATCH", f"/admin/memories/{mem_id}", json={"stale": action == "stale"})
            msg = "Ditandai usang." if action == "stale" else "Ditandai masih berlaku."
        else:
            await core("PATCH", f"/admin/memories/{mem_id}",
                       json={"text": text, "category": category or None, "kind": kind or None})
            msg = "Memori diperbarui."
    except CoreError as e:
        return await render(request, "memory", errors=[str(e)])
    return await render(request, "memory", notice=msg)


@app.post("/selfcheck", response_class=HTMLResponse)
async def selfcheck(request: Request):
    if r := guard(request):
        return r
    try:
        t = await core("POST", "/admin/selfcheck")
    except CoreError as e:
        return await render(request, "self", errors=[str(e)])
    return await render(request, "self", notice=f"Cek diri dimulai (tugas #{t['task_id']}). Hasilnya akan disampaikan JARVIS.")


@app.post("/flow-check", response_class=HTMLResponse)
async def flow_check(request: Request):
    if r := guard(request):
        return r
    try:
        t = await core("POST", "/admin/flow-check")
    except CoreError as e:
        return await render(request, "self", errors=[str(e)])
    return await render(request, "self", notice=f"Pengawas alur selesai memeriksa: {t['new']} masalah baru.")


@app.post("/flow-issues/{issue_id}", response_class=HTMLResponse)
async def flow_issue(request: Request, issue_id: int, status: str = Form(...)):
    if r := guard(request):
        return r
    try:
        await core("POST", f"/admin/flow-issues/{issue_id}", json={"status": status})
    except CoreError as e:
        return await render(request, "self", errors=[str(e)])
    return await render(request, "self", notice=f"Masalah #{issue_id} → {status}.")


@app.post("/efficiency-review", response_class=HTMLResponse)
async def efficiency_review(request: Request):
    if r := guard(request):
        return r
    try:
        t = await core("POST", "/admin/efficiency-review")
    except CoreError as e:
        return await render(request, "self", errors=[str(e)])
    return await render(request, "self", notice=f"Tinjauan efisiensi dimulai (tugas #{t['task_id']}).")


async def _company_action(request: Request, company_id: str | None, call, done: str) -> HTMLResponse:
    """Company tab actions: run `call()` against core, then show the company again."""
    if r := guard(request):
        return r
    try:
        result = await call()
    except CoreError as e:
        return await render(request, "companies", errors=[str(e)])
    if company_id:
        request.scope["query_string"] = f"tab=companies&c={company_id}".encode()
    return await render(request, "companies", notice=done(result) if callable(done) else done)


@app.post("/companies", response_class=HTMLResponse)
async def company_add(request: Request, name: str = Form(...), aliases: str = Form("")):
    return await _company_action(request, None, lambda: core("POST", "/admin/companies", json={
        "name": name, "aliases": [a.strip() for a in aliases.split(",") if a.strip()]}), lambda c: f"Perusahaan {c['name']} ({c['id']}) ditambahkan.")


@app.post("/companies/{company_id}/config", response_class=HTMLResponse)
async def company_config(request: Request, company_id: str, adapter: str = Form("mock"), dgm_url: str = Form(""),
                         dgm_token: str = Form(""), contract_verified: str = Form(""), callback_timeout_s: int = Form(1800),
                         max_retries: int = Form(2), budget_usd_month: str = Form(""), aliases: str = Form(""), active: str = Form("")):
    body = {"adapter": adapter, "dgm_url": dgm_url or None, "contract_verified": contract_verified == "on",
            "callback_timeout_s": callback_timeout_s, "max_retries": max_retries, "active": active == "on",
            "aliases": [a.strip() for a in aliases.split(",") if a.strip()],
            "budget_usd_month": float(budget_usd_month) if budget_usd_month.strip() else None}
    if dgm_token.strip():
        body["dgm_token"] = dgm_token.strip()  # write-only: never shown again
    return await _company_action(request, company_id, lambda: core("PATCH", f"/admin/companies/{company_id}", json=body), "Pengaturan disimpan.")


@app.post("/companies/{company_id}/secret", response_class=HTMLResponse)
async def company_secret(request: Request, company_id: str):
    return await _company_action(request, company_id, lambda: core("POST", f"/admin/companies/{company_id}/callback-secret"),
                                 lambda r: f"Rahasia callback baru (tampil SEKALI, salin ke server Hermes-DGM): {r['callback_secret']} · URL callback: {r['callback_url']}")


@app.post("/companies/{company_id}/vault", response_class=HTMLResponse)
async def company_vault_add(request: Request, company_id: str, kind: str = Form(...), title: str = Form(...), body: str = Form(""),
                            metric: str = Form(""), value: str = Form(""), unit: str = Form(""), period: str = Form(""), target: str = Form("")):
    data = None
    if kind in ("kpi", "cashflow") and value.strip():
        data = {"metric": metric or title, "value": value, "unit": unit or None, "period": period or None, "target": target or None}
        data = {k: v for k, v in data.items() if v}
    return await _company_action(request, company_id, lambda: core("POST", f"/admin/companies/{company_id}/vault", json={
        "kind": kind, "title": title, "body": body, "data": data, "verified": True}), "Isian Company Vault disimpan.")


@app.post("/companies/{company_id}/vault/{entry_id}/delete", response_class=HTMLResponse)
async def company_vault_delete(request: Request, company_id: str, entry_id: int):
    return await _company_action(request, company_id, lambda: core("DELETE", f"/admin/companies/{company_id}/vault/{entry_id}"), "Isian dihapus.")


@app.post("/companies/{company_id}/directives", response_class=HTMLResponse)
async def company_directive(request: Request, company_id: str, action: str = Form(...), instruction: str = Form(...),
                            budget_usd: str = Form(""), deadline_hours: str = Form("")):
    body = {"action": action, "instruction": instruction}
    if budget_usd.strip():
        body["budget_usd"] = float(budget_usd)
    if deadline_hours.strip():
        body["deadline_hours"] = float(deadline_hours)
    return await _company_action(request, company_id, lambda: core("POST", f"/admin/companies/{company_id}/directives", json=body),
                                 lambda d: f"Arahan #{d['id']}: {d['status']}" + (" — menunggu persetujuanmu" if d.get("approval_id") else ""))


@app.post("/companies/{company_id}/directives/{directive_id}/cancel", response_class=HTMLResponse)
async def company_directive_cancel(request: Request, company_id: str, directive_id: int):
    return await _company_action(request, company_id, lambda: core("POST", f"/admin/companies/{company_id}/directives/{directive_id}/cancel"),
                                 "Arahan dibatalkan.")


async def _voice_action(request: Request, call, done) -> HTMLResponse:
    """Suara tab (Blueprint v4 Fase 3): run `call()` against core, then show the tab again."""
    if r := guard(request):
        return r
    try:
        result = await call()
    except CoreError as e:
        return await render(request, "voice", errors=[str(e)])
    return await render(request, "voice", notice=done(result) if callable(done) else done)


@app.post("/worker/openjarvis", response_class=HTMLResponse)
async def worker_openjarvis(request: Request, enabled: str = Form(...)):
    """Pekerja berat tab (Fase 2): switch the optional OpenJarvis worker on or off — decided here only."""
    if r := guard(request):
        return r
    try:
        await core("POST", "/admin/openjarvis", json={"enabled": enabled == "on"})
    except CoreError as e:
        return await render(request, "worker", errors=[str(e)])
    return await render(request, "worker", notice="OpenJarvis dinyalakan." if enabled == "on" else "OpenJarvis dimatikan.")


async def _inbox_action(request: Request, call, done) -> HTMLResponse:
    """Inbox & Pantau tab (Blueprint v4 Fase 6): run `call()` against core, then show the tab again."""
    if r := guard(request):
        return r
    try:
        result = await call()
    except CoreError as e:
        return await render(request, "inbox", errors=[str(e)])
    return await render(request, "inbox", notice=done(result) if callable(done) else done)


@app.post("/inbox/install", response_class=HTMLResponse)
async def inbox_install(request: Request):
    return await _inbox_action(request, lambda: core("POST", "/admin/inbox/install"),
                               "Alur n8n dibuat (belum aktif). Setujui pengaktifannya di tab Persetujuan, lalu pasang kredensial Google di n8n.")


@app.post("/inbox/auto", response_class=HTMLResponse)
async def inbox_auto(request: Request, on: str = Form(...)):
    return await _inbox_action(request, lambda: core("POST", "/admin/inbox/auto", json={"on": on == "on"}),
                               "Pemeriksaan email otomatis dinyalakan." if on == "on" else "Pemeriksaan email otomatis dimatikan.")


@app.post("/inbox/check", response_class=HTMLResponse)
async def inbox_check(request: Request):
    return await _inbox_action(request, lambda: core("POST", "/admin/inbox/check"),
                               lambda r: f"Diperiksa: {r.get('baru', 0)} email baru, {len(r.get('penting', []))} penting.")


@app.post("/watchers", response_class=HTMLResponse)
async def watcher_add(request: Request, kind: str = Form(...), label: str = Form(...), query: str = Form(...), op: str = Form(...),
                      threshold: float = Form(...), every_min: int = Form(0)):
    body = {"kind": kind, "label": label, "query": query, "op": op, "threshold": threshold, "every_min": every_min or None}
    return await _inbox_action(request, lambda: core("POST", "/admin/watchers", json=body), "Pantauan ditambahkan.")


@app.post("/watchers/{watcher_id}/active", response_class=HTMLResponse)
async def watcher_active(request: Request, watcher_id: int, active: str = Form(...)):
    return await _inbox_action(request, lambda: core("POST", f"/admin/watchers/{watcher_id}/active", json={"active": active == "on"}), "Pantauan diperbarui.")


@app.post("/watchers/{watcher_id}/delete", response_class=HTMLResponse)
async def watcher_delete(request: Request, watcher_id: int):
    return await _inbox_action(request, lambda: core("DELETE", f"/admin/watchers/{watcher_id}"), "Pantauan dihapus.")


@app.post("/voice/settings", response_class=HTMLResponse)
async def voice_settings(request: Request, field: str = Form(...), value: str = Form(...)):
    """K3 consent (keep utterance audio on this server as a test set) and the second-opinion engine: decided here only."""
    body = {"keep_samples": value == "on"} if field == "keep_samples" else {"second_engine": value}
    return await _voice_action(request, lambda: core("POST", "/admin/voice/settings", json=body), "Pengaturan suara disimpan.")


@app.post("/voice/complements/{name}", response_class=HTMLResponse)
async def voice_mode(request: Request, name: str, mode: str = Form(...)):
    return await _voice_action(request, lambda: core("POST", f"/admin/voice/complements/{name}", json={"mode": mode}),
                               lambda r: f"{name}: mode {r['mode']}" + (" (otomatis lewat gerbang mutu)" if r["auto"] else " (manual)"))


@app.post("/voice/evaluate", response_class=HTMLResponse)
async def voice_evaluate(request: Request):
    return await _voice_action(request, lambda: core("POST", "/admin/voice/evaluate"),
                               lambda r: "Gerbang mutu dijalankan pada " + str(r["labeled"]) + " ucapan terkoreksi. "
                               + ("; ".join(r["changed"]) if r["changed"] else "Tidak ada mode yang berubah."))


@app.post("/voice/data", response_class=HTMLResponse)
async def voice_data_add(request: Request, kind: str = Form(...), key: str = Form(...), value: str = Form("")):
    return await _voice_action(request, lambda: core("POST", "/admin/voice/data", json={"kind": kind, "key": key, "value": value}),
                               "Data suara ditambahkan (berversi; bisa dibatalkan).")


@app.post("/voice/data/{row_id}/delete", response_class=HTMLResponse)
async def voice_data_remove(request: Request, row_id: int):
    return await _voice_action(request, lambda: core("DELETE", f"/admin/voice/data/{row_id}"), "Dibatalkan (riwayat tetap tersimpan).")


@app.post("/voice/events/{event_id}/reference", response_class=HTMLResponse)
async def voice_reference(request: Request, event_id: int, text: str = Form(""), not_me: str = Form("")):
    body = {"not_me": True} if not_me else {"text": text}
    return await _voice_action(request, lambda: core("POST", f"/admin/voice/events/{event_id}/reference", json=body),
                               lambda r: f"Ucapan #{r['event']} diberi teks benar" + (f" (jenis kesalahan: {r['error_kind']})" if r["error_kind"] else " (sudah benar)"))


@app.post("/selfdev/control", response_class=HTMLResponse)
async def selfdev_control(request: Request, field: str = Form(...), value: str = Form(...)):
    """The control point (Blueprint v4 §3.3): pause every self-change at once, or open/close tier T2."""
    if r := guard(request):
        return r
    if field not in ("paused", "t2_enabled"):
        return await render(request, "self", errors=["sakelar tidak dikenal"])
    try:
        c = await core("POST", "/admin/selfdev/control", json={field: value == "on"})
    except CoreError as e:
        return await render(request, "self", errors=[str(e)])
    return await render(request, "self", notice=("Perubahan diri DIJEDA." if c["paused"] else "Perubahan diri berjalan.")
                        + (" Tingkat T2 dibuka." if c["t2_enabled"] else " Tingkat T2 tertutup."))


@app.post("/improvements/{improvement_id}/revert", response_class=HTMLResponse)
async def improvement_revert(request: Request, improvement_id: int):
    if r := guard(request):
        return r
    try:
        await core("POST", f"/admin/improvements/{improvement_id}/revert")
    except CoreError as e:
        return await render(request, "self", errors=[str(e)])
    return await render(request, "self", notice=f"Perbaikan #{improvement_id} dibatalkan.")


@app.post("/vault/{entry_id}/delete", response_class=HTMLResponse)
async def vault_delete(request: Request, entry_id: str):
    if r := guard(request):
        return r
    try:
        await core("DELETE", f"/admin/vault/{entry_id}")
    except CoreError as e:
        return await render(request, "password", errors=[str(e)])
    return await render(request, "password", notice="Login dihapus dari brankas.")


@app.post("/devices", response_class=HTMLResponse)
async def device_create(request: Request, name: str = Form(...), scope: str = Form("owner")):
    if r := guard(request):
        return r
    try:
        d = await core("POST", "/admin/devices", json={"name": name, "scope": scope if scope in ("owner", "basic") else "basic"})
    except CoreError as e:
        return await render(request, "devices", errors=[str(e)])
    return await render(request, "devices", new_device=d)


@app.post("/devices/{device_id}/revoke", response_class=HTMLResponse)
async def device_revoke(request: Request, device_id: str):
    if r := guard(request):
        return r
    try:
        await core("DELETE", f"/admin/devices/{device_id}")
    except CoreError as e:
        return await render(request, "devices", errors=[str(e)])
    return await render(request, "devices", notice="Token perangkat dicabut.")


@app.post("/settings", response_class=HTMLResponse)
async def save_settings(request: Request):
    if r := guard(request):
        return r
    form = await request.form()
    changes, errors = {}, []
    current = ENV.read()
    for key, label, secret, pattern, _ in SETTINGS:
        if key not in form:
            continue
        value = str(form[key]).strip()
        if secret and not value:
            continue  # blank secret field = keep current value
        if not secret and value == current.get(key, ""):
            continue
        if value and not re.match(pattern, value):
            errors.append(f"{label}: format tidak valid")
            continue
        changes[key] = value
    if errors:
        return await render(request, "settings", errors=errors)
    if changes:
        ENV.update(changes)
        msg = f"Disimpan: {', '.join(changes)}. Layanan terkait di-restart otomatis (±30 detik)."
    else:
        msg = "Tidak ada perubahan."
    return await render(request, "settings", notice=msg)


@app.post("/password", response_class=HTMLResponse)
async def change_password(request: Request, current: str = Form(...), new: str = Form(...)):
    if r := guard(request):
        return r
    if not verify_password(current, ENV.read()["ADMIN_PASSWORD_HASH"]):
        return await render(request, "settings", errors=["Password lama salah."])
    if len(new) < 12:
        return await render(request, "settings", errors=["Password baru minimal 12 karakter."])
    ENV.update({"ADMIN_PASSWORD_HASH": hash_password(new)})
    return RedirectResponse("/login", status_code=303)  # old session is now invalid


@app.post("/chat", response_class=HTMLResponse)
async def chat(request: Request, message: str = Form(...)):
    if r := guard(request):
        return r
    try:
        d = await core("POST", "/admin/chat", json={"message": message})
        reply = f"[{d['route']}] {d['reply']}"
    except CoreError as e:
        reply = f"[error] {e}"
    return await render(request, "dashboard", chat_message=message, chat_reply=reply)


@app.get("/releases/{name}")
async def download_release(request: Request, name: str):
    """APK download for the owner (session required; never a public link)."""
    if not authed(request):
        return RedirectResponse("/login", status_code=303)
    if not APK_NAME.match(name) or name not in {r["file"] for r in load_releases()}:
        return HTMLResponse("Not found", status_code=404)
    return FileResponse(RELEASES / name, media_type="application/vnd.android.package-archive", filename=name)


@app.get("/docs/{doc_id}")
async def download_document(request: Request, doc_id: str):
    if not authed(request):
        return RedirectResponse("/login", status_code=303)
    token = ENV.read().get("CORE_ADMIN_TOKEN", "")
    async with httpx.AsyncClient(base_url=CORE, timeout=60, headers={"X-Admin-Token": token}) as c:
        r = await c.get(f"/admin/documents/{doc_id}")
    if r.status_code != 200:
        return HTMLResponse("Not found", status_code=404)
    from fastapi.responses import Response
    return Response(r.content, media_type=r.headers.get("content-type"),
                    headers={"Content-Disposition": r.headers.get("content-disposition", "attachment")})


# ---------- internal API for jarvis-core (the owner's phone console goes through core) ----------

def _internal(request: Request) -> bool:
    """Only jarvis-core, directly on jarvis-network: the public proxy always adds X-Forwarded-For."""
    import hmac
    if "x-forwarded-for" in request.headers or "x-real-ip" in request.headers:
        return False
    token = ENV.read().get("CORE_ADMIN_TOKEN", "")
    return bool(token) and hmac.compare_digest(request.headers.get("x-admin-token", ""), token)


@app.get("/internal/settings")
async def internal_settings(request: Request):
    if not _internal(request):
        return HTMLResponse("Not found", status_code=404)
    env = ENV.read()
    return {"fields": [{"key": k, "label": label, "secret": secret, "help": help_, "is_set": bool(env.get(k)),
                        "value": "" if secret else env.get(k, "")} for k, label, secret, _, help_ in SETTINGS],
            "apply_log": apply_log_tail()}


@app.post("/internal/settings")
async def internal_settings_save(request: Request):
    if not _internal(request):
        return HTMLResponse("Not found", status_code=404)
    body = await request.json()
    changes, errors = {}, []
    for key, label, secret, pattern, _ in SETTINGS:
        if key not in body:
            continue
        value = str(body[key]).strip()
        if secret and not value:
            continue
        if value and not re.match(pattern, value):
            errors.append(f"{label}: format tidak valid")
            continue
        changes[key] = value
    if errors:
        return {"saved": [], "errors": errors}
    if changes:
        ENV.update(changes)
    return {"saved": sorted(changes), "errors": []}


@app.post("/internal/admin-password")
async def internal_admin_password(request: Request):
    """From the owner's phone (owner device, fingerprint in the app): same rules as the web form."""
    if not _internal(request):
        return HTMLResponse("Not found", status_code=404)
    body = await request.json()
    if not verify_password(str(body.get("current") or ""), ENV.read()["ADMIN_PASSWORD_HASH"]):
        return JSONResponse({"error": "Password lama salah."}, status_code=400)
    new = str(body.get("new") or "")
    if len(new) < 12:
        return JSONResponse({"error": "Password baru minimal 12 karakter."}, status_code=400)
    ENV.update({"ADMIN_PASSWORD_HASH": hash_password(new)})
    return {"changed": True}


PAIR_THROTTLE = Throttle(limit=10, window=3600)  # all phones together: a brute-force guard behind core's per-IP one


@app.post("/internal/check-admin-password")
async def internal_check_admin_password(request: Request):
    """Core asks before pairing a phone with the admin password (ADR-037). Never logged, never stored."""
    if not _internal(request):
        return HTMLResponse("Not found", status_code=404)
    if PAIR_THROTTLE.blocked("pair"):
        return JSONResponse({"error": "Terlalu banyak percobaan. Coba lagi dalam 1 jam."}, status_code=429)
    body = await request.json()
    if not verify_password(str(body.get("password") or ""), ENV.read()["ADMIN_PASSWORD_HASH"]):
        PAIR_THROTTLE.fail("pair")
        return JSONResponse({"error": "Password admin salah."}, status_code=401)
    return {"ok": True}


@app.get("/internal/releases")
async def internal_releases(request: Request):
    if not _internal(request):
        return HTMLResponse("Not found", status_code=404)
    return {"releases": load_releases()}


@app.get("/internal/releases/{name}")
async def internal_release_file(request: Request, name: str):
    if not _internal(request) or not APK_NAME.match(name) or name not in {r["file"] for r in load_releases()}:
        return HTMLResponse("Not found", status_code=404)
    return FileResponse(RELEASES / name, media_type="application/vnd.android.package-archive", filename=name)


@app.get("/healthz")
async def healthz():
    return {"ok": True}
