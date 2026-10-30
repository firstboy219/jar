"""JARVIS operates an app on the owner's phone (ADR-077) — first Gojek — through the JARVIS app's accessibility service.

The phone reads the app's screen (the accessibility tree: buttons, texts, fields) and does what core says: tap, type, scroll, back, open.
Core runs the loop: show the model the screen, take ONE action from it, look again — as an ordinary worker task (desk card, progress,
stop, report, episode), so everything the owner sees for a worker applies.

Every run needs the owner's approval in the JARVIS app WITH THE ADMIN PASSWORD (main.py checks it) — except a run the owner scheduled
(a project's schedule). Never done for the owner, scheduled or not: typing a PIN / password / OTP (the run waits for the owner to type it),
acting in any other app than the approved one, top-ups, transfers, account settings. The phone's service enforces the app too.
"""

import asyncio
import json
import logging
import re
import time
import uuid

from . import audit, db, hub, llm
from .routines import screen_words

log = logging.getLogger("jarvis-core.phone_agent")

APPS = {
    "gojek": {"label": "Gojek", "packages": ["com.gojek.app"],
              "words": r"gojek|go-?jek|go-?ride|go-?car|go-?food|go-?send|go-?mart|go-?box|go-?bluebird|go-?pulsa|go-?tagihan",
              "hint": "Beranda Gojek berisi tombol layanan (GoRide, GoCar, GoFood, GoSend, GoMart). Tujuan/alamat diisi di kolom pencarian "
                      "'Mau ke mana?'; pilih hasil yang paling cocok, lalu periksa tarif dan metode bayar sebelum memesan."},
    # ADR-087 (owner 2026-10-29): coffee paid with GoPay — the payment screen may open in GoPay/Gojek; the owner types the PIN there
    "kopikenangan": {"label": "Kopi Kenangan", "packages": ["com.kopikenangan", "com.gojek.gopay", "com.gojek.app"], "words": r"kopi ?kenangan",
                     "hint": "Kopi Kenangan: menu di tab Menu/Order; pilih outlet (Pick Up) atau Delivery; promo & voucher di halaman Voucher/Promo atau "
                             "saat checkout. Bayar dengan GoPay: layar pembayaran bisa pindah ke GoPay/Gojek — PIN diketik pemilik."},
    "qpon": {"label": "Qpon", "packages": ["com.qpon.platform", "com.gojek.gopay", "com.gojek.app"], "words": r"qpon",
             "hint": "Qpon (aplikasi kupon diskon): cari merchant/menu di kolom pencarian, lihat kupon dengan harga diskon, beli kupon lalu bayar "
                     "(GoPay: PIN diketik pemilik); kupon dipakai di outlet."},
    "jobstreet": {"label": "JobStreet", "packages": ["com.jobstreet.jobstreet"], "words": r"job ?street",
                  "hint": "JobStreet: cari lowongan dengan kolom pencarian (judul + perusahaan) atau buka tautannya; di halaman lowongan tekan Lamar / Lamar Cepat, "
                          "pilih CV yang tersimpan, isi surat lamaran, jawab pertanyaan penyaringan, lalu Kirim lamaran. Jangan ubah profil."},
    "pluang": {"label": "Pluang", "packages": ["com.EmasDigi"], "words": r"pluang",
               "hint": "Pluang: Beranda menunjukkan total portofolio; tab Portofolio/Aset berisi tiap aset (emas, saham AS, kripto, reksa dana) dengan "
                       "nilai dan untung/rugi. Membeli: pilih aset → Beli → isi nominal Rupiah → periksa harga & ringkasan → konfirmasi; menjual sama "
                       "dengan Jual. Jangan Top Up/Tarik saldo. PIN diketik pemilik."},
    # ADR-087 batch H (owner 2026-10-30: "visit langsung ke webnya"): the phone's browser, only on these sites — booking a cinema seat goes up to
    # the sign-in / payment page and stops there (the owner signs in and pays himself)
    "web": {"label": "Browser HP", "packages": ["com.android.chrome"], "words": r"21 ?cineplex|\bcgv\b|cin[eé]polis|situs bioskop",
            "sites": ["21cineplex.com", "cgv.id", "cinepolis.co.id", "kci.id", "commuterline.id"], "home": "https://21cineplex.com/",
            "hint": "Browser Chrome di HP, hanya di situs bioskop/KRL yang diizinkan. Pilih kota → bioskop → film → tanggal → jam → jumlah & kursi; "
                    "lanjutkan sampai halaman masuk akun atau pembayaran, lalu BERHENTI dan laporkan: pemilik yang masuk akun dan membayar sendiri."},
}
PAY_WORDS = re.compile(r"\b(bayar sekarang|pay now|konfirmasi pembayaran|lanjut(kan)? (ke )?pembayaran|checkout|proceed to payment|buy now|beli sekarang)\b", re.I)
MARK = "[OPERASI-HP]"
CAP = "phone_agent"                  # what a JARVIS app with the accessibility service says it can do (X-App-Caps)
APPROVAL_MINUTES = 15
MAX_STEPS = 45
MAX_MINUTES = 15
OP_TIMEOUT = 25
OFFLINE_WAIT_S = 300                 # at the start of a run: how long to wait for the owner to open the app (ADR-086)
ONLINE_WAIT_S = 30                   # how long an instruction waits for the phone to be connected
PIN_WAIT_S = 240                     # how long a run waits for the owner to type a PIN / OTP themself
SECRET_WORDS = re.compile(r"\b(pin|otp|kata sandi|password|kode verifikasi|kode otp|verification code|masukkan kode)\b", re.IGNORECASE)
FORBIDDEN = re.compile(r"\b(top ?up|isi saldo|transfer|kirim saldo|tarik tunai|hapus akun|keluar akun|logout|ubah pin|ganti pin|"
                       r"tambah kartu|paylater|pinjam)\b", re.IGNORECASE)

