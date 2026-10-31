#!/usr/bin/env python3
"""Pengelola penyimpanan — host part (owner 2026-10-31: "buat kan fitur khusus untuk manager storage sehingga saya tahu mana saja yg bisa
dihapus atau dizip"). Run as root by jarvis-storage.service when jarvis-core writes data/ops/storage.request:

  {"action": "scan"}                            measure the disk and every known space user → data/ops/storage.json
  {"action": "clean", "items": ["pip", …]}      run ONLY the cleanups named in CLEAN below (never a path from the request), then scan again

Each item says what it is, whether it is safe to remove (and what removing costs), or that it is zipped instead, or kept and why. jarvis-core
has no docker socket and no write access to most of these folders on purpose; the owner's approval (the phone's lock) is checked in core.
"""
import json
import os
import re
import shutil
import subprocess
import tarfile
import time
from pathlib import Path

INFRA = Path(__file__).resolve().parents[1]
DATA = INFRA / "data"
OPS = DATA / "ops"
REQ, OUT = OPS / "storage.request", OPS / "storage.json"
KEEP_APKS = 3
OLD_DAYS = 14
GB = 1024 ** 3


def sh(*cmd: str, timeout: int = 900) -> str:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout).stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def du(path: Path) -> int:
    if not path.exists():
        return 0
    out = sh("du", "-sb", str(path), timeout=600).split()
    return int(out[0]) if out and out[0].isdigit() else 0


UNITS = {"B": 1, "kB": 1e3, "KB": 1e3, "MB": 1e6, "GB": 1e9, "TB": 1e12}


def size_of(text: str) -> int:
    """'22.98GB (76%)' / '65.54kB' / '0B' → bytes."""
    m = re.match(r"\s*([\d.]+)\s*([kKMGT]?B)", text or "")
    return int(float(m.group(1)) * UNITS[m.group(2)]) if m else 0


def docker_df() -> dict:
    rows = [json.loads(ln) for ln in sh("docker", "system", "df", "--format", "{{json .}}").splitlines() if ln.strip().startswith("{")]
    return {r.get("Type"): {"size": size_of(r.get("Size", "")), "free": size_of(r.get("Reclaimable", ""))} for r in rows}


def old_apks() -> list[Path]:
    rel = DATA / "releases"
    try:
        index = json.loads((rel / "releases.json").read_text())
    except (OSError, ValueError):
        index = []
    keep = {r.get("file") for r in sorted(index, key=lambda r: r.get("code", 0), reverse=True)[:KEEP_APKS]}
    apks = sorted(rel.glob("jarvis-*.apk"), key=lambda p: p.stat().st_mtime, reverse=True)
    keep |= {p.name for p in apks[:KEEP_APKS]}
    return [p for p in apks if p.name not in keep]


def idle_folders() -> list[Path]:
    """Hermes' workspace folders untouched for two weeks (not the repo copy self-dev uses)."""
    ws, cutoff = DATA / "hermes" / "workspace", time.time() - OLD_DAYS * 86400
    if not ws.is_dir():
        return []
    out = []
    for p in ws.iterdir():
        if p.is_dir() and p.name not in ("jar", "_arsip") and not p.is_symlink():
            newest = max((f.stat().st_mtime for f in p.rglob("*") if f.is_file() and not f.is_symlink()), default=p.stat().st_mtime)
            if newest < cutoff:
                out.append(p)
    return out


def old_logs() -> list[Path]:
    logs, cutoff = DATA / "hermes" / "logs", time.time() - 7 * 86400
    return [f for f in logs.rglob("*") if f.is_file() and not f.is_symlink() and f.suffix != ".gz" and f.stat().st_mtime < cutoff] if logs.is_dir() else []


def journal_bytes() -> int:
    m = re.search(r"take up ([\d.]+)([KMGT])", sh("journalctl", "--disk-usage"))
    return int(float(m.group(1)) * {"K": 1e3, "M": 1e6, "G": 1e9, "T": 1e12}[m.group(2)]) if m else 0


def builder_running() -> bool:
    return bool(sh("docker", "ps", "-q", "--filter", "ancestor=jarvis-android-builder:1").strip())


def wipe(path: Path) -> None:
    """Empty a cache folder (keep the folder itself and its owner)."""
    if path.is_dir() and not path.is_symlink():
        for child in path.iterdir():
            if child.is_dir() and not child.is_symlink():
                shutil.rmtree(child, ignore_errors=True)
            else:
                child.unlink(missing_ok=True)


