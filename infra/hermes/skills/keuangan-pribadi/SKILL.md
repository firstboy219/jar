---
name: keuangan-pribadi
description: "Hitung cicilan, KPR, bunga, investasi sederhana, anggaran bulanan — dengan rumus yang benar dan asumsi jelas."
version: 1.0.0
author: JARVIS
license: MIT
metadata:
  hermes:
    tags: [JARVIS, Indonesia]
---
# Keuangan pribadi (perhitungan, bukan nasihat investasi berlisensi)

- Cicilan anuitas: A = P·r/(1−(1+r)^−n), r = bunga tahunan/12. Bunga flat: total bunga = P·i·tahun.
- Selalu jelaskan asumsi (bunga fix/floating, biaya provisi, asuransi) dan tampilkan tabel ringkas (bulan, pokok, bunga, sisa) bila diminta → xlsx.
- Anggaran: 50/30/20 sebagai titik awal; sesuaikan dengan data pemilik.
- Pajak & aturan berubah: cek sumber resmi terbaru (pajak.go.id, OJK) dan sebut tanggalnya.
- Tidak melakukan transaksi, transfer, atau pembelian instrumen apa pun.
