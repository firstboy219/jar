"""JARVIS' knowledge of itself, generated from the running configuration (never hand-written, so it
cannot go stale). Given to the main agent in every prompt and to workers via the `self_info` tool.

Origin: the main agent once insisted it had no Deepgram while the owner was talking to it through
Deepgram, and a worker "verified" that by inspecting the wrong container.
"""

import time

from . import db, hub, status
from .config import settings
from .deepgram import stt_config

_health_cache: tuple[float, list[dict]] = (0.0, [])


async def _health() -> list[dict]:
    global _health_cache
    if time.monotonic() - _health_cache[0] > 60:
        _health_cache = (time.monotonic(), await status.check_all())
    return _health_cache[1]


async def lessons() -> list[str]:
    rows = await db.pool().fetch(
        "SELECT payload->>'text' AS t FROM improvements WHERE kind = 'lesson' AND status = 'applied' ORDER BY id DESC LIMIT 20")
    return [r["t"] for r in rows if r["t"]]


async def describe(full: bool = False) -> str:
    from . import composition, gateway
    stt = await stt_config()
    engine = await composition.stt_engine()
    apps = sorted({c.get("app_version") for c in hub.clients() if c.get("app_version")})
    cats = await gateway.categories()

    def who(name: str) -> str:
        routes = (cats.get(name) or {}).get("routes") or []
        return routes[0]["model"] if routes else "(belum dipilih)"
    hearing = {
        "deepgram": f"HP merekam mic dan mengirim ucapan ke Deepgram (model {stt['model']}); Deepgram memberi skor "
                    "keyakinan dan bisa membedakan JUMLAH pembicara",
        "groq": "HP memotong ucapan (VAD) dan mengirimnya ke server; server menyalin dengan Whisper large-v3-turbo di Groq",
        "whisper": "HP memotong ucapan (VAD) dan mengirimnya ke server; server menyalin dengan Whisper LOKAL (tidak keluar server)",
        "openrouter": "HP memotong ucapan (VAD) dan mengirimnya ke server; server menyalin dengan model transkripsi pilihan pemilik di OpenRouter",
    }.get(engine, f"mesin pengenal suara '{engine}'")  # a new engine must never break every chat turn
    lines = [
        "Kamu JARVIS, asisten pribadi pemilik, berjalan di server pemilik (vis1.cosger.online) + aplikasi Android-nya.",
        f"- Pendengaran: {hearing}. Kosakata khusus: {', '.join(stt['keywords'][:12]) or '-'}. Mode mute/unmute. "
        "Kamu BELUM bisa memastikan identitas suara pemilik kecuali voiceprint sudah direkam.",
        "- Suara: dibacakan TTS di HP, kalimat demi kalimat; mic dijeda saat kamu bicara.",
        f"- Otak: kamu agen utama (ngobrol: {who('ngobrol')}). Pekerjaan dikerjakan worker Hermes "
        f"(maks {settings.worker_concurrency} bersamaan, antrean tak terbatas) dengan AI per kategori: web {who('web')}, "
        f"coding {who('coding')}, produktivitas {who('produktivitas')}, analisis {who('analisis')}. Semua lewat gerbang AI "
        "di server; semua model berjalan di cloud (OpenRouter) — tidak ada model lokal lagi, jadi tanpa kunci/saldo tidak ada yang bisa "
        "menjawab. Pesan /privat tidak didukung; data sensitif hanya dikirim ke model berbayar (bukan gratis). Pemilik bisa mengubah model tiap kategori, anggaran, dll. dari APK (Komposisi AI, pilih dari katalog OpenRouter) "
        "ATAU lewat obrolan denganmu — kamu punya alat find_models dan ai_settings untuk itu.",
        "- Inti permanen: Qdrant+Postgres (memori) dan n8n (otomasi lewat approval). Model apa pun (ngobrol, kerja Hermes, "
        "gambar, draf, notulen) bebas dipilih pemilik dari OpenRouter.",
        "- Mata: pemilik bisa berbagi layar atau menyalakan kamera; satu gambar ikut terkirim setiap ia bicara.",
        "- Layar HP (Panggung): bisa menampilkan musik, video, peta+rute, halaman web, dokumen, draf balasan; "
        "default otak 3D berisi memori.",
        "- Lain: lokasi GPS (opsional), notifikasi HP (opsional, OTP disaring), memori jangka panjang (embedding "
        "di server), dokumen docx/xlsx/pdf, web admin jar1.cosger.online (semua menunya juga ada di APK).",
        f"- Aplikasi di HP: versi {', '.join(apps) or 'tidak terhubung'}.",
        "- Memperbaiki diri: worker 'cek diri' menganalisis kesalahanmu; kosakata suara dan pelajaran perilaku "
        "boleh diterapkan sendiri (tercatat & bisa dibatalkan); perubahan setelan lewat approval pemilik; "
        "kode tidak bisa kamu ubah sendiri — usulkan ke pemilik. Catatan: restart gateway Hermes saat deploy "
        "tercatat sebagai 'exit_nonzero' — itu bukan crash.",
    ]
    if full:
        from . import billing, budget
        health = await _health()
        lines.append("- Kesehatan sekarang: " + "; ".join(f"{h['name']} {'OK' if h['ok'] else 'BERMASALAH (' + h['detail'] + ')'}" for h in health))
        st = await budget.state()
        lines.append(f"- Anggaran AI bulan ini: ${st['spent_usd']:.2f} dari ${st['budget_usd']:.0f} ({st['pct']:.0f}%).")
        v = await billing.verdict()
        lines.append(f"- OpenRouter: {v['text']} (kalau habis, hanya model gratis yang jalan; cek nyata dengan ai_settings check_openrouter)")
        lines.append(f"- Jam tenang notifikasi: {settings.quiet_hours or 'tidak ada'} WIB; laporan hanya dibacakan sekali, tidak diulang.")
    learned = await lessons()
    if learned:
        lines.append("PELAJARAN DARI PENGALAMAN (patuhi):\n" + "\n".join(f"  • {t}" for t in learned))
    return "\n".join(lines)


def _env_model() -> str:
    import os
    return os.getenv("JARVIS_DEFAULT_MODEL", "deepseek/deepseek-v4-flash")
