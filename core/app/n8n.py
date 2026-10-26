"""Thin client for the n8n public REST API (v1)."""

from typing import Any

import httpx

from .config import settings


class N8nError(RuntimeError):
    pass


def _client() -> httpx.AsyncClient:
    if not settings.n8n_api_key:
        raise N8nError("N8N_API_KEY belum diisi (web admin → Pengaturan)")
    return httpx.AsyncClient(base_url=f"{settings.n8n_url}/api/v1", timeout=20,
                             headers={"X-N8N-API-KEY": settings.n8n_api_key})


async def _call(method: str, path: str, **kw) -> Any:
    async with _client() as c:
        r = await c.request(method, path, **kw)
    if r.status_code >= 400:
        raise N8nError(f"n8n {method} {path}: HTTP {r.status_code} {r.text[:300]}")
    return r.json() if r.content else None


async def list_workflows() -> list[dict]:
    data = await _call("GET", "/workflows", params={"limit": 100})
    return [{"id": w["id"], "name": w["name"], "active": w.get("active", False)} for w in data["data"]]


async def get_workflow(workflow_id: str) -> dict:
    return await _call("GET", f"/workflows/{workflow_id}")


async def create_inactive(workflow: dict) -> dict:
    """Create a workflow. The public API ignores/forbids `active`; new workflows start inactive."""
    body = {k: workflow[k] for k in ("name", "nodes", "connections") if k in workflow}
    body["settings"] = workflow.get("settings") or {"executionOrder": "v1"}
    created = await _call("POST", "/workflows", json=body)
    return {"id": created["id"], "name": created["name"], "active": created.get("active", False)}


async def update_workflow(workflow_id: str, workflow: dict) -> dict:
    body = {k: workflow[k] for k in ("name", "nodes", "connections") if k in workflow}
    body["settings"] = workflow.get("settings") or {"executionOrder": "v1"}
    w = await _call("PUT", f"/workflows/{workflow_id}", json=body)
    return {"id": w["id"], "name": w["name"], "active": w.get("active", False)}


async def put_credential(cred_id: str | None, name: str, cred_type: str, data: dict) -> dict:
    """Create a credential, or replace the one with this id (a new login). n8n keeps it encrypted; JARVIS never reads it back."""
    if cred_id:
        try:
            c = await _call("PATCH", f"/credentials/{cred_id}", json={"name": name, "type": cred_type, "data": data})
            return {"id": c["id"], "name": c["name"]}
        except N8nError as e:
            if "404" not in str(e):
                raise
    c = await _call("POST", "/credentials", json={"name": name, "type": cred_type, "data": data})
    return {"id": c["id"], "name": c["name"]}


async def delete_credential(cred_id: str) -> None:
    try:
        await _call("DELETE", f"/credentials/{cred_id}")
    except N8nError as e:
        if "404" not in str(e):
            raise


async def deactivate(workflow_id: str) -> None:
    await _call("POST", f"/workflows/{workflow_id}/deactivate")


async def activate(workflow_id: str) -> dict:
    w = await _call("POST", f"/workflows/{workflow_id}/activate")
    return {"id": w["id"], "name": w["name"], "active": w.get("active", True)}


async def executions(limit: int = 12) -> list[dict]:
    """The latest runs across all workflows (the desk shows what the automations are doing)."""
    data = await _call("GET", "/executions", params={"limit": limit})
    return [{"id": e["id"], "workflow_id": e.get("workflowId"), "status": e.get("status") or ("success" if e.get("finished") else "running"),
             "started_at": e.get("startedAt"), "stopped_at": e.get("stoppedAt")} for e in (data or {}).get("data", [])]
