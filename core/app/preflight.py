"""Preflight for a change to JARVIS' own code (ADR-061): the checks the review of the first attempts kept finding by hand, as one command.

    python3 core/app/preflight.py [--base origin/main]     (run it from the repo / worktree you changed)

Prints one line per check — PASS, WARN (understand it before you go on) or FAIL (fix it) — and exits 1 when anything FAILed.
Stdlib only: coder and qaqa (the dev team, devteam.py) run it in Hermes' workspace before they propose / pass a change, the runner
(infra/scripts/self-dev.sh) still judges the real diff with selfdev_policy on main, so this only saves a round trip.
"""

import re
import subprocess
import sys
from pathlib import Path

try:
    from . import selfdev_policy
except ImportError:   # run as a script
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import selfdev_policy

SHARED_TESTS = re.compile(r"(^|/)(lib\.test\.mjs|notes\.test\.mjs|test_acceptance\.py|test_unit\.py|test_integration\.py)$")
TEST_FILE = re.compile(r"(^|/)(tests?/|test_[^/]*\.py$|[^/]*\.test\.mjs$)")
CODEISH = re.compile(r"[;{}]\s*$|^\s*(const|let|var|function|return|import|def|class|await|assert)\b|^\s*(if|for|while)\s*\(|\w\([^()]*\)\s*;?\s*$")


def check_css(text: str) -> list[str]:
    """Problems in a stylesheet that no test catches (pure; unit-tested): stray leading characters, unbalanced braces, an open comment."""
    problems = []
    body = re.sub(r"/\*.*?\*/", lambda m: "\n" * m.group().count("\n"), text, flags=re.DOTALL)
    if "/*" in body:
        problems.append("komentar /* tidak ditutup")
    for n, line in enumerate(body.splitlines(), 1):
        s = line.strip()
        if s and s[0] in "|\\`~^" or s.startswith(("<<<<<<<", "=======", ">>>>>>>")):
            problems.append(f"baris {n}: karakter nyasar di awal baris: {s[:40]!r}")
    if body.count("{") != body.count("}"):
        problems.append(f"kurung tidak seimbang: {body.count('{')} '{{' dan {body.count('}')} '}}'")
    return problems[:8]


def added_lines(diff: str) -> list[tuple[str, int, str]]:
    """(file, line number, text) of every line a unified diff (-U0) adds. Pure; unit-tested."""
    out, path, new = [], None, 0
    for line in diff.splitlines():
        if line.startswith("+++ "):
            path = line[6:] if line.startswith("+++ b/") else None
        elif line.startswith("@@"):
            m = re.search(r"\+(\d+)", line)
            new = int(m.group(1)) if m else 0
        elif path and line.startswith("+") and not line.startswith("+++"):
            out.append((path, new, line[1:]))
            new += 1
    return out


def lint_added(adds: list[tuple[str, int, str]]) -> list[str]:
    """Leftovers in what was added (pure; unit-tested): debug output, markers, commented-out code, empty blocks."""
    found = []
    by_file: dict[str, list[tuple[int, str]]] = {}
    for path, n, text in adds:
        by_file.setdefault(path, []).append((n, text))
    for path, rows in by_file.items():
        for i, (n, text) in enumerate(rows):
            s = text.strip()
            if re.search(r"\bconsole\.(log|debug)\(|\bdebugger\b", s) and not path.endswith(".md"):
                found.append(f"{path}:{n}: sisa debug ({s[:50]})")
            if re.match(r"^(<<<<<<<|=======$|>>>>>>>)", s):
                found.append(f"{path}:{n}: penanda konflik merge")
            if re.match(r"^(//|#)\s*\S", s) and CODEISH.search(s.lstrip("/# ")) and not re.match(r"^(//|#)\s*(https?:|[A-Z][a-z]+ )", s):
                found.append(f"{path}:{n}: kode yang dikomentari? ({s[:50]})")
            if re.match(r"^(if|else|for|while)\b.*\{\s*$", s) and i + 1 < len(rows) and rows[i + 1][0] == n + 1 and rows[i + 1][1].strip() in ("}", "} else {"):
                found.append(f"{path}:{n}: blok kosong")
            if re.match(r"^(if|else)\b.*\{\s*$", s) and i + 2 < len(rows) and rows[i + 2][1].strip() == "}" and re.match(r"^(//|#)", rows[i + 1][1].strip()):
                found.append(f"{path}:{n}: blok hanya berisi komentar")
    return found[:12]


def sh(*args: str, cwd: str | None = None) -> tuple[int, str]:
    try:
        p = subprocess.run(args, cwd=cwd, capture_output=True, text=True, timeout=300)
        return p.returncode, (p.stdout + p.stderr).strip()
    except (OSError, subprocess.TimeoutExpired) as e:
        return 127, str(e)