def zip_folders(folders: list[Path]) -> None:
    arsip = DATA / "hermes" / "workspace" / "_arsip"
    arsip.mkdir(exist_ok=True)
    st = arsip.parent.stat()
    os.chown(arsip, st.st_uid, st.st_gid)
    for p in folders:
        dest = arsip / f"{p.name}-{time.strftime('%Y%m%d')}.tar.gz"
        with tarfile.open(dest, "w:gz") as tar:
            tar.add(p, arcname=p.name)
        os.chown(dest, st.st_uid, st.st_gid)
        shutil.rmtree(p)


def gzip_logs(files: list[Path]) -> None:
    for f in files:
        st = f.stat()
        subprocess.run(["gzip", "-9", "-f", str(f)], check=False)
        gz = f.with_name(f.name + ".gz")
        if gz.exists():
            os.chown(gz, st.st_uid, st.st_gid)


def compose_lock(fn):
    """Docker changes wait for an apply/deploy in progress (the same lock ops.sh and apply.sh take)."""
    def run():
        lock = DATA / "admin" / "compose.lock"
        if lock.exists():
            subprocess.run(["flock", str(lock), "true"], check=False, timeout=1800)
        fn()
    return run


# id → (label, group, how much, what happens when removed, the cleanup); the request may name only these ids
CLEAN = {
    "docker-cache": ("Cache build Docker", "Docker", lambda d: d.get("Build Cache", {}).get("free", 0),
                     "Aman. Build/deploy berikutnya sedikit lebih lama (lapisan diunduh & dibangun ulang).",
                     compose_lock(lambda: sh("docker", "builder", "prune", "-af"))),
    "docker-volumes": ("Volume Docker yatim", "Docker", lambda d: d.get("Local Volumes", {}).get("free", 0),
                       "Aman. Sisa database/Qdrant sementara dari test & pratinjau; data JARVIS ada di folder data/, bukan di volume.",
                       compose_lock(lambda: sh("docker", "volume", "prune", "-f"))),
    "docker-images": ("Image Docker tak terpakai", "Docker",
                      lambda d: sum(size_of(s) for s in sh("docker", "images", "-f", "dangling=true", "--format", "{{.Size}}").split()),
                      "Aman. Image versi lama tanpa nama (hasil build sebelumnya); yang sedang dipakai tidak tersentuh.",
                      compose_lock(lambda: sh("docker", "image", "prune", "-f"))),
    "apk-old": ("APK versi lama", "Aplikasi Android", lambda d: sum(p.stat().st_size for p in old_apks()),
                f"Aman. {KEEP_APKS} versi terbaru tetap ada untuk diunduh; riwayat versinya tetap tercatat.",
                lambda: [p.unlink(missing_ok=True) for p in old_apks()]),
    "gradle": ("Cache Gradle (build APK)", "Aplikasi Android", lambda d: du(DATA / "android" / "gradle-cache"),
               "Aman. Build APK berikutnya mengunduh ulang pustaka Android (±5–10 menit lebih lama).",
               lambda: None if builder_running() else wipe(DATA / "android" / "gradle-cache")),
    "pip": ("Cache unduhan pip Hermes", "Hermes", lambda d: du(DATA / "hermes" / "home" / ".cache" / "pip"),
            "Aman. Hanya salinan unduhan paket Python; paket yang terpasang tetap.", lambda: wipe(DATA / "hermes" / "home" / ".cache" / "pip")),
    "uv": ("Cache uv Hermes", "Hermes", lambda d: du(DATA / "hermes" / "cache" / "uv"),
           "Aman. Cache pemasang paket; dibuat ulang bila perlu.", lambda: wipe(DATA / "hermes" / "cache" / "uv")),
    "npm": ("Cache npm Hermes", "Hermes", lambda d: du(DATA / "hermes" / "home" / ".npm" / "_cacache"),
            "Aman. Cache unduhan paket Node.", lambda: wipe(DATA / "hermes" / "home" / ".npm" / "_cacache")),
    "apt": ("Cache paket sistem (apt)", "Sistem", lambda d: du(Path("/var/cache/apt/archives")),
            "Aman. Paket .deb yang sudah terpasang.", lambda: sh("apt-get", "clean")),
    "journal": ("Log sistem lama (journald)", "Sistem", lambda d: max(0, journal_bytes() - 200_000_000),
                "Aman. Disisakan 200 MB log terbaru.", lambda: sh("journalctl", "--vacuum-size=200M")),
    "workspace-zip": ("Folder kerja Hermes lama → zip", "Hermes", lambda d: sum(du(p) for p in idle_folders()),
                      f"Dizip, tidak dihapus: folder kerja yang tak tersentuh {OLD_DAYS} hari dipadatkan ke workspace/_arsip.",
                      lambda: zip_folders(idle_folders())),
    "logs-zip": ("Log Hermes > 7 hari → gzip", "Hermes", lambda d: sum(f.stat().st_size for f in old_logs()),
                 "Dipadatkan (gzip), isinya tetap bisa dibaca.", lambda: gzip_logs(old_logs())),
}
ZIP = {"workspace-zip", "logs-zip"}

