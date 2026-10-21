"""Performance self-improvement (ADR-026, enabled by the owner 2026-10-21): JARVIS changes its own code
ONLY to do what the owner asks faster, cheaper or more reliably — every change tested, every deploy
approved by the owner, every failure rolled back. New features and anything touching security,
permissions, approvals, secrets or the composition are out of scope (the runner refuses those files).

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
"""

import json
import logging
import os
import re
from pathlib import Path

from . import approvals, audit, db, reports

log = logging.getLogger("jarvis-core.dev")
ROOT = Path(os.getenv("DEV_DIR", "/data/dev"))
BRANCH = re.compile(r"^jarvis/[a-z0-9][a-z0-9-]{2,60}$")


class DevError(ValueError):
    pass


def _write_request(change_id: int, action: str, **extra) -> None:
    (ROOT / "requests").mkdir(parents=True, exist_ok=True)
    tmp = ROOT / "requests" / f".{change_id}-{action}.tmp"
    tmp.write_text(json.dumps({"id": change_id, "action": action, **extra}))
    tmp.rename(ROOT / "requests" / f"{change_id}-{action}.json")  # the runner watches for *.json


async def propose(branch: str, title: str, why: str, task_id: int | None = None) -> dict:
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
        "INSERT INTO dev_changes (branch, title, why, task_id) VALUES ($1, $2, $3, $4) RETURNING id, status",
        branch, title.strip()[:200] or branch, why.strip()[:4000], task_id)
    _write_request(row["id"], "test", branch=branch)
    await audit.record("hermes", "dev.proposed", f"dev:{row['id']}", branch=branch, title=title[:200])
    return dict(row) | {"note": "sedang diuji otomatis (±3–10 menit); cek dengan check_code_change"}


async def get(change_id: int) -> dict | None:
    row = await db.pool().fetchrow("SELECT * FROM dev_changes WHERE id = $1", change_id)
    return dict(row) if row else None


async def list_(limit: int = 30) -> list[dict]:
    rows = await db.pool().fetch(
        """SELECT id, branch, title, why, status, commit, files, diffstat, apk_version, approval_id, created_at, updated_at,
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
        await db.pool().execute(
            """UPDATE dev_changes SET status = $2, commit = $3, files = $4, diffstat = $5, test_log = $6, updated_at = now()
               WHERE id = $1""", cid, "awaiting_approval" if ok else "test_failed", res.get("commit"),
            res.get("files") or [], (res.get("diffstat") or "")[:4000], (res.get("log") or "")[-20000:])
        if not ok:
            return  # Hermes reads check_code_change and fixes; the owner is not bothered by failed attempts
        a = await approvals.create(
            "code_change", f"JARVIS ingin memperbarui dirinya: {change['title']}",
            {"change_id": cid, "branch": change["branch"], "commit": res.get("commit"), "why": change["why"][:1500],
             "files": (res.get("files") or [])[:60], "diffstat": (res.get("diffstat") or "")[:3000]},
            "hermes", "high", idempotency_key=f"dev:{cid}:{res.get('commit')}")
        await db.pool().execute("UPDATE dev_changes SET approval_id = $2 WHERE id = $1", cid, a["id"])
        await reports._create(change["task_id"], "system",
                              f"Aku sudah membuat dan menguji perubahan pada diriku: {change['title']}. Semua tes lulus. "
                              f"Setujui atau tolak di Persetujuan nomor {a['id']}.")
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
