"""The dev team (ADR-059): three named workers for JARVIS' own development, each taught for its position.

    owner's request ─▶ bisan (analyst): spec + acceptance criteria
                    ─▶ coder (expert developer): builds it on jarvis/devjob-<id>, proposes it (propose_code_change)
                    ─▶ the runner (infra/scripts/self-dev.sh) runs every test suite in throwaway containers
                    ─▶ qaqa (QA): reviews the REAL diff + the runner's result against the spec
                         LULUS    → the owner approves the change at the admin page (the usual T1 approval)
                         PERBAIKI → back to coder with the findings (at most MAX_ROUNDS builds), then qaqa again

Core drives the hand-offs (a member's result is delivered here, by task kind 'devteam'); the members never pass work to each other
themselves. Nothing here can merge or deploy: that stays the owner's approval of the tested commit (dev.py / self-dev.sh).
"""

import asyncio
import logging
import re

from . import audit, db, dev, hub, reports

log = logging.getLogger("jarvis-core.devteam")

MAX_ROUNDS = 3            # coder builds at most this often before the team gives the job back to the owner
TEST_WAIT_S = 45 * 60     # the runner's test of one proposal (3–10 min normally)
SESSION = "devteam"

MEMBERS = {
    "bisan": {"name": "bisan", "role": "Analis Bisnis & Sistem", "icon": "🧭", "category": "dev-bisan"},
    "coder": {"name": "coder", "role": "Expert Developer", "icon": "🛠", "category": "dev-coder"},
    "qaqa": {"name": "qaqa", "role": "Quality Assurance", "icon": "🔍", "category": "dev-qaqa"},
}

TEAM = ("Kamu anggota TIM DEV JARVIS: bisan (analis bisnis & sistem), coder (expert developer), qaqa (QA). Pemilik melihat "
        "pekerjaanmu langsung di area Tim Dev di Meja dan bisa mengirim pesan kepadamu. Repo kerja: /opt/data/workspace/jar "
        "(origin = kode JARVIS terbaru, baca saja lewat origin/main). Bahasa: Indonesia, ringkas, fakta. Tiap langkah ±10 detik: "
        "gabungkan pembacaan file/perintah yang tidak saling bergantung, jangan menjelajah tanpa tujuan.\n")

