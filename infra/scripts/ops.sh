#!/usr/bin/env bash
# "Netralkan" — host part (ADR-029). Run as root by jarvis-ops.service when jarvis-core writes
# data/ops/relieve.request (after it has already stopped and saved every task). Frees CPU and memory
# without touching any data: memories, chats, documents, passwords, settings and models stay as they are.
#   1. restart Hermes (frees its browser/agent memory; its data is on the volume)
#   2. swap back into RAM when there is room for it
# (The local worker model and its orphan watchdog are gone, ADR-080.)
set -uo pipefail
cd "$(dirname "$0")/.."
OPS=data/ops
log=()
note() { log+=("$1"); echo "[$(date -Is)] $1"; }

REQ=$OPS/relieve.request
[[ -f $REQ ]] || exit 0
rm -f "$REQ"
log=()

flock data/admin/compose.lock docker restart jarvis-brain >/dev/null && note "Hermes kumulai ulang (memori browsernya bebas)."
sleep 15
read -r avail swap_used < <(awk '/MemAvailable/{a=$2} /SwapTotal/{t=$2} /SwapFree/{f=$2} END{print a, t-f}' /proc/meminfo)
# swapoff pages everything back one by one: ~1 GB took over 6 minutes here (2026-10-21), so only small swap,
# and never longer than 2 minutes (a larger swap just drains by itself as the memory is used again).
if (( swap_used > 300000 && swap_used < 600000 && avail > swap_used + 2000000 )); then
  if timeout -k 10 120 swapoff -a; then note "Swap $((swap_used / 1024)) MB kupindah kembali ke RAM."; fi
  swapon -a
elif (( swap_used >= 600000 )); then
  note "Swap $((swap_used / 1024)) MB kubiarkan (memindahkannya terlalu lama); akan berkurang sendiri."
fi
python3 -c 'import json, sys; json.dump({"summary": " ".join(sys.argv[2:])}, open(sys.argv[1], "w"))' "$OPS/relieve.result" "${log[@]}"
chown "$(stat -c %u:%g data/hermes)" "$OPS/relieve.result"
