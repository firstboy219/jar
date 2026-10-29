"""JARVIS as a companion (ADR-084): a friend to talk with, think aloud with, that reads things out and keeps the thread of a long conversation.

- **Discussion turns** (an opinion, a "what if", weighing options, explaining, a worry, a long message) go to the category `diskusi` — a model
  that reasons well — with room to talk (`is_discussion`); quick commands and small talk stay on `ngobrol`. AI is for exactly this: context,
  thinking, weighing, creativity, initiative, discussion, checking and offering options; what is fixed and repeated is a skill / routine (ADR-083).
- **Reading aloud** ("bacakan …"): a web page, the news, a note, a document, the latest report, what is on the shared screen — or something to
  write first (a poem, a story). Read in pieces of about a minute; "lanjut" reads on.
- **The thread**: a long conversation is summarised (category `ringan`) beyond the last turns the model sees word for word; a new conversation
  starts knowing what the previous one was about.
"""

import logging
import re

from . import db, llm

log = logging.getLogger("jarvis-core.companion")
PIECE = 1100             # characters read in one go (≈ a minute of speech)
SUMMARY_EVERY = 12       # new messages beyond the summary before it is renewed
KEEP_VERBATIM = 16       # the last turns the model already sees
_reading: dict[str, str] = {}   # session → what is left to read

_DISCUSS = re.compile(
    r"\b(menurut ?mu|menurutmu|pendapat ?mu|pendapatmu|gimana kalau|bagaimana kalau|bagaimana jika|gimana jika|kenapa|mengapa|kok bisa|"
    r"diskusi|bertukar pikiran|tukar pikiran|brainstorm|ide|saran(mu)?|pro (dan )?kontra|lebih baik mana|mending mana|bandingkan|jelaskan|"
    r"ajari|ceritakan|curhat|aku (merasa|bingung|khawatir|takut|sedih|senang)|saya (merasa|bingung|khawatir|takut|sedih|senang)|"
    r"apa arti|filosofi|makna|setuju (gak|tidak|nggak)|bantu (aku|saya) (mikir|berpikir|memutuskan)|harus (pilih|bagaimana))\b", re.IGNORECASE)
_COMMAND = re.compile(r"^\s*(putar|stop|berhenti|buka|tutup|catat|ingatkan|jalankan|pesan|bacakan|bacain|tampilkan|cari(kan)?)\b", re.IGNORECASE)


def is_discussion(text: str) -> bool:
    """A turn that deserves thought rather than a quick line (pure; unit-tested)."""
    t = " ".join((text or "").split())
    if not t or _COMMAND.match(t):
        return False
    return bool(_DISCUSS.search(t)) or len(t.split()) >= 30


_READ = re.compile(r"^\s*(?:(?:jarvis|tolong|tlg|coba|bisa)[, ]+)*(?:bacakan|bacain|bacakanlah|baca(?:kan)?\s+(?:dong|ya|keras))\b[\s,:]*(?P<what>.*)$",
                   re.IGNORECASE | re.DOTALL)
_GO_ON = re.compile(r"^\s*(?:ya[, ]+)?(?:lanjut(?:kan)?|terus(?:kan)?|teruskan)(?:\s+(?:baca(?:nya)?|membaca|bacaannya|dong|ya))*\s*[.!]?\s*$", re.IGNORECASE)
_CREATE = re.compile(r"\b(puisi|cerita|dongeng|pantun|doa|sajak|cerpen|kisah|motivasi|renungan|lelucon|humor)\b", re.IGNORECASE)


