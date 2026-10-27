"""Self-improvement (ADR-026, enabled by the owner 2026-10-21): JARVIS changes its own code ONLY to do what
the owner asks faster, cheaper or more reliably, or to add a MINOR missing ability — every change tested,
every deploy approved by the owner, every failure rolled back. Big features and anything touching security,
permissions, approvals, secrets, the composition or budgets are out of scope (the runner refuses those files).

Flow:
  Hermes edits a branch `jarvis/<topic>` in its workspace (/opt/data/workspace/jar, a clone of the repo)
  → propose()   row 'testing' + request file for the host runner (infra/scripts/self-dev.sh)
  → the runner tests it in throwaway containers → result file → poll():
       'test_failed'        Hermes reads the log (check_code_change), fixes, proposes again
       'awaiting_approval'  high-risk approval (fingerprint on the phone) + spoken report
  → owner approves → request 'deploy' → the runner merges into main, rebuilds only the services that
    changed (and publishes a new APK if android/ changed), health-checks, pushes to GitHub — or rolls back
  → poll() → 'deployed' / 'rolled_back' / 'deploy_failed' → spoken report.
jarvis-core never runs git or docker itself; the runner on the host does, and refuses any change to
secrets, to its own script, to systemd units, or to this approval gate.

Blueprint v4 Fase 0 (ADR-047) — the control point is the admin page:
  * code changes are APPROVED only there (approvals.ADMIN_ONLY); the request shows what the runner found in the real
    diff (files, lines, tier, test summary); JARVIS' own "why" is labelled as unverified;
  * a pause switch at the admin page stops every new self-change proposal at once;
  * T2 (Android code, larger rebuilds) needs a design approved at the admin page first, and only once the owner has
    switched T2 on there (decision K2); display changes stay locked until screenshots exist (Phase 4).
"""

import asyncio
import json
import logging
import os
import re
from pathlib import Path

from . import approvals, audit, db, reports

log = logging.getLogger("jarvis-core.dev")
ROOT = Path(os.getenv("DEV_DIR", "/data/dev"))
BRANCH = re.compile(r"^jarvis/[a-z0-9][a-z0-9-]{2,60}$")


CONTROL_KEY = "selfdev:control"


class DevError(ValueError):
    pass


async def control() -> dict:
    """{"paused", "t2_enabled", "by", "at"} — set only from the admin page (core endpoint refuses the app console)."""
    v = await db.pool().fetchval("SELECT value FROM settings_kv WHERE key = $1", CONTROL_KEY)
    v = v if isinstance(v, dict) else {}
    return {"paused": bool(v.get("paused")), "t2_enabled": bool(v.get("t2_enabled")), "by": v.get("by"), "at": v.get("at")}


async def set_control(actor: str, *, paused: bool | None = None, t2_enabled: bool | None = None) -> dict:
    from datetime import datetime, timezone
    cur = await control()
    new = {"paused": cur["paused"] if paused is None else bool(paused),
           "t2_enabled": cur["t2_enabled"] if t2_enabled is None else bool(t2_enabled),
           "by": actor, "at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    await db.pool().execute(
        """INSERT INTO settings_kv (key, value) VALUES ($1, $2) ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value""",
        CONTROL_KEY, new)
    await audit.record(actor, "selfdev.control", None, paused=new["paused"], t2_enabled=new["t2_enabled"])
    return new


async def ensure_not_paused() -> None:
    if (await control())["paused"]:
        raise DevError("perubahan diri sedang DIJEDA oleh pemilik di halaman admin — tidak ada usulan baru yang diterima")


async def propose_design(title: str, plan: str, scope: list[str], task_id: int | None = None) -> dict:
    """T2: describe the larger change BEFORE making it; the owner approves the design at the admin page."""
    await ensure_not_paused()
    if not (await control())["t2_enabled"]:
        raise DevError("perubahan tingkat T2 (APK, modul besar) belum dibuka pemilik di halaman admin")
    from . import selfdev_policy
    if blocked := [s for s in scope if selfdev_policy.FORBIDDEN.match(s.strip())]:
        raise DevError("rancangan menyentuh zona terlindungi (hanya manusia): " + ", ".join(blocked[:8]))
    if len(plan.strip()) < 80:
        raise DevError("rancangan terlalu singkat: jelaskan masalah, perubahan per bagian, risiko, cara menguji, cara membatalkan")
    row = await db.pool().fetchrow(
        "INSERT INTO dev_designs (title, plan, scope, task_id) VALUES ($1, $2, $3, $4) RETURNING id",
        title.strip()[:200], plan.strip()[:8000], [s.strip()[:200] for s in scope][:40], task_id)
    display = [s for s in scope if selfdev_policy.DISPLAY.match(s.strip())]
    a = await approvals.create(
        "code_design", f"Rancangan perubahan T2: {title.strip()[:120]}",
        {"design_id": row["id"], "plan": plan.strip()[:6000], "scope": scope[:40],
         "catatan": "Setujui RANCANGAN dulu; hasilnya nanti diuji dan diminta persetujuan lagi di sini."
                    + (" Bagian tampilan masih terkunci sampai tangkapan layar tersedia." if display else "")},
        "hermes", "high", idempotency_key=f"design:{row['id']}")
    await db.pool().execute("UPDATE dev_designs SET approval_id = $2 WHERE id = $1", row["id"], a["id"])
    await audit.record("hermes", "dev.design_proposed", f"design:{row['id']}", title=title[:200])
    return {"design_id": row["id"], "status": "awaiting_approval", "approval_id": a["id"]}


