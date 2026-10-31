""""Butuh kamu" (ADR-087): everything that waits for the owner, in one list — approvals, a run on his phone, a pick between options a
project asked for, a question a worker asked. Each kind keeps its own rules (the admin password for the phone, admin-only kinds that
the phone cannot approve); this module only gathers them and passes the owner's answer to the right place."""

import re
from collections import Counter

from . import approvals, db, phone_agent, project_flow, questions

KIND_ICON = {"approval": "shield", "phone": "car", "choice": "list", "question": "chat", "lagu": "music"}
APPROVAL_LABEL = {"mail_send": "Kirim email", "calendar_create": "Buat acara kalender", "n8n_activate_workflow": "Aktifkan workflow",
                  "setting_change": "Ubah pengaturan", "task_budget": "Tambah anggaran tugas", "skill_publish": "Terbitkan skill"}


def approval_item(a: dict) -> dict:
    detail = a.get("detail") or {}
    sub = detail.get("summary") or detail.get("to") or detail.get("reason") or ""
    if isinstance(sub, list):
        sub = ", ".join(map(str, sub))
    return {"kind": "approval", "id": a["id"], "title": a["title"], "sub": f"{APPROVAL_LABEL.get(a['kind'], a['kind'])} · {str(sub)[:120]}".strip(" ·"),
            "icon": "mail" if a["kind"].startswith("mail") else KIND_ICON["approval"], "cta": "Setujui", "risk": a.get("risk"),
            "password": True, "detail": detail, "approval_kind": a["kind"],
            "at": a.get("created_at")}


def route_of(goal: str) -> dict:
    """'Pesan GoRide dari Stasiun Bogor ke Kantor Sudirman' → {'dari': …, 'ke': …}. Pure."""
    m = re.search(r"\bdari\s+(.+?)\s+(?:ke|menuju)\s+(.+?)(?:[.,;]|\s+(?:bayar|pakai|dengan|jam)\b|$)", goal or "", re.I)
    return {"dari": m.group(1).strip()[:80], "ke": m.group(2).strip()[:80]} if m else {}


def rules_of(app: str) -> list[str]:
    """What JARVIS will and will not do in that app — the same rules the phone agent enforces. Pure."""
    label = phone_agent.APPS.get(app, {}).get("label", app)
    if sites := phone_agent.APPS.get(app, {}).get("sites"):
        return [f"Hanya situs {', '.join(sites)} di browser HP", "Tidak mengetik kata sandi; berhenti di halaman masuk akun & pembayaran — kamu yang lanjutkan",
                "Tanpa top-up, transfer, atau ubah akun"]
    out = [f"Hanya {label}" + (" (dan layar bayar GoPay)" if "com.gojek.gopay" in phone_agent.APPS.get(app, {}).get("packages", []) and app != "gojek" else ""),
           "Tanpa top-up, transfer, pinjaman, atau ubah akun", "Berhenti di layar PIN/OTP — kamu yang mengetik",
           "Periksa harga & detail sebelum menekan tombol terakhir; tanya bila jauh dari perkiraan"]
    return out


def phone_item(r: dict) -> dict:
    card = phone_agent.approval_card(r)
    return {"kind": "phone", "id": r["id"], "title": f"{card['label']}: {r['goal'][:90]}", "sub": f"Operasi HP · dari {r.get('requested_by') or 'obrolan'}",
            "icon": "car", "cta": "Tinjau & setujui", "password": True, "app": r["app"], "goal": r["goal"], "route": route_of(r["goal"]),
            "rules": rules_of(r["app"]), "expires_in_s": card["expires_in_s"], "at": r.get("created_at")}


