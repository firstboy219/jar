"""The state of a conversation between two turns (ADR-086): what a short reply means after what JARVIS just said.

Real conversations (the flow watcher, a week of them) showed the main agent failing on the shortest replies: "Setuju" after it asked for a
yes → it asked again, five times; "maksudnya?" → it invented new facts; "ulangi" → it ignored it; and the same answer twice for different
questions. These are recognised here, without a model, and either answered directly (ulangi) or turned into a clear note in front of the model.
"""

import re

_AFFIRM = re.compile(r"^(?:ya+|iya+|yes|yup|setuju|oke+|ok|okay|boleh|lanjut(?:kan)?|gas(?:kan)?|langsung(?:\s+(?:aja|saja))?|silakan|sip|betul|"
                     r"benar|bener|mau|tentu|jadi|deal|lakukan|kerjakan|eksekusi|jalan(?:kan)?)(?:[\s,]+(?:aja|saja|dong|ya|deh|banget|sekarang|jarvis|gas|lanjut))*[.!]*$",
                     re.IGNORECASE)
_DENY = re.compile(r"^(?:tidak|nggak|ngga|gak|enggak|ga|jangan|batal(?:kan)?|tidak usah|gak usah|nggak usah|ga usah|nanti (?:aja|saja)|skip|cancel|stop)"
                   r"(?:[\s,]+(?:aja|saja|dulu|dong|ya|deh|jarvis))*[.!]*$", re.IGNORECASE)
_REPEAT = re.compile(r"^(?:coba\s+)?(?:ulangi|ulang(?:in)?|sekali lagi|apa tadi|tadi apa|bilang apa tadi|tolong ulangi|bisa diulang)(?:[\s,]+(?:dong|ya|lagi|jarvis|tadi))*[?.!]*$",
                     re.IGNORECASE)
_CLARIFY = re.compile(r"^(?:maksud(?:nya|mu)?(?:\s+(?:gimana|bagaimana|apa))?|gimana maksudnya|apa maksudnya|kurang jelas|nggak ngerti|gak ngerti|"
                      r"tidak mengerti|belum paham|jelasin lagi|jelaskan lagi)[?.!]*$", re.IGNORECASE)
_ASKED = re.compile(r"\?\s*$|\b(mau|apakah|boleh|perlu|lanjut|setuju|oke)\b[^.!]*\?|\bkonfirmasi\b", re.IGNORECASE)
_INTERNAL = re.compile(r"^\s*(?:tugas|instruksi|task|judul|kategori|category|instruction|title)\s*[:：]", re.IGNORECASE)


def kind(text: str) -> str | None:
    """affirm / deny / repeat / clarify, or None (pure; unit-tested). Only short replies — a sentence with content is not a 'ya'."""
    t = " ".join((text or "").strip().split())
    if not t or len(t.split()) > 5:
        return None
    for name, rx in (("repeat", _REPEAT), ("clarify", _CLARIFY), ("deny", _DENY), ("affirm", _AFFIRM)):
        if rx.match(t):
            return name
    return None


def asked_something(reply: str) -> bool:
    """Did JARVIS end its turn with a question / an offer? (pure)"""
    return bool(_ASKED.search((reply or "").strip()[-300:]))


def note(k: str | None, last_reply: str) -> str:
    """What the model is told about a short reply (pure; unit-tested). '' when nothing needs saying."""
    last = " ".join((last_reply or "").split())[:400]
    if not k or not last:
        return ""
    if k == "affirm" and asked_something(last):
        return (f"KONTEKS GILIRAN INI: pemilik menjawab YA atas pertanyaan/tawaranmu barusan («{last}»). LAKSANAKAN sekarang dengan alat yang tepat. "
                "Jangan bertanya atau meminta konfirmasi lagi, jangan mengulang penjelasan.")
    if k == "deny" and asked_something(last):
        return f"KONTEKS GILIRAN INI: pemilik menjawab TIDAK atas tawaranmu barusan («{last}»). Jangan lakukan; akui singkat (satu kalimat)."
    if k == "clarify":
        return (f"KONTEKS GILIRAN INI: pemilik belum paham jawabanmu barusan («{last}»). Jelaskan ULANG dengan kata yang lebih sederhana. "
                "JANGAN menambah fakta, nama, atau angka yang tidak ada di jawaban itu; kalau memang tidak tahu, katakan.")
    return ""


def is_repeat_of(new: str, old: str) -> bool:
    """The same answer again (pure): what the flow watcher kept finding."""
    a, b = " ".join((new or "").lower().split()), " ".join((old or "").lower().split())
    return len(a) >= 20 and a == b


def clean_reply(text: str) -> str:
    """A spoken reply without internal formats that leaked ("Tugas: …", "Kategori: web") or markdown marks (pure; unit-tested)."""
    lines = [l for l in (text or "").splitlines() if not _INTERNAL.match(l)]
    out = "\n".join(lines).strip()
    out = re.sub(r"\*\*(.+?)\*\*", r"\1", out)
    out = re.sub(r"^#+\s*", "", out, flags=re.MULTILINE)
    return out or (text or "").strip()
