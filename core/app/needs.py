""""Butuh kamu" (ADR-087): everything that waits for the owner, in one list — approvals, a run on his phone, a pick between options a
project asked for, a question a worker asked. Each kind keeps its own rules (the admin password for the phone, admin-only kinds that
the phone cannot approve); this module only gathers them and passes the owner's answer to the right place."""

from . import approvals, phone_agent, project_flow, questions

KIND_ICON = {"approval": "shield", "phone": "car", "choice": "list", "question": "chat"}
APPROVAL_LABEL = {"mail_send": "Kirim email", "calendar_create": "Buat acara kalender", "n8n_activate_workflow": "Aktifkan workflow",
                  "setting_change": "Ubah pengaturan", "task_budget": "Tambah anggaran tugas", "skill_publish": "Terbitkan skill"}


def approval_item(a: dict) -> dict:
    detail = a.get("detail") or {}
    sub = detail.get("summary") or detail.get("to") or detail.get("reason") or ""
    if isinstance(sub, list):
        sub = ", ".join(map(str, sub))
    return {"kind": "approval", "id": a["id"], "title": a["title"], "sub": f"{APPROVAL_LABEL.get(a['kind'], a['kind'])} · {str(sub)[:120]}".strip(" ·"),
            "icon": "mail" if a["kind"].startswith("mail") else KIND_ICON["approval"], "cta": "Setujui", "risk": a.get("risk"),
            "admin_only": a["kind"] in approvals.ADMIN_ONLY, "password": False, "detail": detail, "approval_kind": a["kind"],
            "at": a.get("created_at")}


def phone_item(r: dict) -> dict:
    card = phone_agent.approval_card(r)
    return {"kind": "phone", "id": r["id"], "title": f"{card['label']}: {r['goal'][:90]}", "sub": f"Operasi HP · dari {r.get('requested_by') or 'obrolan'}",
            "icon": "car", "cta": "Tinjau & setujui", "password": True, "app": r["app"], "goal": r["goal"],
            "expires_in_s": card["expires_in_s"], "at": r.get("created_at")}


def choice_item(c: dict) -> dict:
    return {"kind": "choice", "id": c["id"], "title": c["title"], "sub": c["prompt"][:140], "icon": "list", "cta": "Pilih",
            "password": False, "options": c["options"], "expires_in_s": c["expires_in_s"]}


def question_item(q: dict) -> dict:
    return {"kind": "question", "id": q["id"], "title": q["question"][:140], "sub": f"Ditanya oleh misi: {q.get('title') or '#' + str(q.get('task_id'))}",
            "icon": "chat", "cta": "Jawab", "password": False, "task_id": q.get("task_id")}


async def listing() -> list[dict]:
    out: list[dict] = []
    out += [phone_item(r) for r in await phone_agent.pending()]
    out += [choice_item(c) for c in await project_flow.open_choices()]
    out += [question_item(q) for q in await questions.open_questions()]
    out += [approval_item(a) for a in await approvals.list_("awaiting_approval")]
    return out


class NeedError(RuntimeError):
    pass


async def answer(kind: str, item_id: int, actor: str, approve: bool | None = None, option: int | None = None, text: str = "") -> dict:
    """The owner's answer to one item. The phone kind is approved in appapi (it checks the admin password first)."""
    if kind == "approval":
        if approve is None:
            raise NeedError("setujui atau tolak?")
        try:
            return {"ok": True, "approval": await approvals.decide(item_id, approve, actor)}
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
    if kind == "question":
        if not text.strip():
            raise NeedError("jawabannya kosong")
        return {"ok": await questions.answer(item_id, text, actor)}
    raise NeedError(f"jenis tidak dikenal: {kind}")
