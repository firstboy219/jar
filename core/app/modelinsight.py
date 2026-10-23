"""What the owner needs to choose a model: pros and cons, how often it fails, how fast it answers (ADR-039).

Four sources, kept apart so the owner sees what each says:
  catalog    OpenRouter's list: price, context, abilities (openrouter.py)
  market     OpenRouter's per-provider stats for the model: uptime, latency, throughput (public endpoint)
  jarvis     this server's own calls (llm_usage): how many, how often they failed and why, how long they took
  bench      the owner's "Uji sekarang" checks (model_bench): first token, speed, does it call a tool
`assess()` turns them into plain statements. It measures price, speed, reliability and abilities — NOT how smart the
answers are; no source for that exists and the app says so.
"""

import logging
import re
import statistics
import time

import httpx

from . import db, openrouter

log = logging.getLogger("jarvis-core.modelinsight")
ENDPOINTS_URL = "https://openrouter.ai/api/v1/models/{id}/endpoints"
_ep_cache: dict[str, tuple[float, dict | None]] = {}
BENCH_PROMPT = "Jelaskan dalam dua kalimat pendek apa itu API."
BENCH_TOOL = {"type": "function", "function": {"name": "get_time", "description": "Jam sekarang.",
                                                "parameters": {"type": "object", "properties": {}}}}


# ---------- pure: from raw numbers to statements ----------

def summarize_endpoints(endpoints: list[dict]) -> dict:
    """OpenRouter serves a model through several providers; the numbers that matter, over all of them."""
    def med(values):
        values = [v for v in values if isinstance(v, (int, float))]
        return round(statistics.median(values), 1) if values else None
    lat = [(e.get("latency_last_30m") or {}) for e in endpoints]
    thr = [(e.get("throughput_last_30m") or {}) for e in endpoints]
    return {
        "providers": len(endpoints),
        "uptime_1d_avg": med([e.get("uptime_last_1d") for e in endpoints]),
        "uptime_1d_min": min([e["uptime_last_1d"] for e in endpoints if isinstance(e.get("uptime_last_1d"), (int, float))], default=None),
        "uptime_30m_avg": med([e.get("uptime_last_30m") for e in endpoints]),
        "latency_p50_ms": med([x.get("p50") for x in lat]),
        "latency_p90_ms": med([x.get("p90") for x in lat]),
        "latency_best_ms": min([x["p50"] for x in lat if isinstance(x.get("p50"), (int, float))], default=None),
        "throughput_p50": med([x.get("p50") for x in thr]),
        "throughput_best": max([x["p50"] for x in thr if isinstance(x.get("p50"), (int, float))], default=None),
        "quantization": sorted({str(e.get("quantization")) for e in endpoints if e.get("quantization") not in (None, "unknown")}),
        "max_output": max([e["max_completion_tokens"] for e in endpoints if e.get("max_completion_tokens")], default=None),
    }


CREDIT = "kredit tidak cukup (402)"


def fmt_ms(ms) -> str:
    if ms is None:
        return "?"
    return f"{ms / 1000:.1f} dtk".replace(".", ",") if ms >= 1000 else f"{int(ms)} ms"


def classify_error(text: str) -> str:
    """A short label for an error message, for "paling sering: …". Pure."""
    m = re.search(r"HTTP (\d{3})", text or "")
    if m:
        return {"402": "kredit tidak cukup (402)", "403": "ditolak OpenRouter (403)", "404": "model tidak tersedia (404)",
                "429": "kena batas permintaan (429)", "400": "permintaan ditolak (400)", "422": "permintaan ditolak (422)"}.get(
            m.group(1), f"HTTP {m.group(1)}")
    low = (text or "").lower()
    if "timeout" in low:
        return "timeout"
    if "dihentikan" in low or "cancel" in low:
        return "dibatalkan"
    return "gagal lainnya"


CATEGORY_TITLE = {"ngobrol": "Ngobrol", "cepat": "Tugas cepat", "penglihatan": "Melihat gambar", "balas-pesan": "Draf balasan",
                  "web": "Cek web & riset", "coding": "Coding", "produktivitas": "Produktivitas", "analisis": "Analisis berat",
                  "rapat": "Notulen rapat", "latar-belakang": "Kerja latar belakang"}


