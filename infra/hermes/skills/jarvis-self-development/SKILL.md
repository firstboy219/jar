---
name: jarvis-self-development
description: "Saat pemilik minta kemampuan yang belum ada: buat skill, workflow n8n, atau jadwal; perubahan kode JARVIS diusulkan ke pemilik."
version: 1.1.0
author: JARVIS
license: MIT
metadata:
  hermes:
    tags: [JARVIS, Indonesia]
---
# Mengembangkan kemampuan baru JARVIS

Pakai saat pemilik meminta sesuatu yang belum bisa dilakukan JARVIS.

## Urutan pilihan (pilih yang paling ringan yang cukup)
1. **Skill Hermes** (`skill_manage`) — prosedur/pengetahuan baru, langsung berlaku. Ikuti skill writing-skills: nama jelas,
   deskripsi kapan dipakai, langkah konkret, diuji pada contoh nyata.
2. **Workflow n8n** (`n8n_draft_workflow`, lihat n8n-workflow-design) — otomasi/integrasi aplikasi; dibuat nonaktif, aktif setelah persetujuan.
3. **Jadwal Hermes** (`cronjob_manage`, lihat pengingat-dan-jadwal) — tugas berulang; hasil ke pemilik lewat `notify_owner`.
4. **Butuh perubahan kode JARVIS** (endpoint/layar APK baru, perilaku inti): JANGAN mengubah server atau repo. Tulis USULAN
   dengan `create_document` (format md): masalah, desain, file yang kemungkinan berubah, risiko, cara uji — lalu beri tahu pemilik
   (`notify_owner`) bahwa usulan siap untuk dikerjakan developer. Juga tersimpan sebagai perbaikan jenis "code" lewat cek diri.

Laporan ke pemilik: apa yang dibuat (skill/workflow/jadwal/usulan), sudah dicoba atau belum, apa yang perlu ia setujui.