_waiting: dict[str, asyncio.Future] = {}
_learning: set = set()   # routines being learned in the background (ADR-083)
_lock = asyncio.Lock()


class PhoneError(RuntimeError):
    pass


class PhoneOpError(PhoneError):
    """The phone answered an instruction with an error (wrong screen, no such element …): the model is told and tries something else."""


# ---------- pure parts (unit-tested) ----------

def detect_app(text: str) -> str | None:
    """Which supported app a request is about ("pesankan gofood nasi padang" → 'gojek')."""
    for key, a in APPS.items():
        if re.search(rf"\b({a['words']})\b", text or "", re.IGNORECASE):
            return key
    return None


def screen_text(obs: dict, limit: int = 9000) -> str:
    """The phone's screen as the model reads it: one numbered line per element it can see or use."""
    lines = [f"Aplikasi di depan: {obs.get('package') or '?'}" + (" · keyboard terbuka" if obs.get("keyboard") else "")]
    for n in obs.get("nodes") or []:
        kind = {"Button": "Tombol", "ImageButton": "Tombol", "EditText": "Kolom isian", "CheckBox": "Kotak centang", "Switch": "Saklar",
                "RadioButton": "Pilihan", "TextView": "Teks", "ImageView": "Gambar"}.get(n.get("c") or "", n.get("c") or "Elemen")
        label = " · ".join(x for x in (n.get("t"), n.get("d"), n.get("h") and f"petunjuk: {n['h']}") if x)
        tags = [t for t, on in (("klik", n.get("k")), ("isi", n.get("e")), ("gulir", n.get("s")), ("RAHASIA", n.get("p")),
                                ("tercentang", n.get("ch")), ("dipilih", n.get("sel"))) if on]
        lines.append(f"[{n.get('i')}] {kind}" + (f' "{label[:140]}"' if label else "") + (f" ‹{', '.join(tags)}›" if tags else ""))
    text = "\n".join(lines)
    return text if len(text) <= limit else text[:limit] + "\n… (layar dipotong — gulir untuk melihat sisanya)"


def is_secret_screen(obs: dict) -> bool:
    """A PIN / password / OTP screen: the owner types it, never JARVIS."""
    nodes = obs.get("nodes") or []
    if any(n.get("p") for n in nodes):
        return True
    editable = [n for n in nodes if n.get("e")]
    words = " ".join(str(n.get(k) or "") for n in nodes for k in ("t", "d", "h"))
    return bool(SECRET_WORDS.search(words)) and (bool(editable) or bool(obs.get("keyboard")) or
                                               sum(1 for n in nodes if re.fullmatch(r"\d", str(n.get("t") or ""))) >= 9)


def in_app(obs: dict, app: str) -> bool:
    return (obs.get("package") or "") in APPS[app]["packages"]


def node(obs: dict, index) -> dict | None:
    try:
        i = int(index)
    except (TypeError, ValueError):
        return None
    return next((n for n in obs.get("nodes") or [] if n.get("i") == i), None)