async def on_design_approved(detail: dict) -> dict:
    await db.pool().execute("UPDATE dev_designs SET status = 'approved', updated_at = now() WHERE id = $1 AND status = 'awaiting_approval'",
                            int(detail["design_id"]))
    return {"design": detail["design_id"], "status": "approved"}


async def get_design(design_id: int) -> dict | None:
    await db.pool().execute(  # the owner said no at the admin page
        """UPDATE dev_designs d SET status = 'rejected', updated_at = now() FROM approvals a
           WHERE a.id = d.approval_id AND d.status = 'awaiting_approval' AND a.status IN ('rejected', 'expired')""")
    row = await db.pool().fetchrow("SELECT * FROM dev_designs WHERE id = $1", design_id)
    return dict(row) if row else None


def _write_request(change_id: int, action: str, **extra) -> None:
    (ROOT / "requests").mkdir(parents=True, exist_ok=True)
    tmp = ROOT / "requests" / f".{change_id}-{action}.tmp"
    tmp.write_text(json.dumps({"id": change_id, "action": action, **extra}))
    tmp.rename(ROOT / "requests" / f"{change_id}-{action}.json")  # the runner watches for *.json


async def sync_mirror(wait_s: float = 40.0) -> bool:
    """Make the runner refresh Hermes' read-only copy of main (it does that at the start of every run; the request itself is just
    moved aside). A worker that branches from a stale copy produces changes that conflict at deploy. True when it happened in time."""
    _write_request(0, "sync")
    path = ROOT / "requests" / "0-sync.json"
    waited = 0.0
    while waited < wait_s:
        if not path.exists():
            return True
        await asyncio.sleep(2)
        waited += 2
    return False


async def propose(branch: str, title: str, why: str, task_id: int | None = None, design_id: int | None = None) -> dict:
    await ensure_not_paused()
    max_tier = 1
    if design_id:
        design = await get_design(design_id)
        if not design or design["status"] not in ("approved", "used"):
            raise DevError("rancangan T2 itu belum disetujui pemilik di halaman admin")
        if not (await control())["t2_enabled"]:
            raise DevError("perubahan tingkat T2 sedang ditutup pemilik di halaman admin")
        max_tier = 2
    branch = branch.strip()
    if not BRANCH.match(branch):
        raise DevError("nama cabang harus 'jarvis/<topik>' (huruf kecil, angka, tanda minus)")
    busy = await db.pool().fetchrow(
        "SELECT id, status FROM dev_changes WHERE branch = $1 AND status IN ('testing', 'deploying') ORDER BY id DESC LIMIT 1",
        branch)
    if busy:
        return {"id": busy["id"], "status": busy["status"], "note": "cabang ini sedang diproses"}
    # a re-proposal supersedes an older one still waiting for approval
    await db.pool().execute(
        "UPDATE dev_changes SET status = 'rejected', updated_at = now() WHERE branch = $1 AND status = 'awaiting_approval'",
        branch)
    row = await db.pool().fetchrow(
        "INSERT INTO dev_changes (branch, title, why, task_id, design_id) VALUES ($1, $2, $3, $4, $5) RETURNING id, status",
        branch, title.strip()[:200] or branch, why.strip()[:4000], task_id, design_id)
    _write_request(row["id"], "test", branch=branch, max_tier=max_tier)
    await audit.record("hermes", "dev.proposed", f"dev:{row['id']}", branch=branch, title=title[:200])
    return dict(row) | {"note": "sedang diuji otomatis (±3–10 menit); cek dengan check_code_change"}


async def get(change_id: int) -> dict | None:
    row = await db.pool().fetchrow("SELECT * FROM dev_changes WHERE id = $1", change_id)
    return dict(row) if row else None


async def list_(limit: int = 30) -> list[dict]:
    rows = await db.pool().fetch(
        """SELECT id, branch, title, why, status, commit, files, diffstat, apk_version, approval_id, created_at, updated_at, tier, tests, design_id,
                  right(coalesce(test_log, ''), 1500) AS test_log, right(coalesce(deploy_log, ''), 1500) AS deploy_log
           FROM dev_changes ORDER BY id DESC LIMIT $1""", limit)
    return [dict(r) for r in rows]


