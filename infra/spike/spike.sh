#!/usr/bin/env bash
# The OpenJarvis spike (Blueprint v4 Fase 2, ADR-043). Run from infra/ as root:
#   spike/spike.sh setup              keys, configs, the problem snapshots (from git) and the usage export
#   spike/spike.sh up | down          start / stop the spike Hermes and OpenJarvis (docker run, never in compose)
#   spike/spike.sh run <batch> [n] [p1,p2]   n attempts (default 3) per problem and runtime, sequential
#   spike/spike.sh grade <batch>      hidden tests on every patch, then ingest + report
#   spike/spike.sh reference          check the graders: the real fixes must score 1, the untouched snapshots 0
#   spike/spike.sh revoke             forget the spike keys (the gateway refuses them from then on)
set -euo pipefail
cd "$(dirname "$0")/.."
REPO=$(git rev-parse --show-toplevel)
D=data/spike
AD=$(pwd)/$D
NET=jarvis_jarvis-network
# The spike containers are started here with docker run, never from docker-compose.yml: a normal deploy cannot start
# them, and the spike cannot touch the stack's definition. None publishes a port; all are on jarvis-network only
# (they must reach jarvis-core's gateway), with a gateway key good for category 'spike' and nothing else.
SEC=(--security-opt no-new-privileges:true --memory 2g --pids-limit 512)
harness() {
  docker run --rm --network $NET --user 1000:1000 -e PYTHONPATH=/srv \
    -e DATABASE_URL="postgresql://jarvis_core:$(grep -E '^JARVIS_DB_PASSWORD=' .env | cut -d= -f2-)@jarvis-db/jarvis" \
    -v "$(pwd)/spike:/harness:ro" -v "$AD:/spike" --entrypoint python jarvis-core:local /harness/harness.py "$@"
}
up() {
  docker build -q -t jarvis-openjarvis:40092da openjarvis >/dev/null
  docker rm -f jarvis-spike-hermes jarvis-spike-openjarvis >/dev/null 2>&1 || true
  # Hermes-Brain's image and init script with JARVIS_SPIKE=1: no JARVIS tools (MCP), no shared memory, file + code only
  docker run -d --name jarvis-spike-hermes --network $NET "${SEC[@]}" --cap-drop NET_RAW --cap-drop MKNOD \
    --env-file $D/hermes.env -e HERMES_UID=1000 -e HERMES_GID=1000 -e API_SERVER_HOST=0.0.0.0 -e JARVIS_SPIKE=1 \
    -e HERMES_PROFILE=full -e TZ=Asia/Jakarta \
    -v "$AD/hermes-home:/opt/data" -v "$(pwd)/hermes/03-jarvis-config:/etc/cont-init.d/03-jarvis-config:ro" \
    -v "$(pwd)/hermes/SOUL.md:/opt/data/SOUL.md:ro" -v "$AD/work:/work" \
    nousresearch/hermes-agent:v0.22.2 gateway run >/dev/null
  docker run -d --name jarvis-spike-openjarvis --network $NET "${SEC[@]}" --env-file $D/openjarvis.env \
    -v "$AD/openjarvis-home:/home/oj" -v "$AD/work:/work" jarvis-openjarvis:40092da >/dev/null
  echo "spike up: jarvis-spike-hermes, jarvis-spike-openjarvis"
}
psql_() { docker exec -i jarvis-db sh -c 'psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d jarvis -Atq' "$@"; }

setup() {
  mkdir -p $D/work $D/base $D/grade $D/hermes-home $D/openjarvis-home/.openjarvis
  chown -R "${HOST_UID:-1000}:${HOST_GID:-1000}" $D
  if [ ! -f $D/hermes.env ]; then  # keys: random, git-ignored, readable by root only; the DB keeps their SHA-256
    hk=$(openssl rand -hex 32); ok=$(openssl rand -hex 32)
    umask 077
    printf 'SPIKE_GATEWAY_KEY=%s\nAPI_SERVER_KEY=%s\n' "$hk" "$(openssl rand -hex 32)" > $D/hermes.env
    printf 'VLLM_API_KEY=%s\nOPENJARVIS_API_KEY=%s\n' "$ok" "$(openssl rand -hex 32)" > $D/openjarvis.env
    umask 022
    for rt in hermes:$hk openjarvis:$ok; do
      h=$(printf '%s' "${rt#*:}" | sha256sum | cut -d' ' -f1)
      echo "INSERT INTO settings_kv (key, value) VALUES ('spike:key:${rt%%:*}', to_jsonb('$h'::text))
            ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value;" | psql_
    done
  fi
  cat > $D/openjarvis-home/.openjarvis/config.toml <<'TOML'
[engine]
default = "vllm"

[engine.vllm]
host = "http://jarvis-core:8000/llm"

[server]
agent = "orchestrator"
model = "jarvis-spike"

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
  for p in $(python3 -c "import json; [print(p['id'], p.get('snapshot', '-')) for p in json.load(open('spike/problems.json'))]" | tr ' ' ':'); do
    id=${p%%:*}; snap=${p#*:}
    rm -rf "$D/base/$id"; mkdir -p "$D/base/$id"
    if [ "$snap" != "-" ]; then
      git -C "$REPO" archive "$snap" core | tar -x -C "$D/base/$id"
    else  # p3: the last 7 days of model usage — no prompts, no answers, no session ids
      echo "COPY (SELECT at, category, caller, provider, model, prompt_tokens, completion_tokens, cost_usd, latency_ms,
                        ok::text AS ok, fallback_reason FROM llm_usage
                 WHERE at > now() - interval '7 days' AND category <> 'spike' ORDER BY at) TO STDOUT WITH CSV HEADER" \
        | psql_ > "$D/base/$id/usage.csv"
    fi
  done
  chown -R "${HOST_UID:-1000}:${HOST_GID:-1000}" $D
  echo "spike setup done: $(ls $D/base)"
}

