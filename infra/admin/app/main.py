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
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
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

MODEL = r"^[a-z0-9._-]+/[A-Za-z0-9._:-]+$"
# key, label, is_secret, validation pattern, help text
SETTINGS = [
    ("OPENROUTER_API_KEY", "OpenRouter API key", True, r"^sk-or-[A-Za-z0-9_-]{10,}$",
     "Dari openrouter.ai/keys."),
    ("JARVIS_CHAT_MODEL", "Model agen utama (ngobrol)", False, MODEL,
     "Harus cepat, mendukung tool calling (dan gambar untuk share screen). Default: anthropic/claude-haiku-5.5."),
    ("JARVIS_DEFAULT_MODEL", "Model worker (Hermes)", False, MODEL,
     "Dipakai worker yang mengerjakan tugas. Harus mendukung tool calling."),
    ("JARVIS_EXPERT_MODEL", "Model ahli", False, MODEL,
     "Dipakai worker hanya saat ia memutuskan butuh kemampuan lebih (delegasi)."),
    ("WORKER_CONCURRENCY", "Worker berjalan bersamaan", False, r"^([1-9]|1[0-9]|20)$",
     "Jumlah tugas tak terbatas (antre); ini berapa yang dikerjakan sekaligus (1–20)."),
    ("JARVIS_CODER_MODEL", "Model coding / n8n JSON", False, MODEL,
     "Membuat JSON workflow n8n."),
    ("N8N_API_KEY", "n8n API key", True, r"^[A-Za-z0-9._-]{20,}$",
     "Buat di https://flow1.cosger.online → Settings → n8n API."),
    ("DEEPGRAM_API_KEY", "Deepgram API key", True, r"^[A-Za-z0-9]{20,}$",
     "Untuk voice di APK. APK hanya menerima token berumur pendek dari server."),
    ("DEEPGRAM_MODEL", "Model pengenalan suara", False, r"^[a-z0-9-]+$",
     "nova-2 terbukti paling akurat untuk bahasa Indonesia (WER ±12%)."),
    ("DEEPGRAM_KEYWORDS", "Kosakata khusus suara", False, r"^[A-Za-z0-9 ,._-]{0,500}$",
     "Nama/istilah yang sering kamu ucapkan, pisahkan dengan koma (mis. nama proyek, orang, tempat)."),
]
TABS = [("dashboard", "Dasbor"), ("approvals", "Persetujuan"), ("memory", "Memori"),
        ("devices", "Perangkat"), ("app", "Aplikasi"), ("audit", "Audit"), ("settings", "Pengaturan")]
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
    return [r for r in releases if APK_NAME.match(r.get("file", ""))]


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


@app.post("/devices", response_class=HTMLResponse)
async def device_create(request: Request, name: str = Form(...)):
    if r := guard(request):
        return r
    try:
        d = await core("POST", "/admin/devices", json={"name": name})
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


@app.get("/healthz")
async def healthz():
    return {"ok": True}
