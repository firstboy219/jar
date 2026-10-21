---
name: pengingat-dan-jadwal
description: "Buat pengingat & tugas berulang yang benar-benar sampai ke pemilik (cron Hermes + notify_owner / n8n)."
version: 1.0.0
author: JARVIS
license: MIT
metadata:
  hermes:
    tags: [JARVIS, Indonesia]
---
# Pengingat & jadwal

- Sekali/berulang sederhana → `cronjob_manage` (zona WIB). Prompt job HARUS berakhir dengan memanggil `notify_owner` berisi kalimat lisan singkat; atau jawab "[SILENT]" bila tidak ada yang perlu disampaikan.
- Integrasi aplikasi (email, sheet, API) atau sangat andal → workflow n8n (skill n8n-workflow-design).
- Konfirmasikan ke pemilik: apa, kapan (hari/jam WIB), berapa kali.
- Hindari job yang sering (< 15 menit) memanggil model: boros; pakai gerbang `wakeAgent`/skrip.