def check_action(name: str, args: dict, obs: dict, app: str) -> str | None:
    """Why this action may not be done on this screen (None = go ahead). Pure; unit-tested."""
    if name in ("ketuk", "ketik", "gulir") and not in_app(obs, app):
        return f"layar yang terbuka bukan {APPS[app]['label']} — pakai buka_aplikasi atau kembali dulu"
    if name in ("ketuk", "ketik"):
        n = node(obs, args.get("nomor"))
        if not n:
            return f"tidak ada elemen nomor {args.get('nomor')} di layar ini"
        if name == "ketik" and (n.get("p") or is_secret_screen(obs)):
            return "ini kolom PIN/kata sandi/OTP — JARVIS tidak pernah mengetiknya; pemilik yang mengisi"
        label = " ".join(str(n.get(k) or "") for k in ("t", "d"))
        if name == "ketuk" and FORBIDDEN.search(label):
            return f"\"{label.strip()[:60]}\" di luar izin (isi saldo, transfer, akun, kartu, pinjaman) — tidak boleh"
        if name == "ketuk" and app == "web" and PAY_WORDS.search(label):
            return f"\"{label.strip()[:60]}\": pembayaran di situs dilakukan pemilik sendiri — berhenti di sini dan laporkan"
    if name == "ketik" and len(str(args.get("teks") or "")) > 500:
        return "teks terlalu panjang"
    return None


def approval_card(run: dict) -> dict:
    """What the phone shows to ask for approval."""
    a = APPS.get(run["app"], {"label": run["app"]})
    return {"type": "phone_approval", "id": run["id"], "app": run["app"], "label": a["label"], "goal": run["goal"],
            "requested_by": run["requested_by"], "status": run["status"],
            "expires_in_s": max(0, int(APPROVAL_MINUTES * 60 - (time.time() - run["created_at"].timestamp()))) if run.get("created_at") else APPROVAL_MINUTES * 60}


# ---------- runs and approval ----------

async def _row(run_id: int) -> dict | None:
    r = await db.pool().fetchrow("SELECT * FROM phone_runs WHERE id = $1", run_id)
    return dict(r) if r else None


async def _set(run_id: int, **cols) -> None:
    sets = ", ".join(f"{k} = ${i + 2}" for i, k in enumerate(cols))
    await db.pool().execute(f"UPDATE phone_runs SET {sets}, updated_at = now() WHERE id = $1", run_id, *cols.values())


async def request(goal: str, app: str, actor: str, session_id: str | None = None, scheduled: bool = False,
                  project: dict | None = None, by: str = "jadwal") -> dict:
    """A run of `app` for `goal`: asked for approval in the JARVIS app (admin password) — or started at once when it comes from one of the
    owner's projects (`scheduled`: its schedule or his ▶ Jalankan; `by` says which, ADR-079)."""
    goal = " ".join((goal or "").split())[:1500]
    if app not in APPS:
        raise PhoneError(f"aplikasi belum didukung: {app} (yang bisa: {', '.join(a['label'] for a in APPS.values())})")
    if len(goal) < 5:
        raise PhoneError("tulis apa yang harus dikerjakan di aplikasinya")
    p = project or {}
    row = dict(await db.pool().fetchrow(
        """INSERT INTO phone_runs (app, goal, scheduled, requested_by, session_id, project_id, project_role, project_run, model_override)
           VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9) RETURNING *""",
        app, goal, scheduled, actor, session_id, p.get("project_id"), p.get("role_id"), p.get("run"), p.get("model")))
    await audit.record(actor, "phone.requested", f"phone_run:{row['id']}", app=app, scheduled=scheduled)
    if scheduled:
        return await _start(row, by)
    await hub.broadcast(approval_card(row))
    return row


async def pending() -> list[dict]:
    await db.pool().execute(
        "UPDATE phone_runs SET status = 'expired', updated_at = now() WHERE status = 'awaiting' AND created_at < now() - make_interval(mins => $1)",
        APPROVAL_MINUTES)
    return [dict(r) for r in await db.pool().fetch("SELECT * FROM phone_runs WHERE status = 'awaiting' ORDER BY id")]


async def recent(limit: int = 20) -> list[dict]:
    return [dict(r) for r in await db.pool().fetch("SELECT * FROM phone_runs ORDER BY id DESC LIMIT $1", limit)]


