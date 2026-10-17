"""Tier 1 of the tiered routing: deterministic commands answered by jarvis-core without any LLM.

parse() is pure (unit-tested); anything it does not recognise goes to Hermes (tier 2), which decides
on its own whether to delegate to a stronger cloud model (tier 3).
"""

import re
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Intent:
    name: str
    args: dict = field(default_factory=dict)


_RULES: list[tuple[re.Pattern, str]] = [
    (re.compile(r"^(bantuan|help|perintah|menu)\??$"), "help"),
    (re.compile(r"^(status|cek status|status server|status sistem|health)\??$"), "status"),
    (re.compile(r"^(daftar )?(persetujuan|approval|approvals|antrean persetujuan)\??$"), "approvals"),
    (re.compile(r"^(setujui|approve|acc)\s+#?(?P<id>\d+)$"), "approve"),
    (re.compile(r"^(tolak|reject)\s+#?(?P<id>\d+)$"), "reject"),
    (re.compile(r"^(ingat|catat|remember)\s*:\s*(?P<text>.+)$", re.DOTALL), "remember"),
    (re.compile(r"^(lupakan|hapus memori|forget)\s+(?P<id>[0-9a-f-]{36})$"), "forget"),
    (re.compile(r"^(cari memori|memori|apa yang kamu ingat tentang)\s+(?P<query>.+?)\??$"), "recall"),
    (re.compile(r"^(daftar )?(workflow|workflows|alur kerja)( n8n)?\??$"), "workflows"),
    (re.compile(r"^(di ?mana (saya|aku)( sekarang)?|lokasi (saya|aku)( sekarang)?|where am i)\??$"), "whereami"),
]


def parse(text: str) -> Intent | None:
    normalized = " ".join(text.strip().split())
    lowered = normalized.lower()
    for rx, name in _RULES:
        m = rx.match(lowered)
        if not m:
            continue
        args = m.groupdict()
        if name == "remember":  # keep the user's original casing for stored text
            args["text"] = normalized.split(":", 1)[1].strip()
        if "id" in args and name in ("approve", "reject"):
            args["id"] = int(args["id"])
        return Intent(name, args)
    return None


HELP = """Perintah cepat (dijawab langsung tanpa model AI):
• status — kesehatan layanan
• persetujuan — daftar tindakan yang menunggu persetujuan
• setujui <id> / tolak <id>
• ingat: <teks> — simpan ke memori
• memori <kata kunci> — cari di memori
• lupakan <id memori>
• workflow — daftar workflow n8n
• di mana saya — lokasi HP saat ini (jika berbagi lokasi aktif)
Awali pesan dengan /privat agar tidak dikirim ke model cloud.
Pesan lain dijawab oleh JARVIS (Hermes)."""
