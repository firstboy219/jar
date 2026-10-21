---
name: jarvis-self-repair
description: "Diagnosa bug/masalah JARVIS dari log error, tugas gagal, atau keluhan pemilik — temukan akar masalah dan usulkan perbaikan."
version: 1.1.0
author: JARVIS
license: MIT
metadata:
  hermes:
    tags: [JARVIS, Indonesia]
---
# Mendiagnosa masalah JARVIS

1. **Kumpulkan bukti** (baca-saja):
   - `db_query_ro`: `SELECT at, source, message, left(traceback,800) FROM error_log ORDER BY id DESC LIMIT 20`
   - tugas gagal: `SELECT id, title, left(error,300) FROM tasks WHERE status='failed' ORDER BY id DESC LIMIT 10`
   - jawaban error ke pemilik: `SELECT created_at, content FROM messages WHERE route='error' ORDER BY id DESC LIMIT 10`
   - kesehatan: `host_metrics`; log proxy `/opt/external/proxy_logs`.
2. **Akar masalah, bukan gejala** (skill systematic-debugging): urutan kejadian, pola berulang, sejak kapan.
3. **Bukan bug kode** (kunci API habis, saldo, layanan luar mati, setelan): beri tahu pemilik penyebab & langkahnya (`notify_owner`);
   bila bisa diatasi dengan skill/setelan yang diizinkan, lakukan.
4. **Bug kode**: jangan mengubah server/repo. Buat laporan perbaikan (`create_document`, md): gejala, bukti, akar masalah, perbaikan yang
   diusulkan (potongan kode bila jelas), cara menguji — lalu beri tahu pemilik.
Jangan pernah "memperbaiki" dengan mematikan pemeriksaan keamanan, persetujuan, atau tes.
