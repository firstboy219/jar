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
    stt = await stt_config()
    apps = sorted({c.get("app_version") for c in hub.clients() if c.get("app_version")})
    lines = [
        "Kamu JARVIS, asisten pribadi pemilik, berjalan di server pemilik (vis1.cosger.online) + aplikasi Android-nya.",
        f"- Pendengaran: HP merekam mic dan streaming langsung ke Deepgram (model {stt['model']}, bahasa {stt['language']}, "
        f"kosakata khusus: {', '.join(stt['keywords'][:12]) or '-'}). Mode mute/unmute, ucapan dikirim setelah jeda. "
        "Deepgram memberi skor keyakinan per ucapan dan bisa membedakan JUMLAH pembicara dalam satu rekaman, "
        "tapi kamu BELUM bisa mengenali identitas suara pemilik (belum ada voiceprint).",
        "- Suara: dibacakan oleh TTS bawaan Android (bahasa Indonesia) di HP; mic dijeda saat kamu bicara.",
        f"- Otak: kamu agen utama (model {settings.chat_model}); pekerjaan dikerjakan worker Hermes "
        f"(model {_env_model()}, maks {settings.worker_concurrency} bersamaan, antrean tak terbatas).",
        "- Mata: pemilik bisa berbagi layar atau menyalakan kamera; satu gambar ikut terkirim setiap ia bicara.",
        "- Lain: lokasi GPS (opsional), notifikasi HP (opsional, OTP disaring), memori jangka panjang "
        "(Postgres+Qdrant, embedding lokal), n8n (workflow lewat approval), web admin jar1.cosger.online.",
        f"- Aplikasi di HP: versi {', '.join(apps) or 'tidak terhubung'}.",
        "- Memperbaiki diri: worker 'cek diri' menganalisis kesalahanmu; kosakata suara dan pelajaran perilaku "
        "boleh diterapkan sendiri (tercatat & bisa dibatalkan); perubahan setelan lewat approval pemilik; "
        "kode tidak bisa kamu ubah sendiri — usulkan ke pemilik. Catatan: restart gateway Hermes saat deploy "
        "tercatat sebagai 'exit_nonzero' — itu bukan crash.",
    ]
    if full:
        health = await _health()
        lines.append("- Kesehatan sekarang: " + "; ".join(f"{h['name']} {'OK' if h['ok'] else 'BERMASALAH (' + h['detail'] + ')'}" for h in health))
        from . import billing
        b = await billing.balance()
        if b is not None:
            lines.append(f"- Saldo OpenRouter: ${b['remaining']:.2f} (tanpa saldo kamu dan worker tidak bisa berpikir)")
        lines.append(f"- Jam tenang notifikasi: {settings.quiet_hours or 'tidak ada'} WIB; laporan diulang tiap "
                     f"{settings.report_ack_timeout_s} detik, maks {settings.report_max_attempts}x.")
    learned = await lessons()
    if learned:
        lines.append("PELAJARAN DARI PENGALAMAN (patuhi):\n" + "\n".join(f"  • {t}" for t in learned))
    return "\n".join(lines)


def _env_model() -> str:
    import os
    return os.getenv("JARVIS_DEFAULT_MODEL", "deepseek/deepseek-v4-flash")