async def approve(run_id: int, actor: str) -> dict:
    """The owner approved in the app (main.py has checked the admin password)."""
    await pending()   # expire the stale ones first
    row = await _row(run_id)
    if not row:
        raise PhoneError("permintaan tidak ditemukan")
    if row["status"] != "awaiting":
        raise PhoneError({"expired": "permintaan ini sudah kedaluwarsa — minta lagi"}.get(row["status"], f"permintaan ini sudah {row['status']}"))
    return await _start(row, actor)


async def reject(run_id: int, actor: str) -> bool:
    done = (await db.pool().execute(
        "UPDATE phone_runs SET status = 'rejected', approved_by = $2, updated_at = now() WHERE id = $1 AND status = 'awaiting'",
        run_id, actor)).endswith("1")
    if done:
        await audit.record(actor, "phone.rejected", f"phone_run:{run_id}")
        await hub.broadcast({"type": "phone_approval", "id": run_id, "status": "rejected"})
    return done


async def _start(row: dict, actor: str) -> dict:
    from . import workers
    a = APPS[row["app"]]
    await db.pool().execute("UPDATE phone_runs SET status = 'approved', approved_by = $2, approved_at = now(), updated_at = now() WHERE id = $1",
                            row["id"], actor)
    await audit.record(actor, "phone.approved", f"phone_run:{row['id']}", app=row["app"])
    t = await workers.spawn(f"{a['label']}: {row['goal'][:80]}", f"{MARK}{json.dumps({'run': row['id']})}\n{row['goal']}",
                            row["session_id"] or "phone", row["requested_by"], category="hp")
    if row["project_id"]:
        await db.pool().execute("UPDATE tasks SET project_id = $2, project_role = $3, project_run = $4, model_override = $5 WHERE id = $1",
                                t["id"], row["project_id"], row["project_role"], row["project_run"], row["model_override"])
    await _set(row["id"], task_id=t["id"])
    await hub.broadcast({"type": "phone_approval", "id": row["id"], "status": "approved", "task_id": t["id"]})
    if actor in ("jadwal", "proyek"):   # nobody approved it just now: say it begins (the banner on the screen has "Hentikan")
        await hub.broadcast({"type": "notify", "title": f"JARVIS mengoperasikan {a['label']}", "kind": "phone",
                             "text": f"{row['goal'][:160]} — ada tombol Hentikan di spanduk layar."})
    return {**row, "status": "approved", "task_id": t["id"]}


# ---------- the phone link ----------

def phone_online() -> bool:
    return any(CAP in (c.get("caps") or []) for c in hub.clients())


async def wait_online(seconds: int = ONLINE_WAIT_S) -> bool:
    """The phone's link drops and comes back (app reopened, mobile data): give it a moment before giving up."""
    end = time.monotonic() + seconds
    while not phone_online() and time.monotonic() < end:
        await asyncio.sleep(1)
    return phone_online()


async def op(name: str, *, wait: float | None = None, **args) -> dict:
    """One instruction to the phone's accessibility service; its answer (a fresh screen for most). `wait`: how long the phone may take
    (a web page that loads and settles on the phone needs longer than a tap)."""
    if not await wait_online():
        raise PhoneError("HP dengan aplikasi JARVIS terbaru tidak tersambung (buka aplikasi JARVIS di HP)")
    req = uuid.uuid4().hex[:12]
    fut = asyncio.get_running_loop().create_future()
    _waiting[req] = fut
    try:
        if not await hub.send_cap(CAP, {"type": "phone_op", "req": req, "op": name, **args}):
            raise PhoneError("HP tidak tersambung")
        reply = await asyncio.wait_for(fut, wait or OP_TIMEOUT)
    except asyncio.TimeoutError:
        raise PhoneError("HP tidak menjawab (layar terkunci? aplikasi JARVIS ditutup?)") from None
    finally:
        _waiting.pop(req, None)
    if reply.get("error"):
        raise PhoneOpError(str(reply["error"])[:300])
    return reply


def on_reply(msg: dict) -> None:
    fut = _waiting.get(str(msg.get("req") or ""))
    if fut and not fut.done():
        fut.set_result(msg)


async def stop_from_phone(run_id: int, actor: str) -> bool:
    """The owner tapped "Hentikan" on the banner the phone shows while JARVIS operates it."""
    from . import workers
    row = await _row(run_id)
    if not row or not row["task_id"]:
        return False
    return await workers.stop(row["task_id"], actor)


# ---------- the loop ----------

