#!/usr/bin/env bash
# Build, test and publish a signed JARVIS APK release.
#   ./scripts/build-apk.sh 0.1.0 "Catatan rilis"
# Output: data/releases/jarvis-<version>.apk + data/releases/releases.json (shown in the web admin → Aplikasi).
set -euo pipefail
cd "$(dirname "$0")/.."
VERSION=${1:?usage: build-apk.sh <version e.g. 0.1.0> "<release notes>"}
NOTES=${2:-}
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

docker build -q -t jarvis-android-builder:1 android-builder >/dev/null
docker run --rm --user "$(stat -c %u:%g ../android)" -e HOME=/tmp \
  -e JARVIS_KEYSTORE_FILE=/keys/release.keystore -e JARVIS_KEYSTORE_PASSWORD="$PASS" \
  -v "$PWD/../android:/src" -v "$PWD/data/android/gradle-cache:/cache/gradle" \
  -v "$PWD/data/android:/keys:ro" \
  jarvis-android-builder:1 \
  ./gradlew --no-daemon -q testReleaseUnitTest verifyPaparazziDebug assembleRelease \
    -PversionName="$VERSION" -PversionCode="$CODE"

APK=data/releases/jarvis-$VERSION.apk
cp ../android/app/build/outputs/apk/release/app-release.apk "$APK"

python3 - "$INDEX" "$VERSION" "$CODE" "$APK" "$NOTES" "$(git -C .. rev-parse --short HEAD)" <<'PY'
import datetime, hashlib, json, os, sys
index, version, code, apk, notes, commit = sys.argv[1:]
releases = json.load(open(index))
releases.insert(0, {
    "version": version, "code": int(code), "file": os.path.basename(apk),
    "size": os.path.getsize(apk), "sha256": hashlib.sha256(open(apk, "rb").read()).hexdigest(),
    "date": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
    "notes": notes, "commit": commit,
})
json.dump(releases, open(index, "w"), indent=2)
PY
echo "published $APK (versionCode $CODE)"