grade_one() {  # <run dir> <problem id> <snapshot>: the runtime's core/app on the snapshot, the snapshot's own tests + the hidden ones
  local run=$1 id=$2 hidden=$3 g=$D/grade/$(basename "$1")
  rm -rf "$g"; mkdir -p "$g"; cp -r "$D/base/$id/core" "$g/core"
  rm -rf "$g/core/app"; cp -r "$run/core/app" "$g/core/app"
  cp "spike/$hidden" "$g/core/tests/test_spike_hidden.py"
  local out hp=0 ht=0 suite=0
  out=$(CORE_DIR="$g/core" scripts/test-core.sh tests/test_spike_hidden.py 2>&1 || true)
  hp=$(grep -oE '[0-9]+ passed' <<<"$out" | tail -1 | cut -d' ' -f1 || true); hp=${hp:-0}
  ht=$(grep -cE '^(async )?def test_' "spike/$hidden")
  if CORE_DIR="$g/core" scripts/test-core.sh --ignore=tests/test_spike_hidden.py >"$g/suite.log" 2>&1; then suite=1
  else  # a flaky test must not cost a runtime its score: the failures get one rerun on their own
    mapfile -t failed < <(grep -oE '^FAILED [^ ]+' "$g/suite.log" | cut -d' ' -f2 || true)
    if [ ${#failed[@]} -gt 0 ] && CORE_DIR="$g/core" scripts/test-core.sh "${failed[@]}" >"$g/rerun.log" 2>&1; then suite=1; fi
  fi
  python3 - "$run/grade.json" "$hp" "$ht" "$suite" <<'PY'
import json, sys
path, hp, ht, suite = sys.argv[1], int(sys.argv[2]), int(sys.argv[3]), int(sys.argv[4])
q = round(hp / ht * (1 if suite else 0.5), 3) if ht else 0
json.dump({"hidden_passed": hp, "hidden_total": ht, "suite_ok": bool(suite), "quality": q}, open(path, "w"))
print(path, q)
PY
}

grade() {
  local batch=$1
  for run in $D/work/$batch/*/; do
    run=${run%/}; name=$(basename "$run"); id=${name%%-*}
    kind_hidden=$(python3 -c "import json,sys; p=[p for p in json.load(open('spike/problems.json')) if p['id']=='$id'][0]; print(p['kind'], p.get('hidden',''))")
    [ "${kind_hidden%% *}" = patch ] || continue
    [ -f "$run/grade.json" ] && continue
    grade_one "$run" "$id" "${kind_hidden#* }"
  done
  harness ingest "$batch"
  harness report "$batch"
}

reference() {  # the graders must tell a real fix (1.0) from no fix (0)
  for p in $(python3 -c "import json; [print(p['id'], p['reference'], p['hidden'], ','.join(p['reference_files'])) for p in json.load(open('spike/problems.json')) if p['kind']=='patch']" | tr ' ' '|'); do
    IFS='|' read -r id ref hidden files <<<"$p"
    for variant in none fix; do
      run=$D/work/_reference/$id-$variant-0; rm -rf "$run"; mkdir -p "$run"; cp -r "$D/base/$id/core" "$run/core"
      if [ $variant = fix ]; then  # the real fix: only the files it changed, as of the reference commit
        git -C "$REPO" archive "$ref" ${files//,/ } | tar -x -C "$run"; fi
      grade_one "$run" "$id" "$hidden"
    done
  done
}

case "${1:-}" in
  setup) setup ;;
  up) up ;;
  down) docker rm -f jarvis-spike-hermes jarvis-spike-openjarvis ;;
  run) harness run "$2" "${3:-3}" ${4:+"$4"} ;;
  report) harness report "$2" ;;
  grade) grade "$2" ;;
  reference) reference ;;
  revoke) echo "DELETE FROM settings_kv WHERE key LIKE 'spike:key:%';" | psql_ && rm -f $D/hermes.env $D/openjarvis.env ;;
  *) sed -n 2,9p "$0"; exit 1 ;;
esac
