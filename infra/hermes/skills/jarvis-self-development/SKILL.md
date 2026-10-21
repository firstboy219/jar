---
name: jarvis-self-development
description: "Saat pemilik minta kemampuan yang belum ada, permintaannya gagal karena kemampuan kecil yang kurang, atau JARVIS lambat/boros/sering gagal: skill, workflow n8n, jadwal — dan perubahan KODE (performa & fitur minor) lewat propose_code_change."
version: 2.1.0
author: JARVIS
license: MIT
metadata:
  hermes:
    tags: [JARVIS, Indonesia]
---
# Mengembangkan & mempercepat JARVIS

## Batas dari pemilik (tidak bisa ditawar)
Perubahan KODE pada diri JARVIS hanya boleh untuk:
1. **Performa** — mengerjakan permintaan pemilik lebih cepat, lebih murah, atau lebih jarang gagal.
2. **Fitur minor** — menutup kemampuan kecil yang kurang di dalam arsitektur yang ada (mis. sumber lagu baru,
   format file baru, sumber data baru, perbaikan panel Panggung yang sudah ada).
Tidak boleh: fitur besar/arsitektur baru, mengubah keamanan/izin/persetujuan/rahasia/komposisi AI/anggaran,
izin Android baru, melemahkan atau menghapus tes. File di luar batas (mis. `core/app/approvals.py`, `vault.py`,
`main.py`, `infra/scripts/`, `docker-compose.yml`, `.env`, Dockerfile, gradle, manifest) DITOLAK otomatis oleh
penguji — jangan mencoba mengakalinya. Pustaka Python baru hanya di `core/requirements.txt`, dipin persis
`nama==versi` (pemilik melihat daftarnya saat menyetujui).
Hukum & hak cipta: utamakan sumber resmi/berlisensi. Bila satu-satunya cara berisiko melanggar ketentuan
layanan atau hak cipta (mis. mengunduh audio dari YouTube), tulis risikonya terang-terangan di `why` — pemilik
yang memutuskan lewat persetujuan.

## Urutan pilihan (paling ringan yang cukup)
1. **Skill Hermes** (`skill_manage`) — prosedur/pengetahuan baru, langsung berlaku.
2. **Workflow n8n** (`n8n_draft_workflow`, lihat n8n-workflow-design) — dibuat nonaktif, aktif setelah persetujuan.
3. **Jadwal Hermes** (`cronjob_manage`) — tugas berulang; hasil lewat `notify_owner`.
4. **Kode — performa atau fitur minor** (alur di bawah).
5. **Fitur besar** (arsitektur/layanan baru, izin baru): JANGAN dikerjakan. Tulis usulan (`create_document`, md: masalah,
   desain, file, risiko, cara uji) dan beri tahu pemilik (`notify_owner`) — developer yang mengerjakan.

## Saat permintaan pemilik gagal ("kemampuan kurang")
Contoh: lagu yang diminta tidak ada di sumber musik berlisensi bebas. Analisis akar penyebab (sumber? alat? format?),
cari cara sendiri (riset web, pustaka yang sudah terpasang — cek `core/requirements.txt`, API gratis tanpa kunci), uji
idenya di workspace, lalu pilih jalan paling ringan di atas. Yang tampil di HP memakai panel Panggung yang sudah ada
(mis. panel musik memutar file dari `/api/v1/media/{id}`), jadi biasanya tidak perlu APK baru.

## Alur perubahan kode (performa / fitur minor)
Workspace: `/opt/data/workspace/jar` (salinan repo JARVIS; `origin` = main terbaru, hanya-baca).
1. `cd /opt/data/workspace/jar && git fetch origin main && git checkout -B jarvis/<topik> origin/main`
   (topik: huruf kecil/angka/minus, mis. `jarvis/cache-ringkasan-rapat`).
2. Pahami kodenya dulu (`grep -rn`, baca modul terkait mis. `core/app/media_tools.py`, `musiclib.py`) dan ukur masalahnya (angka dari tinjauan, `db_query_ro` ke `llm_usage`/`tasks`/`messages.trace`, atau tes waktu).
3. Ubah sesedikit mungkin (≤ 1500 baris). Migrasi hanya boleh FILE BARU `core/app/migrations/NNN_*.sql`, tidak mengubah yang lama.
4. Tambah/ubah tes yang membuktikan perbaikan di `core/tests/` (atau tes unit Android). Jalankan yang bisa dijalankan lokal
   (`python -m py_compile`, potongan logika) — tes penuh dijalankan penguji.
5. `git add -A && git commit -m "<apa yang lebih cepat/murah/andal dan seberapa>"`.
6. `propose_code_change(branch, title, why, task_id)` — `why`: untuk performa angka sebelum/target dan cara mengukurnya; untuk fitur minor apa yang kurang, cara kerjanya, dan risikonya.
7. Tunggu 3–10 menit lalu `check_code_change(change_id)`:
   - `test_failed` → baca `test_log`, perbaiki di cabang yang sama, commit, ajukan lagi (maks 3 kali, lalu laporkan ke pemilik).
   - `awaiting_approval` → selesai; pemilik menyetujui di HP. Setelah dipasang, JARVIS otomatis melapor (atau mengembalikan bila gagal).
   - KONFLIK → `git fetch origin main && git rebase origin/main`, ajukan lagi.

Laporan ke pemilik: apa yang diperbaiki, dampak yang diharapkan (angka), apa yang perlu ia setujui.