def assess(info: dict, market: dict | None, own: dict | None, bench: dict | None) -> dict:
    """Pros, cons and "good for", each with the number behind it. Pure; unit-tested.
    own: {calls, ok_calls, p50_ms, errors: {label: n}}; bench: the latest model_bench row (or None)."""
    pros: list[str] = []
    cons: list[str] = []
    free, tools, vision = info["free"], info["tools"], info["vision"]
    out = info["price_out"]
    # price
    if free:
        pros.append("Gratis")
        cons.append("Gratis dibatasi kuota harian (akun tanpa kredit: 50 permintaan/hari) dan lebih sering tidak stabil")
    elif out <= 0.3:
        pros.append(f"Sangat murah (${out:g} per juta token keluar)")
    elif out <= 1.5:
        pros.append(f"Murah (${out:g} per juta token keluar)")
    elif out > 15:
        cons.append(f"Sangat mahal (${out:g} per juta token keluar) — satu percakapan panjang bisa belasan sen")
    elif out > 5:
        cons.append(f"Cukup mahal (${out:g} per juta token keluar)")
    # abilities
    if info["context"] >= 1_000_000:
        pros.append("Konteks sangat besar (1 juta token): sanggup membaca dokumen/riwayat panjang")
    elif info["context"] >= 200_000:
        pros.append(f"Konteks besar ({info['context'] // 1000}K token)")
    elif 0 < info["context"] < 32_000:
        cons.append(f"Konteks kecil ({info['context'] // 1000}K token): mudah kepenuhan pada tugas Hermes")
    if vision:
        pros.append("Bisa melihat gambar")
    if not tools:
        cons.append("Tidak bisa memakai alat (tool calling): tidak cocok untuk ngobrol dengan JARVIS maupun kerja Hermes")
    if bench and bench.get("tools_ok") is True:
        pros.append("Terbukti memanggil alat saat diuji")
    elif bench and bench.get("tools_ok") is False and tools:
        cons.append("Diuji: tidak memanggil alat meski diminta — chat/Hermes bisa macet")
    # speed (market, then own, then bench)
    p50 = (market or {}).get("latency_p50_ms")
    thr = (market or {}).get("throughput_p50")
    if p50 is not None:
        if p50 <= 800:
            pros.append(f"Mulai menjawab cepat (median {fmt_ms(p50)} di OpenRouter)")
        elif p50 >= 3000:
            cons.append(f"Lambat memulai (median {fmt_ms(p50)} di OpenRouter)")
    if thr is not None:
        if thr >= 60:
            pros.append(f"Menulis cepat (~{thr:g} token/detik)")
        elif thr < 25:
            cons.append(f"Menulis lambat (~{thr:g} token/detik)")
    if info.get("reasoning_forced"):
        cons.append("Selalu berpikir dulu (reasoning wajib): lebih teliti tapi lebih lambat dan lebih mahal per jawaban")
    elif info.get("reasoning"):
        pros.append("Bisa diminta berpikir mendalam (reasoning); JARVIS mematikannya untuk chat agar cepat")
    # reliability
    up = (market or {}).get("uptime_1d_avg")
    if up is not None:
        if up >= 99.5 and ((market or {}).get("uptime_1d_min") or 0) >= 95:
            pros.append(f"Stabil di OpenRouter (aktif {up:g}% sehari terakhir)")
        elif up < 97:
            cons.append(f"Sering turun di OpenRouter (aktif {up:g}% sehari terakhir)")
    if market and market["providers"] >= 5:
        pros.append(f"{market['providers']} penyedia: kalau satu turun, OpenRouter pindah ke yang lain")
    elif market and market["providers"] == 1:
        cons.append("Hanya satu penyedia: kalau turun, tidak ada cadangan di OpenRouter")
    if market and "fp4" in market["quantization"]:
        cons.append("Sebagian penyedia menjalankannya terkompresi (fp4): kualitas bisa sedikit turun")
    rate = None
    counted = (own or {}).get("counted_calls", (own or {}).get("calls", 0))
    if own and counted >= 5:
        rate = 100 * own["ok_calls"] / counted
        faults = {k: n for k, n in own["errors"].items() if k != CREDIT}
        worst = max(faults.items(), key=lambda kv: kv[1])[0] if faults else None
        if rate >= 97:
            pros.append(f"Andal di JARVIS: {rate:.0f}% berhasil dari {counted} panggilan")
        elif rate < 85:
            cons.append(f"Sering gagal di JARVIS: hanya {rate:.0f}% berhasil dari {counted} panggilan"
                        + (f" (paling sering: {worst})" if worst else ""))
    if own and own.get("credit_fails"):
        cons.append(f"{own['credit_fails']} panggilan gagal karena kredit akun habis (bukan salah model; tidak dihitung di atas)")
    if info.get("expires"):
        cons.append(f"Akan dihentikan OpenRouter pada {info['expires']}")
    if bench and bench.get("ok") is False:
        cons.append(f"Uji terakhir gagal: {classify_error(bench.get('error') or '')}")
    # good for
    good = []
    fast = (p50 is not None and p50 <= 1500) or (bench and bench.get("ok") and (bench.get("first_ms") or 99999) <= 1500)
    if tools and fast and out <= 1.5:
        good.append("ngobrol")
    if fast and out <= 0.5:
        good += ["cepat", "balas-pesan"]
    if tools and info["context"] >= 128_000 and (info.get("reasoning") or re.search(r"code|coder|codex", info["id"], re.I)):
        good.append("coding")
    if tools and info["context"] >= 200_000:
        good += ["web", "produktivitas"]
    if tools and info.get("reasoning") and info["context"] >= 128_000:
        good.append("analisis")
    if vision:
        good.append("penglihatan")
    if info["context"] >= 128_000 and out <= 1.5 and not free:
        good.append("rapat")
    if (rate is not None and rate < 50) or (bench and bench.get("ok") is False):
        good = []  # what does not work in practice is not "good for" anything
    seen: set[str] = set()
    good = [g for g in good if not (g in seen or seen.add(g))]
    return {"kelebihan": pros, "kekurangan": cons, "cocok_untuk": [{"kategori": g, "nama": CATEGORY_TITLE.get(g, g)} for g in good],
            "catatan": "Yang diukur: harga, kecepatan, keandalan, kemampuan. Seberapa pintar jawabannya tidak bisa diukur otomatis — "
                       "coba lewat 'Uji sekarang' atau pakai beberapa hari."}


