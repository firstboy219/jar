"""Routing for company work (Blueprint v4 §7.1, the 2×3 matrix's Company row).

  fast   "KPI Renature?", "status arahan Jack Healer" → answered from the Company Vault and the directive list, no model
  heavy  "Renature: susun kampanye Ramadan…" → the main agent sends a directive through Jarvis-GM (company_directive)
The owner's explicit prefix wins ("riset:" / "cepat:"). A turn naming two companies gets no company context at all:
work is always for ONE company, so nothing of one company can end up in a directive for the other.
"""

import re

from . import companies, gm

FAST = re.compile(r"\b(kpi|status|omzet|omset|penjualan|revenue|arus kas|cash ?flow|kas|batasan|target|"
                  r"temuan|pivot|arahan|direktif|laporan terakhir|progres|progress)\b", re.I)
HEAVY = re.compile(r"\b(buat(kan)?|susun(kan)?|kerjakan|minta|suruh|arahkan|tugaskan|jalankan|siapkan|rencanakan|"
                   r"luncurkan|kirim(kan)?|bayar|publikasi(kan)?|rekrut|analisis|analisa|riset|teliti)\b", re.I)


def lane(text: str) -> str:
    """'fast' | 'heavy' for a turn about ONE company. Explicit prefix wins. Pure; unit-tested."""
    low = text.strip().lower()
    if low.startswith(("riset:", "berat:", "kerjakan:")):
        return "heavy"
    if low.startswith(("cepat:", "status:")):
        return "fast"
    if HEAVY.search(low):
        return "heavy"
    return "fast" if FAST.search(low) else "heavy"


def directive_line(d: dict) -> str:
    state = {"awaiting_owner": "menunggu persetujuanmu", "queued": "antre", "sent": "terkirim, menunggu balasan",
             "acknowledged": "sedang dikerjakan", "awaiting_owner_result": "minta persetujuanmu", "completed": "selesai",
             "failed": "gagal", "timed_out": "tidak dibalas", "cancelled": "dibatalkan", "rejected": "ditolak"}.get(d["status"], d["status"])
    result = (d.get("callback") or {}).get("result") if isinstance(d.get("callback"), dict) else None
    return f"#{d['id']} {d['action'].replace('_', ' ')} — {state}" + (f": {str(result)[:140]}" if result and d["status"] == "completed" else "")


async def fast_answer(company_id: str) -> str:
    """KPIs, cash flow, constraints and the latest directives of ONE company, from stored data only."""
    c = await companies.get(company_id)
    entries = await companies.vault_list(company_id)
    kpis = [companies.kpi_line(e) for e in entries if e["kind"] in ("kpi", "cashflow")][:8]
    limits = [e["title"] for e in entries if e["kind"] == "core_constraint"][:4]
    directives = (await gm.list_(company_id, limit=5))
    parts = [f"{c['name']}:"]
    parts.append("KPI & kas: " + "; ".join(kpis) if kpis else "Belum ada KPI atau arus kas yang tercatat di Company Vault.")
    if limits:
        parts.append("Batasan inti: " + "; ".join(limits))
    parts.append("Arahan terakhir: " + " | ".join(directive_line(d) for d in directives) if directives else "Belum ada arahan ke Hermes-DGM.")
    if c["adapter"] == "mock":
        parts.append("(Hermes-DGM masih tiruan — kontrak API-nya belum diverifikasi.)")
    return "\n".join(parts)


async def situation(text: str) -> tuple[str | None, str]:
    """(company_id or None, the block for the main agent's situation)."""
    found = await companies.mentioned(text)
    if len(found) == 1:
        return found[0], await companies.context_block(found[0]) + \
            "\n(Untuk mengarahkan tim perusahaan ini pakai company_directive; catat keputusan dengan decision_record.)"
    if len(found) > 1:
        names = ", ".join(c["name"] for c in await companies.all_() if c["id"] in found)
        return None, (f"PERUSAHAAN DISEBUT: {names}. Kerjakan untuk SATU perusahaan per perintah — tanyakan pemilik "
                      "perusahaan mana dulu; jangan mencampur data mereka.")
    return None, ""
