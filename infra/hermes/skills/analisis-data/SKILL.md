---
name: analisis-data
description: "Analisis data/tabel (CSV/xlsx/hasil query): bersihkan, hitung, temukan pola, buat grafik & kesimpulan."
version: 1.0.0
author: JARVIS
license: MIT
metadata:
  hermes:
    tags: [JARVIS, Indonesia]
---
# Analisis data

1. Pahami pertanyaan bisnisnya dulu; tulis metrik yang dicari.
2. Muat data dengan pandas (`execute_code`), cek: jumlah baris, kolom kosong, duplikat, tipe tanggal/angka.
3. Hitung yang ditanya + 1–2 temuan tak terduga yang relevan. Sebutkan asumsi & data yang dibuang.
4. Grafik bila membantu (matplotlib → PNG → `show_media` atau lampirkan di dokumen).
5. Hasil: 3 temuan utama dengan angka, keterbatasan data, rekomendasi. Simpan tabel hasil ke xlsx bila diminta.