# ---------- data ----------

async def market(model_id: str) -> dict | None:
    """OpenRouter's public per-provider stats (10 min cache); None when unavailable."""
    hit = _ep_cache.get(model_id)
    if hit and time.monotonic() - hit[0] < 600:
        return hit[1]
    result = None
    try:
        async with httpx.AsyncClient(timeout=20) as c:
            r = await c.get(ENDPOINTS_URL.format(id=model_id))
        if r.status_code == 200:
            result = summarize_endpoints((r.json().get("data") or {}).get("endpoints") or [])
    except (httpx.HTTPError, ValueError) as e:
        log.warning("endpoint stats for %s: %s", model_id, e)
    _ep_cache[model_id] = (time.monotonic(), result)
    return result


async def usage(days: int = 14, model: str | None = None) -> dict[str, dict]:
    """This server's own calls per model (real traffic, not tests): calls, successes, latency, cost, error causes."""
    days = max(1, min(int(days), 90))
    where, args = "at > now() - make_interval(days => $1) AND caller <> 'test'", [days]
    if model:
        where += " AND model = $2"
        args.append(model)
    rows = await db.pool().fetch(
        f"""SELECT provider, model, count(*) AS calls, count(*) FILTER (WHERE ok) AS ok_calls,
                   percentile_cont(0.5) WITHIN GROUP (ORDER BY latency_ms) FILTER (WHERE ok) AS p50,
                   percentile_cont(0.95) WITHIN GROUP (ORDER BY latency_ms) FILTER (WHERE ok) AS p95,
                   percentile_cont(0.5) WITHIN GROUP (ORDER BY first_token_ms) FILTER (WHERE ok AND first_token_ms IS NOT NULL) AS ft50,
                   coalesce(sum(cost_usd), 0)::float AS cost, max(at) AS last_at
            FROM llm_usage WHERE {where} GROUP BY provider, model""", *args)
    errs = await db.pool().fetch(
        f"SELECT model, error FROM llm_usage WHERE {where} AND NOT ok AND error IS NOT NULL", *args)
    by_model: dict[str, dict] = {}
    for r in rows:
        calls = r["calls"]
        by_model[r["model"] if r["provider"] == "openrouter" else r["provider"]] = {
            "provider": r["provider"], "model": r["model"], "calls": calls, "ok_calls": r["ok_calls"],
            "ok_pct": round(100 * r["ok_calls"] / calls, 1) if calls else None,
            "p50_ms": int(r["p50"]) if r["p50"] is not None else None, "p95_ms": int(r["p95"]) if r["p95"] is not None else None,
            "first_token_ms": int(r["ft50"]) if r["ft50"] is not None else None, "cost_usd": round(r["cost"], 5),
            "cost_per_call_usd": round(r["cost"] / max(r["ok_calls"], 1), 6), "last_at": r["last_at"], "errors": {}}
    for e in errs:
        key = next((k for k, v in by_model.items() if v["model"] == e["model"]), None)
        if key:
            label = classify_error(e["error"])
            by_model[key]["errors"][label] = by_model[key]["errors"].get(label, 0) + 1
    for v in by_model.values():  # no credit is the account's problem, not the model's: left out of the success rate
        credit = v["errors"].get(CREDIT, 0)
        v["credit_fails"] = credit
        v["counted_calls"] = v["calls"] - credit
        v["ok_pct"] = round(100 * v["ok_calls"] / v["counted_calls"], 1) if v["counted_calls"] else None
    return by_model


async def latest_bench(model_id: str) -> dict | None:
    row = await db.pool().fetchrow("SELECT * FROM model_bench WHERE model = $1 ORDER BY at DESC LIMIT 1", model_id)
    return dict(row) if row else None