BISAN = TEAM + """KAMU: bisan — Analis Bisnis & Sistem. Kamu TIDAK menulis kode dan TIDAK mengubah file.
Tugasmu: ubah permintaan pemilik menjadi spesifikasi yang bisa langsung dikerjakan coder dan diperiksa qaqa.
Anggaran: paling banyak ±10 langkah baca. Baca berkas besar per rentang (git show origin/main:<berkas> | sed -n 'a,bp'; git grep -n), bukan utuh;
tulis spesifikasi ≤ 60 baris. Spesifikasi yang tepat dalam 8 menit lebih berguna daripada yang sempurna dalam 30.
Cara kerja:
1. Pahami MAKSUD pemilik (masalah apa yang ingin ia selesaikan, di layar mana, di HP atau desktop). Kalau ada hal penting yang
   ambigu dan tebakanmu bisa salah arah, tanya lewat ask_owner (satu pertanyaan, dengan pilihan). Kalau kecil, putuskan sendiri dan tulis asumsinya.
   Kalau permintaan menyebut sesuatu dengan nama yang tidak kamu temukan di kode, cari dulu nama panel/kartu yang paling mirip dan SEBUT temuanmu.
2. Baca kode yang relevan di origin/main (git -C /opt/data/workspace/jar fetch origin; git show origin/main:<berkas>; git grep di origin/main)
   supaya spesifikasi menyebut berkas, fungsi, dan pola yang SUDAH ada — jangan mengarang arsitektur baru.
3. Jaga lingkup kecil (tingkat T1: ≤1500 baris, tanpa Android, tanpa zona terlindungi seperti main.py, approvals, composition, runner).
   Kalau permintaan terlalu besar, pecah dan kerjakan bagian pertama saja; sebut sisanya.
4. Cek zona terlindungi SEBELUM menulis spesifikasi — untuk setiap berkas yang perlu diubah:
   cd /opt/data/workspace/jar && python3 -c "import sys; sys.path.insert(0, 'core/app'); import selfdev_policy as p; print([f for f in sys.argv[1:] if p.FORBIDDEN.match(f)])" <berkas…>
   Kalau permintaan MUSTAHIL tanpa berkas terlindungi (hanya manusia yang boleh mengubahnya), BARIS PERTAMA HASIL-mu: BUTUH MANUSIA — <berkas
   terlindungi + alasan>; tim berhenti di situ dan pemilik diberi tahu. Tetap tulis spesifikasi lengkap di bawahnya untuk pengembang manusia.
Mutu spesifikasi (dari ulasan nyata):
- Kriteria terima = pernyataan yang BELUM terpenuhi dan bisa diperiksa qaqa dari diff/tes/perintah. Jangan beri tanda ✓ dan jangan mengulang bagian "Perilaku".
- Sebelum menulis, git grep di origin/main: siapa lagi yang memakai hal yang akan diubah, dan tes YANG SUDAH ADA yang akan terpengaruh
  (mis. tes yang menyebut daftar kunci/panel/fungsi itu). Cantumkan tes lama yang HARUS diperbarui coder.
- Sebut hanya berkas yang benar-benar perlu diubah, dengan path relatif repo (core/app/web/canvas/app.js), bukan path absolut dan bukan "kalau perlu".
- Tes baru hanya untuk hal yang BISA diuji tanpa browser (fungsi murni di lib.js, bukan app.js yang penuh DOM). Jangan mengarang berkas atau fungsi yang tidak ada.
- Kalau permintaan meminta memeriksa/mengusulkan sesuatu (mis. kandidat lain), tuliskan hasilnya di bagian "Temuan untuk pemilik", jangan dilewatkan.
Akhiri dengan HASIL berformat persis:
SPESIFIKASI
Tujuan: <satu kalimat, dari sudut pandang pemilik>
Berkas: <daftar berkas yang diubah + alasannya>
Perilaku: <poin-poin perilaku yang harus terjadi, termasuk di HP>
Kriteria terima: <daftar bernomor, masing-masing bisa diperiksa qaqa dari diff / tes / perintah>
Tes baru: <nama BERKAS TES BARU yang harus dibuat coder (mis. core/app/web/canvas/tests/<fitur>.test.mjs) dan apa yang dibuktikannya>
Tes lama yang terpengaruh: <nama tes + apa yang harus diubah, atau "tidak ada">
Bukan lingkup: <yang sengaja tidak dikerjakan>
Risiko: <efek samping yang harus diwaspadai coder>
Temuan untuk pemilik: <kandidat/jawaban atas hal yang diminta diperiksa, atau "tidak ada">
"""

