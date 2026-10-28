"""Reply drafts for WhatsApp / email the owner is showing on screen ("bantu balas ini").

The phone reads the chat itself (ML Kit OCR on the shared screen, plus the WhatsApp notification thread)
and sends TEXT, not a picture. The 'balas-pesan' category writes three variants in the owner's own style
(from memory). Other people's messages are private by nature: if that category's model is a cloud
model, the owner confirms first. JARVIS never sends anything — the owner copies, opens the app, or taps
"Kirim lewat Balas notifikasi" on the phone.
"""

import json
import re

from . import gateway, llm, memory, stage

PROMPT = """Kamu menyusun draf balasan pesan untuk pemilik (JARVIS tidak pernah mengirim; pemilik yang memilih \
dan mengirim). Baca percakapan yang ditampilkan di layar HP pemilik (teks hasil baca layar, bisa ada salah \
baca), pahami pesan terakhir yang perlu dibalas, lalu tulis TIGA varian balasan dalam bahasa yang sama \
dengan percakapannya: Singkat, Santai, Formal. Ikuti gaya bahasa pemilik bila diketahui. Jangan mengarang \
janji, angka, atau jadwal yang tidak diminta pemilik.

Gaya bahasa pemilik (dari ingatan, bisa kosong): {style}
Permintaan pemilik: {instruction}

Jawab HANYA dengan JSON:
{{"to": "nama lawan bicara bila terbaca", "channel": "whatsapp|email|lainnya",
  "wa_phone": "nomor bila terlihat atau kosong", "email": "alamat bila terlihat atau kosong",
  "subject": "untuk email: 'Re: ...' atau kosong", "summary": "inti pesan yang dibalas, 1 kalimat",
  "variants": [{{"label": "Singkat", "text": "..."}}, {{"label": "Santai", "text": "..."}}, {{"label": "Formal", "text": "..."}}]}}"""


async def needs_confirmation() -> bool:
    """True when drafts would be written by a cloud model and the owner must agree first."""
    cats = await gateway.categories()
    cat = cats.get("balas-pesan") or {}
    if not cat.get("confirm_cloud"):
        return False
    return True   # every model is a cloud model (ADR-080)


def _json(text: str) -> dict:
    m = re.search(r"\{.*\}", text or "", re.DOTALL)
    try:
        return json.loads(m.group(0)) if m else {}
    except ValueError:
        return {}


async def make(screen_text: str, instruction: str, *, private: bool = False) -> dict:
    if not screen_text.strip():
        return {"error": "tidak ada teks percakapan — bagikan layar WhatsApp/email dulu"}
    try:
        style = "; ".join(m["text"] for m in await memory.search("gaya bahasa pemilik saat membalas pesan", limit=3)
                          if m["score"] >= 0.3) or "-"
    except Exception:
        style = "-"
    raw = await llm.complete([{"role": "system", "content": PROMPT.format(style=style, instruction=instruction or "balas dengan wajar")},
                              {"role": "user", "content": f"PERCAKAPAN DI LAYAR:\n{screen_text[:12000]}"}],
                             category="balas-pesan", caller="chat", private=private, max_tokens=900, temperature=0.5)
    d = _json(raw)
    variants = [v for v in d.get("variants") or [] if isinstance(v, dict) and str(v.get("text", "")).strip()][:4]
    if not variants:
        return {"error": "draf tidak berhasil disusun"}
    payload = {"to": str(d.get("to") or "")[:80], "channel": d.get("channel") if d.get("channel") in ("whatsapp", "email") else "lainnya",
               "wa_phone": re.sub(r"[^0-9+]", "", str(d.get("wa_phone") or ""))[:20],
               "email": str(d.get("email") or "")[:120] if "@" in str(d.get("email") or "") else "",
               "subject": str(d.get("subject") or "")[:150], "summary": str(d.get("summary") or "")[:300],
               "variants": [{"label": str(v.get("label") or f"Varian {i + 1}")[:20], "text": str(v["text"])[:3000]}
                            for i, v in enumerate(variants)]}
    shown = await stage.show("draft", payload, f"Draf balasan untuk {payload['to'] or 'pesan ini'}", "jarvis")
    return {"shown": True, "stage_id": shown["id"], "summary": payload["summary"],
            "variants": [v["label"] for v in payload["variants"]]}
