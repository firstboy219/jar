#!/usr/bin/env bash
# "Netralkan" — host part (ADR-029). Run as root by jarvis-ops.service when jarvis-core writes
# data/ops/relieve.request (after it has already stopped and saved every task). Frees CPU and memory
# without touching any data: memories, chats, documents, passwords, settings and models stay as they are.
#   1. restart Hermes (frees its browser/agent memory; its data is on the volume)
#   2. the local worker model: restart only if it is still busy (a generation nobody waits for any more)
#   3. swap back into RAM when there is room for it
# Also: data/ops/worker-reset.request from the orphan watchdog (core/app/ops.py) — the local worker model
# keeps computing an answer nobody waits for: restart it (core restores its prompt cache afterwards).
set -uo pipefail
cd "$(dirname "$0")/.."
OPS=data/ops
log=()
note() { log+=("$1"); echo "[$(date -Is)] $1"; }

if [[ -f $OPS/worker-reset.request ]]; then
  rm -f "$OPS/worker-reset.request" "$OPS/worker-reset.result"
  flock data/admin/compose.lock docker restart jarvis-llm-worker >/dev/null && note "watchdog: jarvis-llm-worker dimulai ulang"
  echo '{}' > "$OPS/worker-reset.result"; chown "$(stat -c %u:%g data/hermes)" "$OPS/worker-reset.result"
fi
REQ=$OPS/relieve.request
[[ -f $REQ ]] || exit 0
rm -f "$REQ"
log=()

flock data/admin/compose.lock docker restart jarvis-brain >/dev/null && note "Hermes kumulai ulang (memori browsernya bebas)."
sleep 15
cpu=$(docker stats --no-stream --format '{{.CPUPerc}}' jarvis-llm-worker 2>/dev/null | tr -d '%' | cut -d. -f1)
if [[ ${cpu:-0} -gt 50 ]]; then
  flock data/admin/compose.lock docker restart jarvis-llm-worker >/dev/null && note "Model AI kerja lokal masih sibuk (${cpu}%), jadi kumulai ulang."
fi
read -r avail swap_used < <(awk '/MemAvailable/{a=$2} /SwapTotal/{t=$2} /SwapFree/{f=$2} END{print a, t-f}' /proc/meminfo)
if (( swap_used > 300000 && avail > swap_used + 2000000 )); then
  if timeout 180 swapoff -a && swapon -a; then note "Swap $((swap_used / 1024)) MB kupindah kembali ke RAM."; else swapon -a; fi
fi
python3 -c 'import json, sys; json.dump({"summary": " ".join(sys.argv[2:])}, open(sys.argv[1], "w"))' "$OPS/relieve.result" "${log[@]}"
chown "$(stat -c %u:%g data/hermes)" "$OPS/relieve.result"
