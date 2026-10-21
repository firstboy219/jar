---
name: jarvis-self-development
description: "Saat pemilik minta kemampuan yang belum ada, atau JARVIS lambat/boros/sering gagal: skill, workflow n8n, jadwal — dan perbaikan KODE khusus performa lewat propose_code_change."
version: 2.0.0
author: JARVIS
license: MIT
metadata:
  hermes:
    tags: [JARVIS, Indonesia]
---
# Mengembangkan & mempercepat JARVIS

## Batas dari pemilik (tidak bisa ditawar)
Perubahan KODE pada diri JARVIS hanya boleh untuk **performa**: mengerjakan permintaan pemilik lebih cepat, lebih murah,
atau lebih jarang gagal. Tidak boleh: fitur baru, mengubah keamanan/izin/persetujuan/rahasia/komposisi AI/anggaran,
melemahkan atau menghapus tes. File di luar batas (mis. `core/app/approvals.py`, `vault.py`, `main.py`, `infra/scripts/`,
`docker-compose.yml`, `.env`, gradle, manifest) DITOLAK otomatis oleh penguji — jangan mencoba mengakalinya.

## Urutan pilihan (paling ringan yang cukup)
1. **Skill Hermes** (`skill_manage`) — prosedur/pengetahuan baru, langsung berlaku.
2. **Workflow n8n** (`n8n_draft_workflow`, lihat n8n-workflow-design) — dibuat nonaktif, aktif setelah persetujuan.
3. **Jadwal Hermes** (`cronjob_manage`) — tugas berulang; hasil lewat `notify_owner`.
4. **Kode — hanya untuk performa** (alur di bawah).
5. **Fitur baru yang butuh kode**: JANGAN dikerjakan. Tulis usulan (`create_document`, md: masalah, desain, file, risiko, cara uji)
   dan beri tahu pemilik (`notify_owner`) — developer yang mengerjakan.

## Alur perubahan kode performa
Workspace: `/opt/data/workspace/jar` (salinan repo JARVIS; `origin` = main terbaru, hanya-baca).
1. `cd /opt/data/workspace/jar && git fetch origin main && git checkout -B jarvis/<topik> origin/main`
   (topik: huruf kecil/angka/minus, mis. `jarvis/cache-ringkasan-rapat`).
2. Ukur dulu masalahnya (angka dari tinjauan, `db_query_ro` ke `llm_usage`/`tasks`/`messages.trace`, atau tes waktu).
3. Ubah sesedikit mungkin (≤ 1500 baris). Migrasi hanya boleh FILE BARU `core/app/migrations/NNN_*.sql`, tidak mengubah yang lama.
4. Tambah/ubah tes yang membuktikan perbaikan di `core/tests/` (atau tes unit Android). Jalankan yang bisa dijalankan lokal
   (`python -m py_compile`, potongan logika) — tes penuh dijalankan penguji.
5. `git add -A && git commit -m "<apa yang lebih cepat/murah/andal dan seberapa>"`.
6. `propose_code_change(branch, title, why, task_id)` — `why` berisi angka sebelum/target dan cara mengukurnya.
7. Tunggu 3–10 menit lalu `check_code_change(change_id)`:
   - `test_failed` → baca `test_log`, perbaiki di cabang yang sama, commit, ajukan lagi (maks 3 kali, lalu laporkan ke pemilik).
   - `awaiting_approval` → selesai; pemilik menyetujui di HP. Setelah dipasang, JARVIS otomatis melapor (atau mengembalikan bila gagal).
   - KONFLIK → `git fetch origin main && git rebase origin/main`, ajukan lagi.

Laporan ke pemilik: apa yang diperbaiki, dampak yang diharapkan (angka), apa yang perlu ia setujui.