def main(argv: list[str]) -> int:
    base = argv[argv.index("--base") + 1] if "--base" in argv else "origin/main"
    results: list[tuple[str, str, str]] = []

    def add(level: str, name: str, detail: str = "") -> None:
        results.append((level, name, detail))

    rc, top = sh("git", "rev-parse", "--show-toplevel")
    if rc:
        print("FAIL repo — jalankan dari dalam repo/worktree git")
        return 1
    root = top.strip()
    rc, _ = sh("git", "rev-parse", "--verify", base, cwd=root)
    if rc:
        print(f"FAIL base — {base} tidak ada (jalankan: git fetch origin)")
        return 1

    _, numstat = sh("git", "diff", "--numstat", f"{base}...HEAD", cwd=root)
    _, names_deleted = sh("git", "diff", "--name-only", "--diff-filter=D", f"{base}...HEAD", cwd=root)
    _, diff = sh("git", "diff", "--no-color", f"{base}...HEAD", cwd=root)
    _, diff0 = sh("git", "diff", "--no-color", "-U0", f"{base}...HEAD", cwd=root)
    stats = selfdev_policy.parse_numstat(numstat)
    files = [n["file"] for n in stats]
    if not files:
        add("FAIL", "perubahan", "tidak ada commit di atas " + base + " — commit pekerjaanmu dulu")
    else:
        add("PASS", "perubahan", f"{len(files)} berkas, {sum(n['added'] + n['deleted'] for n in stats)} baris: {', '.join(files[:6])}")

    _, dirty = sh("git", "status", "--porcelain", cwd=root)
    if dirty:
        add("WARN", "belum di-commit", "; ".join(l.strip() for l in dirty.splitlines()[:6]) + " — bukan bagian commit; pastikan memang tidak perlu")

    verdict = selfdev_policy.judge(stats, diff, [f for f in names_deleted.splitlines() if f], 1)
    if verdict["ok"]:
        add("PASS", "kebijakan", f"tingkat T{verdict['tier']}, {verdict['changed_lines']} baris — boleh diusulkan")
    else:
        for r in verdict["reasons"]:
            add("FAIL", "kebijakan", r)

    rc, mb = sh("git", "merge-base", base, "HEAD", cwd=root)
    rc2, bh = sh("git", "rev-parse", base, cwd=root)
    if rc == 0 and rc2 == 0 and mb.strip() != bh.strip():
        add("WARN", "basis lama", f"{base} sudah maju sejak cabangmu dibuat — jalankan: git fetch origin && git rebase {base}")
    rc, out = sh("git", "merge-tree", "--write-tree", base, "HEAD", cwd=root)
    if rc == 1:
        add("FAIL", "konflik", "cabangmu akan konflik dengan " + base + " (deploy akan gagal): " + "; ".join(l for l in out.splitlines() if "CONFLICT" in l)[:300]
            + f" — git rebase {base}, selesaikan konflik dengan menjaga KEDUA sisi")
    elif rc == 0:
        add("PASS", "konflik", "bisa digabung bersih dengan " + base)

    for f in files:
        p = Path(root, f)
        if not p.is_file():
            continue
        if f.endswith(".css"):
            probs = check_css(p.read_text(errors="replace"))
            add("FAIL" if probs else "PASS", f"css {f}", "; ".join(probs))
        elif f.endswith((".js", ".mjs")):
            rc, out = sh("node", "--check", f, cwd=root)
            add("PASS" if rc == 0 else "FAIL", f"sintaks {f}", out[:240] if rc else "")
        elif f.endswith(".py"):
            rc, out = sh(sys.executable, "-m", "py_compile", f, cwd=root)
            add("PASS" if rc == 0 else "FAIL", f"sintaks {f}", out[:240] if rc else "")

    leftovers = lint_added(added_lines(diff0))
    add("WARN" if leftovers else "PASS", "sisa/kode mati", "; ".join(leftovers))

    sources = [f for f in files if not TEST_FILE.search(f) and f.endswith((".js", ".mjs", ".py")) and not f.startswith("docs/")]
    tests = [f for f in files if TEST_FILE.search(f)]
    if sources and not tests:
        add("WARN", "tes", "kode berubah tapi tidak ada tes baru/diubah — tulis tes untuk perilaku barunya")
    shared = [f for f in tests if SHARED_TESTS.search(f)]
    if shared:
        add("WARN", "tes di berkas bersama", f"{', '.join(shared)} — menambah tes di akhir berkas bersama sering konflik saat deploy; "
            "taruh tes barumu di BERKAS TES BARU (mis. tests/<fitur>.test.mjs atau tests/test_<fitur>.py)")
    for d in ("core/app/web/canvas", "core/app/web/notes"):
        if any(f.startswith(d + "/") for f in files) and Path(root, d, "tests").is_dir():
            rc, out = sh("node", "--test", "tests/", cwd=str(Path(root, d)))
            m = re.search(r"# pass (\d+)", out), re.search(r"# fail (\d+)", out)
            add("PASS" if rc == 0 else "FAIL", f"tes JS {d}", f"lulus {m[0].group(1) if m[0] else '?'}" if rc == 0 else out[-400:])
    if any(f.startswith("core/") and f.endswith(".py") for f in files):
        add("WARN", "tes server", "pytest butuh Postgres: dijalankan penguji otomatis setelah propose; baca log-nya (check_code_change)")

    width = max(len(n) for _, n, _ in results)
    for level, name, detail in results:
        print(f"{level:4} {name:<{width}}  {detail}".rstrip())
    fails = sum(1 for lv, *_ in results if lv == "FAIL")
    print(f"\n{'SIAP DIUSULKAN' if not fails else f'{fails} FAIL — perbaiki dulu'}; {sum(1 for lv, *_ in results if lv == 'WARN')} WARN")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
