---
name: security-review
description: "Tinjau kode/konfigurasi untuk celah keamanan (injeksi, auth, rahasia, akses) sebelum diusulkan."
version: 1.0.0
author: JARVIS
license: MIT
metadata:
  hermes:
    tags: [JARVIS, Indonesia]
---
# Review keamanan

Periksa: input tak tervalidasi (SQL/command/path), auth & scope endpoint baru (device `owner`, admin internal-only, tolak X-Forwarded-For untuk internal), rahasia di kode/log, SSRF (URL dari pengguna/web), izin file, dependensi baru (versi dipin, sumber tepercaya), data pribadi ke cloud (`/privat` harus lokal).
Temuan: tingkat (tinggi/sedang/rendah), skenario serangan konkret, perbaikan. Temuan tinggi harus diselesaikan sebelum perubahan diusulkan ke pemilik.
