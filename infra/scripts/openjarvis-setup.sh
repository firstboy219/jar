#!/usr/bin/env bash
# Set up OpenJarvis as the optional heavy worker (Blueprint v4 Fase 2, ADR-043). Run from infra/ as root; safe to rerun
# (keys are kept). It never touches .env. Afterwards switch the worker on at the admin page → "Pekerja berat".
set -euo pipefail
cd "$(dirname "$0")/.."
D=data/openjarvis
mkdir -p $D/home/.openjarvis $D/work
if [ ! -f $D/openjarvis.env ]; then
  gw=$(openssl rand -hex 32); api=$(openssl rand -hex 32)
  umask 077
  printf 'OPENJARVIS_API_KEY=%s\nVLLM_API_KEY=%s\nOJ_MODEL=jarvis-web\n' "$api" "$gw" > $D/openjarvis.env
  umask 022
  h=$(printf '%s' "$gw" | sha256sum | cut -d' ' -f1)  # the DB keeps only the hash of the gateway key
  echo "INSERT INTO settings_kv (key, value) VALUES ('worker:key:openjarvis', to_jsonb('$h'::text))
        ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value;" |
    docker exec -i jarvis-db sh -c 'psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d jarvis -q'
fi
cat > $D/home/.openjarvis/config.toml <<'TOML'
[engine]
default = "vllm"

[engine.vllm]
host = "http://jarvis-core:8000/llm"

[server]
agent = "orchestrator"
model = "jarvis-web"

[agent]
max_turns = 60
context_from_memory = false

[tools]
enabled = "file_read,file_write,apply_patch,code_interpreter,think"

[security]
allowed_dirs = ["/work"]

[analytics]
enabled = false
choice_recorded = true
TOML
chown -R "${HOST_UID:-1000}:${HOST_GID:-1000}" $D/home $D/work
chmod 640 $D/openjarvis.env; chown "root:${HOST_GID:-1000}" $D/openjarvis.env
docker compose --profile openjarvis up -d --build openjarvis
echo "OpenJarvis is up (still OFF for tasks). Switch it on at the admin page → Pekerja berat."