TOOLS = [
    {"type": "function", "function": {"name": "ketuk", "description": "Ketuk satu elemen di layar (nomor dari daftar layar).",
                                      "parameters": {"type": "object", "properties": {"nomor": {"type": "integer"}, "alasan": {"type": "string"}},
                                                     "required": ["nomor"]}}},
    {"type": "function", "function": {"name": "ketik", "description": "Isi kolom isian (nomor) dengan teks. Jangan untuk PIN/kata sandi/OTP.",
                                      "parameters": {"type": "object", "properties": {"nomor": {"type": "integer"}, "teks": {"type": "string"},
                                                                                      "kirim": {"type": "boolean", "description": "tekan Enter/cari sesudahnya"}},
                                                     "required": ["nomor", "teks"]}}},
    {"type": "function", "function": {"name": "gulir", "description": "Gulir layar (atau elemen bernomor yang bisa digulir).",
                                      "parameters": {"type": "object", "properties": {"arah": {"type": "string", "enum": ["bawah", "atas", "kiri", "kanan"]},
                                                                                      "nomor": {"type": "integer"}}, "required": ["arah"]}}},
    {"type": "function", "function": {"name": "kembali", "description": "Tombol Kembali Android.", "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {"name": "buka_aplikasi", "description": "Buka (lagi) aplikasinya dari awal.",
                                      "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {"name": "tunggu", "description": "Tunggu layar memuat (1–10 detik).",
                                      "parameters": {"type": "object", "properties": {"detik": {"type": "integer"}}}}},
    {"type": "function", "function": {"name": "lihat_gambar", "description": "Ambil tangkapan layar dan baca isinya bila daftar layar kurang jelas "
                                                                              "(peta, gambar, harga di gambar).",
                                      "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {"name": "tanya_pemilik", "description": "Tanya pemilik bila ada pilihan yang tidak bisa kamu putuskan sendiri "
                                                                              "(alamat ambigu, harga jauh di atas perkiraan, menu habis). Menunggu jawabannya.",
                                      "parameters": {"type": "object", "properties": {"pertanyaan": {"type": "string"}}, "required": ["pertanyaan"]}}},
    {"type": "function", "function": {"name": "selesai", "description": "Tugas selesai: tulis hasilnya (apa yang dipesan, harga, perkiraan waktu, "
                                                                        "nomor pesanan/driver bila ada).",
                                      "parameters": {"type": "object", "properties": {"hasil": {"type": "string"}}, "required": ["hasil"]}}},
    {"type": "function", "function": {"name": "gagal", "description": "Berhenti karena tidak bisa diselesaikan; tulis alasannya.",
                                      "parameters": {"type": "object", "properties": {"alasan": {"type": "string"}}, "required": ["alasan"]}}},
]

SYSTEM = """Kamu JARVIS yang sedang MENGOPERASIKAN aplikasi {label} di HP pemilik, langkah demi langkah, untuk satu tugas yang sudah ia setujui.
Setiap giliran kamu melihat daftar elemen layar saat ini (bernomor) dan memanggil TEPAT SATU alat. Pemilik melihat HP-nya bergerak.
Aturan:
- Kerjakan HANYA tugas yang disetujui; jangan membuka layanan lain, jangan isi saldo/top up, transfer, ubah akun, tambah kartu, pinjaman.
- PIN, kata sandi, OTP: JANGAN pernah diketik. Bila layar memintanya, JARVIS otomatis menunggu pemilik mengetiknya sendiri.
- Sebelum menekan tombol pesan/bayar terakhir, pastikan detailnya sesuai tugas (layanan, tujuan/menu, jumlah, metode bayar). Bila harga jauh
  di atas yang pemilik sebut, alamat ambigu, atau pilihan tidak jelas → tanya_pemilik, jangan menebak.
- Kolom pencarian sering tampak sebagai teks/tombol: ketuk dulu, tunggu kolom isian muncul, baru ketik.
- Bila sebuah langkah tidak mengubah layar, coba cara lain (gulir, tunggu, kembali); jangan mengulang hal yang sama lebih dari dua kali.
- Selesai → panggil selesai dengan hasil yang jelas. Tidak mungkin → gagal dengan alasannya.
{hint}"""


def _brief(row: dict) -> tuple[int, str]:
    first, _, goal = row["instruction"].partition("\n")
    return int(json.loads(first[len(MARK):])["run"]), goal.strip()