CODER = TEAM + """KAMU: coder — Expert Developer. Kamu membangun persis spesifikasi dari bisan, dengan kualitas senior, dalam langkah sesedikit mungkin.
Urutan kerja (cepat DAN benar — tiap langkah ±10 detik, jadi hemat langkah):
1. Tempat kerjamu sendiri (jangan pakai folder jar bersama: pekerja lain memakainya):
   cd /opt/data/workspace/jar && git fetch origin && (git worktree add -B {branch} {dir} origin/main || git -C {dir} rebase origin/main)
   Semua langkah berikutnya di {dir}. Gunakan origin/main yang baru: basis lama = konflik saat deploy.
2. Baca seperlunya: git grep -n untuk mencari, sed -n 'a,bp' untuk berkas besar; baca utuh hanya berkas < 300 baris, dan jangan membaca ulang
   yang sudah kamu baca. Baca gaya sekitar (indentasi, penamaan, bahasa komentar) sebelum menulis.
3. Tulis semua perubahan satu berkas sekaligus: SATU skrip python/sed yang menerapkan semua penggantian dan assert tiap penggantian benar-benar
   terjadi (bukan puluhan edit kecil). Ubah seperlunya saja. Tanpa kode mati, blok kosong, kode lama yang dikomentari, console.log sisa, atau
   komentar yang mengulang kode. Komentar singkat dalam gaya file itu. Penuhi SETIAP kriteria terima dan pikirkan efek sampingnya (layar HP,
   mode gelap, state yang tersimpan, hal yang membuka/menutup sendiri).
4. Tes baru di BERKAS TES BARU (core/app/web/canvas/tests/<fitur>.test.mjs atau core/tests/test_<fitur>.py), bukan ditambah di akhir berkas
   bersama (lib.test.mjs, test_acceptance.py…): menambah di akhir berkas bersama membuat konflik merge saat deploy. Tes tidak boleh dilemahkan atau dihapus.
5. Periksa: cd {dir} && python3 core/app/preflight.py — perbaiki SETIAP FAIL dan pahami SETIAP WARN, baca hasil tes JS-nya. Tes JS manual: cd <folder web> && node --test tests/*.test.mjs (Node baru menolak
   direktori kosong sebagai argumen: beri daftar berkas). Lalu baca
   git diff origin/main SEKALI sebagai reviewer yang curiga (karakter nyasar, selector yang tak cocok elemennya, perilaku di HP, state saat dimuat).
6. git add <berkas> (bukan git add -A), cek git diff --stat origin/main, commit dengan pesan jelas.
7. Tepat sebelum propose: git fetch origin && git rebase origin/main && python3 core/app/preflight.py — harus tanpa FAIL (konflik dengan main terdeteksi di sini).
8. propose_code_change(branch='{branch}', title=..., why=<masalah, manfaat, risiko>). Jangan menunggu hasil tes server: tim yang menunggu.
   Kalau propose_code_change menolak, perbaiki penyebabnya dan coba lagi.
Kalau ternyata perubahan ini HANYA bisa dibuat dengan mengubah berkas zona terlindungi (preflight: "FAIL kebijakan — zona terlindungi"), jangan
mengakalinya dan jangan mengusulkan setengahnya: BARIS PERTAMA HASIL-mu: BUTUH MANUSIA — <berkas + alasan>, lalu apa yang sudah kamu siapkan.
Akhiri dengan HASIL: id perubahan dari propose_code_change, commit, berkas yang berubah, hasil preflight, dan bagaimana tiap kriteria terima dipenuhi.
"""

QAQA = TEAM + """KAMU: qaqa — Quality Assurance. Kamu TIDAK mengubah kode dan TIDAK commit; kamu memeriksa dan memutuskan, dalam ≤ ±12 langkah.
Yang kamu periksa: cabang {branch} (perubahan #{change}) terhadap SPESIFIKASI di bawah, plus hasil tes server dari penguji otomatis.
Cara kerja:
1. Jalankan SEKALI: cd {dir} && python3 core/app/preflight.py (tempat kerja coder; kalau folder itu tidak ada: cd /opt/data/workspace/jar &&
   git fetch origin && git diff origin/main...{branch}). Setiap FAIL = temuan PERBAIKI (kecuali FAIL yang jelas dari lingkunganmu, bukan dari perubahan: buktikan dengan perintah yang sama di origin/main). WARN "tes di berkas bersama" / "basis lama" = temuan.
2. Lihat diff NYATA: git diff origin/main...{branch} (bukan klaim coder). Baca berkas utuh di sekitar perubahan hanya bila perlu untuk menilai konteks
   (mis. selector CSS yang dirujuk benar-benar ada di HTML/JS).
3. Periksa tiap kriteria terima satu per satu: TERPENUHI / TIDAK, dengan bukti (baris diff, hasil perintah).
4. Cari cacat yang sering lolos tes: karakter nyasar, selector yang tidak cocok dengan elemennya, perilaku HP (media query), state yang tidak
   dipulihkan saat dimuat, sesuatu yang membuka/menutup sendiri, kode mati, berkas di luar lingkup, tes yang dilemahkan, tes yang tidak benar-benar
   membuktikan perilakunya.
5. Baca hasil tes server. Kalau gagal, tentukan: karena perubahan ini (cacat) atau tes lain yang tidak berhubungan (sebut nama tesnya dan alasannya).
Akhiri dengan HASIL yang BARIS PERTAMANYA persis salah satu:
LULUS — semua kriteria terpenuhi dan tidak ada cacat berarti (tes server lulus, atau gagalnya jelas tidak berhubungan — jelaskan).
PERBAIKI — lalu daftar bernomor temuan, dari paling parah, masing-masing: berkas/baris, apa salahnya, apa yang harus dilakukan coder.
Jangan menulis LULUS kalau ragu.
"""


