#!/usr/bin/env bash
# Skill sandbox (Blueprint v2 Sprint 4, ADR-040). Run as root by jarvis-skill.service when jarvis-core drops a request in
# data/skills/requests/. Each request = {"id", "name", "files": {"scripts/main.py": "…"}, "cases": [{"name","args","stdin","expect"}]}.
# Every case runs in a THROWAWAY container: no network, 128 MB, half a CPU, 64 processes, read-only filesystem, no capabilities,
# unprivileged user, the skill folder mounted read-only, no credentials, 20 s limit. Output is capped. The skill's own code
# never runs on the host and jarvis-core never touches the docker socket. Result → data/skills/results/<id>.json.
set -uo pipefail
cd "$(dirname "$0")/.."
BASE=$PWD/data/skills
IMAGE=python:3.12-slim
mkdir -p "$BASE/requests" "$BASE/results" "$BASE/done"
log() { echo "[$(date -Is)] $*"; }

shopt -s nullglob
for req in "$BASE"/requests/*.json; do
  id=$(basename "$req" .json)
  log "request $id"
  work=$(mktemp -d /tmp/jarvis-skill.XXXXXX)
  python3 - "$req" "$work" "$BASE/results/$id.json" "$IMAGE" <<'PY'
import json, os, re, subprocess, sys, time

req_path, work, out_path, image = sys.argv[1:5]
req = json.load(open(req_path))
files, cases = req.get("files") or {}, req.get("cases") or []
result = {"id": req.get("id"), "cases": []}
ok_name = re.compile(r"^scripts/[a-z0-9_]+\.py$")
if len(files) > 3 or "scripts/main.py" not in files or not all(ok_name.match(p) for p in files) \
        or any(len(str(c).encode()) > 20_000 for c in files.values()) or not 1 <= len(cases) <= 8:
    result["error"] = "permintaan tidak valid"
else:
    os.makedirs(os.path.join(work, "scripts"))
    for path, code in files.items():
        with open(os.path.join(work, path), "w") as f:
            f.write(str(code))
    os.chmod(work, 0o755)
    for case in cases:
        args = [str(a)[:200] for a in (case.get("args") or [])][:5]
        cmd = ["docker", "run", "--rm", "-i", "--network", "none", "--memory", "128m", "--memory-swap", "128m", "--cpus", "0.5",
               "--pids-limit", "64", "--read-only", "--tmpfs", "/tmp:rw,size=16m,noexec", "--cap-drop", "ALL",
               "--security-opt", "no-new-privileges", "--user", "65534:65534", "-v", f"{work}:/work:ro", "-w", "/work",
               image, "python", "-I", "-B", "scripts/main.py", *args]
        started = time.monotonic()
        try:
            p = subprocess.run(cmd, input=str(case.get("stdin") or "")[:4000], capture_output=True, text=True, timeout=25)
            out, err, code = p.stdout[:4000], p.stderr[:1500], p.returncode
        except subprocess.TimeoutExpired:
            out, err, code = "", "melewati batas waktu 20 detik", 124
        expect = str(case.get("expect") or "")
        ok = code == 0 and expect.lower() in out.lower()
        note = "" if ok else (err.strip().splitlines()[-1][:200] if err.strip() else f"keluaran tidak memuat “{expect[:60]}”")
        result["cases"].append({"name": str(case.get("name"))[:120], "ok": ok, "exit": code, "stdout": out[:600], "note": note,
                                "ms": int((time.monotonic() - started) * 1000)})
tmp = out_path + ".tmp"
with open(tmp, "w") as f:
    json.dump(result, f, ensure_ascii=False)
os.rename(tmp, out_path)
PY
  rm -rf "$work"
  mv "$req" "$BASE/done/$id.json"
done