def read_request(text: str, reading_left: bool = False) -> dict | None:
    """What to read (pure; unit-tested): {kind: url|news|note|doc|report|screen|create|continue, arg}; None when it is not a reading request."""
    t = (text or "").strip()
    if reading_left and _GO_ON.match(t):
        return {"kind": "continue", "arg": ""}
    m = _READ.match(t)
    if not m:
        return None
    what = m["what"].strip().rstrip(".!?")
    low = what.lower()
    if url := re.search(r"https?://\S+", what):
        return {"kind": "url", "arg": url.group(0).rstrip(").,")}
    if re.match(r"^(berita|kabar|headline)", low):
        topic = re.sub(r"^(berita|kabar|headline)\s*(terbaru|terkini|hari ini)?\s*(tentang|soal|mengenai)?\s*", "", low).strip()
        return {"kind": "news", "arg": "" if topic in ("", "hari ini", "terbaru", "terkini") else topic}
    if m2 := re.match(r"^(catatan|catatanku|catatan saya|note)\s*(?P<q>.*)$", low):
        return {"kind": "note", "arg": m2["q"].strip(" \"'")}
    if m2 := re.match(r"^(dokumen|file|berkas|laporan berkas)\s*(?P<q>.*)$", low):
        return {"kind": "doc", "arg": m2["q"].strip(" \"'")}
    if re.match(r"^(hasil|laporan)(nya)?(\s+(terakhir|tadi|tugas))?\s*$", low):
        return {"kind": "report", "arg": ""}
    if re.match(r"^(ini|yang (ada )?di layar|layar(nya)?|lampiran(nya)?|email ini|teks ini)\b", low):
        return {"kind": "screen", "arg": ""}
    if _CREATE.search(low) or not low:
        return {"kind": "create", "arg": what or "cerita pendek yang menenangkan"}
    return {"kind": "create", "arg": what}


def pieces(text: str, size: int = PIECE) -> tuple[str, str]:
    """(what to read now, what is left) — cut at the end of a sentence (pure; unit-tested)."""
    t = re.sub(r"\s+\n", "\n", (text or "").strip())
    if len(t) <= size:
        return t, ""
    cut = max((m.end() for m in re.finditer(r"[.!?…](?:\s|$)|\n", t[:size])), default=0)
    cut = cut if cut >= size // 3 else size
    return t[:cut].strip(), t[cut:].strip()


def speakable(text: str) -> str:
    """Text as it is read out: no markdown marks, links shortened (pure; unit-tested)."""
    t = re.sub(r"```.*?```", " ", text or "", flags=re.DOTALL)
    t = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", t)
    t = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", t)
    t = re.sub(r"https?://\S+", "(tautan)", t)
    t = re.sub(r"^[#>*\-\s]+", "", t, flags=re.MULTILINE)
    t = re.sub(r"[*_`|]", "", t)
    return re.sub(r"[ \t]+", " ", t).strip()


async def gather(req: dict, session_id: str, screen_text: str = "") -> tuple[str, str]:
    """(title, text) to read for a request; text '' when there is nothing."""
    kind, arg = req["kind"], req["arg"]
    if kind == "continue":
        return "lanjutan", _reading.pop(session_id, "")
    if kind == "url":
        from . import quick
        return "halaman itu", await quick.page_text(arg, 9000)
    if kind == "news":
        from . import quick
        items = await quick.news(arg)
        if not items:
            return "berita", ""
        return "berita", f"Berita terbaru{' tentang ' + arg if arg else ''}. " + " ".join(f"{i + 1}. {it['title']}, dari {it['source']}." for i, it in enumerate(items[:6]))
    if kind == "note":
        from . import notes
        hits = await notes.search(arg) if arg else []
        page = await notes.get(str(hits[0]["id"])) if hits else None
        if not page:
            return "catatan", ""
        lines = [b.get("text", "") for b in page.get("blocks") or [] if b.get("text")]
        return page.get("title") or "catatan", f"{page.get('title') or ''}. " + "\n".join(lines)
    if kind == "doc":
        from . import attachments, documents
        rows = [d for d in await documents.list_(80) if not arg or arg.lower() in d["title"].lower()]
        found = await documents.get(str(rows[0]["id"])) if rows else None
        if not found:
            return "dokumen", ""
        row, path = found
        try:
            _, text, _ = attachments.extract(path.name, documents.FORMATS[row["format"]], path.read_bytes())
        except Exception:
            text = ""
        return row["title"], text
    if kind == "report":
        r = await db.pool().fetchrow("SELECT text FROM reports ORDER BY id DESC LIMIT 1")
        return "laporan terakhir", (r["text"] if r else "")
    if kind == "screen":
        return "yang di layar", screen_text
    text = await llm.complete([
        {"role": "system", "content": "Kamu JARVIS, teman bicara pemilik. Tulis teks untuk DIBACAKAN dengan suara: bahasa Indonesia yang hangat dan enak "
                                      "didengar, tanpa markdown, tanpa daftar bernomor, paragraf pendek. Paling banyak 250 kata."},
        {"role": "user", "content": arg}], category="diskusi", max_tokens=700, caller="chat", temperature=0.8)
    return arg[:60], text