class DevTeamError(ValueError):
    pass


def branch_for(job_id: int) -> str:
    return f"jarvis/devjob-{job_id}"


def dir_for(job_id: int) -> str:
    """The job's own git worktree in Hermes' workspace (jobs never share a working tree)."""
    return f"/opt/data/workspace/devjob-{job_id}"


def needs_human(text: str) -> str:
    """'BUTUH MANUSIA — <why>' as a member's first line (pure; unit-tested): the job can only be done by a human developer. Returns the why, or ''."""
    for line in (text or "").splitlines():
        s = re.sub(r"^[\s>*#_`-]+", "", line).strip()
        if not s or s.upper().startswith("HASIL"):
            continue
        m = re.match(r"BUTUH MANUSIA\W*(.*)$", s, re.IGNORECASE)
        return (m.group(1).strip() or "butuh pengembang manusia") if m else ""
    return ""


def verdict(text: str) -> str:
    """qaqa's decision from its result (pure; unit-tested): 'lulus', 'perbaiki', or '' when it did not say."""
    for line in (text or "").splitlines():
        s = re.sub(r"^[\s>*#_`-]+", "", line).strip().upper()
        if not s or s.startswith("HASIL"):
            continue
        if s.startswith("LULUS"):
            return "lulus"
        if s.startswith("PERBAIKI"):
            return "perbaiki"
        if s.startswith("TIDAK LULUS") or s.startswith("GAGAL"):
            return "perbaiki"
    return ""


async def _job(job_id: int) -> dict | None:
    row = await db.pool().fetchrow("SELECT * FROM dev_jobs WHERE id = $1", job_id)
    return dict(row) if row else None


async def _set(job_id: int, **cols) -> None:
    sets = ", ".join(f"{k} = ${i + 2}" for i, k in enumerate(cols))
    await db.pool().execute(f"UPDATE dev_jobs SET {sets}, updated_at = now() WHERE id = $1", job_id, *cols.values())
    await hub.broadcast({"type": "devteam", "job": job_id, **{k: v for k, v in cols.items() if k in ("status", "round", "change_id")}})


async def _spawn(job: dict, role: str, title: str, instruction: str) -> int:
    from . import workers
    m = MEMBERS[role]
    if role in ("bisan", "coder"):   # they read / branch from Hermes' copy of main: bring it up to date first, or the change conflicts at deploy
        await dev.sync_mirror()
    t = await workers.spawn(f"{m['name']} · {title}"[:120], instruction, f"{SESSION}-{job['id']}", f"devteam:{role}",
                            kind="devteam", category=m["category"])
    await db.pool().execute("UPDATE tasks SET dev_job = $2, dev_role = $3 WHERE id = $1", t["id"], job["id"], role)
    return t["id"]


def _short(text: str, n: int = 60) -> str:
    return re.sub(r"\s+", " ", text or "").strip()[:n]


async def request(text: str, actor: str) -> dict:
    """The owner asks the team for something (a fix or a small feature of JARVIS itself)."""
    text = (text or "").strip()
    if len(text) < 8:
        raise DevTeamError("tulis permintaannya lebih jelas")
    busy = await db.pool().fetchval("SELECT count(*) FROM dev_jobs WHERE status IN ('analysing', 'coding', 'testing', 'reviewing')")
    if busy >= 3:
        raise DevTeamError("tim dev sedang mengerjakan 3 permintaan — tunggu salah satunya selesai")
    row = await db.pool().fetchrow("INSERT INTO dev_jobs (request, created_by) VALUES ($1, $2) RETURNING *", text[:6000], actor)
    job = dict(row)
    await _set(job["id"], branch=branch_for(job["id"]))
    job["branch"] = branch_for(job["id"])
    await audit.record(actor, "devteam.requested", f"devjob:{job['id']}")
    await _spawn(job, "bisan", f"spesifikasi: {_short(text)}", BISAN + "\nPERMINTAAN PEMILIK:\n" + text)
    return job


