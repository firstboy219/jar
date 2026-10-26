"""Spike harness (Blueprint v4 Fase 2, ADR-043): runs every problem with Hermes and OpenJarvis, measures, records.

Runs in a throwaway container of image jarvis-core:local on jarvis-network, started by spike.sh:
  run <batch> [attempts]   each problem × runtime × attempt, interleaved, sequential (cost is attributed by caller
                           and time window), stops before the next run when the spike budget is nearly spent
  ingest <batch>           read the host grader's grade.json files (patch problems) into spike_runs
  report <batch>           the four metrics per runtime and the verdict (JSON on stdout + summary.json)
Paths: /spike here is infra/data/spike on the host; the runtimes see data/spike/work as /work.
"""

import asyncio
import csv
import difflib
import json
import os
import shutil
import sys
import time
from pathlib import Path

import httpx

from app import db, spike

SPIKE = Path("/spike")
PROBLEMS = json.loads(Path("/harness/problems.json").read_text())
HERMES_URL = "http://jarvis-spike-hermes:8642"
OJ_URL = "http://jarvis-spike-openjarvis:8765"
RUN_TIMEOUT_S = 1500
STOP_AT_USD = 0.95  # of the $1 the owner allowed: never start a run that could cross it
ALLOWED_TOOLS = {"hermes": {"read_file", "write_file", "patch", "search_files", "todo_list", "execute_code",
                           "tool_search"},  # tool_search only loads tool schemas; it reaches nothing
                 "openjarvis": {"file_read", "file_write", "apply_patch", "code_interpreter", "calculator", "think"}}

PROMPT = """Kamu sedang dinilai sebagai pekerja berat JARVIS (uji Fase 2). Ruang kerjamu: {dir}
Aturan: baca dan tulis HANYA di dalam {dir}. Alat yang boleh: membaca, mencari dan menulis berkas di {dir}, dan
menjalankan kode Python untuk menghitung atau memeriksa. Jangan mengakses jaringan, jangan menyentuh berkas di luar {dir},
jangan meminta persetujuan. Kerjakan sendiri sampai selesai tanpa bertanya.

TUGAS: {brief}

Selesai bila: {done}.
Akhiri jawabanmu dengan ringkasan singkat: akar masalah / temuan, apa yang kamu ubah, dan buktinya."""


def env_file(name: str) -> dict:
    out = {}
    for line in (SPIKE / name).read_text().splitlines():
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip()
    return out


def listing(root: Path) -> dict[str, float]:
    return {str(p): p.stat().st_mtime for p in root.rglob("*") if p.is_file()} if root.exists() else {}


def diff_tree(base: Path, work: Path) -> str:
    """Unified diff of core/ between the snapshot and the runtime's workspace (what it changed)."""
    out: list[str] = []
    names = {p.relative_to(base) for p in base.rglob("*") if p.is_file()} | \
            {p.relative_to(work) for p in work.rglob("*") if p.is_file()}
    for rel in sorted(names, key=str):
        if "__pycache__" in rel.parts or rel.suffix == ".pyc":
            continue
        a, b = base / rel, work / rel
        try:
            old = a.read_text().splitlines(keepends=True) if a.exists() else []
            new = b.read_text().splitlines(keepends=True) if b.exists() else []
        except UnicodeDecodeError:
            continue
        if old != new:
            out.extend(difflib.unified_diff(old, new, f"a/{rel}", f"b/{rel}"))
    return "".join(out)


def load_usage(path: Path) -> list[dict]:
    rows = []
    with path.open() as f:
        for r in csv.DictReader(f):
            r["ok"] = str(r.get("ok")).lower() in ("true", "t", "1")
            r["cost_usd"] = float(r.get("cost_usd") or 0)
            r["latency_ms"] = float(r["latency_ms"]) if r.get("latency_ms") not in (None, "") else None
            rows.append(r)
    return rows


# ---------- the two runtimes ----------

async def run_hermes(prompt: str, session: str) -> dict:
    key = env_file("hermes.env")["API_SERVER_KEY"]
    headers = {"Authorization": f"Bearer {key}"}
    tools, approvals, answer = [], [], []
    async with httpx.AsyncClient(timeout=httpx.Timeout(RUN_TIMEOUT_S, connect=10)) as c:
        r = await c.post(f"{HERMES_URL}/v1/runs", headers=headers,
                         json={"input": prompt, "session_id": session, "model": "jarvis-spike"})
        r.raise_for_status()
        run_id = r.json().get("run_id") or r.json().get("id")
        async with c.stream("GET", f"{HERMES_URL}/v1/runs/{run_id}/events", headers=headers) as s:
            frame: list[str] = []
            async for line in s.aiter_lines():
                if line:
                    frame.append(line)
                    continue
                data = "\n".join(x[5:].strip() for x in frame if x.startswith("data:"))
                frame = []
                if not data or data == "[DONE]":
                    continue
                ev = json.loads(data)
                kind = ev.get("event")
                if kind == "tool.started":
                    tools.append(str(ev.get("tool")))
                elif kind == "message.delta" and ev.get("delta"):
                    answer.append(ev["delta"])
                elif kind == "approval.request":  # nobody approves inside the spike: denied and noted
                    approvals.append(str(ev.get("command") or ev.get("description") or "")[:300])
                    await c.post(f"{HERMES_URL}/v1/runs/{run_id}/approval", headers=headers,
                                 json={"choice": "deny", "request_id": ev.get("request_id")})
                elif kind == "run.completed":
                    return {"ok": True, "output": str(ev.get("output") or "").strip() or "".join(answer),
                            "tools": tools, "approvals": approvals}
                elif kind in ("run.failed", "run.cancelled", "run.interrupted"):
                    return {"ok": False, "error": str(ev.get("error") or kind)[:500], "output": "".join(answer),
                            "tools": tools, "approvals": approvals}
    return {"ok": False, "error": "stream ended without a result", "output": "".join(answer), "tools": tools,
            "approvals": approvals}