async def read_turn(req: dict, session_id: str, screen_text: str = "") -> str:
    """The text read this turn (the rest is kept for "lanjut")."""
    title, text = await gather(req, session_id, screen_text)
    text = speakable(text)
    if not text:
        return {"note": "Aku tidak menemukan catatan itu.", "doc": "Aku tidak menemukan dokumen itu.", "url": "Halaman itu tidak bisa kubaca.",
                "news": "Belum ada berita yang bisa kubacakan.", "report": "Belum ada laporan.", "continue": "Sudah habis — tidak ada lanjutan.",
                "screen": "Aku belum melihat teks apa pun — bagikan layarnya atau tempel teksnya dulu."}.get(req["kind"], "Tidak ada yang bisa kubacakan.")
    now, rest = pieces(text)
    if rest:
        _reading[session_id] = rest
        return now + " … Mau kulanjutkan?"
    _reading.pop(session_id, None)
    return now


def reading_left(session_id: str) -> bool:
    return bool(_reading.get(session_id))


# ---------- the thread of a long conversation ----------

async def summary(session_id: str) -> str:
    row = await db.pool().fetchrow("SELECT summary FROM session_summaries WHERE session_id = $1", session_id)
    return row["summary"] if row else ""


async def previous(session_id: str) -> str:
    """What the last OTHER conversation (within 3 days) was about — a new conversation starts knowing it."""
    row = await db.pool().fetchrow(
        """SELECT summary FROM session_summaries WHERE session_id <> $1 AND updated_at > now() - interval '3 days'
           ORDER BY updated_at DESC LIMIT 1""", session_id)
    return row["summary"] if row else ""


async def remember_thread(session_id: str) -> bool:
    """After a turn: when enough has been said beyond the last turns the model sees, (re)write the conversation's summary. Best effort."""
    try:
        have = await db.pool().fetchrow("SELECT summary, upto_id FROM session_summaries WHERE session_id = $1", session_id)
        rows = await db.pool().fetch(
            """SELECT id, role, left(content, 700) AS content FROM messages WHERE session_id = $1 AND route NOT IN ('blocked', 'silent', 'private')
               ORDER BY id DESC OFFSET $2 LIMIT 80""", session_id, KEEP_VERBATIM)
        older = [r for r in reversed(rows) if not have or r["id"] > have["upto_id"]]
        if len(older) < (SUMMARY_EVERY if have else 6):
            return False
        lines = "\n".join(f"{'Pemilik' if r['role'] == 'user' else 'JARVIS'}: {r['content']}" for r in older)
        text = await llm.complete([
            {"role": "system", "content": "Ringkas obrolan ini untuk ingatan JARVIS: topik yang dibahas, pendapat/perasaan pemilik, keputusan, janji yang "
                                          "belum ditepati, dan hal yang mungkin ia bahas lagi. Bahasa Indonesia, paling banyak 120 kata, tanpa daftar."},
            {"role": "user", "content": (f"RINGKASAN SEBELUMNYA: {have['summary']}\n\n" if have else "") + f"OBROLAN LANJUTANNYA:\n{lines[:12000]}"}],
            category="ringan", max_tokens=300, caller="chat", temperature=0.2)
        if not text.strip():
            return False
        await db.pool().execute(
            """INSERT INTO session_summaries (session_id, summary, upto_id) VALUES ($1, $2, $3)
               ON CONFLICT (session_id) DO UPDATE SET summary = $2, upto_id = $3, updated_at = now()""",
            session_id, text.strip()[:1500], older[-1]["id"])
        return True
    except Exception as e:
        log.warning("conversation summary for %s: %s", session_id, e)
        return False
