---
name: perjalanan-dan-rute
description: "Rencanakan perjalanan: jarak, waktu tempuh, pilihan rute, waktu berangkat terbaik, persiapan."
version: 1.0.0
author: JARVIS
license: MIT
metadata:
  hermes:
    tags: [JARVIS, Indonesia]
---
# Perjalanan & rute

- Jarak/rute → `show_route(destination, origin, mode)`; origin kosong = lokasi pemilik sekarang.
- Sebutkan apakah waktu tempuh memakai data macet (TomTom) atau tidak.
- Jam sibuk Jabodetabek: 06.00–09.00 & 16.00–20.00; tambahkan cadangan waktu.
- Untuk agenda: hitung jam berangkat = jam acara − waktu tempuh − cadangan 15–30 mnt; tawarkan pengingat (cron + notify_owner).
- Perjalanan jauh: opsi kereta/pesawat/mobil dengan perkiraan biaya & durasi; cuaca tujuan.
