"""ADR-084: JARVIS as a companion — discussion on a thinking model, reading aloud in pieces, and the thread of a long conversation."""
import os

import pytest

from tests.test_integration import _no_memory, pool  # noqa: F401  (fixture)

needs_db = pytest.mark.skipif(not os.getenv("TEST_DATABASE_URL"), reason="needs TEST_DATABASE_URL")


def test_a_turn_that_needs_thought_is_told_from_a_command():
    from app import companion
    for t in ("menurutmu lebih baik beli rumah atau sewa?", "Aku bingung harus pilih kerjaan yang mana", "jelaskan kenapa langit biru",
              "gimana kalau aku resign bulan depan", " ".join(["kata"] * 31)):
        assert companion.is_discussion(t), t
    for t in ("putar lagu coldplay", "bacakan berita", "jam berapa sekarang", "oke makasih", "catat beli susu", ""):
        assert not companion.is_discussion(t), t


def test_what_to_read_is_understood():
    from app import companion
    r = companion.read_request
    assert r("bacakan https://kompas.com/a/b.") == {"kind": "url", "arg": "https://kompas.com/a/b"}
    assert r("tolong bacakan berita hari ini") == {"kind": "news", "arg": ""}
    assert r("bacakan berita tentang ekonomi") == {"kind": "news", "arg": "ekonomi"}
    assert r("bacain catatan rapat anggaran") == {"kind": "note", "arg": "rapat anggaran"}
    assert r("bacakan dokumen laporan Q4") == {"kind": "doc", "arg": "laporan q4"}
    assert r("bacakan hasilnya") == {"kind": "report", "arg": ""}
    assert r("bacakan yang di layar") == {"kind": "screen", "arg": ""}
    assert r("bacakan puisi tentang hujan") == {"kind": "create", "arg": "puisi tentang hujan"}
    assert r("lanjutkan bacanya", reading_left=True) == {"kind": "continue", "arg": ""}
    assert r("lanjut", reading_left=False) is None and r("berita hari ini apa") is None


def test_long_text_is_read_in_pieces_at_the_end_of_a_sentence():
    from app import companion
    text = ("Kalimat satu cukup panjang untuk diuji. " * 60).strip()
    now, rest = companion.pieces(text, 300)
    assert now.endswith(".") and len(now) <= 300 and rest and (now + " " + rest).split() == text.split()
    assert companion.pieces("pendek.", 300) == ("pendek.", "")
    said = companion.speakable("# Judul\n**Tebal** dan [tautan](https://x.y) lihat https://a.b/c\n- poin")
    assert said == "Judul\nTebal dan tautan lihat (tautan)\npoin"


@needs_db
async def test_reading_starts_with_a_summary_and_asks_before_the_details(pool, monkeypatch):
    from app import companion, llm, quick

    async def page(url, chars=2500):
        return "Paragraf panjang tentang ekonomi. " * 120

    async def summary(messages, **k):
        assert k["category"] == "ringan"
        return "Artikel ini membahas ekonomi: inflasi turun dan rupiah menguat."
    monkeypatch.setattr(quick, "page_text", page)
    monkeypatch.setattr(llm, "complete", summary)
    first = await companion.read_turn({"kind": "url", "arg": "https://a.b/c"}, "s-baca")
    assert first == "Artikel ini membahas ekonomi: inflasi turun dan rupiah menguat. Mau kubacakan detailnya?"
    assert companion.detail_offered("s-baca") and not companion.reading_left("s-baca")
    assert companion.read_request("ya, bacakan detailnya", False, True) == {"kind": "detail", "arg": ""}
    detail = await companion.read_turn(companion.read_request("ya", False, True), "s-baca")
    assert detail.startswith("Paragraf panjang") and detail.endswith("Mau kulanjutkan?") and companion.reading_left("s-baca")
    nxt = await companion.read_turn(companion.read_request("lanjutkan", True), "s-baca")
    assert nxt.startswith("Paragraf panjang")
    await companion.read_turn({"kind": "url", "arg": "https://a.b/c"}, "s-baca")
    assert companion.read_request("nggak usah", False, True) == {"kind": "decline", "arg": ""}
    assert await companion.read_turn({"kind": "decline", "arg": ""}, "s-baca") == "Oke, cukup ringkasannya saja."
    assert not companion.detail_offered("s-baca")
    nothing = await companion.read_turn({"kind": "note", "arg": "tidak ada sama sekali"}, "s-baca")
    assert "tidak menemukan" in nothing


