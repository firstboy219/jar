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

## Batas dari pemilik (tidak bisa ditawar): tangga T0–T3
| Tingkat | Cakupan | Jalan |
|---|---|---|
| T0 | skill, draf alur n8n, jadwal | aturan biasa (skill lewat `skill_submit`) |
| T1 | performa & kemampuan kecil di backend (≤1500 baris) | `propose_code_change` → tes otomatis → pemilik menyetujui di HALAMAN ADMIN |
| T2 | kode APK, rekonstruksi modul besar (≤6000 baris), penyetelan STT/TTS | hanya bila pemilik membuka T2 di halaman admin: `propose_design` dulu (masalah, perubahan per bagian, risiko, cara uji, cara batal) → disetujui → kerjakan → `propose_code_change(..., design_id=…)` → disetujui lagi |
| T2 tampilan | layar APK, tampilan web | TERKUNCI sampai tangkapan layar sebelum/sesudah tersedia (Fase 4) |
| T3 | zona terlindungi: seluruh `infra/admin/` (halaman admin = titik kontrol), `infra/scripts/`, systemd, compose, `.env`, keamanan/izin/persetujuan/rahasia/komposisi AI/anggaran/router model (`approvals`, `vault`, `sensitive`, `dev`, `selfdev_policy`, `modelrouter`, `chat_settings`, `skills_pipeline`, `gateway`, `composition`, `budget`, `main`…), Dockerfile, gradle, manifest | hanya manusia — boleh mengusulkan lewat `notify_owner`, tidak pernah mengubah |
Tes boleh ditambah, TIDAK boleh dilemahkan atau dihapus (penjalan menolak diff yang menghapus/mengubah baris tes).
Penjalan menilai diff yang SEBENARNYA dengan aturan dari `main` — jangan mencoba mengakalinya. Ringkasan untuk
pemilik dibuat penjalan; alasanmu (`why`) ditampilkan berlabel "tidak diverifikasi", jadi tulis jujur dan lengkap.
Pemilik bisa MENJEDA semua perubahan diri dari halaman admin; saat dijeda, usulan apa pun ditolak. Pustaka Python baru hanya di `core/requirements.txt`, dipin persis
`nama==versi` (pemilik melihat daftarnya saat menyetujui).
Hukum & hak cipta: utamakan sumber resmi/berlisensi. Bila satu-satunya cara berisiko melanggar ketentuan
layanan atau hak cipta (mis. mengunduh audio dari YouTube), tulis risikonya terang-terangan di `why` — pemilik
yang memutuskan lewat persetujuan.

## Belajar skill baru (prosedur) — jalur yang menguji dulu
Tiga jenis belajar, jangan dicampur:
- **Pengetahuan** (fakta, dokumentasi, angka) → `memory_save` dengan `evidence` (sumber) dan `verified` bila sudah dicek; ingatan salah → `memory_correct`.
- **Prosedur** (cara mengerjakan sesuatu yang berulang) → `skill_submit`. Sebelum itu `capability_search`: mungkin sudah ada.
- **Sistem** (konfigurasi, dependensi, izin, kode JARVIS) → persetujuan pemilik / `propose_code_change` (batas di bawah tetap berlaku).

`skill_submit(name, description, content, cases, scripts?)`: `content` = isi skill dengan bagian `## Kapan dipakai`, `## Input dan output`,
`## Langkah`, `## Kriteria berhasil`, `## Jika gagal`, `## Izin yang dibutuhkan`, `## Kasus uji`. `cases` (2–8) =
`{"situation","expect"}`: model penguji LAIN menilai apakah mengikuti langkahmu menghasilkan yang diharapkan. Tanpa rahasia, tanpa
instruksi yang mengubah aturan/persetujuan. Skrip (opsional, maks 3, pustaka standar saja, tanpa jaringan/berkas/eval) dijalankan
di sandbox tanpa jaringan dan butuh persetujuan pemilik; kasusnya `{"name","args":[…],"expect":"teks di keluaran"}`.
Bila `rejected`, perbaiki sesuai `problems` lalu ajukan lagi; `skill_status(name)` menunjukkan hasil per kasus. Skill yang sudah
terbit dipakai ulang lewat `capability_search`; catat hasilnya di `task_verify`. Setiap versi tersimpan dan bisa dikembalikan pemilik.

## Urutan pilihan (paling ringan yang cukup)
1. **Skill baru** (`skill_submit`, BUKAN `skill_manage`) — prosedur baru. Lihat "Belajar skill baru" di bawah.
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
