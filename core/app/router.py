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
    (re.compile(r"^(jarvis,? )?(tolong |coba )?(netralkan|netralisir|reset|ringankan|kosongkan) (server|cpu|memori|ram|beban)"
                r"( (dan|&) (cpu|memori|ram|memory))?( (server|nya))?( dong| sekarang)?[.!]?$"), "relieve"),
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
_POLITE = r"^(?:(?:jarvis|tolong|tlg|coba|dong|bisa|bisakah|boleh|kamu|ayo)[, ]+)*"
_NEWS_WORD = r"(?:berita|brita|beritah|baritah?|berta|kabar terkini)"  # how STT often hears "berita"
_ACTIONS: list[tuple[re.Pattern, str]] = [
    (re.compile(_POLITE + r"(?:putar(?:kan|in)?|puterin|mainkan|tampilkan|tunjukkan|lihat|nonton|cari(?:kan)?)\s+"
                r"(?:video|film|youtube)\s+(?P<query>.{2,80}?)[.!?]*$"), "play_video"),
    (re.compile(_POLITE + r"(?:putar(?:kan|in)?|puterin|mainkan|setel(?:kan)?|play)\s+(?:lagu(?:nya)?\s+|musik\s+)?"
                r"(?P<query>.{2,80}?)(?:\s+(?:dong|ya|ke hp|di hp))?[.!?]*$"), "play_music"),
    (re.compile(_POLITE + r"(?:kita |saya |aku )?(?:mulai(?:kan)?|buka|rekam)\s+(?:rekam(?:an)?\s+)?(?:rapat|meeting)(?:\s+(?:ini|sekarang|dong|ya))*"
                r"(?:\s+(?:tentang|soal|mengenai|membahas)\s+(?P<title>.{2,100}?))?(?:\s+(?:dong|ya|sekarang))*[.!?]*$"), "meeting_start"),
    (re.compile(_POLITE + r"(?:kita |saya |aku )?(?:(?:selesai(?:kan)?|stop|akhiri|hentikan|sudah|tutup)\s+(?:rekam(?:an)?\s+)?(?:rapat|meeting|rekaman)|"
                r"(?:rapat|meetingnya?|rapatnya)\s+(?:sudah\s+)?(?:selesai|usai))(?:\s+(?:ini|nya|sekarang|dong|ya))*[.!?]*$"), "meeting_stop"),
    (re.compile(_POLITE + r"(?:tunjukkan |tampilkan |cari(?:kan)? |lihat )?(?:rute|jalan|arah|navigasi)\s+(?:ke|menuju)\s+"
                r"(?P<destination>.{2,80}?)[.!?]*$"), "show_route"),
    (re.compile(_POLITE + r"(?:cek |cari(?:kan)? |lihat |bacakan |apa |ada )?" + _NEWS_WORD +
                r"(?:\s+(?:tentang|soal|mengenai|terkait))?\s*(?P<topic>.{0,80}?)[.!?]*$"), "news"),
]
_CHART = re.compile(r"\b(top ?\d*|terpopuler|paling populer|populer|hits|tangga lagu|chart|teratas|terlaris)\b")
_PLAY_PLAYLIST = re.compile(_POLITE + r"(?:putar(?:kan|in)?|mainkan|setel(?:kan)?|play)\s+playlist(?:\s+(?P<name>.{1,60}?))?[.!?]*$")
_DRAFT = re.compile(r"\b(buat|bikin|buatkan|bikinin|draftkan|draftin|tuliskan|tulis|susun|susunkan|siapkan)\b.{0,40}"
                    r"\b(draft?|draf|konsep|balasan|reply)\b.{0,30}\b(email|e-mail|surel|surat|pesan|wa|whatsapp|chat|ini)\b"
                    r"|\b(draftkan|draftin)\b|\breply draft\b|\b(balas|bales)(kan)? email\b"
                    # "tolong bantu saya menjawab email ini", "balasin chat ini" (ADR-069) — not a question like "sudah kubalas emailnya?"
                    r"|^(?!\s*(sudah|udah|apakah|apa|kapan|siapa|kenapa)\b).{0,40}\b(jawab|jawabin|jawabkan|menjawab|balas|balasin|balaskan|membalas|"
                    r"bales|balesin)\b.{0,25}\b(email|e-mail|surel|surat|pesan|chat|wa|whatsapp)\b")
_NOT_A_SONG = {"lagi", "ulang", "terus", "balik", "kembali", "sebelumnya", "berikutnya", "selanjutnya", "video", "film"}
_SHORT_NEWS = re.compile(r"^(?:\w+\s+)?" + _NEWS_WORD + r"\s*(?P<topic>(?:\w+\s*){0,4}?)[.!?]*$")
_NO_TOPIC = re.compile(r"^(hari ini|terkini|terbaru|sekarang|apa|apa saja|apa aja|hari ini apa|pagi ini|malam ini)?$")