def _coder_brief(job: dict) -> str:
    out = CODER.format(branch=job["branch"], dir=dir_for(job["id"])) + "\nPERMINTAAN PEMILIK:\n" + job["request"] + "\n\nSPESIFIKASI (dari bisan):\n" + (job["spec"] or "")
    if job.get("review"):
        out += (f"\n\nPUTARAN PERBAIKAN ke-{job['round'] + 1}. Temuan qaqa atas versimu sebelumnya — selesaikan SEMUA, di cabang yang sama, "
                "commit baru, lalu propose_code_change lagi:\n" + job["review"])
    return out


async def on_result(task_id: int, result: str) -> None:
    """A member finished: hand the work to the next one."""
    t = await db.pool().fetchrow("SELECT dev_job, dev_role FROM tasks WHERE id = $1", task_id)
    if not t or not t["dev_job"]:
        return
    job = await _job(t["dev_job"])
    if not job or job["status"] in ("done", "failed", "cancelled", "needs_human"):
        return
    role = t["dev_role"]
    if role in ("bisan", "coder") and (why := needs_human(result)):
        await _set(job["id"], status="needs_human", note=f"Butuh pengembang manusia: {why}"[:500],
                   **({"spec": result[:12000]} if role == "bisan" else {}))
        await reports._create(task_id, SESSION, f"Tim dev: permintaan #{job['id']} ({_short(job['request'], 80)}) butuh pengembang manusia — {why[:200]}. "
                              "Spesifikasinya sudah siap di area Tim Dev.")
        return
    if role == "bisan":
        await _set(job["id"], spec=result[:12000], status="coding")
        job = await _job(job["id"])
        await _spawn(job, "coder", f"bangun: {_short(job['request'])}", _coder_brief(job))
    elif role == "coder":
        change = await db.pool().fetchrow(
            "SELECT id, status FROM dev_changes WHERE branch = $1 AND created_at >= $2 ORDER BY id DESC LIMIT 1", job["branch"], job["updated_at"])
        rounds = job["round"] + 1
        if not change:
            if rounds >= MAX_ROUNDS:
                return await _fail(job, "coder tidak berhasil mengusulkan perubahannya (propose_code_change tidak terpanggil)", rounds)
            await _set(job["id"], round=rounds, review="Kamu belum memanggil propose_code_change, atau ia menolak. Pastikan commit ada di "
                       f"{job['branch']} lalu panggil propose_code_change. Hasilmu sebelumnya:\n{result[:2000]}")
            job = await _job(job["id"])
            await _spawn(job, "coder", f"usulkan ulang: {_short(job['request'])}", _coder_brief(job))
            return
        await _set(job["id"], round=rounds, change_id=change["id"], status="testing")
        asyncio.create_task(_after_tests(job["id"]))
    elif role == "qaqa":
        v = verdict(result)
        change = await db.pool().fetchrow("SELECT status, approval_id FROM dev_changes WHERE id = $1", job["change_id"])
        if v == "lulus" and change and change["status"] == "awaiting_approval":
            await _set(job["id"], review=result[:8000], status="awaiting_owner",
                       note=f"Siap disetujui: perubahan #{job['change_id']} di halaman admin (Pengembangan diri).")
            await reports._create(task_id, SESSION, f"Tim dev selesai: {_short(job['request'], 120)}. qaqa meluluskan perubahan "
                                  f"#{job['change_id']} — tinggal persetujuanmu di halaman admin.")
            return
        if v == "lulus":   # qaqa is satisfied but the runner did not pass it: the runner decides, so it is not done
            result = ("qaqa menilai lulus, tetapi penguji server tidak meluluskan perubahan ini (status: "
                      f"{change['status'] if change else 'tidak ada'}). Perbaiki penyebab kegagalan tes.\n" + result)
        if job["round"] >= MAX_ROUNDS:
            return await _fail(job, f"belum lulus QA setelah {job['round']} putaran", job["round"], review=result)
        await _set(job["id"], review=result[:8000], status="coding")
        job = await _job(job["id"])
        await _spawn(job, "coder", f"perbaiki temuan qaqa: {_short(job['request'])}", _coder_brief(job))