async def _routine_info(app: str, goal: str) -> dict | None:
    """The learned routine this run would replay (no AI), with its track record — matched by its keywords only (no model call here)."""
    from .routines import keys_match
    for r in await db.pool().fetch("SELECT name, keys, runs, ok_runs, steps, auto_steps FROM routines WHERE app = $1 AND status = 'active' ORDER BY ok_runs DESC", app):
        if keys_match(r["keys"], goal):
            return {"name": r["name"], "runs": r["runs"], "ok": r["ok_runs"], "steps": len(r["steps"] or [])}
    return None


def fare_of(goal: str, trip: dict | None) -> int | None:
    """What a Gojek ride in this run should cost: the price written in the goal, else the trip plan's estimate for the ride/car. Pure."""
    import re
    m = re.search(r"Rp\.?\s?([\d.]{4,})", goal or "")
    if m:
        return int(m.group(1).replace(".", ""))
    if not trip:
        return None
    chosen, plan = trip.get("chosen") or {}, trip.get("plan") or {}
    if re.search(r"gocar|go-car|mobil", goal or "", re.I):
        return (plan.get("car") or {}).get("cost")
    return ((chosen.get("ride") or {}).get("cost")) if re.search(r"goride|go-ride|ojek|motor", goal or "", re.I) else None


async def _fare(app: str, goal: str) -> int | None:
    if app != "gojek":
        return None
    row = await db.pool().fetchrow("SELECT plan, chosen FROM commute_trips WHERE created_at > now() - interval '6 hours' ORDER BY id DESC LIMIT 1")
    return fare_of(goal, dict(row) if row else None)


def recommend(options: list[dict], past: list[dict]) -> int | None:
    """The option he usually picks (the same label, or the same time, most often before). Pure."""
    if not past:
        return None
    labels = Counter((p.get("label") or "").strip().lower() for p in past)
    times = Counter((p.get("waktu") or "").strip() for p in past if p.get("waktu"))
    best, score = None, 0
    for o in options:
        sc = 2 * labels.get((o.get("label") or "").strip().lower(), 0) + times.get((o.get("waktu") or "").strip(), 0)
        if sc > score:
            best, score = o["i"], sc
    return best


def choice_item(c: dict) -> dict:
    return {"kind": "choice", "id": c["id"], "title": c["title"], "sub": c["prompt"][:140], "icon": "list", "cta": "Pilih",
            "password": False, "options": c["options"], "expires_in_s": c["expires_in_s"]}


WEB_LABEL = {"masuk": ("Masuk akun di situs", "lock", "Buka di HP"), "verifikasi": ("Verifikasi di situs", "shield", "Buka di HP"),
             "bayar": ("Bayar sendiri", "wallet", "Buka di HP"), "macet": ("JARVIS macet", "alert", "Bantu di HP"),
             "pilih": ("Pilih", "list", "Pilih"), "tanya": ("Pertanyaan", "chat", "Jawab"), "tinjau": ("Periksa sebelum dikirim", "check", "Kirim")}


def web_item(w: dict) -> dict:
    """A web task waiting for the owner (ADR-087 batch I): sign in / verify / pay / help on the page, pick, answer, or review before sending."""
    label, ic, cta = WEB_LABEL[w["kind"]]
    d = w.get("detail") or {}
    return {"kind": "web", "id": w["id"], "wait": w["kind"], "title": w["title"], "sub": f"{label} · {w.get('site') or ''} · {(w.get('goal') or '')[:90]}",
            "icon": ic, "cta": cta, "password": w["kind"] == "tinjau" and bool(d.get("password")), "session": d.get("session") if w["kind"] in ("masuk", "verifikasi", "bayar", "macet") else None,
            "options": [{"label": o} for o in d.get("options") or []], "cards": d.get("cards") or [], "rows": d.get("rows") or [], "summary": d.get("summary") or d.get("why") or "",
            "button": d.get("button") or "", "missing": d.get("missing") or [], "url": d.get("url") or "", "at": w.get("created_at")}


