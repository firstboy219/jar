---
name: web-login-aman
description: "Masuk ke situs untuk pemilik memakai brankas (browser_vault) tanpa pernah melihat/meminta password di chat."
version: 1.0.0
author: JARVIS
license: MIT
metadata:
  hermes:
    tags: [JARVIS, Indonesia]
---
# Login web yang aman

- Jangan pernah meminta pemilik mengetik password di chat; jangan menulis password di memori, file, atau hasil.
- Di halaman login: `browser_vault list` → ada handle untuk origin persis itu? → ketik identifier (boleh dilihat) → `browser_vault fill` untuk password. Origin harus sama persis.
- Tidak ada di brankas → minta pemilik menyimpannya di APK (Lainnya → Password, centang "boleh dipakai JARVIS") atau login sendiri lewat panel web di HP (`stage_show` panel "web" mode "login").
- OTP/2FA: tanya pemilik lewat `ask_owner` (kode berlaku singkat), jangan simpan.
- Setelah login, kerjakan hanya yang diminta; tindakan finansial/kirim/hapus tetap butuh persetujuan.
