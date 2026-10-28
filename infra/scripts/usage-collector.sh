#!/usr/bin/env bash
# Per-container CPU/memory for the app's home screen (jarvis-core has no docker socket on purpose).
# Run by jarvis-usage.service: every 10 s, `docker stats` → data/ops/containers.json (read by core/app/ops.py).
set -uo pipefail
cd "$(dirname "$0")/.."
OUT=data/ops
mkdir -p "$OUT"
chown "$(stat -c %u:%g data/hermes)" "$OUT"
while true; do
  docker stats --no-stream --format '{{json .}}' 2>/dev/null | python3 -c '
import json, sys, time
rows = [json.loads(l) for l in sys.stdin if l.strip()]
keep = ("Name", "CPUPerc", "MemUsage", "MemPerc")
json.dump({"at": time.time(), "containers": [{k: r.get(k) for k in keep} for r in rows]}, open(sys.argv[1], "w"))
' "$OUT/.containers.tmp" && mv -f "$OUT/.containers.tmp" "$OUT/containers.json" && chmod 644 "$OUT/containers.json"
  sleep 10
done
