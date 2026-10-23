"""Questions about models that deserve a grounded answer, not a model's memory (ADR-039).

Asked "apa kelebihan deepseek v4 flash dibanding qwen3.7 flash?" the chat model answered from imagination ($0.001
per million, 256K context, "Qwen reasons better" — all invented), and for "cek saldo openrouter" it only said "aku
cek sekarang ya". These questions are recognised by the router and answered here with the real catalog, OpenRouter's
provider stats, JARVIS' own calls and the live check — the numbers are code's, the wording is fixed.
"""

import re

from . import composition, modelinsight, openrouter

STOP = {"apa", "kelebihan", "kekurangan", "dan", "bandingkan", "banding", "dibanding", "dibandingkan", "dengan", "vs", "versus", "model",
        "mana", "yang", "lebih", "bagus", "baik", "beda", "perbedaan", "antara", "atau", "dari", "sih", "ya", "dong", "tolong", "itu",
        "nya", "jelaskan", "jarvis", "openrouter", "cepat", "murah", "mana", "untuk", "pakai", "saja", "aja", "ini", "ke", "di"}
_SPLIT = re.compile(r"\b(?:dan|vs|versus|dibanding(?:kan)?|dengan|atau|antara)\b|[,/&]")


def split_names(text: str) -> list[list[str]]:
    """'kelebihan deepseek v4 flash dibanding qwen3.7 flash' → [['deepseek','v4','flash'], ['qwen3.7','flash']]. Pure."""
    chunks = []
    for chunk in _SPLIT.split(re.sub(r"[?!]|\.(?=\s|$)", " ", text.lower())):  # a dot inside "qwen3.7" stays
        tokens = [t for t in chunk.split() if t not in STOP]
        if tokens:
            chunks.append(tokens)
    return chunks[:3]


def pick_best(candidates: list[dict], tokens: list[str], used: set[str]) -> dict | None:
    """Of the catalog matches, the one the owner most likely means: used by JARVIS, no batch/alias variants, free only
    when asked, then the shortest id. Pure."""
    if not candidates:
        return None
    wants_free = "free" in tokens or "gratis" in tokens

    def rank(m: dict):
        return (m["free"] != wants_free, m["id"] not in used, m["id"].endswith(":batch"), m["id"].startswith("~"),
                len(m["id"]), m["id"])
    return sorted(candidates, key=rank)[0]


def _line(label: str, items: list[str], mark: str, limit: int = 4) -> list[str]:
    return [f"{label}:"] + [f"  {mark} {t}" for t in items[:limit]] if items else []


async def compare(text: str) -> str | None:
    """Pros, cons, errors and speed of the models named in the text; None when no model name is recognised."""
    models = await openrouter.catalog()
    if models is None:
        return None
    used = set((await modelinsight.usage(14)).keys())
    found, missing = [], []
    for tokens in split_names(text):
        tokens = [t.replace("free", "") if t in ("free", "gratis") else t for t in tokens if t not in ("gratis",)]
        tokens = [t for t in tokens if t]
        best = pick_best(openrouter.search(models, " ".join(tokens), sort="termurah", limit=200), tokens, used) if tokens else None
        (found if best else missing).append(best or " ".join(tokens))
    found = [m for i, m in enumerate(found) if m not in found[:i]]
    if not found:
        return None
    out = []
    for m in found:
        d = await modelinsight.insight(m["id"])
        mk, jv = d["pasar"] or {}, d["jarvis"] or {}
        head = f"{m['name']} ({m['id']}) — {openrouter.short(m)['harga_per_juta_token']}, konteks {m['context'] // 1000}K"
        facts = []
        if mk.get("latency_p50_ms") is not None:
            facts.append(f"mulai menjawab median {modelinsight.fmt_ms(mk['latency_p50_ms'])}, menulis ~{mk.get('throughput_p50') or '?'} token/detik, "
                         f"aktif {mk.get('uptime_1d_avg')}% sehari terakhir")
        if jv:
            facts.append(f"di JARVIS {jv['calls']} panggilan, {jv['ok_pct']}% berhasil, median {modelinsight.fmt_ms(jv['p50_ms'])}"
                         + (f"; gagal karena {', '.join(f'{k} ×{n}' for k, n in jv['errors'].items())}" if jv["errors"] else ""))
        out.append("\n".join([head] + [f"  • {f}" for f in facts] + _line("  Kelebihan", d["kelebihan"], "✓") + _line("  Kekurangan", d["kekurangan"], "⚠")
                             + ([f"  Cocok untuk: {', '.join(g['nama'] for g in d['cocok_untuk'])}"] if d["cocok_untuk"] else [])))
    tail = ("\n\n(Tidak kutemukan di katalog: " + ", ".join(missing) + ".)") if missing else ""
    return "\n\n".join(out) + tail + "\n\nYang kuukur hanya harga, kecepatan, keandalan dan kemampuan — kualitas jawabannya tidak bisa diukur otomatis. " \
        "Di aplikasi: Komposisi AI → pilih model → ketuk untuk detail & Uji sekarang."


async def stats(text: str) -> str:
    """The models JARVIS used, worst reliability / slowest / cheapest first, depending on the question."""
    m = re.search(r"(\d{1,2})\s*(hari|minggu|bulan)", text.lower())
    days = int(m.group(1)) * {"hari": 1, "minggu": 7, "bulan": 30}[m.group(2)] if m else 7
    rows = [s for s in (await modelinsight.usage(days)).values() if s["calls"] >= 3]
    if not rows:
        return f"Belum ada cukup panggilan model dalam {days} hari terakhir."
    low = text.lower()
    if re.search(r"tercepat|paling cepat", low):
        rows = sorted((r for r in rows if r["p50_ms"]), key=lambda r: r["p50_ms"])
        title = "Tercepat (median waktu per panggilan)"
    elif re.search(r"termurah|paling murah", low):
        rows = sorted(rows, key=lambda r: r["cost_per_call_usd"])
        title = "Termurah per panggilan"
    else:
        rows = sorted(rows, key=lambda r: (r["ok_pct"] if r["ok_pct"] is not None else 101, -r["calls"]))
        title = "Paling sering gagal"
    lines = [f"{title} — {days} hari terakhir (kegagalan karena kredit habis tidak dihitung):"]
    for r in rows[:6]:
        name = r["model"] if r["provider"] == "openrouter" else ("model lokal (ngobrol)" if r["provider"] == "lokal" else "model lokal (kerja)")
        err = ", ".join(f"{k} ×{n}" for k, n in sorted(r["errors"].items(), key=lambda kv: -kv[1])[:2])
        lines.append(f"• {name}: {r['calls']} panggilan, {r['ok_pct']}% berhasil, median {modelinsight.fmt_ms(r['p50_ms'])}, "
                     f"{'gratis' if not r['cost_usd'] else f'${r['cost_per_call_usd']:.4f}/panggilan'}" + (f" — gagal: {err}" if err else ""))
    return "\n".join(lines) + "\nRinci per model: Lainnya → Statistik model."


async def openrouter_check(actor: str) -> str:
    r = await composition.check_openrouter(actor)
    bits = [r.get("kesimpulan") or "Tidak ada hasil."]
    if r.get("kredit_menurut_openrouter_usd") is not None:
        bits.append(f"Menurut OpenRouter: kredit ${r['kredit_menurut_openrouter_usd']:g}, terpakai ${r.get('terpakai_usd', 0):.2f}.")
    if r.get("akun_gratis"):
        bits.append("Akun masih berstatus gratis (model :free dibatasi 50 permintaan/hari).")
    return " ".join(bits)