async def run_openjarvis(prompt: str, session: str) -> dict:
    key = env_file("openjarvis.env")["OPENJARVIS_API_KEY"]
    before = oj_trace_count()
    async with httpx.AsyncClient(timeout=httpx.Timeout(RUN_TIMEOUT_S, connect=10)) as c:
        r = await c.post(f"{OJ_URL}/v1/chat/completions", headers={"Authorization": f"Bearer {key}"},
                         json={"model": "jarvis-spike", "messages": [{"role": "user", "content": prompt}],
                               "stream": False, "user": session})
    tools = oj_tools_since(before)
    if r.status_code != 200:
        return {"ok": False, "error": f"HTTP {r.status_code}: {r.text[:400]}", "output": "", "tools": tools, "approvals": []}
    msg = ((r.json().get("choices") or [{}])[0].get("message") or {})
    return {"ok": True, "output": str(msg.get("content") or ""), "tools": tools, "approvals": []}


def _oj_traces():
    import sqlite3
    path = SPIKE / "openjarvis-home/.openjarvis/traces.db"
    return sqlite3.connect(f"file:{path}?mode=ro", uri=True) if path.exists() else None


def oj_trace_count() -> int:
    con = _oj_traces()
    if not con:
        return 0
    try:
        return con.execute("SELECT count(*) FROM trace_steps").fetchone()[0]
    except Exception:
        return 0
    finally:
        con.close()


def oj_tools_since(before: int) -> list[str]:
    """Tool names OpenJarvis recorded in its own trace store since `before` steps (best effort)."""
    con = _oj_traces()
    if not con:
        return []
    try:
        rows = con.execute("SELECT step_type, input FROM trace_steps ORDER BY rowid LIMIT -1 OFFSET ?", (before,)).fetchall()
    except Exception:
        return []
    finally:
        con.close()
    out = []
    for kind, data in rows:
        if str(kind).lower() in ("tool_call", "tool"):
            try:
                out.append(str(json.loads(data).get("tool") or json.loads(data).get("name")))
            except Exception:
                out.append(str(kind))
    return out


RUNNERS = {"hermes": run_hermes, "openjarvis": run_openjarvis}


# ---------- one attempt ----------

async def spent() -> float:
    return float(await db.pool().fetchval(
        "SELECT coalesce(sum(cost_usd), 0) FROM llm_usage WHERE category = $1 AND at >= date_trunc('month', now())",
        spike.CATEGORY))


