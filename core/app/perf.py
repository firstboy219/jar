"""Efficiency self-review (ADR-026): once a week — and when the same error keeps failing work — JARVIS
looks at how well it did what the owner asked (speed, cost, failures) and makes itself better at it.

Allowed means, lightest first: a Hermes skill (applies at once), a whitelisted setting (owner approval),
or a code change via propose_code_change (tests + owner approval + automatic rollback). The scope is
performance only: new features and anything about security, permissions, approvals or secrets are not.
"""

import logging
from datetime import datetime, timedelta, timezone

from . import db
from .location import WIB

log = logging.getLogger("jarvis-core.perf")

SCOPE = """BATAS (ditetapkan pemilik): perbaikan HANYA untuk membuat JARVIS mengerjakan permintaan pemilik lebih
cepat, lebih murah, atau lebih jarang gagal. TIDAK BOLEH: fitur baru, mengubah keamanan/izin/persetujuan/
rahasia/komposisi AI, atau melemahkan tes. Setiap perubahan kode lewat propose_code_change (diuji otomatis,
pemilik menyetujui di HP, otomatis dikembalikan bila gagal)."""

REVIEW_TASK = """[tinjauan efisiensi mingguan] Tinjau seberapa efisien JARVIS mengerjakan permintaan pemilik minggu ini
dan perbaiki SATU atau DUA hal dengan dampak terbesar.

{scope}

DATA 7 HARI:
{data}

Langkah: cari pola (tugas lambat/gagal berulang, kategori mahal, langkah yang sia-sia, latensi suara). Untuk
tiap perbaikan pilih cara paling ringan: (1) skill Hermes baru/diperbaiki — langsung, (2) setelan yang
diizinkan — usulkan, (3) kode — kerjakan di workspace dengan tes yang membuktikan perbaikannya (ukur
sebelum/sesudah bila bisa), lalu propose_code_change dengan alasan berbasis angka di atas.
Akhiri dengan ringkasan lisan 2–3 kalimat untuk pemilik: apa yang ditemukan dan apa yang diperbaiki/diusulkan."""


async def digest(days: int = 7) -> str:
    since = datetime.now(timezone.utc) - timedelta(days=days)
    q = db.pool()
    tasks = await q.fetch(
        """SELECT category, count(*) AS n, count(*) FILTER (WHERE status = 'failed') AS failed,
                  percentile_cont(0.5) WITHIN GROUP (ORDER BY extract(epoch FROM finished_at - started_at)) AS p50,
                  max(extract(epoch FROM finished_at - started_at)) AS worst,
                  avg(prompt_tokens)::int AS ptok
           FROM tasks WHERE created_at > $1 AND finished_at IS NOT NULL GROUP BY category ORDER BY n DESC""", since)
    slow = await q.fetch(
        """SELECT id, title, category, extract(epoch FROM finished_at - started_at)::int AS s, status
           FROM tasks WHERE created_at > $1 AND finished_at IS NOT NULL ORDER BY s DESC NULLS LAST LIMIT 5""", since)
    failed = await q.fetch(
        "SELECT title, left(coalesce(error, ''), 150) AS e FROM tasks WHERE created_at > $1 AND status = 'failed' ORDER BY id DESC LIMIT 8",
        since)
    llm = await q.fetch(
        """SELECT category, provider, model, count(*) AS calls, count(*) FILTER (WHERE NOT ok) AS failed,
                  coalesce(sum(cost_usd), 0)::float AS cost, avg(first_token_ms)::int AS ftok,
                  (sum(cached_tokens)::float / nullif(sum(prompt_tokens), 0))::numeric(4,2) AS cache
           FROM llm_usage WHERE at > $1 GROUP BY 1, 2, 3 ORDER BY cost DESC, calls DESC LIMIT 15""", since)
    voice = await q.fetchrow(
        """SELECT count(*) AS n, percentile_cont(0.5) WITHIN GROUP (ORDER BY (trace->>'first_say_ms')::int) AS say_p50,
                  percentile_cont(0.5) WITHIN GROUP (ORDER BY (trace->>'stt_ms')::int) AS stt_p50
           FROM messages WHERE created_at > $1 AND trace ? 'first_say_ms'""", since)
    errors = await q.fetch(
        """SELECT count(*) AS n, min(source) AS source, (array_agg(left(message, 140) ORDER BY id DESC))[1] AS m
           FROM error_log WHERE at > $1 GROUP BY signature ORDER BY count(*) DESC LIMIT 6""", since)

    def lines(title, rows, fmt):
        return title + ":\n" + ("\n".join("- " + fmt(r) for r in rows) if rows else "- (tidak ada)")
    return "\n\n".join([
        lines("TUGAS PER KATEGORI", tasks, lambda r: f"{r['category']}: {r['n']} tugas, {r['failed']} gagal, median "
              f"{int(r['p50'] or 0)} dtk, terlama {int(r['worst'] or 0)} dtk, ±{r['ptok'] or 0} token prompt"),
        lines("TUGAS TERLAMA", slow, lambda r: f"#{r['id']} {r['title']} ({r['category']}, {r['s']} dtk, {r['status']})"),
        lines("TUGAS GAGAL", failed, lambda r: f"{r['title']}: {r['e']}"),
        lines("MODEL AI (biaya, kegagalan, cache)", llm, lambda r: f"{r['category']} {r['provider']}/{r['model']}: {r['calls']}x, "
              f"{r['failed']} gagal, ${r['cost']:.4f}, kata pertama {r['ftok'] or '-'} ms, cache {r['cache'] or 0}"),
        f"SUARA: {voice['n'] if voice else 0} giliran, mulai bicara median {int((voice or {}).get('say_p50') or 0)} ms, "
        f"STT median {int((voice or {}).get('stt_p50') or 0)} ms",
        lines("ERROR LAYANAN", errors, lambda r: f"{r['n']}x [{r['source']}] {r['m']}"),
    ])