async def on_approved(detail: dict) -> dict:
    """Approval executor: hand the tested commit to the runner for merge + deploy."""
    change = await get(int(detail["change_id"]))
    if not change or change["status"] != "awaiting_approval":
        raise DevError("perubahan ini tidak sedang menunggu persetujuan")
    await db.pool().execute("UPDATE dev_changes SET status = 'deploying', updated_at = now() WHERE id = $1", change["id"])
    _write_request(change["id"], "deploy", branch=change["branch"], commit=change["commit"])
    return {"deploying": change["id"]}


def approval_detail(cid: int, change: dict, res: dict, verdict: dict) -> dict:
    """The approval request, built from what the RUNNER measured; JARVIS' text is labelled as unverified. Pure."""
    return {"change_id": cid, "branch": change["branch"], "commit": res.get("commit"),
            "tingkat": f"T{verdict.get('tier') or 1}", "baris_berubah": verdict.get("changed_lines"),
            "file_dari_diff_nyata": (res.get("files") or verdict.get("files") or [])[:60],
            "hasil_tes_dari_penjalan": (res.get("tests") or "")[:300],
            "diffstat": (res.get("diffstat") or "")[:3000], "new_packages": (res.get("deps") or [])[:20],
            "design_id": change.get("design_id"),
            "alasan_dari_jarvis_tidak_diverifikasi": change["why"][:1500]}


async def poll() -> int:
    """Read runner results; returns how many were applied."""
    await db.pool().execute(  # the owner said no (or let it expire): nothing will be deployed
        """UPDATE dev_changes c SET status = 'rejected', updated_at = now() FROM approvals a
           WHERE a.id = c.approval_id AND c.status = 'awaiting_approval' AND a.status IN ('rejected', 'expired')""")
    done_dir = ROOT / "results"
    if not done_dir.is_dir():
        return 0
    n = 0
    for f in sorted(done_dir.glob("*.json")):
        try:
            res = json.loads(f.read_text())
        except (OSError, ValueError):
            continue
        await _apply(res)
        f.rename(f.with_suffix(".seen"))
        n += 1
    return n


async def _apply(res: dict) -> None:
    change = await get(int(res.get("id", 0)))
    if not change:
        return
    cid, status = change["id"], res.get("status")
    if res.get("action") == "test":
        ok = status == "passed"
        verdict = res.get("verdict") if isinstance(res.get("verdict"), dict) else {}
        await db.pool().execute(
            """UPDATE dev_changes SET status = $2, commit = $3, files = $4, diffstat = $5, test_log = $6, updated_at = now(),
                      tier = $7, verdict = $8, tests = $9 WHERE id = $1""", cid, "awaiting_approval" if ok else "test_failed", res.get("commit"),
            res.get("files") or [], (res.get("diffstat") or "")[:4000], (res.get("log") or "")[-20000:],
            verdict.get("tier"), verdict or None, (res.get("tests") or "")[:300])
        if not ok:
            return  # Hermes reads check_code_change and fixes; the owner is not bothered by failed attempts
        a = await approvals.create(  # everything but "why" comes from the runner's look at the real diff
            "code_change", f"JARVIS ingin memperbarui dirinya (T{verdict.get('tier') or 1}): {change['title']}",
            approval_detail(cid, change, res, verdict),
            "hermes", "high", idempotency_key=f"dev:{cid}:{res.get('commit')}")
        await db.pool().execute("UPDATE dev_changes SET approval_id = $2 WHERE id = $1", cid, a["id"])
        await reports._create(change["task_id"], "system",
                              f"Aku sudah membuat dan menguji perubahan pada diriku: {change['title']}. Semua tes lulus. "
                              + (f"Perubahan ini menambah pustaka {', '.join(res['deps'][:5])}. " if res.get("deps") else "")
                              + f"Tinjau dan setujui di halaman admin (Persetujuan nomor {a['id']}); dari aplikasi hanya bisa ditolak.")
    elif res.get("action") == "deploy":
        final = {"deployed": "deployed", "rolled_back": "rolled_back"}.get(status, "deploy_failed")
        await db.pool().execute(
            "UPDATE dev_changes SET status = $2, deploy_log = $3, apk_version = $4, updated_at = now() WHERE id = $1",
            cid, final, (res.get("log") or "")[-20000:], res.get("apk_version"))
        text = {
            "deployed": f"Pembaruan diriku sudah aktif: {change['title']}."
                        + (f" Ada APK baru versi {res['apk_version']} — kamu akan ditawari update." if res.get("apk_version") else ""),
            "rolled_back": f"Pembaruan {change['title']} kupasang tapi gagal cek kesehatan, jadi kukembalikan ke versi sebelumnya.",
        }.get(final, f"Pembaruan {change['title']} gagal dipasang: {str(res.get('error') or '')[:150]}")
        await reports._create(change["task_id"], "system", text)
    await audit.record("jarvis-runner", f"dev.{res.get('action')}.{status}", f"dev:{cid}")