async def _wait_for_owner_secret(app: str, emit) -> dict:
    """A PIN / OTP screen: tell the owner, wait until it is gone (the owner typed it) or give up."""
    await hub.broadcast({"type": "announce", "text": f"Di {APPS[app]['label']} ada layar PIN/OTP — silakan ketik sendiri di HP; aku lanjut setelahnya."})
    await emit({"type": "thought", "text": "menunggu pemilik mengetik PIN/OTP sendiri"})
    end = time.monotonic() + PIN_WAIT_S
    while time.monotonic() < end:
        await asyncio.sleep(3)
        obs = await op("observe")
        if not is_secret_screen(obs):
            return obs
    raise PhoneError("PIN/OTP tidak diisi dalam 4 menit — dihentikan")


async def _ask_owner(task_id: int, question: str, emit) -> str:
    from . import questions
    q = await questions.ask(question, task_id)
    await emit({"type": "thought", "text": f"bertanya ke pemilik: {question[:120]}"})   # questions.ask already speaks it as a report
    end = time.monotonic() + 600
    while time.monotonic() < end:
        await asyncio.sleep(3)
        got = await questions.get(q["id"])
        if got and got.get("status") == "answered":
            return got.get("answer") or ""
    return "(pemilik belum menjawab dalam 10 menit — putuskan yang paling aman, atau berhenti dengan gagal)"


async def produce(task_id: int, row: dict, progress, emit) -> str:
    """The worker branch (workers._run): a learned routine first (no AI but for the steps that need judgement, ADR-083), else — or from where
    it stopped — the AI decides every tap. A successful AI run is learned as a routine for next time. One phone, one run at a time."""
    from . import routines
    run_id, goal = _brief(row)
    run = await _row(run_id)
    if not run:
        raise PhoneError("permintaan operasi HP tidak ditemukan")
    app, a = run["app"], APPS[run["app"]]
    started = time.monotonic()
    async with _lock:
        await _set(run_id, status="running")
        try:
            obs = await _start_app(run_id, app, a, progress, goal)
            trace: list[dict] = []
            text, used, todo = None, None, goal
            try:
                used = await routines.find(app, goal)
            except Exception as e:
                log.warning("routine lookup failed: %s", e)
            if used:
                await emit({"type": "thought", "text": f"pakai rutin yang sudah dipelajari: {used['name']} (v{used['version']})"})
                await progress(15, f"Rutin: {used['name']}")
                io = _PhoneIO(task_id, app, a, progress, emit, started)
                res = await routines.execute(used["steps"], await routines.params_for(used, goal), io)
                await routines.record(used["id"], res["ok"], res["auto"], res["ai"])
                if res["ok"]:
                    text = res["result"] + f"\n\n(dikerjakan dengan rutin \"{used['name']}\": {res['auto']} langkah tanpa AI, {res['ai']} langkah dengan AI)"
                else:
                    await emit({"type": "thought", "text": f"rutin berhenti di langkah {res['at']} ({res['why'][:120]}) — AI melanjutkan"})
                    todo = f"{goal}\n(Rutin '{used['name']}' sudah menjalankan sebagian dan berhenti di langkah {res['at']}: {res['why']}. Lanjutkan dari layar sekarang.)"
                    obs = await op("observe")
            if text is None:
                text, obs = await _loop(task_id, app, a, todo, progress, emit, obs, started=started, trace=trace)
                t = asyncio.create_task(routines.learn(app, a["label"], goal, trace, text, task_id, replaces=used))
                _learning.add(t)
                t.add_done_callback(_learning.discard)
        except asyncio.CancelledError:
            await _set(run_id, status="stopped")
            raise
        except Exception as e:
            await _set(run_id, status="failed", result=str(e)[:1000])
            raise
        finally:
            try:
                await op("end")
            except Exception:
                pass
    await _set(run_id, status="done", result=text[:4000])
    return text


def start_url(goal: str, a: dict) -> str:
    """Where a browser run starts: the first allowed https address in the goal, else the app's home. Pure."""
    from .webvisit import allowed
    for u in re.findall(r"https://[^\s\"'<>)]+", goal or ""):
        if allowed(u.rstrip(".,"), a.get("sites") or []):
            return u.rstrip(".,")
    return a.get("home") or ""