async def start_review(actor: str = "jarvis-core") -> dict:
    from . import workers
    return await workers.spawn("Tinjauan efisiensi mingguan", REVIEW_TASK.format(scope=SCOPE, data=await digest()),
                               "selfimprove", actor, kind="selfimprove", category="coding")


def weekly_due(last_day, now: datetime | None = None) -> bool:
    now = (now or datetime.now(timezone.utc)).astimezone(WIB)
    return now.weekday() == 6 and now.hour == 2 and last_day != now.date()  # Sunday 02:00 WIB


REPAIR_TASK = """[perbaikan otomatis] Error ini terjadi {n} kali dalam 1 jam terakhir di layanan JARVIS ({source}) dan
membuat pekerjaan gagal:
{message}

Traceback terakhir:
{traceback}

{scope}

Pakai skill jarvis-self-repair: cari akar masalahnya. Bila bug kode, perbaiki di workspace dengan tes yang
membuktikan perbaikannya, lalu propose_code_change. Bila bukan bug kode (kunci, saldo, layanan luar), beri
tahu pemilik penyebab dan langkahnya lewat notify_owner."""


async def watch_recurring_errors() -> int:
    """Same error ≥ 3× in an hour → one repair task per signature per day. Returns tasks started."""
    from . import workers
    rows = await db.pool().fetch(
        """SELECT signature, count(*) AS n, min(source) AS source, (array_agg(message ORDER BY id DESC))[1] AS message,
                  (array_agg(traceback ORDER BY id DESC))[1] AS traceback
           FROM error_log WHERE at > now() - interval '1 hour' GROUP BY signature HAVING count(*) >= 3""")
    started = 0
    for r in rows:
        if await db.pool().fetchval(
                "SELECT 1 FROM repair_attempts WHERE signature = $1 AND at > now() - interval '1 day'", r["signature"]):
            continue
        t = await workers.spawn("Perbaiki error berulang", REPAIR_TASK.format(
            n=r["n"], source=r["source"], message=r["message"][:600], traceback=(r["traceback"] or "-")[-2500:], scope=SCOPE),
            "selfimprove", "jarvis-core", kind="selfimprove", category="coding")
        await db.pool().execute(
            """INSERT INTO repair_attempts (signature, task_id) VALUES ($1, $2)
               ON CONFLICT (signature) DO UPDATE SET task_id = EXCLUDED.task_id, at = now()""", r["signature"], t["id"])
        started += 1
    return started
