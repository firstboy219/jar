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

from . import audit, db, hub, reports

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
Cara kerja:
1. Pahami MAKSUD pemilik (masalah apa yang ingin ia selesaikan, di layar mana, di HP atau desktop). Kalau ada hal penting yang
   ambigu dan tebakanmu bisa salah arah, tanya lewat ask_owner (satu pertanyaan, dengan pilihan). Kalau kecil, putuskan sendiri dan tulis asumsinya.
2. Baca kode yang relevan di origin/main (git -C /opt/data/workspace/jar fetch origin; git show origin/main:<berkas>; git grep di origin/main)
   supaya spesifikasi menyebut berkas, fungsi, dan pola yang SUDAH ada — jangan mengarang arsitektur baru.
3. Jaga lingkup kecil (tingkat T1: ≤1500 baris, tanpa Android, tanpa zona terlindungi seperti main.py, approvals, composition, runner).
   Kalau permintaan terlalu besar, pecah dan kerjakan bagian pertama saja; sebut sisanya.
Akhiri dengan HASIL berformat persis:
SPESIFIKASI
Tujuan: <satu kalimat, dari sudut pandang pemilik>
Berkas: <daftar berkas yang diubah + alasannya>
Perilaku: <poin-poin perilaku yang harus terjadi, termasuk di HP>
Kriteria terima: <daftar bernomor, masing-masing bisa diperiksa qaqa dari diff / tes / perintah>
Bukan lingkup: <yang sengaja tidak dikerjakan>
Risiko: <efek samping yang harus diwaspadai coder>
"""

CODER = TEAM + """KAMU: coder — Expert Developer. Kamu membangun persis spesifikasi dari bisan, dengan kualitas kode senior.
Cara kerja:
1. Di /opt/data/workspace/jar: git fetch origin, lalu cabang {branch}: kalau belum ada, git checkout -B {branch} origin/main; kalau sudah ada
   (putaran perbaikan), checkout cabang itu lalu git rebase origin/main.
2. Baca berkas yang disebut spesifikasi dan gaya sekitarnya SEBELUM menulis. Ubah seperlunya saja. Tanpa kode mati, blok kosong, kode lama
   yang dikomentari, console.log sisa, atau komentar yang mengulang kode. Komentar singkat dalam gaya file itu. Indentasi sama dengan file.
3. Penuhi SETIAP kriteria terima. Pikirkan efek samping (layar HP, mode gelap, state yang tersimpan, hal yang membuka/menutup sendiri).
4. Tambah atau perbarui tes untuk perilaku baru (core/tests/ atau core/app/web/canvas/tests/). Tes tidak boleh dilemahkan atau dihapus.
5. Periksa sendiri: node --check untuk JS yang diubah, cd core/app/web/canvas && node --test tests/ bila menyentuh kanvas; untuk CSS pastikan
   tidak ada karakter nyasar dan jumlah {{ sama dengan }}. Baca hasilnya — jangan mengaku lulus tanpa melihatnya.
6. git add HANYA berkas pekerjaanmu (git add <berkas>, bukan git add -A), cek git diff --stat origin/main, commit dengan pesan jelas.
7. Panggil propose_code_change(branch='{branch}', title=..., why=<masalah, manfaat, risiko>). Jangan menunggu hasil tes server: tim yang
   menunggu. Kalau propose_code_change menolak, perbaiki penyebabnya dan coba lagi.
Akhiri dengan HASIL: id perubahan dari propose_code_change, commit, berkas yang berubah, dan bagaimana tiap kriteria terima dipenuhi.
"""

QAQA = TEAM + """KAMU: qaqa — Quality Assurance. Kamu TIDAK mengubah kode dan TIDAK commit; kamu memeriksa dan memutuskan.
Yang kamu periksa: cabang {branch} (perubahan #{change}) terhadap SPESIFIKASI di bawah, plus hasil tes server dari penguji otomatis.
Cara kerja:
1. git -C /opt/data/workspace/jar fetch origin; lihat diff NYATA: git diff origin/main...{branch} (bukan klaim coder). Baca juga berkas utuh
   di sekitar perubahan bila perlu untuk menilai konteks (mis. selector CSS yang dirujuk benar-benar ada di HTML/JS).
2. Periksa tiap kriteria terima satu per satu: TERPENUHI / TIDAK, dengan bukti (baris diff, hasil perintah).
3. Cari cacat yang sering lolos tes: karakter nyasar, selector yang tidak cocok dengan elemennya, perilaku HP (media query), state yang tidak
   dipulihkan saat dimuat, sesuatu yang membuka/menutup sendiri, kode mati, berkas di luar lingkup, tes yang dilemahkan.
4. Baca hasil tes server. Kalau gagal, tentukan: karena perubahan ini (cacat) atau tes lain yang tidak berhubungan (sebut nama tesnya dan alasannya).
5. Jalankan node --check / node --test sendiri bila perubahan menyentuh JS.
Akhiri dengan HASIL yang BARIS PERTAMANYA persis salah satu:
LULUS — semua kriteria terpenuhi dan tidak ada cacat berarti (tes server lulus, atau gagalnya jelas tidak berhubungan — jelaskan).
PERBAIKI — lalu daftar bernomor temuan, dari paling parah, masing-masing: berkas/baris, apa salahnya, apa yang harus dilakukan coder.
Jangan menulis LULUS kalau ragu.
"""


class DevTeamError(ValueError):
    pass


def branch_for(job_id: int) -> str:
    return f"jarvis/devjob-{job_id}"


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
    out = CODER.format(branch=job["branch"]) + "\nPERMINTAAN PEMILIK:\n" + job["request"] + "\n\nSPESIFIKASI (dari bisan):\n" + (job["spec"] or "")
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
    if not job or job["status"] in ("done", "failed", "cancelled"):
        return
    role = t["dev_role"]
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
    if not job or job["status"] in ("done", "failed", "cancelled"):
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
    brief = (QAQA.format(branch=job["branch"], change=job["change_id"]) + "\nPERMINTAAN PEMILIK:\n" + job["request"]
             + "\n\nSPESIFIKASI (dari bisan):\n" + (job["spec"] or "") + "\n\n" + runner)
    await _spawn(job, "qaqa", f"periksa #{job['change_id']}: {_short(job['request'])}", brief)


async def resume() -> int:
    """After a restart: proposals still under test get their waiter back."""
    rows = await db.pool().fetch("SELECT id FROM dev_jobs WHERE status = 'testing'")
    for r in rows:
        asyncio.create_task(_after_tests(r["id"]))
    return len(rows)


async def cancel(job_id: int, actor: str) -> bool:
    from . import workers
    job = await _job(job_id)
    if not job or job["status"] in ("done", "failed", "cancelled"):
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