async def _start_app(run_id: int, app: str, a: dict, progress, goal: str = "") -> dict:
    if not phone_online():   # ADR-086: the app is closed or asleep — ask for it and wait a few minutes instead of failing at once
        await progress(6, "Menunggu HP tersambung — buka aplikasi JARVIS")
        await hub.broadcast({"type": "notify", "kind": "phone", "title": f"Buka aplikasi JARVIS untuk {a['label']}",
                             "text": "Aku menunggu HP-mu tersambung supaya bisa mengoperasikan aplikasinya (sampai 5 menit)."})
        await hub.broadcast({"type": "announce", "text": f"Buka aplikasi JARVIS di HP ya, aku perlu HP-nya untuk membuka {a['label']}."})
        if not await wait_online(OFFLINE_WAIT_S):
            raise PhoneError("HP tidak tersambung selama 5 menit — buka aplikasi JARVIS (dan nyalakan JARVIS siaga di Setelan HP)")
    await progress(8, f"Membuka {a['label']} di HP…")
    await op("begin", run=run_id, app=app, label=a["label"], packages=a["packages"], domains=a.get("sites") or [])
    obs = await op("open_url", url=start_url(goal, a)) if a.get("sites") else await op("open", package=a["packages"][0])
    for _ in range(3):   # the app is slow to come to the front, or a system overlay (screenshot, permission) is in the way
        if in_app(obs, app):
            break
        await asyncio.sleep(3)
        obs = await op("observe")
    return obs


class _PhoneIO:
    """What a routine may do on the phone (routines.execute): the same guards as the AI's steps."""

    def __init__(self, task_id, app, a, progress, emit, started):
        self.task_id, self.app, self.a, self.progress, self.emit, self.started = task_id, app, a, progress, emit, started
        self.obs: dict = {}
        self.n = 0

    async def observe(self, pause: float = 0.0) -> dict:
        if pause:
            await asyncio.sleep(pause)
        self.obs = await op("observe")
        if in_app(self.obs, self.app) and is_secret_screen(self.obs):
            self.obs = await _wait_for_owner_secret(self.app, self.emit)
        return self.obs

    async def act(self, kind: str, **args) -> dict:
        self.n += 1
        name = {"tap": "ketuk", "type": "ketik", "scroll": "gulir", "back": "kembali", "open": "buka_aplikasi"}[kind]
        check = {"nomor": args.get("index"), "teks": args.get("text"), "arah": args.get("direction")}
        if refused := check_action(name, check, self.obs, self.app):
            raise PhoneError(refused)
        await self.progress(min(92, 15 + self.n * 3), _label(name, check, self.obs))
        self.obs = await op(kind, index=args.get("index"), text=args.get("text") or "", submit=bool(args.get("submit")),
                            direction=args.get("direction") or "bawah", package=self.a["packages"][0])
        if in_app(self.obs, self.app) and is_secret_screen(self.obs):
            self.obs = await _wait_for_owner_secret(self.app, self.emit)
        return self.obs

    async def ai(self, goal: str, max_steps: int) -> str:
        text, self.obs = await _loop(self.task_id, self.app, self.a, goal, self.progress, self.emit, self.obs or await op("observe"),
                                     max_steps=max(2, min(15, max_steps)), started=self.started)
        return text

    async def ask(self, question: str) -> str:
        return await _ask_owner(self.task_id, question, self.emit)


def _desc(n: dict) -> dict:
    """An element as a routine can find it again."""
    return {k: n[k] for k in ("id", "t", "d", "h", "c", "e", "k") if n.get(k)}


