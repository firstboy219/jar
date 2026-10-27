"""What is written on a shared screen (ADR-066).

The phone reads its shared screen itself (ML Kit) and sends the text; a browser sends only pictures. For a draft — "buatkan balasan email
ini" while the owner shares an email — the writer needs the words, so the latest frame is read once by the vision model (category
'penglihatan'; never a free endpoint, and only the local model for a private turn) and the text is cached per frame.
"""

import hashlib
import json
import logging
import re

from . import gateway, llm

log = logging.getLogger("jarvis-core.screen")
_cache: dict[str, str] = {}
KEEP = 12
PROMPT = ("Salin SEMUA teks yang terlihat di tangkapan layar ini, persis apa adanya, urut dari atas ke bawah; pertahankan baris dan paragraf. "
          "Kalau ini email/chat, tulis dulu baris 'Dari:', 'Kepada:', 'Subjek:', 'Tanggal:' yang terlihat. Abaikan menu dan tombol aplikasi. "
          "Kalau teksnya jelas terpotong di tepi layar (kalimat/email berlanjut di luar gambar), akhiri dengan satu baris: [TERPOTONG]. "
          "Jangan menambah, meringkas, atau menerjemahkan.")
CLARIFY = ("Pemilik membagikan layar dan minta dibuatkan draf. Dari PERMINTAAN dan TEKS LAYAR, putuskan apakah ada SATU hal penting yang "
           "belum jelas sehingga drafnya bisa salah arah (mis. setuju atau menolak, angka/tanggal yang harus disebut, siapa penerimanya), atau "
           "apakah emailnya terpotong. Jawab HANYA JSON: {\"tanya\": \"<satu pertanyaan singkat dalam bahasa Indonesia>\"} atau {\"tanya\": \"\"} "
           "kalau sudah cukup jelas untuk langsung menulis. Jangan bertanya hal yang bisa diputuskan sendiri dengan wajar (nada sopan, salam).")


def truncated(text: str) -> bool:
    return "[TERPOTONG]" in (text or "")


async def read(image_b64: str | None, private: bool = False) -> str:
    """The text on one screen picture ('' when none can be read)."""
    if not image_b64:
        return ""
    key = hashlib.sha1(image_b64.encode()).hexdigest()
    if key in _cache:
        return _cache[key]
    try:
        route = (await gateway.plan("penglihatan", caller="core", private=private))[0]
        if not route.vision:
            return ""
        text = await llm.complete([
            {"role": "system", "content": "Kamu mata JARVIS: penyalin teks layar yang teliti."},
            {"role": "user", "content": [{"type": "text", "text": PROMPT},
                                         {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"}}]}],
            category="penglihatan", caller="core", max_tokens=2500, private=private, temperature=0)
    except Exception as e:   # no vision model reachable: the draft is written from the words and the chat instead
        log.warning("screen not read: %s", e)
        return ""
    text = (text or "").strip()[:12000]
    _cache[key] = text
    while len(_cache) > KEEP:
        _cache.pop(next(iter(_cache)))
    return text


def parse_question(raw: str) -> str:
    """The clarifying question from the model's JSON (pure; unit-tested). '' = write the draft now."""
    m = re.search(r"\{.*\}", raw or "", re.S)
    try:
        q = str((json.loads(m.group()) if m else {}).get("tanya") or "").strip()
    except ValueError:
        return ""
    return q[:300]


async def question(request: str, screen_text: str, private: bool = False) -> str:
    """One question worth asking before the draft (or '')."""
    if truncated(screen_text):
        return ("Emailnya terpotong di layar. Tempel teks lengkapnya di chat (salin dari emailnya), atau bilang 'lanjut' kalau cukup dari yang terlihat.")
    try:
        raw = await llm.complete([{"role": "system", "content": CLARIFY},
                                  {"role": "user", "content": f"PERMINTAAN: {request}\n\nTEKS LAYAR:\n{screen_text[:6000]}"}],
                                 category="cepat", caller="core", max_tokens=120, private=private, temperature=0)
    except Exception:
        return ""
    return parse_question(raw)