_OR_CHECK = re.compile(r"\b(cek|periksa|tes|test|coba)\b.*\b(saldo|koneksi|kredit|openrouter)\b|\b(saldo|kredit) openrouter\b")
_MODEL_STATS = re.compile(r"\bstatistik model\b|\b(model|ai)\b.*\b(sering error|paling error|error|gagal|bermasalah|tercepat|paling cepat|termurah|paling murah)\b")
_MODEL_COMPARE = re.compile(r"\b(kelebihan|kekurangan|bandingkan|banding|dibanding|lebih (?:bagus|baik)|beda|perbedaan|vs|versus)\b")
_MODEL_NAMES = re.compile(r"\b(model|deepseek|qwen\S*|claude|gpt\S*|gemini|gemma|llama|mistral|nemotron|grok|kimi|glm|haiku|sonnet|opus|minimax|cohere|inkling)\b")


# "sudah jadi draftnya?", "mana drafnya", "draft balasannya belum?" — about a draft already asked for (ADR-070)
_DRAFT_STATUS = re.compile(r"\b(draf|draft|drafnya|draftnya|balasannya)\b.{0,30}(\?|\b(sudah|udah|belum|jadi|mana|selesai|progress|gimana|bagaimana)\b)"
                           r"|\b(sudah|udah|belum|mana|apakah)\b.{0,30}\b(draf|draft|drafnya|draftnya|balasannya)\b", re.IGNORECASE)
_DEV_TEAM = re.compile(r"^(?:(?:jarvis|tolong|hai|halo)[, ]+)*(?:tim|team)\s?dev(?:elop(?:er|ment)?)?\b[\s,:.!-]*(?P<rest>.*)$", re.IGNORECASE | re.DOTALL)


_NOTE = re.compile(r"^(?:(?:jarvis|tolong|tlg|coba)[, ]+)*catat(?:kan|in)?(?:\s+(?:ini|ya|dong|bahwa))?\s*[:,-]?\s*(?P<text>.{3,})$",
                   re.IGNORECASE | re.DOTALL)
_TODO = re.compile(r"^(?:(?:jarvis|tolong|tlg|coba)[, ]+)*(?:tambah(?:kan|in)?|masuk(?:kan|in))\s+(?:ke\s+)?(?:tugas|task|to-?do|daftar tugas)"
                   r"(?:\s+(?:saya|ku|aku|baru))?\s*[:,-]?\s*(?P<text>.{3,})$", re.IGNORECASE | re.DOTALL)


def parse_action(text: str) -> Intent | None:
    lowered = " ".join(text.strip().lower().split())
    if m := _TODO.match(text.strip()):   # "tambah tugas telepon pak budi besok" → Catatan's task list (ADR-060)
        return Intent("todo_add", {"text": m["text"].strip()})
    if m := _NOTE.match(text.strip()):   # "catat: …" → the Inbox page
        return Intent("note_add", {"text": m["text"].strip()})
    if _DRAFT_STATUS.search(lowered) and not _DRAFT.search(lowered):
        return Intent("draft_status", {})
    if (m := _DEV_TEAM.match(text.strip())) and len(m["rest"].strip()) >= 8:   # "tim dev, …" goes to the dev team as said (ADR-059)
        return Intent("dev_team", {"text": text.strip()})
    if _OR_CHECK.search(lowered):
        return Intent("openrouter_check", {})
    if _MODEL_STATS.search(lowered):
        return Intent("model_stats", {"text": lowered})
    if _MODEL_COMPARE.search(lowered) and _MODEL_NAMES.search(lowered):
        return Intent("model_compare", {"text": lowered})
    # charts and playlists first: "carikan lagu RnB top 10 dan masukkan ke playlist saya", "putar playlist saya"
    if m := _PLAY_PLAYLIST.match(lowered):
        name = (m["name"] or "").strip()
        return Intent("play_playlist", {"name": "" if name in ("", "saya", "ku", "aku", "kamu") else name})
    if _DRAFT.search(lowered):
        return Intent("write_draft", {"text": text.strip()})
    if "lagu" in lowered and _CHART.search(lowered):
        n = re.search(r"\btop ?(\d{1,2})\b", lowered)
        return Intent("chart", {"text": lowered, "limit": int(n.group(1)) if n else 10,
                                "to_playlist": "playlist" in lowered})
    for rx, name in _ACTIONS:
        m = rx.match(lowered)
        if not m:
            continue
        args = {k: (v or "").strip() for k, v in m.groupdict().items()}
        if name == "play_music" and (args["query"] in _NOT_A_SONG or args["query"].split()[0] in _NOT_A_SONG):
            return None
        if name == "news" and _NO_TOPIC.match(args["topic"]):
            args["topic"] = ""
        return Intent(name, args)
    # "Terupdate brita hari ini" (a mis-heard first word): a short utterance about the news is still news
    if (m := _SHORT_NEWS.match(lowered)) and len(lowered.split()) <= 6:
        topic = m["topic"].strip()
        return Intent("news", {"topic": "" if _NO_TOPIC.match(topic) else topic})
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
• netralkan server — hentikan (dan simpan) semua tugas untuk meringankan CPU & memori
Awali pesan dengan /privat agar tidak dikirim ke model cloud.
Pesan lain dijawab JARVIS (agen utama), yang menugaskan worker bila perlu."""
