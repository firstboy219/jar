"""What JARVIS may change in itself, decided from the REAL diff (Blueprint v4 §3, ADR-047).

Used by the host runner (infra/scripts/self-dev.sh runs `python3 <main checkout>/core/app/selfdev_policy.py`, i.e.
the copy on main — never the copy in the branch being judged) and by jarvis-core's tests. This file is itself in the
protected zone, so a branch cannot loosen the rules it is judged by.

Ladder (T0 skills/n8n/schedules are not code and do not come here):
  T1  performance and small abilities in the backend                    tests + owner approval at the admin page
  T2  larger rebuilds outside the protected zone, Android code, STT/TTS  a design approved at the admin page first,
                                                                         then tests + approval of the result
  T2 display (Android UI, web views)                                      locked until screenshots exist (Phase 4)
  T3  protected zone                                                      humans only; always refused here
Plus, whatever the tier: tests may be added, never weakened or deleted; old migrations are never edited.
"""

import json
import re
import sys

# T3: the admin page (the control point), the host runners, secrets, security and money guards, the build chain.
FORBIDDEN = re.compile(
    r"^(infra/admin/|infra/\.env|infra/scripts/|infra/systemd/|infra/docker-compose\.yml|infra/postgres/|"
    r"infra/android-builder/|infra/hermes/03-jarvis-config|infra/hermes/SOUL\.md|infra/hermes/plugins/|"
    r"infra/ears/Dockerfile|infra/ears/requirements\.txt|infra/spike/|infra/openjarvis/|core/Dockerfile|core/requirements-dev|core/config/|"
    r"core/app/(main|approvals|devices|vault|sensitive|dev|perf|auditor|ops|composition|budget|errors|config|db|"
    r"selfdev_policy|modelrouter|chat_settings|skills_pipeline|gateway|kpi|companies|gm|voice|voice_quality|canvas|spike)\.py|core/app/web/canvas/gestures\.js|"
    r"android/(build\.gradle\.kts|settings\.gradle\.kts|gradle/|gradlew|app/build\.gradle\.kts|app/src/main/AndroidManifest\.xml)|"
    r"\.github/|\.claude/|BRD\.docx)")
# Anything the owner SEES: locked for T2 until before/after screenshots can be shown with the approval.
DISPLAY = re.compile(r"^(android/app/src/main/java/.*/ui/|android/app/src/main/res/|web/|core/app/web/|.*\.(html|css|jinja2?)$)")
TEST_PATH = re.compile(r"^(core/tests/|android/app/src/test/|android/app/src/androidTest/)")
TEST_LINE = re.compile(r"^\s*(async\s+def\s+test_|def\s+test_|@Test\b|@pytest\.mark|assert\b|assert[A-Z]\w*\(|fun\s+`?\w)")
LIMITS = {1: 1500, 2: 6000}   # changed lines (added + deleted)


def parse_numstat(text: str) -> list[dict]:
    """`git diff --numstat` → [{file, added, deleted}] (binary files count as 0/0 but are listed). Pure."""
    out = []
    for line in text.splitlines():
        parts = line.split("\t")
        if len(parts) == 3:
            a, d, f = parts
            out.append({"file": f, "added": int(a) if a.isdigit() else 0, "deleted": int(d) if d.isdigit() else 0})
    return out


def weakened_tests(diff: str, deleted_files: list[str]) -> list[str]:
    """Test files deleted, or test/assertion lines removed or rewritten, in a unified diff. Pure; unit-tested."""
    found = [f"berkas tes dihapus: {f}" for f in deleted_files if TEST_PATH.match(f)]
    current = None
    for line in diff.splitlines():
        if line.startswith("+++ ") or line.startswith("--- "):
            if line.startswith("--- "):
                path = line[4:].strip()
                current = path[2:] if path.startswith("a/") else None
            continue
        if line.startswith("diff --git"):
            m = re.match(r"diff --git a/(\S+) b/", line)
            current = m.group(1) if m else None
            continue
        if current and TEST_PATH.match(current) and line.startswith("-") and TEST_LINE.match(line[1:]):
            found.append(f"{current}: baris tes dihapus/diubah: {line[1:].strip()[:100]}")
    return found


def tier_of(files: list[str]) -> int:
    """1 = backend (and tests/skills/docs), 2 = Android code or a change too large for T1. Pure."""
    return 2 if any(f.startswith("android/") for f in files) else 1


def judge(numstat: list[dict], diff: str, deleted_files: list[str], max_tier: int) -> dict:
    """The runner's verdict. max_tier: 1 normally; 2 only when the owner approved a design for this change AND T2 is
    switched on at the admin page (jarvis-core decides that; protected code). Pure; unit-tested."""
    files = [n["file"] for n in numstat]
    changed = sum(n["added"] + n["deleted"] for n in numstat)
    tier = tier_of(files)
    if tier == 1 and changed > LIMITS[1]:
        tier = 2
    reasons = []
    if not files:
        reasons.append("tidak ada perubahan")
    if bad := [f for f in files if FORBIDDEN.match(f)]:
        reasons.append("zona terlindungi (T3, hanya manusia): " + ", ".join(bad[:12]))
    if weak := weakened_tests(diff, deleted_files):
        reasons.append("tes tidak boleh dilemahkan atau dihapus: " + "; ".join(weak[:6]))
    display = [f for f in files if DISPLAY.match(f)]
    if tier >= 2 and display:
        reasons.append("perubahan tampilan T2 terkunci sampai tangkapan layar sebelum/sesudah tersedia (Fase 4): " + ", ".join(display[:8]))
    if tier > max_tier:
        reasons.append(f"perubahan ini tingkat T{tier} ({changed} baris" + (", menyentuh APK" if tier_of(files) == 2 else "")
                       + ") dan butuh rancangan yang disetujui di halaman admin lebih dulu")
    if changed > LIMITS[2]:
        reasons.append(f"perubahan terlalu besar ({changed} baris > {LIMITS[2]})")
    return {"ok": not reasons, "tier": tier, "changed_lines": changed, "files": files, "display_files": display,
            "reasons": reasons}


if __name__ == "__main__":  # runner: {"numstat": "...", "diff": "...", "deleted": [...], "max_tier": 1} on stdin
    req = json.load(sys.stdin)
    print(json.dumps(judge(parse_numstat(req.get("numstat", "")), req.get("diff", ""), req.get("deleted") or [],
                           int(req.get("max_tier") or 1)), ensure_ascii=False))
