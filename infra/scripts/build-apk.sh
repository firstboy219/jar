#!/usr/bin/env bash
# Build, test and publish a signed JARVIS APK release.
#   ./scripts/build-apk.sh 0.1.0 "Catatan rilis"
#   ./scripts/build-apk.sh 0.14.3 "Kembali ke 0.14.0" --android-from <commit>   (rollback, ADR-047)
# Rollback: Android refuses to install a LOWER versionCode over a higher one, so going back means rebuilding the
# android/ tree of an earlier release (its commit is in releases.json) as a NEW version with the next versionCode;
# the app's updater (ADR-025: /api/v1/app/latest + SHA-256) then offers it like any update.
# Output: data/releases/jarvis-<version>.apk + data/releases/releases.json (shown in the web admin → Aplikasi).
set -euo pipefail
cd "$(dirname "$0")/.."
VERSION=${1:?usage: build-apk.sh <version e.g. 0.1.0> "<release notes>"}
NOTES=${2:-}
FROM=""
[[ ${3:-} == --android-from ]] && FROM=${4:?commit for --android-from}
[[ $VERSION =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || { echo "version must be MAJOR.MINOR.PATCH"; exit 1; }

PASS=$(grep '^ANDROID_KEYSTORE_PASSWORD=' .env | cut -d= -f2)
[[ -n $PASS && -f data/android/release.keystore ]] || { echo "missing keystore or ANDROID_KEYSTORE_PASSWORD"; exit 1; }
mkdir -p data/releases data/android/gradle-cache
INDEX=data/releases/releases.json
[[ -f $INDEX ]] || echo '[]' > "$INDEX"

CODE=$(python3 - "$INDEX" "$VERSION" <<'PY'
import json, sys
releases = json.load(open(sys.argv[1]))
if any(r["version"] == sys.argv[2] for r in releases):
    sys.exit(f"version {sys.argv[2]} already released")
print(max((r["code"] for r in releases), default=0) + 1)
PY
)

SRC=$PWD/../android
if [[ -n $FROM ]]; then  # rollback: the android tree of that commit, built in a throwaway worktree
  git -C .. cat-file -e "$FROM^{commit}" 2>/dev/null || { echo "commit $FROM tidak ada"; exit 1; }
  RB=$(mktemp -d /tmp/jarvis-apk-rollback.XXXXXX); trap 'git -C .. worktree remove --force "$RB" >/dev/null 2>&1; rm -rf "$RB"' EXIT
  git -C .. worktree add -q --detach "$RB" "$FROM"
  chown -R "$(stat -c %u:%g ../android)" "$RB"
  SRC=$RB/android
fi
docker build -q -t jarvis-android-builder:1 android-builder >/dev/null
docker run --rm --user "$(stat -c %u:%g ../android)" -e HOME=/tmp \
  -e JARVIS_KEYSTORE_FILE=/keys/release.keystore -e JARVIS_KEYSTORE_PASSWORD="$PASS" \
  -v "$SRC:/src" -v "$PWD/data/android/gradle-cache:/cache/gradle" \
  -v "$PWD/data/android:/keys:ro" \
  jarvis-android-builder:1 \
  ./gradlew --no-daemon -q testReleaseUnitTest verifyPaparazziDebug assembleRelease \
    -PversionName="$VERSION" -PversionCode="$CODE"

APK=data/releases/jarvis-$VERSION.apk
cp "$SRC/app/build/outputs/apk/release/app-release.apk" "$APK"
# AGP drops v1 (JAR) signing when minSdk >= 24; some OEM installers (e.g. Transsion XOS) still want it.
docker run --rm --user "$(stat -c %u:%g ../android)" -e KSPASS="$PASS" \
  -v "$PWD/data/android:/keys:ro" -v "$PWD/data/releases:/out" jarvis-android-builder:1 \
  /opt/android-sdk/build-tools/35.0.0/apksigner sign --ks /keys/release.keystore --ks-key-alias jarvis \
    --ks-pass env:KSPASS --key-pass env:KSPASS \
    --v1-signing-enabled true --v2-signing-enabled true --v3-signing-enabled true "/out/$(basename "$APK")"
rm -f "$APK.idsig"
chown -R "$(stat -c %u:%g ../android)" data/releases

COMMIT=${FROM:-$(git -C .. rev-parse HEAD)}
DIRTY=$([[ -z $FROM && -n $(git -C .. status --porcelain -- android) ]] && echo 1 || echo 0)  # built from uncommitted code: not reproducible
python3 - "$INDEX" "$VERSION" "$CODE" "$APK" "$NOTES" "$(git -C .. rev-parse --short "$COMMIT")" "$DIRTY" "$FROM" <<'PY'
import datetime, hashlib, json, os, sys
index, version, code, apk, notes, commit, dirty, rollback_of = sys.argv[1:]
releases = json.load(open(index))
releases.insert(0, {
    "version": version, "code": int(code), "file": os.path.basename(apk),
    "size": os.path.getsize(apk), "sha256": hashlib.sha256(open(apk, "rb").read()).hexdigest(),
    "date": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
    "notes": notes, "commit": commit, "reproducible": dirty != "1",
    **({"rollback_to_commit": rollback_of} if rollback_of else {}),
})
json.dump(releases, open(index, "w"), indent=2)
PY
echo "published $APK (versionCode $CODE)"
