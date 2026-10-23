"""Changing JARVIS' settings by talking to it (ADR-038).

Until now the main agent had no tool for any setting: asked "ganti model ngobrol ke deepseek flash" it could
only say it was "not possible from the chat". Two tools, kept few and compact because every tool schema costs
the (possibly local) model prompt tokens:
  find_models(query, …)   search OpenRouter's live catalog (the same list the app's picker shows)
  ai_settings(action, …)  show / set_model / set_budget / set_stt / set_strong_mode / apply_preset /
                          create_category / delete_category / check_openrouter / list_settings / change_setting
Guards: only the owner (owner-scope device, recognised voice), never in a turn that carries attachments or
screen text (text from outside is data, it must not be able to change settings), secrets never through the chat
(they would sit in the history — the app's settings page is write-only), everything audited.
"""

import logging

import httpx

from . import audit, composition, db, gateway, modelinsight, openrouter
from .config import settings

log = logging.getLogger("jarvis-core.chat_settings")
READ_ONLY = {"show", "check_openrouter", "list_settings", "model_info", "model_stats"}
# Settings the chat may not touch: managed by JARVIS itself or covered by a dedicated action.
SETTING_BLOCKED = {"HERMES_PROFILE", "JARVIS_BUDGET_USD"}
ADMIN_URL = "http://jarvis-admin:8000"


async def guard(action: str, device_id, stt: dict | None, has_outside_text: bool) -> str | None:
    """None when allowed, else the plain-language reason. Read-only actions are always allowed."""
    if action in READ_ONLY:
        return None
    if (stt or {}).get("is_owner") is False:
        return "Suara itu belum kukenali sebagai pemilik, jadi pengaturan tidak kuubah."
    if device_id:
        scope = await db.pool().fetchval("SELECT scope FROM devices WHERE id = $1 AND revoked_at IS NULL", device_id)
        if scope != "owner":
            return "Perangkat ini bukan perangkat pemilik, jadi pengaturan hanya bisa dilihat."
    if has_outside_text:
        return ("Ada lampiran/teks layar di pesan ini, jadi pengaturan tidak kuubah (isi lampiran bukan perintah). "
                "Tulis permintaannya sebagai pesan biasa.")
    return None


async def find_models(args: dict) -> dict:
    models = await openrouter.catalog()
    if models is None:
        return {"error": "daftar model OpenRouter belum bisa diambil"}
    found = openrouter.search(models, str(args.get("query") or ""),
                              free=True if args.get("free") else None, vision=True if args.get("vision") else None,
                              tools=True if args.get("tools") else None,
                              max_price_out=args.get("max_price_out") if isinstance(args.get("max_price_out"), (int, float)) else None,
                              sort=str(args.get("sort") or "termurah"), limit=8)
    return {"jumlah_di_katalog": len(models), "hasil": [openrouter.short(m) for m in found]}


async def _admin(method: str, path: str, **kw):
    async with httpx.AsyncClient(timeout=30) as c:
        return await c.request(method, ADMIN_URL + path, headers={"X-Admin-Token": settings.admin_token}, **kw)


async def _fields() -> list[dict]:
    return [f for f in (await _admin("GET", "/internal/settings")).json().get("fields", [])
            if not f.get("secret") and f["key"] not in SETTING_BLOCKED]