async def _fail(job: dict, why: str, rounds: int, review: str | None = None) -> None:
    await _set(job["id"], status="failed", note=why[:500], round=rounds, **({"review": review[:8000]} if review else {}))
    await reports._create(None, SESSION, f"Tim dev berhenti: {_short(job['request'], 120)} — {why}. Lihat area Tim Dev di Meja.")


async def on_failed(task_id: int, error: str) -> None:
    """A member's run failed (not a QA verdict): one more try for the same member, then the job stops."""
    from . import workers
    t = await db.pool().fetchrow("SELECT dev_job, dev_role, retries FROM tasks WHERE id = $1", task_id)
    if not t or not t["dev_job"]:
        return
    job = await _job(t["dev_job"])
    if not job or job["status"] in ("done", "failed", "cancelled", "needs_human"):
        return
    if (t["retries"] or 0) < 1:
        await db.pool().execute("UPDATE tasks SET retries = coalesce(retries, 0) + 1 WHERE id = $1", task_id)
        await workers.retry(task_id, "devteam")
        return
    await _fail(job, f"{t['dev_role']} gagal: {error[:200]}", job["round"])


async def _after_tests(job_id: int) -> None:
    """Wait for the runner's verdict on coder's proposal, then qaqa reviews it."""
    job = await _job(job_id)
    if not job:
        return
    waited = 0
    while waited < TEST_WAIT_S:
        st = await db.pool().fetchval("SELECT status FROM dev_changes WHERE id = $1", job["change_id"])
        if st and st != "testing":
            break
        await asyncio.sleep(15)
        waited += 15
    job = await _job(job_id)
    if not job or job["status"] != "testing":
        return
    ch = await db.pool().fetchrow("SELECT status, commit, files, right(coalesce(test_log, ''), 3500) AS log FROM dev_changes WHERE id = $1",
                                  job["change_id"])
    await _set(job_id, status="reviewing")
    runner = (f"HASIL PENGUJI OTOMATIS: status {ch['status'] if ch else 'tidak ada'}"
              + (f", commit {ch['commit']}, berkas {', '.join(ch['files'] or [])}" if ch else "")
              + ("\nCuplikan log tes:\n" + ch["log"] if ch and ch["log"] else "")
              + ("\n(Penguji belum memberi hasil dalam 45 menit.)" if ch and ch["status"] == "testing" else ""))
    brief = (QAQA.format(branch=job["branch"], change=job["change_id"], dir=dir_for(job["id"])) + "\nPERMINTAAN PEMILIK:\n" + job["request"]
             + "\n\nSPESIFIKASI (dari bisan):\n" + (job["spec"] or "") + "\n\n" + runner)
    await _spawn(job, "qaqa", f"periksa #{job['change_id']}: {_short(job['request'])}", brief)


REBASE_NOTE = ("DEPLOY GAGAL setelah pemilik menyetujui — biasanya karena main sudah maju (konflik merge) sejak versimu dites. Log deploy:\n{log}\n"
               "Perbaiki: git fetch origin && git rebase origin/main di tempat kerjamu, selesaikan konflik dengan menjaga KEDUA sisi, taruh tes barumu "
               "di berkas tes baru, jalankan preflight, lalu propose_code_change lagi. Pemilik akan diminta menyetujui sekali lagi.")


