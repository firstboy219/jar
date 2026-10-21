#!/usr/bin/env bash
# JARVIS self-improvement runner (ADR-026: performance + minor features). Run as root by jarvis-dev.service when jarvis-core
# drops a request in data/dev/requests/. Never edit this file from the workspace — it is refused.
#
#   test    fetch branch jarvis/<topic> from Hermes' workspace into the live repo (as refs/jarvis/<id>),
#           check it only touches allowed files and stays small, merge it onto main in a throwaway
#           worktree and run the test suites there → results/<id>-test.json
#   deploy  (only after the owner approved the exact tested commit) merge into main, rebuild the services
#           that changed, health-check; on failure reset main and redeploy; on success push to GitHub and
#           publish an APK if android/ changed → results/<id>-deploy.json
#
# Safety: git never runs INSIDE the workspace (a planted .git/config or hook there must not execute on the
# host); objects are only fetched from it into the live repo. Hermes reads current main from a root-owned
# mirror outside its data directory, mounted read-only (it can neither modify it nor plant hooks in it).
set -uo pipefail
cd "$(dirname "$0")/.."
INFRA=$PWD
REPO=$(cd .. && pwd)
DEV=$INFRA/data/dev
WS=$INFRA/data/hermes/workspace/jar
MIRROR=$INFRA/data/dev-mirror/upstream.git   # root-owned, mounted read-only into Hermes at /opt/upstream.git
OWNER=$(stat -c %U "$REPO")
# root reads the owner's repo (and the mirror fetches from it): trust exactly that repo, nothing else (never the workspace)
export GIT_CONFIG_COUNT=2 GIT_CONFIG_KEY_0=safe.directory GIT_CONFIG_VALUE_0=$REPO GIT_CONFIG_KEY_1=safe.directory GIT_CONFIG_VALUE_1=$REPO/.git
MAX_CHANGED_LINES=1500
# Out of scope for self-improvement (security, permissions, secrets, money guards, build/supply chain, itself)
FORBIDDEN='^(infra/\.env|infra/scripts/|infra/systemd/|infra/docker-compose\.yml|infra/postgres/|infra/android-builder/|infra/hermes/03-jarvis-config|infra/hermes/SOUL\.md|infra/hermes/plugins/|infra/admin/app/(auth|main)\.py|infra/admin/Dockerfile|infra/ears/Dockerfile|infra/ears/requirements\.txt|core/Dockerfile|core/requirements-dev|core/app/(main|approvals|devices|vault|sensitive|dev|perf|auditor|composition|budget|errors|config|db)\.py|android/(build\.gradle\.kts|settings\.gradle\.kts|gradle/|gradlew|app/build\.gradle\.kts|app/src/main/AndroidManifest\.xml)|\.github/|\.claude/|BRD\.docx)'

mkdir -p "$DEV/requests" "$DEV/results" "$DEV/done"
as_owner() { runuser -u "$OWNER" -- "$@"; }
log() { echo "[$(date -Is)] $*"; }

result() { # file json-fields...
  python3 - "$@" <<'PY'
import json, sys
out, pairs = sys.argv[1], sys.argv[2:]
data = {}
for p in pairs:
    k, _, v = p.partition("=")
    if v.startswith("@"):
        try:
            v = open(v[1:], errors="replace").read()[-20000:]
        except OSError:
            v = ""
    data[k] = v
for k in ("files", "deps"):
    if k in data:
        data[k] = [f for f in data[k].splitlines() if f]
if "id" in data:
    data["id"] = int(data["id"])
tmp = out + ".tmp"
json.dump(data, open(tmp, "w"))
import os; os.rename(tmp, out)
PY
}

refresh_mirror() { # current main for Hermes (read-only mount)
  mkdir -p "$(dirname "$MIRROR")"; chown root:root "$(dirname "$MIRROR")"; chmod 755 "$(dirname "$MIRROR")"
  [[ -d $MIRROR ]] || git init -q --bare "$MIRROR"
  git -C "$REPO" push -q --force "$MIRROR" main:main  # receive-pack runs in the root-owned mirror
  chmod -R go-w,a+rX "$MIRROR"
}

ensure_workspace() {
  # the mirror is root-owned; Hermes' git (HOME=/opt/data) must be told to read it
  as_owner git config --file "$INFRA/data/hermes/.gitconfig" --get-all safe.directory 2>/dev/null | grep -qx /opt/upstream.git \
    || as_owner git config --file "$INFRA/data/hermes/.gitconfig" --add safe.directory /opt/upstream.git
  [[ -d $WS/.git ]] && return
  mkdir -p "$(dirname "$WS")"
  refresh_mirror
  as_owner git clone -q "$REPO" "$WS"
  as_owner git -C "$WS" remote set-url origin /opt/upstream.git
  as_owner git -C "$WS" checkout -q -b jarvis-main
  as_owner git -C "$WS" config user.name "JARVIS (Hermes)"
  as_owner git -C "$WS" config user.email "jarvis@vis1.cosger.online"
}