async def ai_settings(args: dict, actor: str) -> dict:
    action = str(args.get("action") or "show")
    category, model = str(args.get("category") or ""), str(args.get("model") or "")
    try:
        match action:
            case "show":
                return await composition.summary()
            case "check_openrouter":
                return await composition.check_openrouter(actor)
            case "model_info":
                if not model:
                    return {"error": "sebutkan model (cari idnya dulu dengan find_models)"}
                r = await modelinsight.insight(model, category)
                if "error" in r:
                    return r
                mk, own, bench = r["pasar"] or {}, r["jarvis"] or {}, r["uji"] or {}
                return {"model": r["model"]["name"], "kelebihan": r["kelebihan"], "kekurangan": r["kekurangan"],
                        "cocok_untuk": [g["nama"] for g in r["cocok_untuk"]],
                        "openrouter": {"median_mulai_ms": mk.get("latency_p50_ms"), "token_per_detik": mk.get("throughput_p50"),
                                       "aktif_sehari_pct": mk.get("uptime_1d_avg"), "penyedia": mk.get("providers")},
                        "di_jarvis": {"panggilan": own.get("calls"), "berhasil_pct": own.get("ok_pct"), "median_ms": own.get("p50_ms"),
                                      "error": own.get("errors")} if own else "belum pernah dipakai",
                        "uji_terakhir": {"mulai_ms": bench.get("first_ms"), "token_per_detik": bench.get("tok_s"),
                                         "bisa_alat": bench.get("tools_ok")} if bench else "belum pernah diuji",
                        "catatan": r["catatan"]}
            case "model_stats":
                days = int(args.get("value") or 7) if str(args.get("value") or "7").isdigit() else 7
                stats = sorted((await modelinsight.usage(days)).values(), key=lambda s: -s["calls"])[:12]
                return {"hari": days, "model": [{"model": s["model"], "penyedia": s["provider"], "panggilan": s["calls"],
                                                 "berhasil_pct": s["ok_pct"], "median_ms": s["p50_ms"], "error": s["errors"]} for s in stats]}
            case "benchmark":
                if not model:
                    return {"error": "sebutkan model yang diuji"}
                return await modelinsight.run_bench(model, actor)
            case "set_model":
                if not (category and model):
                    return {"error": "sebutkan category dan model (cari idnya dulu dengan find_models)"}
                return await composition.set_model(category, model, actor, role=str(args.get("role") or "utama"),
                                                   confirmed=bool(args.get("confirmed")))
            case "set_budget":
                value = args.get("value")
                if category == "harian":
                    return {"anggaran_harian_usd": await composition.set_daily_budget(value, actor)}
                if category == "tugas":
                    return {"anggaran_per_tugas_usd": await composition.set_task_budget(value, actor)}
                if category and category != "total":
                    await composition.update({"categories": {category: {"budget_usd": value}}}, actor)
                    return {"category": category, "budget_usd": value}
                return {"anggaran_total_usd": await composition.set_total_budget(value, actor)}
            case "set_stt":
                await composition.update({"stt": str(args.get("value") or "")}, actor)
                return {"mesin_suara": args.get("value"), "catatan": "bisukan mic dulu agar berlaku"}
            case "set_strong_mode":
                await composition.update({"strong_mode": bool(args.get("value"))}, actor)
                return {"mode_kuat": bool(args.get("value"))}
            case "apply_preset":
                await composition.apply_preset(str(args.get("value") or ""), actor)
                return {"preset": args.get("value")}
            case "create_category":
                return await composition.create_category(category, str(args.get("title") or ""),
                                                         str(args.get("description") or ""), model, actor)
            case "delete_category":
                return {"dihapus": await composition.delete_category(category, actor)}
            case "list_settings":
                return {"pengaturan": [{"key": f["key"], "nama": f.get("label"), "nilai": f.get("value")} for f in await _fields()],
                        "catatan": "kunci rahasia hanya lewat Lainnya → Pengaturan server"}
            case "change_setting":
                key, value = str(args.get("key") or ""), str(args.get("value") if args.get("value") is not None else "")
                if key not in {f["key"] for f in await _fields()}:
                    return {"error": f"{key} tidak bisa diubah lewat obrolan (rahasia, otomatis, atau tidak dikenal)"}
                r = (await _admin("POST", "/internal/settings", json={key: value})).json()
                if r.get("errors"):
                    return {"error": r["errors"]}
                await audit.record(actor, "settings.chat_change", None, key=key)
                return {"disimpan": key, "catatan": "layanan terkait dimulai ulang otomatis beberapa detik"}
    except composition.CompositionError as e:
        return {"error": str(e)}
    except (httpx.HTTPError, ValueError) as e:
        return {"error": f"gagal menghubungi layanan ({type(e).__name__})"}
    return {"error": f"aksi tidak dikenal: {action}"}