def test_yes_and_no_after_a_summary():
    from app import companion
    r = companion.read_request
    for yes in ("ya", "iya", "boleh", "oke", "lanjut", "bacakan detailnya", "ya bacakan semuanya", "baca lengkapnya dong", "mau"):
        assert r(yes, False, True) == {"kind": "detail", "arg": ""}, yes
    for no in ("tidak", "nggak usah", "cukup", "nanti saja"):
        assert r(no, False, True) == {"kind": "decline", "arg": ""}, no
    assert r("ya", False, False) is None                                    # nothing was offered: just a "ya"
    assert r("menurutmu inflasinya bagaimana?", False, True) is None        # a question about it goes to the conversation


@needs_db
async def test_the_main_agent_reads_and_discusses_on_the_right_model(pool, monkeypatch):
    from app import assistant, companion, llm, memory, quick
    monkeypatch.setattr(memory, "search", _no_memory)
    seen = []

    async def stream(messages, tools=None, **kw):
        seen.append((kw.get("category"), kw.get("max_tokens"), messages[-1]["content"] if isinstance(messages[-1]["content"], str) else ""))
        yield {"type": "done", "completion": llm.Completion(text="Menurutku sewa dulu lebih aman, karena…")}
    monkeypatch.setattr(llm, "stream_chat", stream)

    async def news(topic="", limit=6):
        return [{"title": "Rupiah menguat", "source": "Kompas"}, {"title": "Hujan di Jakarta", "source": "Detik"}]
    monkeypatch.setattr(quick, "news", news)
    said = []

    async def emit(ev):
        if ev["type"] == "say":
            said.append(ev["text"])
    a = await assistant.respond("bacakan berita hari ini", "s-teman", "owner", emit=emit, speak_live=True)
    assert "Rupiah menguat" in a.text and a.route["model"] == "bacakan" and not seen and said     # read, no model
    a = await assistant.respond("menurutmu lebih baik beli rumah atau sewa dulu?", "s-teman", "owner", emit=emit)
    assert seen[-1][:2] == ("diskusi", 1000)
    await assistant.respond("jam berapa sekarang", "s-teman", "owner", emit=emit)
    assert seen[-1][:2] == ("ngobrol", 400)
    await pool.execute("INSERT INTO session_summaries (session_id, summary, upto_id) VALUES ('s-teman', 'Kami membahas rencana pindah rumah.', 1)")
    await assistant.respond("lanjut soal yang tadi", "s-teman", "owner", emit=emit)
    assert "RINGKASAN OBROLAN SEBELUMNYA" in seen[-1][2] and "rencana pindah rumah" in seen[-1][2]
    await assistant.respond("halo", "s-baru", "owner", emit=emit)
    assert "OBROLAN TERAKHIR KITA" in seen[-1][2]                                                       # a new conversation remembers the last


@needs_db
async def test_a_long_conversation_keeps_its_thread(pool, monkeypatch):
    from app import companion, llm
    await pool.execute("DELETE FROM session_summaries")
    for i in range(30):
        await pool.execute("INSERT INTO messages (session_id, role, content, route) VALUES ('s-panjang', $1, $2, 'assistant')",
                           "user" if i % 2 == 0 else "assistant", f"pesan {i} tentang liburan ke Bali")
    asked = []

    async def summarise(messages, **k):
        asked.append(k["category"])
        return "Pemilik merencanakan liburan ke Bali."
    monkeypatch.setattr(llm, "complete", summarise)
    assert await companion.remember_thread("s-panjang") and asked == ["ringan"]
    assert await companion.summary("s-panjang") == "Pemilik merencanakan liburan ke Bali."
    assert not await companion.remember_thread("s-panjang")                                              # nothing new beyond it yet