test_steps() { # uses id branch wt; sets commit files diffstat deps
    [[ $branch =~ ^jarvis/[a-z0-9][a-z0-9-]{2,60}$ ]] || { echo "nama cabang tidak valid"; return 1; }
    as_owner git -C "$REPO" fetch -q --no-tags "$WS" "+refs/heads/$branch:refs/jarvis/$id" || { echo "cabang $branch tidak ada di workspace"; return 1; }
    commit=$(git -C "$REPO" rev-parse "refs/jarvis/$id")
    files=$(git -C "$REPO" diff --name-only "main...refs/jarvis/$id")
    diffstat=$(git -C "$REPO" diff --stat "main...refs/jarvis/$id" | tail -40)
    [[ -n $files ]] || { echo "tidak ada perubahan"; return 1; }
    if bad=$(grep -E "$FORBIDDEN" <<<"$files"); then echo "DITOLAK — di luar batas perbaikan performa:"; echo "$bad"; return 1; fi
    if edited=$(git -C "$REPO" diff --name-only --diff-filter=MDR "main...refs/jarvis/$id" -- core/app/migrations); [[ -n $edited ]]; then
      echo "DITOLAK — migrasi lama tidak boleh diubah: $edited"; return 1; fi
    changed=$(git -C "$REPO" diff --numstat "main...refs/jarvis/$id" | awk '{a+=$1; d+=$2} END {print a+d}')
    (( changed <= MAX_CHANGED_LINES )) || { echo "DITOLAK — perubahan terlalu besar ($changed baris > $MAX_CHANGED_LINES)"; return 1; }
    if grep -qx 'core/requirements.txt' <<<"$files"; then  # new packages: pinned exactly, shown to the owner
      deps=$(git -C "$REPO" diff "main...refs/jarvis/$id" -- core/requirements.txt | grep '^+[^+]' | cut -c2- | grep -v '^[[:space:]]*$')
      if [[ -n $deps ]] && bad=$(grep -vE '^[A-Za-z0-9][A-Za-z0-9._-]*(\[[A-Za-z0-9,._-]+\])?==[0-9][A-Za-z0-9.+!-]*$' <<<"$deps"); then
        echo "DITOLAK — pustaka harus dipin persis (nama==versi), tanpa opsi pip/URL:"; echo "$bad"; return 1; fi
      echo "== pustaka baru/berubah:"; echo "$deps"
    fi
    echo "== $changed baris berubah; file:"; echo "$files"
    rm -rf "$wt"
    as_owner git -C "$REPO" worktree add -q --detach "$wt" main
    as_owner git -C "$wt" -c user.name=runner -c user.email=runner@local merge -q --no-edit "refs/jarvis/$id" \
      || { echo "KONFLIK dengan main — di workspace jalankan: git fetch origin main && git rebase origin/main, lalu ajukan lagi"; return 1; }
    echo "== tes server"
    CORE_DIR="$wt/core" "$INFRA/scripts/test-core.sh" -q 2>&1 | tail -40
    [[ ${PIPESTATUS[0]} -eq 0 ]] || { echo "TES SERVER GAGAL"; return 1; }
    for f in $(grep -E '\.py$' <<<"$files"); do
      [[ -f $wt/$f ]] && { python3 -m py_compile "$wt/$f" || { echo "sintaks Python salah: $f"; return 1; }; }
    done
    if grep -q '^android/' <<<"$files"; then
      echo "== tes Android"
      docker run --rm --user "$(stat -c %u:%g "$REPO/android")" -e HOME=/tmp -v "$wt/android:/src" \
        -v "$INFRA/data/android/gradle-cache:/cache/gradle" jarvis-android-builder:1 \
        ./gradlew --no-daemon -q testReleaseUnitTest verifyPaparazziDebug 2>&1 | tail -40
      [[ ${PIPESTATUS[0]} -eq 0 ]] || { echo "TES ANDROID GAGAL"; return 1; }
    fi
}

do_test() { # id branch
  local id=$1 branch=$2 L=$DEV/results/$1-test.log wt=/tmp/jarvis-dev-$1 status=failed commit="" files="" diffstat="" deps=""
  : > "$L"
  test_steps >>"$L" 2>&1 && status=passed
  as_owner git -C "$REPO" worktree remove --force "$wt" >/dev/null 2>&1; rm -rf "$wt"
  [[ $status == passed ]] && echo "== SEMUA TES LULUS" >>"$L"
  printf '%s\n' "$files" > "$L.files"; printf '%s\n' "$deps" > "$L.deps"
  result "$DEV/results/$id-test.json" id="$id" action=test status="$status" commit="$commit" files="@$L.files" \
    deps="@$L.deps" diffstat="$diffstat" log="@$L"
  rm -f "$L.files" "$L.deps"
}