def music_item(p: dict) -> dict:
    """Songs he asked for, to tick (owner 2026-10-31): the ticked ones become MP3s."""
    return {"kind": "lagu", "id": p["id"], "title": f"Pilih lagu: {p['query']}"[:140], "sub": f"{len(p['options'])} hasil YouTube · centang yang mau diputar",
            "icon": "music", "cta": "Proses", "password": False, "options": p["options"]}


def question_item(q: dict) -> dict:
    text = q["question"]
    title = text if len(text) <= 160 else text[:157].rsplit(" ", 1)[0] + "…"
    sub = f"Ditanya oleh misi: {q['title']}" if q.get("title") else (f"Ditanya oleh misi #{q['task_id']}" if q.get("task_id") else "Ditanya oleh pekerja JARVIS")
    return {"kind": "question", "id": q["id"], "title": title, "text": text, "sub": sub, "icon": "chat", "cta": "Jawab", "password": False,
            "task_id": q.get("task_id"), "takeover": bool(TAKEOVER.search(text))}


# a worker asking him to do something on its browser (a robot check, a sign-in): he acts on the page, he does not type an answer
TAKEOVER = re.compile(r"verifikasi|captcha|cloudflare|just a moment|bukan robot|intervensi|ambil alih|login|masuk akun|kode otp", re.I)


async def listing() -> list[dict]:
    out: list[dict] = []
    for r in await phone_agent.pending():
        it = phone_item(r)
        it["routine"] = await _routine_info(r["app"], r["goal"])
        it["estimate"] = await _fare(r["app"], r["goal"])
        out.append(it)
    for c in await project_flow.open_choices():
        it = choice_item(c)
        past = [x["answer"] for x in await db.pool().fetch(
            "SELECT answer FROM owner_choices WHERE project_id = $1 AND status = 'answered' AND answer IS NOT NULL ORDER BY id DESC LIMIT 12", c["project_id"])]
        it["recommended"] = recommend(it["options"], [a if isinstance(a, dict) else {} for a in past])
        out.append(it)
    out += [question_item(q) for q in await questions.open_questions()]
    from . import musik
    if pick := await musik.open_pick():
        out.append(music_item(pick))
    from . import webagent
    out += [web_item(w) for w in await webagent.open_waits()]
    out += [approval_item(a) for a in await approvals.list_("awaiting_approval")]
    return out


class NeedError(RuntimeError):
    pass


async def answer(kind: str, item_id: int, actor: str, approve: bool | None = None, option: int | None = None, text: str = "",
                 channel: str = "device") -> dict:
    """The owner's answer to one item. The phone kind is approved in appapi (it checks the admin password first); an approval
    approved from the app comes with channel "phone_lock" once appapi checked the phone's lock."""
    if kind == "approval":
        if approve is None:
            raise NeedError("setujui atau tolak?")
        try:
            return {"ok": True, "approval": await approvals.decide(item_id, approve, actor, channel=channel)}
        except approvals.ApprovalError as e:
            raise NeedError(str(e))
    if kind == "phone":
        if approve:
            raise NeedError("operasi HP disetujui dengan password admin")
        return {"ok": await phone_agent.reject(item_id, actor)}
    if kind == "choice":
        if option is None:
            raise NeedError("pilih salah satu opsi")
        try:
            return {"ok": True, "result": await project_flow.answer(item_id, option, actor)}
        except project_flow.FlowError as e:
            raise NeedError(str(e))
    if kind == "lagu":   # "Batal" on the list (ticking goes through /music/picks)
        from . import musik
        return {"ok": await musik.dismiss(item_id)}
    if kind == "question":
        if not text.strip():
            raise NeedError("jawabannya kosong")
        return {"ok": await questions.answer(item_id, text, actor)}
    if kind == "web":
        from . import webagent
        try:
            return await webagent.answer_wait(item_id, actor, approve=approve, option=option, text=text)
        except webagent.WebError as e:
            raise NeedError(str(e))
    raise NeedError(f"jenis tidak dikenal: {kind}")
