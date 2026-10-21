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
    (re.compile(r"^(daftar )?(tugas|task|tasks|worker)( (aktif|worker))?\??$"), "tasks"),
    (re.compile(r"^(di ?mana (saya|aku)( sekarang)?|lokasi (saya|aku)( sekarang)?|where am i)\??$"), "whereami"),
    (re.compile(r"^(jarvis,? )?(kamu |anda )?(sekarang |lagi )?(pakai|pake|memakai|menggunakan) (model|ai|otak) apa"
                r"( (untuk|buat) \w+)?( sekarang)?\??$"), "model"),
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


# Clear action requests the main agent executes directly (no model guessing whether to call a tool —
# the small local model often only SAID it would). Pure; executed by assistant.respond.
_POLITE = r"^(?:(?:jarvis|tolong|coba|dong|bisa|bisakah|boleh|kamu|ayo)[, ]+)*"
_ACTIONS: list[tuple[re.Pattern, str]] = [
    (re.compile(_POLITE + r"(?:putar(?:kan|in)?|puterin|mainkan|setel(?:kan)?|play)\s+(?:lagu(?:nya)?\s+|musik\s+)?"
                r"(?P<query>.{2,80}?)(?:\s+(?:dong|ya|ke hp|di hp))?[.!?]*$"), "play_music"),
    (re.compile(_POLITE + r"(?:tunjukkan |tampilkan |cari(?:kan)? |lihat )?(?:rute|jalan|arah|navigasi)\s+(?:ke|menuju)\s+"
                r"(?P<destination>.{2,80}?)[.!?]*$"), "show_route"),
    (re.compile(_POLITE + r"(?:cek |cari(?:kan)? |lihat |bacakan |apa |ada )?(?:berita|kabar terkini)"
                r"(?:\s+(?:tentang|soal|mengenai|terkait))?\s*(?P<topic>.{0,80}?)[.!?]*$"), "news"),
]
_NOT_A_SONG = {"lagi", "ulang", "terus", "balik", "kembali", "sebelumnya", "berikutnya", "selanjutnya"}
_NO_TOPIC = re.compile(r"^(hari ini|terkini|terbaru|sekarang|apa|apa saja|apa aja|hari ini apa|pagi ini|malam ini)?$")


def parse_action(text: str) -> Intent | None:
    lowered = " ".join(text.strip().lower().split())
    for rx, name in _ACTIONS:
        m = rx.match(lowered)
        if not m:
            continue
        args = {k: v.strip() for k, v in m.groupdict().items()}
        if name == "play_music" and (args["query"] in _NOT_A_SONG or args["query"].split()[0] in _NOT_A_SONG):
            return None
        if name == "news" and _NO_TOPIC.match(args["topic"]):
            args["topic"] = ""
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
• tugas — tugas worker yang sedang berjalan
• di mana saya — lokasi HP saat ini (jika berbagi lokasi aktif)
• pakai model apa — AI yang sedang dipakai
Awali pesan dengan /privat agar tidak dikirim ke model cloud.
Pesan lain dijawab JARVIS (agen utama), yang menugaskan worker bila perlu."""