services_for() { # files → compose services to rebuild
  local s=""
  grep -q '^core/' <<<"$1" && s+=" jarvis-core jarvis-tools"
  grep -q '^infra/admin/' <<<"$1" && s+=" admin"
  grep -q '^infra/ears/' <<<"$1" && s+=" jarvis-ears"
  echo "$s"
}

healthy() {
  sleep 25
  docker exec jarvis-core python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8000/healthz',timeout=10).status==200 else 1)" \
    && docker exec jarvis-admin python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8000/healthz',timeout=10).status==200 else 1)"
}

deploy_steps() { # uses id want; sets status apk err
    local have; have=$(git -C "$REPO" rev-parse "refs/jarvis/$id" 2>/dev/null)
    [[ -n $want && $have == "$want" ]] || { err="commit yang disetujui tidak cocok dengan yang diuji"; echo "$err"; return 1; }
    [[ -z $(git -C "$REPO" status --porcelain --untracked-files=no) ]] || { err="repo server sedang punya perubahan lain yang belum di-commit"; echo "$err"; return 1; }
    local prev; prev=$(git -C "$REPO" rev-parse main)
    local files; files=$(git -C "$REPO" diff --name-only "main...refs/jarvis/$id")
    local title; title=$(git -C "$REPO" log -1 --format=%s "refs/jarvis/$id")
    as_owner git -C "$REPO" merge -q --no-ff -m "JARVIS performance improvement #$id: $title

Tested by infra/scripts/self-dev.sh and approved by the owner (approval in jarvis-core).

Co-Authored-By: JARVIS (Hermes) <jarvis@vis1.cosger.online>" "refs/jarvis/$id" || { as_owner git -C "$REPO" merge --abort; err="merge gagal"; return 1; }
    local svc; svc=$(services_for "$files")
    if [[ -n $svc ]]; then
      echo "== deploy:$svc"
      flock "$INFRA/data/admin/compose.lock" docker compose -f "$INFRA/docker-compose.yml" up -d --build $svc 2>&1 | tail -15
    fi
    if grep -q '^infra/hermes/skills/' <<<"$files"; then "$INFRA/scripts/install-skills.sh" | tail -2; fi
    if [[ -n $svc ]] && ! healthy; then
      echo "== CEK KESEHATAN GAGAL — kembali ke $prev"
      as_owner git -C "$REPO" reset -q --hard "$prev"
      flock "$INFRA/data/admin/compose.lock" docker compose -f "$INFRA/docker-compose.yml" up -d --build $svc 2>&1 | tail -5
      status=rolled_back
      return 1
    fi
    if grep -q '^android/' <<<"$files"; then
      apk=$(python3 -c "import json;r=json.load(open('$INFRA/data/releases/releases.json'));v=max(r,key=lambda x:x['code'])['version'].split('.');print(f'{v[0]}.{v[1]}.{int(v[2])+1}')")
      echo "== APK $apk"
      "$INFRA/scripts/build-apk.sh" "$apk" "Perbaikan performa otomatis: $title" 2>&1 | tail -3 || { echo "build APK gagal (server tetap jalan)"; apk=""; }
    fi
    as_owner git -C "$REPO" push -q origin main 2>&1 | tail -2 || echo "push ke GitHub gagal (perubahan tetap aktif)"
    refresh_mirror
    status=deployed
}

do_deploy() { # id commit
  local id=$1 want=$2 L=$DEV/results/$1-deploy.log status=deploy_failed apk="" err=""
  : > "$L"
  deploy_steps >>"$L" 2>&1
  result "$DEV/results/$id-deploy.json" id="$id" action=deploy status="$status" apk_version="$apk" error="$err" log="@$L"
}

ensure_workspace
refresh_mirror
for req in $(ls -1 "$DEV/requests"/*.json 2>/dev/null | sort -V); do
  read -r id action branch commit < <(python3 -c "import json,sys;d=json.load(open(sys.argv[1]));print(d.get('id',''),d.get('action',''),d.get('branch','-'),d.get('commit','-'))" "$req")
  mv "$req" "$DEV/done/$(basename "$req")"
  log "request #$id $action $branch"
  case $action in
    test) do_test "$id" "$branch" ;;
    deploy) do_deploy "$id" "$commit" ;;
  esac
done
chown -R "$(stat -c %u:%g "$INFRA/data/hermes")" "$DEV" 2>/dev/null
exit 0
