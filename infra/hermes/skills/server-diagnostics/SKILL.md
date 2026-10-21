---
name: server-diagnostics
description: "Periksa kesehatan server JARVIS: CPU/RAM/disk, layanan, error, biaya AI, latensi — baca-saja."
version: 1.0.0
author: JARVIS
license: MIT
metadata:
  hermes:
    tags: [JARVIS, Indonesia]
---
# Diagnostik server

- `host_metrics`: load, RAM, swap, disk, status tiap layanan.
- Biaya & model: `db_query_ro` → `SELECT category, model, count(*), sum(cost_usd) FROM llm_usage WHERE at > now()-interval '1 day' GROUP BY 1,2 ORDER BY 4 DESC`.
- Latensi suara: `SELECT created_at, trace FROM messages WHERE trace IS NOT NULL ORDER BY id DESC LIMIT 20`.
- Error: tabel `error_log`; log proxy `/opt/external/proxy_logs`, log host `/opt/external/host_logs`.
- Server 2 core: beban tinggi saat model lokal bekerja itu normal (prioritas rendah).
- Temuan → ringkas untuk pemilik; tindakan yang mengubah server = minta persetujuan.