# what stays, and why (shown so he knows it was looked at)
KEEP = [
    ("hermes-lib", "Paket Python Hermes", "Hermes", DATA / "hermes" / "home" / ".local", "Dipakai Hermes untuk alat-alatnya."),
    ("hermes-installs", "Instalasi Hermes", "Hermes", DATA / "hermes" / "installs", "Program Hermes itu sendiri."),
    ("whisper", "Model Whisper (telinga)", "Data JARVIS", DATA / "models", "Dipakai untuk mendengar suara & rapat."),
    ("media", "Lagu & suara", "Data JARVIS", DATA / "media", "Kelola di Musik → Koleksi (hapus per lagu). Lagu di luar koleksi terhapus sendiri setelah 30 hari."),
    ("postgres", "Database", "Data JARVIS", DATA / "postgres", "Seluruh data JARVIS."),
    ("voice", "Rekaman suara", "Data JARVIS", DATA / "voice", "Dibatasi & dibersihkan otomatis oleh JARVIS."),
    ("attachments", "Lampiran obrolan", "Data JARVIS", DATA / "attachments", "Terhapus otomatis setelah 30 hari."),
    ("meetings", "Rekaman rapat", "Data JARVIS", DATA / "meetings", "Bahan transkrip rapat."),
    ("documents", "Dokumen", "Data JARVIS", DATA / "documents", "Dokumen milikmu."),
]


def scan(last: dict | None = None) -> dict:
    total, used, free = shutil.disk_usage("/")
    d = docker_df()
    items = []
    for key, (label, group, measure, note, _) in CLEAN.items():
        try:
            n = int(measure(d))
        except Exception:   # one item failing to measure never stops the rest
            n = 0
        items.append({"id": key, "label": label, "group": group, "bytes": n, "action": "zip" if key in ZIP else "hapus", "note": note})
    for key, label, group, path, note in KEEP:
        items.append({"id": key, "label": label, "group": group, "bytes": du(path), "action": None, "note": note})
    images = d.get("Images", {})
    items.append({"id": "docker-images-used", "label": "Image Docker yang dipakai", "group": "Docker",
                  "bytes": max(0, images.get("size", 0) - images.get("free", 0)), "action": None, "note": "Program JARVIS yang sedang berjalan."})
    return {"at": time.time(), "disk": {"total": total, "used": used, "free": free}, "items": items,
            "can_free": sum(i["bytes"] for i in items if i["action"] == "hapus"), "last": last}


def write(state: dict) -> None:
    tmp = OPS / ".storage.tmp"
    tmp.write_text(json.dumps(state))
    st = (DATA / "hermes").stat()
    os.chown(tmp, st.st_uid, st.st_gid)
    tmp.chmod(0o644)
    tmp.replace(OUT)


def main() -> None:
    if not REQ.exists():
        return
    try:
        req = json.loads(REQ.read_text())
    except (OSError, ValueError):
        req = {"action": "scan"}
    REQ.unlink(missing_ok=True)
    try:
        last = json.loads(OUT.read_text()).get("last")
    except (OSError, ValueError):
        last = None
    if req.get("action") == "clean":
        before_free = shutil.disk_usage("/").free
        done = []
        for key in [k for k in req.get("items", []) if k in CLEAN][:len(CLEAN)]:
            free0 = shutil.disk_usage("/").free
            try:
                CLEAN[key][4]()
                done.append({"id": key, "label": CLEAN[key][0], "ok": True, "freed": max(0, shutil.disk_usage("/").free - free0)})
            except Exception as e:
                done.append({"id": key, "label": CLEAN[key][0], "ok": False, "error": str(e)[:200]})
        last = {"at": time.time(), "request": req.get("at"), "actor": req.get("actor"), "items": done,
                "freed": max(0, shutil.disk_usage("/").free - before_free)}
    write(scan(last))


if __name__ == "__main__":
    main()