async def check_deploys() -> int:
    """Jobs waiting for the owner whose change was since deployed (done), rejected (stopped) or failed to deploy (back to coder). Returns how many moved."""
    rows = await db.pool().fetch(
        """SELECT j.id, j.round, c.id AS change_id, c.status, right(coalesce(c.deploy_log, ''), 1200) AS log
           FROM dev_jobs j JOIN dev_changes c ON c.id = j.change_id
           WHERE j.status = 'awaiting_owner' AND c.status IN ('deployed', 'rejected', 'deploy_failed', 'rolled_back')""")
    for r in rows:
        job = await _job(r["id"])
        if r["status"] == "deployed":
            await _set(job["id"], status="done", note=f"Sudah ter-deploy (perubahan #{r['change_id']}).")
        elif r["status"] == "rejected":
            await _set(job["id"], status="cancelled", note=f"Perubahan #{r['change_id']} ditolak pemilik.")
        elif job["round"] >= MAX_ROUNDS + 1:
            await _fail(job, f"deploy perubahan #{r['change_id']} gagal berulang kali", job["round"], review=r["log"])
        else:
            await _set(job["id"], status="coding", review=REBASE_NOTE.format(log=r["log"] or "(kosong)"))
            await reports._create(None, SESSION, f"Deploy perubahan #{r['change_id']} gagal; coder memperbaikinya (rebase). Kamu akan diminta menyetujui sekali lagi.")
            await _spawn(await _job(job["id"]), "coder", f"rebase & usulkan ulang: {_short(job['request'])}", _coder_brief(await _job(job["id"])))
    return len(rows)


async def watch() -> None:
    while True:
        await asyncio.sleep(60)
        try:
            await check_deploys()
        except Exception:
            log.exception("dev team deploy check failed")


async def resume() -> int:
    """After a restart: proposals still under test get their waiter back."""
    rows = await db.pool().fetch("SELECT id FROM dev_jobs WHERE status = 'testing'")
    for r in rows:
        asyncio.create_task(_after_tests(r["id"]))
    return len(rows)


async def cancel(job_id: int, actor: str) -> bool:
    from . import workers
    job = await _job(job_id)
    if not job or job["status"] in ("done", "failed", "cancelled", "needs_human"):
        return False
    for t in await db.pool().fetch("SELECT id FROM tasks WHERE dev_job = $1 AND status IN ('queued', 'running')", job_id):
        await workers.stop(t["id"], actor)
    await _set(job_id, status="cancelled", note=f"dibatalkan oleh {actor}")
    await audit.record(actor, "devteam.cancelled", f"devjob:{job_id}")
    return True


async def overview() -> dict:
    """The desk's Tim Dev area: each member (what it is doing now, its model) and the latest jobs."""
    from . import gateway, workers
    cats = await gateway.categories()
    members = []
    for role, m in MEMBERS.items():
        cur = await db.pool().fetchrow(
            """SELECT id, title, status, model_used, hermes_run, dev_job, left(coalesce(result, error, ''), 600) AS out,
                      EXTRACT(EPOCH FROM (COALESCE(finished_at, now()) - COALESCE(started_at, created_at)))::int AS seconds
               FROM tasks WHERE dev_role = $1 ORDER BY (status IN ('queued', 'running')) DESC, id DESC LIMIT 1""", role)
        chain = workers._chain(cats, m["category"])
        busy = bool(cur and cur["status"] in ("queued", "running"))
        members.append({**m, "id": role, "busy": busy, "model": (cur and cur["model_used"]) or (chain[0] if chain else ""), "chain": chain,
                        "task_id": cur and cur["id"], "task_title": cur and cur["title"], "task_status": cur and cur["status"],
                        "job": cur and cur["dev_job"], "seconds": cur and cur["seconds"], "last": "" if busy or not cur else cur["out"],
                        "can_say": busy and bool(cur and cur["hermes_run"]) and cur["status"] == "running"})
    jobs = [dict(r) for r in await db.pool().fetch(
        """SELECT id, left(request, 160) AS request, status, round, change_id, left(coalesce(note, ''), 200) AS note,
                  left(coalesce(review, ''), 400) AS review, updated_at FROM dev_jobs ORDER BY id DESC LIMIT 6""")]
    return {"members": members, "jobs": jobs, "max_rounds": MAX_ROUNDS}
