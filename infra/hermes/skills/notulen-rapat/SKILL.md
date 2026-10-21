---
name: notulen-rapat
description: "Buat notulen rapat Indonesia yang bisa ditindaklanjuti dari transkrip: ringkasan, keputusan, action item, pertanyaan terbuka."
version: 1.0.0
author: JARVIS
license: MIT
metadata:
  hermes:
    tags: [JARVIS, Indonesia]
---
# Notulen rapat

Struktur: Judul · Waktu · Peserta · **Ringkasan** (3–6 kalimat) · **Keputusan** (daftar) · **Action items** (tabel Siapa | Apa | Tenggat) · **Pertanyaan terbuka** · **Catatan penting** (bagian yang ditandai pemilik).
- Transkrip mesin bisa salah dengar: perbaiki nama/istilah dari konteks & memori, tandai yang ragu dengan (?).
- Action item harus spesifik & bisa dicentang: kata kerja + objek + tenggat ("Opik kirim data UAT, Kamis").
- Keputusan ≠ diskusi: hanya yang disepakati.
- Simpan sebagai docx dengan `create_document`; tawarkan pengingat n8n/cron untuk tiap tenggat (dengan persetujuan).