async def run_bench(model_id: str, actor: str) -> dict:
    """Two small real requests (≈ $0.0001): the speed of a short answer, and whether the model calls a tool."""
    from .config import settings
    if not settings.openrouter_api_key:
        return {"ok": False, "error": "belum ada API key OpenRouter"}
    headers = {"Authorization": f"Bearer {settings.openrouter_api_key}", "HTTP-Referer": "https://vis1.cosger.online", "X-Title": "JARVIS"}
    result: dict = {"model": model_id, "ok": False, "first_ms": None, "total_ms": None, "tokens": None, "tok_s": None,
                    "tools_ok": None, "cost_usd": 0.0, "error": None}
    body = {"model": model_id, "stream": True, "max_tokens": 200, "usage": {"include": True}, "reasoning": {"enabled": False},
            "stream_options": {"include_usage": True}, "messages": [{"role": "user", "content": BENCH_PROMPT}]}
    t0 = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=90) as c:
            async with c.stream("POST", "https://openrouter.ai/api/v1/chat/completions", headers=headers, json=body) as r:
                if r.status_code != 200:
                    result["error"] = f"HTTP {r.status_code}: {(await r.aread()).decode(errors='replace')[:200]}"
                else:
                    usage_data: dict = {}
                    async for line in r.aiter_lines():
                        if not line.startswith("data:") or line.strip() == "data: [DONE]":
                            continue
                        try:
                            chunk = __import__("json").loads(line[5:])
                        except ValueError:
                            continue
                        delta = ((chunk.get("choices") or [{}])[0].get("delta") or {})
                        if result["first_ms"] is None and (delta.get("content") or delta.get("reasoning")):
                            result["first_ms"] = int((time.monotonic() - t0) * 1000)
                        if chunk.get("usage"):
                            usage_data = chunk["usage"]
                    result["total_ms"] = int((time.monotonic() - t0) * 1000)
                    result["tokens"] = usage_data.get("completion_tokens")
                    result["cost_usd"] = float(usage_data.get("cost") or 0)
                    if result["first_ms"] is not None and result["tokens"] and result["total_ms"] > result["first_ms"]:
                        result["tok_s"] = round(result["tokens"] / ((result["total_ms"] - result["first_ms"]) / 1000), 1)
                    result["ok"] = result["first_ms"] is not None
                    if not result["ok"]:
                        result["error"] = "jawaban kosong"
            if result["ok"]:
                tool_body = {"model": model_id, "max_tokens": 200, "tools": [BENCH_TOOL], "tool_choice": "auto",
                             "reasoning": {"enabled": False},
                             "messages": [{"role": "user", "content": "Jam berapa sekarang? Pakai alat get_time."}]}
                tr = await c.post("https://openrouter.ai/api/v1/chat/completions", headers=headers, json=tool_body)
                if tr.status_code == 200:
                    msg = ((tr.json().get("choices") or [{}])[0].get("message") or {})
                    result["tools_ok"] = bool(msg.get("tool_calls"))
                    result["cost_usd"] += float((tr.json().get("usage") or {}).get("cost") or 0)
    except (httpx.HTTPError, ValueError) as e:
        result["error"] = type(e).__name__
    await db.pool().execute(
        """INSERT INTO model_bench (model, ok, first_ms, total_ms, tokens, tok_s, tools_ok, cost_usd, error)
           VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)""", model_id, result["ok"], result["first_ms"], result["total_ms"],
        result["tokens"], result["tok_s"], result["tools_ok"], result["cost_usd"], (result["error"] or "")[:300] or None)
    await db.pool().execute(
        "DELETE FROM model_bench WHERE model = $1 AND id NOT IN (SELECT id FROM model_bench WHERE model = $1 ORDER BY at DESC LIMIT 20)", model_id)
    from . import audit
    await audit.record(actor, "model.bench", None, model=model_id, ok=result["ok"])
    return result


async def insight(model_id: str, category: str = "") -> dict:
    models = await openrouter.catalog() or []
    info = openrouter.get(models, model_id)
    if not info:
        return {"error": f"model {model_id} tidak ada di katalog OpenRouter"}
    mk = await market(model_id)
    own = (await usage(14, model_id)).get(model_id)
    bench = await latest_bench(model_id)
    verdict = assess(info, mk, own, bench)
    if category and category in CATEGORY_TITLE:
        fit = any(g["kategori"] == category for g in verdict["cocok_untuk"])
        verdict["untuk_kategori"] = {"kategori": category, "cocok": fit,
                                     "kata": f"Cocok untuk {CATEGORY_TITLE[category]}" if fit else
                                             f"Tidak termasuk yang paling cocok untuk {CATEGORY_TITLE[category]} (lihat kekurangan)"}
    return {"model": info, "pasar": mk, "jarvis": own, "uji": bench, **verdict}
