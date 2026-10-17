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


async def activate(workflow_id: str) -> dict:
    w = await _call("POST", f"/workflows/{workflow_id}/activate")
    return {"id": w["id"], "name": w["name"], "active": w.get("active", True)}