async def _loop(task_id, app, a, goal, progress, emit, obs, *, max_steps: int = MAX_STEPS, started: float | None = None,
                trace: list | None = None) -> tuple[str, dict]:
    """The AI decides every step, from `obs`, until selesai / gagal (or `max_steps`). Returns (result, the last screen). Each action is added to
    `trace` with the element it touched — that is what a routine is learned from."""
    started = started or time.monotonic()
    history: list[str] = []
    slips = 0
    system = SYSTEM.format(label=a["label"], hint=a["hint"])
    for step in range(1, max_steps + 1):
        if time.monotonic() - started > MAX_MINUTES * 60:
            raise PhoneError(f"lebih dari {MAX_MINUTES} menit — dihentikan supaya HP tidak dikendalikan terlalu lama")
        if in_app(obs, app) and is_secret_screen(obs):
            obs = await _wait_for_owner_secret(app, emit)
            history.append("(pemilik mengetik PIN/OTP sendiri)")
            continue
        messages = [{"role": "system", "content": system},
                    {"role": "user", "content": f"TUGAS DARI PEMILIK: {goal}\n\nLANGKAH SEBELUMNYA:\n" + ("\n".join(history[-10:]) or "(belum ada)")
                     + f"\n\nLAYAR SAAT INI (langkah {step}/{max_steps}):\n{screen_text(obs)}\n\nPanggil satu alat."}]
        call = None
        for attempt in range(2):
            async for ev in llm.stream_chat(messages, tools=TOOLS, category="hp", max_tokens=400, temperature=0.2,
                                            caller="core", session_id=f"task-{task_id}"):
                if ev["type"] == "done":
                    c = ev["completion"]
                    call = c.tool_calls[0] if c.tool_calls else None
            if call:
                break
            messages.append({"role": "user", "content": "Kamu harus memanggil SATU alat (ketuk/ketik/gulir/…/selesai/gagal)."})
        if not call:
            raise PhoneError("model tidak memilih langkah")
        name, args = call.name, call.arguments or {}
        if name == "selesai":
            return str(args.get("hasil") or "Selesai."), obs
        if name == "gagal":
            raise PhoneError(str(args.get("alasan") or "tidak bisa diselesaikan"))
        label = _label(name, args, obs)
        if refused := check_action(name, args, obs, app):
            history.append(f"{step}. {label} → DITOLAK: {refused}")
            await emit({"type": "thought", "text": f"ditolak: {refused}"[:200]})
            continue
        await emit({"type": "tool", "id": f"hp{step}", "name": f"hp_{name}", "label": label, "status": "running"})
        await progress(min(92, 10 + step * 2), label)
        touched = node(obs, args.get("nomor"))
        if trace is not None:
            trace.append({"aksi": name, **({"elemen": _desc(touched)} if touched else {}),
                          **{k: args[k] for k in ("teks", "kirim", "arah", "pertanyaan", "alasan", "detik") if args.get(k) not in (None, "")},
                          "layar": screen_words(obs)[:300]})
        if name == "tanya_pemilik":
            answer = await _ask_owner(task_id, str(args.get("pertanyaan") or ""), emit)
            history.append(f"{step}. tanya pemilik: {args.get('pertanyaan')} → jawab: {answer[:300]}")
            if trace is not None:
                trace[-1]["jawaban"] = answer[:200]
            obs = await op("observe")
        elif name == "lihat_gambar":
            from . import screen_reader
            shot = await op("screenshot")
            seen = await screen_reader.read(shot.get("jpeg"))
            history.append(f"{step}. lihat gambar layar → {seen[:1200] or '(tidak terbaca)'}")
            obs = await op("observe")
        elif name == "tunggu":
            await asyncio.sleep(max(1, min(10, int(args.get("detik") or 2))))
            obs = await op("observe")
            history.append(f"{step}. tunggu")
        else:
            before = screen_text(obs)
            try:
                obs = await op({"ketuk": "tap", "ketik": "type", "gulir": "scroll", "kembali": "back", "buka_aplikasi": "open"}[name],
                               index=args.get("nomor"), text=str(args.get("teks") or ""), submit=bool(args.get("kirim")),
                               direction=args.get("arah") or "bawah", package=a["packages"][0])
                slips = 0
            except PhoneOpError as e:   # the phone refused (wrong screen, no such field): the model is told and tries another way
                slips += 1
                if slips >= 4:
                    raise PhoneError(f"HP menolak 4 kali berturut-turut: {e}") from None
                history.append(f"{step}. {label} → HP MENOLAK: {e}")
                if trace is not None:
                    trace.pop()
                await emit({"type": "thought", "text": f"HP menolak: {e}"[:200]})
                await asyncio.sleep(2)
                obs = await op("observe")
                continue
            history.append(f"{step}. {label}" + (" (layar tidak berubah)" if screen_text(obs) == before else ""))
        await emit({"type": "tool", "id": f"hp{step}", "name": f"hp_{name}", "label": label, "status": "completed"})
    raise PhoneError(f"belum selesai setelah {max_steps} langkah")


def _label(name: str, args: dict, obs: dict) -> str:
    n = node(obs, args.get("nomor")) or {}
    what = (n.get("t") or n.get("d") or n.get("h") or f"#{args.get('nomor')}")[:60]
    return {"ketuk": f"ketuk \"{what}\"", "ketik": f"ketik \"{str(args.get('teks') or '')[:60]}\" di \"{what}\"",
            "gulir": f"gulir ke {args.get('arah') or 'bawah'}", "kembali": "kembali", "buka_aplikasi": "buka aplikasi",
            "tunggu": "tunggu layar", "lihat_gambar": "baca gambar layar", "tanya_pemilik": f"tanya pemilik: {str(args.get('pertanyaan') or '')[:80]}"
            }.get(name, name)
