---
name: n8n-workflow-design
description: "Rancang otomasi n8n yang andal: trigger, langkah, penanganan error — dibuat nonaktif dan menunggu persetujuan."
version: 1.0.0
author: JARVIS
license: MIT
metadata:
  hermes:
    tags: [JARVIS, Indonesia]
---
# Desain workflow n8n

Sebelum `n8n_draft_workflow`, tulis deskripsi lengkap:
- **Trigger**: jadwal (cron WIB), webhook, atau event aplikasi.
- **Langkah** berurutan dengan node nyata (HTTP Request, Code, IF, Set, Gmail, Google Sheets, Telegram…).
- **Data**: input/output tiap langkah, format.
- **Error**: retry, timeout (≤10 detik untuk web, BRD), notifikasi kegagalan.
- **Kredensial**: sebutkan yang dibutuhkan; pemilik memilihnya di n8n — jangan pernah menaruh rahasia di workflow.
Workflow dibuat NONAKTIF; aktivasi hanya lewat persetujuan pemilik. Beri tahu nomor persetujuannya.
