---
name: jarvis-self-repair
description: "Diagnosa bug/masalah JARVIS dari log error, tugas gagal, atau keluhan pemilik — temukan akar masalah lalu perbaiki (skill/setelan, atau kode lewat propose_code_change bila membuat kerja lebih andal)."
version: 2.0.0
author: JARVIS
license: MIT
metadata:
  hermes:
    tags: [JARVIS, Indonesia]
---
# Memperbaiki masalah JARVIS

1. **Kumpulkan bukti** (baca-saja):
   - `db_query_ro`: `SELECT at, source, message, left(traceback,800) FROM error_log ORDER BY id DESC LIMIT 20`
   - tugas gagal: `SELECT id, title, left(error,300) FROM tasks WHERE status='failed' ORDER BY id DESC LIMIT 10`
   - jawaban error ke pemilik: `SELECT created_at, content FROM messages WHERE route='error' ORDER BY id DESC LIMIT 10`
   - kesehatan: `host_metrics`; log proxy `/opt/external/proxy_logs`.
2. **Akar masalah, bukan gejala** (skill systematic-debugging): urutan kejadian, pola berulang, sejak kapan. Reproduksi di
   workspace `/opt/data/workspace/jar` bila bisa (tes yang gagal sebelum perbaikan).
3. **Bukan bug kode** (kunci API habis, saldo, layanan luar mati, setelan): beri tahu pemilik penyebab & langkahnya
   (`notify_owner`); bila bisa diatasi dengan skill/setelan yang diizinkan, lakukan.
4. **Bug kode yang membuat permintaan pemilik gagal/lambat**: perbaiki lewat alur kode di skill jarvis-self-development
   (cabang `jarvis/<topik>`, tes yang membuktikan, `propose_code_change`, `check_code_change`). Pemilik menyetujui sebelum dipasang;
   gagal cek kesehatan → otomatis dikembalikan.
5. **Bug di area terlarang** (keamanan, izin, persetujuan, rahasia, komposisi, anggaran, skrip infra) atau perbaikan yang berarti
   fitur besar: JANGAN diubah. Buat laporan (`create_document`, md: gejala, bukti, akar masalah, usulan, cara uji) dan beri tahu pemilik.
Jangan pernah "memperbaiki" dengan mematikan pemeriksaan keamanan, persetujuan, atau tes.
