#!/usr/bin/env bash
# Download the local AI models (not in git, not in backups — they can always be fetched again).
#   llama-chat   Qwen3.5-2B  Q4_0    — answers the owner (measured: ~42 tok/s read, ~7 tok/s write here)
#   llama-worker Qwen3.5-4B  Q4_K_M  — Hermes' local brain (~20 / ~4.7 tok/s)
# Whisper and speaker models are fetched by jarvis-ears itself on first use / at image build.
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p data/models
fetch() {
  local repo=$1 file=$2
  if [[ -s data/models/$file ]]; then echo "ok   $file"; return; fi
  echo "get  $file"
  curl -fL --retry 3 -o "data/models/$file.part" "https://huggingface.co/$repo/resolve/main/$file"
  mv "data/models/$file.part" "data/models/$file"
}
fetch unsloth/Qwen3.5-2B-GGUF Qwen3.5-2B-Q4_0.gguf
fetch unsloth/Qwen3.5-4B-GGUF Qwen3.5-4B-Q4_K_M.gguf
chown -R "$(stat -c %u:%g .)" data/models
echo "models ready in data/models"
