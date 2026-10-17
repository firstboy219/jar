"""JARVIS Web Admin (FS-105, first slice): settings, service status, test chat.

Settings are written to the stack's .env; a host systemd path unit
(infra/systemd/jarvis-apply.*) notices the change and runs `docker compose up -d`.
This container has no Docker socket.
"""

import os
import re
from pathlib import Path

import httpx
from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .auth import Throttle, check_session, hash_password, make_session, verify_password
from .envfile import EnvFile

ENV = EnvFile(os.getenv("JARVIS_ENV_FILE", "/config/.env"))
APPLY_LOG = Path(os.getenv("JARVIS_APPLY_LOG", "/status/apply.log"))
PUBLIC_ORIGIN = os.getenv("ADMIN_PUBLIC_ORIGIN", "")
COOKIE = "jarvis_admin"

HERMES = "http://jarvis-brain:8642"
N8N = "http://jarvis-executor:5678"
QDRANT = "http://jarvis-memory:6333"

# key, label, is_secret, validation pattern, help text
SETTINGS = [
    ("OPENROUTER_API_KEY", "OpenRouter API key", True, r"^sk-or-[A-Za-z0-9_-]{10,}$",
     "Dari openrouter.ai/keys. Dipakai Hermes untuk memanggil model."),
    ("JARVIS_DEFAULT_MODEL", "Model utama", False, r"^[a-z0-9._-]+/[A-Za-z0-9._:-]+$",
     "Harus mendukung tool calling. Contoh: deepseek/deepseek-v4-flash"),
    ("JARVIS_CODER_MODEL", "Model coding / n8n JSON", False, r"^[a-z0-9._-]+/[A-Za-z0-9._:-]+$",
     "Contoh: qwen/qwen3-coder-next"),
    ("N8N_API_KEY", "n8n API key", True, r"^[A-Za-z0-9._-]{20,}$",
     "Buat di n8n: Settings → n8n API."),
]

app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
app.mount("/static", StaticFiles(directory=Path(__file__).parent / "static"), name="static")
templates = Jinja2Templates(directory=Path(__file__).parent / "templates")
throttle = Throttle()


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


async def service_status(env: dict[str, str]) -> list[dict]:
    checks = []
    async with httpx.AsyncClient(timeout=5) as client:
        async def probe(name, url, headers=None, ok=200):
            try:
                r = await client.get(url, headers=headers or {})
                checks.append({"name": name, "ok": r.status_code == ok, "detail": f"HTTP {r.status_code}"})
            except httpx.HTTPError as e:
                checks.append({"name": name, "ok": False, "detail": type(e).__name__})

        await probe("Hermes Agent", f"{HERMES}/v1/models",
                    {"Authorization": f"Bearer {env.get('HERMES_API_KEY', '')}"})
        await probe("n8n", f"{N8N}/healthz")
        if env.get("N8N_API_KEY"):
            await probe("n8n API key", f"{N8N}/api/v1/workflows?limit=1",
                        {"X-N8N-API-KEY": env["N8N_API_KEY"]})
        else:
            checks.append({"name": "n8n API key", "ok": False, "detail": "belum diisi"})
        await probe("Qdrant", f"{QDRANT}/collections", {"api-key": env.get("QDRANT_API_KEY", "")})
    checks.append({"name": "OpenRouter key", "ok": bool(env.get("OPENROUTER_API_KEY")),
                   "detail": "terisi" if env.get("OPENROUTER_API_KEY") else "belum diisi"})
    return checks


def apply_log_tail(lines: int = 8) -> str:
    try:
        return "\n".join(APPLY_LOG.read_text().splitlines()[-lines:])
    except OSError:
        return ""


async def render_dashboard(request: Request, **extra) -> HTMLResponse:
    env = ENV.read()
    fields = [
        {"key": k, "label": label, "secret": secret, "help": help_,
         "display": mask(env.get(k, "")) if secret else env.get(k, "")}
        for k, label, secret, _, help_ in SETTINGS
    ]
    return templates.TemplateResponse(request, "dashboard.html", {
        "fields": fields,
        "status": await service_status(env),
        "apply_log": apply_log_tail(),
        "backend_url": f"https://{env.get('BACKEND_DOMAIN', '')}",
        **extra,
    })


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    if not authed(request):
        return RedirectResponse("/login", status_code=303)
    return await render_dashboard(request)


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


@app.post("/settings", response_class=HTMLResponse)
async def save_settings(request: Request):
    if not authed(request) or not same_origin(request):
        return RedirectResponse("/login", status_code=303)
    form = await request.form()
    changes, errors = {}, []
    for key, label, secret, pattern, _ in SETTINGS:
        if key not in form:
            continue
        value = str(form[key]).strip()
        if secret and not value:
            continue  # blank secret field = keep current value
        if not secret and value == ENV.read().get(key, ""):
            continue
        if value and not re.match(pattern, value):
            errors.append(f"{label}: format tidak valid")
            continue
        changes[key] = value
    if errors:
        return await render_dashboard(request, errors=errors)
    if changes:
        ENV.update(changes)
        msg = f"Disimpan: {', '.join(changes)}. Layanan terkait di-restart otomatis (±30 detik)."
    else:
        msg = "Tidak ada perubahan."
    return await render_dashboard(request, notice=msg)


@app.post("/password", response_class=HTMLResponse)
async def change_password(request: Request, current: str = Form(...), new: str = Form(...)):
    if not authed(request) or not same_origin(request):
        return RedirectResponse("/login", status_code=303)
    if not verify_password(current, ENV.read()["ADMIN_PASSWORD_HASH"]):
        return await render_dashboard(request, errors=["Password lama salah."])
    if len(new) < 12:
        return await render_dashboard(request, errors=["Password baru minimal 12 karakter."])
    ENV.update({"ADMIN_PASSWORD_HASH": hash_password(new)})
    return RedirectResponse("/login", status_code=303)  # old session is now invalid


@app.post("/chat", response_class=HTMLResponse)
async def chat(request: Request, message: str = Form(...)):
    if not authed(request) or not same_origin(request):
        return RedirectResponse("/login", status_code=303)
    env = ENV.read()
    try:
        async with httpx.AsyncClient(timeout=180) as client:
            r = await client.post(
                f"{HERMES}/v1/chat/completions",
                headers={"Authorization": f"Bearer {env['HERMES_API_KEY']}"},
                json={"model": "hermes-agent", "messages": [{"role": "user", "content": message}]},
            )
        if r.status_code == 200:
            reply = r.json()["choices"][0]["message"]["content"]
        else:
            reply = f"[error HTTP {r.status_code}] {r.text[:500]}"
    except httpx.HTTPError as e:
        reply = f"[error] {type(e).__name__}"
    return await render_dashboard(request, chat_message=message, chat_reply=reply)


@app.get("/healthz")
async def healthz():
    return {"ok": True}
