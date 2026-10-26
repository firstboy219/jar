#!/bin/sh
# OpenJarvis as a worker (ADR-043): the agent loop only. Model calls go to JARVIS' gateway as 'jarvis-spike'
# (engine "vllm" = any OpenAI-compatible server; VLLM_API_KEY is the spike gateway key), file tools limited to
# /work, no memory context, no analytics. Config: data/spike/openjarvis-home/.openjarvis/config.toml (spike.sh).
set -e
: "${OPENJARVIS_API_KEY:?OPENJARVIS_API_KEY is required}"
exec jarvis serve --engine vllm --model jarvis-spike --agent "${OJ_AGENT:-orchestrator}" --host 0.0.0.0 --port 8765
