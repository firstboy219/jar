---
name: dokumen-kantor
description: "Buat dokumen kerja (laporan, proposal, surat, tabel, notulen) sebagai docx/xlsx/pdf dengan struktur yang rapi."
version: 1.0.0
author: JARVIS
license: MIT
metadata:
  hermes:
    tags: [JARVIS, Indonesia]
---
# Dokumen kantor

Pakai `create_document(title, format, content)`:
- **docx**: laporan, proposal, surat, notulen. Markdown sederhana: `#`/`##` judul, `- ` poin, `1. ` nomor, tabel `| a | b |`, **tebal**.
- **xlsx**: data/tabel/perhitungan. Kirim `rows` (list of lists, baris pertama header); angka sebagai angka.
- **pdf**: versi final untuk dibagikan.
Pola isi:
- Laporan: Ringkasan eksekutif → Latar → Temuan (dengan angka & sumber) → Rekomendasi → Lampiran.
- Proposal: Masalah → Solusi → Ruang lingkup → Jadwal → Biaya → Risiko → Langkah berikut.
- Surat resmi Indonesia: kop (bila ada), nomor, lampiran, perihal, "Yth.", isi, "Hormat kami".
Format angka Indonesia: Rp1.250.000, tanggal 21 Oktober 2026. Tampilkan hasil ke HP (`show=true`).
Untuk spreadsheet/presentasi kompleks lihat juga skill excel-author / pptx-author.
