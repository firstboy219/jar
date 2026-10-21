#!/usr/bin/env bash
# Per-container CPU/memory for the app's home screen (jarvis-core has no docker socket on purpose).
# Run by jarvis-usage.service: every 10 s, `docker stats` → data/ops/containers.json (read by core/app/ops.py),
# and applies the local worker model's CPU limit that core/app/ops.py decides (data/ops/policy.json):
# 2 of 4 threads while only JARVIS' background work runs, all 4 for the owner's work.
set -uo pipefail
cd "$(dirname "$0")/.."
OUT=data/ops
mkdir -p "$OUT"
chown "$(stat -c %u:%g data/hermes)" "$OUT"
while true; do
  want=$(python3 -c 'import json,sys; print(int(float(json.load(open(sys.argv[1]))["worker_cpus"]) * 1e9))' "$OUT/policy.json" 2>/dev/null)
  have=$(docker inspect -f '{{.HostConfig.NanoCpus}}' jarvis-llm-worker 2>/dev/null)  # also right after a recreate
  if [[ $want =~ ^[0-9]+$ && -n $have && $want != "$have" ]] && \
     docker update --cpus "$(python3 -c "print($want / 1e9)")" jarvis-llm-worker >/dev/null 2>&1; then
    echo "[$(date -Is)] jarvis-llm-worker cpus $have -> $want (nano)"
  fi
  docker stats --no-stream --format '{{json .}}' 2>/dev/null | python3 -c '
import json, sys, time
rows = [json.loads(l) for l in sys.stdin if l.strip()]
keep = ("Name", "CPUPerc", "MemUsage", "MemPerc")
json.dump({"at": time.time(), "containers": [{k: r.get(k) for k in keep} for r in rows]}, open(sys.argv[1], "w"))
' "$OUT/.containers.tmp" && mv -f "$OUT/.containers.tmp" "$OUT/containers.json" && chmod 644 "$OUT/containers.json"
  sleep 10
done