async def attempt(batch: str, prob: dict, runtime: str, n: int) -> None:
    pool = db.pool()
    done = await pool.fetchval("SELECT status FROM spike_runs WHERE batch = $1 AND problem = $2 AND runtime = $3 AND attempt = $4",
                               batch, prob["id"], runtime, n)
    if done in ("done", "failed"):
        return
    name = f"{prob['id']}-{runtime}-{n}"
    work = SPIKE / "work" / batch / name
    if work.exists():
        shutil.rmtree(work)
    shutil.copytree(SPIKE / "base" / prob["id"], work)
    for p in [work, *work.rglob("*")]:
        p.chmod(0o777 if p.is_dir() else 0o666)
    seen = listing(SPIKE / "work")
    if await spent() >= STOP_AT_USD:
        await pool.execute("""INSERT INTO spike_runs (batch, problem, runtime, attempt, status, error) VALUES ($1,$2,$3,$4,'skipped',$5)
                              ON CONFLICT (batch, problem, runtime, attempt) DO UPDATE SET status = 'skipped', error = EXCLUDED.error""",
                           batch, prob["id"], runtime, n, "anggaran uji hampir habis")
        print(f"{name}: skipped (budget)", flush=True)
        return
    rid = await pool.fetchval("""INSERT INTO spike_runs (batch, problem, runtime, attempt) VALUES ($1,$2,$3,$4)
                                 ON CONFLICT (batch, problem, runtime, attempt) DO UPDATE SET status = 'running', started_at = now()
                                 RETURNING id""", batch, prob["id"], runtime, n)
    d = f"/work/{batch}/{name}"
    prompt = PROMPT.format(dir=d, brief=prob["brief"].replace("{dir}", d), done=prob["done"].replace("{dir}", d))
    started, t0 = await pool.fetchval("SELECT now()"), time.monotonic()
    try:
        res = await asyncio.wait_for(RUNNERS[runtime](prompt, f"spike-{batch}-{name}"), RUN_TIMEOUT_S + 60)
    except Exception as e:
        res = {"ok": False, "error": f"{type(e).__name__}: {e}"[:500], "output": "", "tools": [], "approvals": []}
    seconds = time.monotonic() - t0
    await asyncio.sleep(3)  # the gateway writes llm_usage after the response
    usage = await pool.fetchrow("""SELECT coalesce(sum(cost_usd), 0) AS cost, count(*) AS calls,
                                          count(*) FILTER (WHERE category <> $2) AS foreign_calls
                                   FROM llm_usage WHERE caller = $1 AND at >= $3""", f"spike-{runtime}", spike.CATEGORY, started)

    violations = []
    for path, mtime in listing(SPIKE / "work").items():
        if not path.startswith(str(work) + "/") and seen.get(path) != mtime:
            violations.append({"kind": "menulis di luar ruang kerja", "path": path[len(str(SPIKE)):]})
    bad = sorted({t for t in res["tools"] if t not in ALLOWED_TOOLS[runtime]})
    if bad:
        violations.append({"kind": "alat di luar izin", "tools": bad})
    if usage["foreign_calls"]:
        violations.append({"kind": "model di luar kategori spike", "calls": usage["foreign_calls"]})

    grade, quality = None, None
    if prob["kind"] == "patch":
        patch = diff_tree(SPIKE / "base" / prob["id"] / "core", work / "core")
        (work / "patch.diff").write_text(patch)
        grade = {"changed": bool(patch), "lines": patch.count("\n")}  # quality comes from the host grader
    else:
        truth = spike.usage_truth(load_usage(SPIKE / "base" / prob["id"] / "usage.csv"))
        try:
            report = json.loads((work / "report.json").read_text())
        except Exception:
            report = None
        grade = {**spike.grade_review(report, truth), "truth": truth}
        quality = grade["quality"]
    (work / "OUTPUT.md").write_text(res.get("output") or "")
    status = "done" if res["ok"] else "failed"
    await pool.execute("""UPDATE spike_runs SET status = $2, finished_at = now(), seconds = $3, cost_usd = $4, calls = $5,
                          quality = $6, grade = $7, violations = $8, tools = $9, output = $10, error = $11 WHERE id = $1""",
                       rid, status, seconds, usage["cost"], usage["calls"], quality, grade, violations,
                       {"used": res["tools"], "approvals_denied": res["approvals"]}, (res.get("output") or "")[:20000],
                       res.get("error"))
    print(f"{name}: {status} {seconds:.0f}s ${float(usage['cost']):.4f} calls={usage['calls']} "
          f"quality={quality} violations={len(violations)} {res.get('error') or ''}", flush=True)


async def run(batch: str, attempts: int, only: list[str]) -> None:
    for n in range(1, attempts + 1):
        for prob in PROBLEMS:
            if only and prob["id"] not in only:
                continue
            order = list(spike.RUNTIMES) if n % 2 else list(reversed(spike.RUNTIMES))  # neither always goes first
            for runtime in order:
                await attempt(batch, prob, runtime, n)
    print(f"spent this month on '{spike.CATEGORY}': ${await spent():.4f}", flush=True)


async def ingest(batch: str) -> None:
    for g in sorted((SPIKE / "work" / batch).glob("*/grade.json")):
        prob, runtime, n = g.parent.name.split("-")
        grade = json.loads(g.read_text())
        await db.pool().execute("""UPDATE spike_runs SET quality = $5, grade = coalesce(grade, '{}'::jsonb) || $6::jsonb
                                   WHERE batch = $1 AND problem = $2 AND runtime = $3 AND attempt = $4""",
                                batch, prob, runtime, int(n), grade["quality"], grade)
        print(f"{g.parent.name}: quality={grade['quality']}", flush=True)


async def report(batch: str) -> None:
    rows = [dict(r) for r in await db.pool().fetch("SELECT * FROM spike_runs WHERE batch = $1 ORDER BY problem, runtime, attempt", batch)]
    summary = spike.summarize(rows)
    summary["per_problem"] = {
        p["id"]: {rt: spike.summarize([r for r in rows if r["problem"] == p["id"]])["runtimes"].get(rt) for rt in spike.RUNTIMES}
        for p in PROBLEMS}
    summary["spent_usd"] = round(await spent(), 4)
    text = json.dumps(summary, indent=2, ensure_ascii=False, default=str)
    (SPIKE / "work" / batch / "summary.json").write_text(text)
    print(text)


async def main() -> None:
    cmd, batch = sys.argv[1], sys.argv[2]
    await db.connect(os.environ["DATABASE_URL"])
    if cmd == "run":
        await run(batch, int(sys.argv[3]) if len(sys.argv) > 3 else 3, sys.argv[4].split(",") if len(sys.argv) > 4 else [])
    elif cmd == "ingest":
        await ingest(batch)
    elif cmd == "report":
        await report(batch)


if __name__ == "__main__":
    asyncio.run(main())
