---
name: jarvis-flow-audit
description: "Pengawas Alur: memperbaiki masalah cara JARVIS melayani pemilik — jawaban tidak sesuai konteks, janji tanpa tugas, jawaban berulang, lambat, tugas gagal. Dipakai oleh tugas '[pengawas alur]'."
version: 1.0.0
author: JARVIS
license: MIT
metadata:
  hermes:
    tags: [JARVIS, Indonesia]
---
# Pengawas Alur — dari masalah obrolan ke perbaikan

Konsep pemilik: hanya AGEN UTAMA yang mengobrol (memahami, menyusun konteks, mendelegasikan, melaporkan);
WORKER hanya mengerjakan dan melapor ke agen utama. Masalah alur = salah satu mata rantai itu putus.

## 1. Pahami buktinya (baca-saja)
- Masalah: `db_query_ro`: `SELECT id, kind, detail, owner_said, jarvis_said FROM flow_issues WHERE status IN ('open','fixing') ORDER BY id DESC LIMIT 20`
- Percakapan lengkap di sekitarnya: `SELECT id, created_at, role, route, left(content,300), trace FROM messages WHERE session_id = '<sid>' AND id BETWEEN <id-12> AND <id+4> ORDER BY id`
- Tugas di sekitarnya: `SELECT id, kind, title, status, category, left(instruction,300), left(error,200), started_at, finished_at FROM tasks WHERE created_at BETWEEN … ORDER BY id`
- Model yang menjawab: kolom `trace->'route'` (lokal = Qwen kecil di CPU) dan `llm_usage`.

## 2. Petakan ke penyebab
| Gejala | Tempat yang biasanya salah |
|---|---|
| janji tanpa tugas, tidak mendelegasikan | prompt SYSTEM di `core/app/assistant.py`; pola `_PROMISE`; aksi langsung `core/app/router.py` (`parse_action`) |
| tidak nyambung / membeo konteks | `_situation()` di assistant.py (apa saja yang masuk prompt), riwayat `_history()` |
| jawaban berulang | riwayat & konteks; suhu model |
| tugas lambat/gagal | `core/app/workers.py`, pekerja cepat `core/app/quick.py`, skill Hermes yang dipakai tugas itu |
| salah dengar | kosakata STT (perbaikan "stt_keyword" lewat cek diri) |
| model terlalu kecil / saldo habis | BUKAN bug kode — sarankan pemilik (kunci Groq gratis untuk ngobrol, isi OpenRouter) |

## 3. Perbaiki (paling ringan dulu)
1. Skill Hermes (bila masalahnya di cara worker bekerja).
2. Setelan yang diizinkan (lewat persetujuan).
3. Kode lewat alur skill jarvis-self-development: cabang `jarvis/<topik>`, TES yang mereproduksi percakapan
   bermasalah (contoh: `core/tests/test_integration.py::test_a_promise_without_action_still_starts_the_work`),
   `propose_code_change`, `check_code_change`. Batas: performa & fitur minor; bukan keamanan/izin/persetujuan.
Jangan "memperbaiki" dengan mematikan pemeriksaan, menghapus tes, atau menyembunyikan masalah dari pemilik.

## 4. Laporan
2–3 kalimat lisan: masalahnya (dengan contoh ucapan pemilik), penyebabnya, apa yang diperbaiki atau perlu disetujui.
