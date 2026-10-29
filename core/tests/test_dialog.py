"""ADR-086: short replies after what JARVIS just said (ya / tidak / ulangi / maksudnya), no repeated answers, no internal formats —
the problems the flow watcher found in a week of real conversations."""
import os

import pytest

from tests.test_integration import _no_memory, pool  # noqa: F401  (fixture)

needs_db = pytest.mark.skipif(not os.getenv("TEST_DATABASE_URL"), reason="needs TEST_DATABASE_URL")


def test_short_replies_are_recognised():
    from app import dialog
    for t in ("Setuju", "ya", "iya dong", "Langsung aja", "oke gas", "boleh", "lanjutkan", "jalankan sekarang"):
        assert dialog.kind(t) == "affirm", t
    for t in ("tidak", "nggak usah", "batal", "jangan dulu", "nanti aja"):
        assert dialog.kind(t) == "deny", t
    for t in ("Ulangi", "coba ulangi dong", "apa tadi?", "sekali lagi"):
        assert dialog.kind(t) == "repeat", t
    for t in ("maksudnya gimana?", "maksudnya?", "kurang jelas", "nggak ngerti"):
        assert dialog.kind(t) == "clarify", t
    for t in ("ya tolong pesankan goride ke kantor sekarang juga", "setuju dengan kenaikan harga BBM?", "", "jam berapa"):
        assert dialog.kind(t) is None, t


def test_the_model_is_told_what_a_short_reply_means():
    from app import dialog
    asked = "Pesanan GoRide ke Ancol Rp18.000. Mau kupesankan sekarang?"
    yes = dialog.note("affirm", asked)
    assert "menjawab YA" in yes and "Jangan bertanya" in yes and "Mau kupesankan" in yes
    assert "TIDAK" in dialog.note("deny", asked)
    assert "JANGAN menambah fakta" in dialog.note("clarify", "Demo di Bundaran HI bubar.")
    assert dialog.note("affirm", "Rupiah menguat hari ini.") == ""           # "ya" to a statement is just a "ya"
    assert dialog.note(None, asked) == "" and dialog.note("affirm", "") == ""


def test_replies_are_clean_and_repeats_are_noticed():
    from app import dialog
    assert dialog.clean_reply("Tugas: Cek harga GoRide\nKategori: web\nOke, kucek harganya dulu ya.") == "Oke, kucek harganya dulu ya."
    assert dialog.clean_reply("**Penting**: harga naik.\n## Ringkasan") == "Penting: harga naik.\nRingkasan"
    assert dialog.is_repeat_of("Oke, aku cek dulu ya, nanti kukabari.", "oke, aku cek dulu ya,  nanti kukabari.")
    assert not dialog.is_repeat_of("Oke.", "Oke.") and not dialog.is_repeat_of("Rupiah menguat.", "Rupiah melemah sedikit hari ini.")


@needs_db
async def test_the_main_agent_acts_on_ya_repeats_on_ulangi_and_does_not_say_the_same_twice(pool, monkeypatch):
    from app import assistant, llm, memory
    monkeypatch.setattr(memory, "search", _no_memory)
    sid = "s-dialog"
    await pool.execute("INSERT INTO messages (session_id, role, content, route) VALUES ($1, 'assistant', $2, 'assistant')",
                       sid, "Ada dua pilihan rute. Mau kupakai yang lewat tol?")
    seen = []

    async def stream(messages, tools=None, **kw):
        seen.append(messages[-1]["content"])
        yield {"type": "done", "completion": llm.Completion(text="Siap, lewat tol.")}
    monkeypatch.setattr(llm, "stream_chat", stream)
    a = await assistant.respond("Setuju", sid, "owner")
    assert "menjawab YA" in seen[-1] and "Mau kupakai yang lewat tol" in seen[-1]

    calls = []

    async def no_model(*a, **k):
        calls.append(1)
        yield {}
    monkeypatch.setattr(llm, "stream_chat", no_model)
    said = []

    async def emit(ev):
        if ev["type"] == "say":
            said.append(ev["text"])
    r = await assistant.respond("ulangi", sid, "owner", emit=emit, speak_live=True)
    assert r.text == "Ada dua pilihan rute. Mau kupakai yang lewat tol?" and not calls and said == ["Ada dua pilihan rute.", "Mau kupakai yang lewat tol?"]

    await pool.execute("INSERT INTO messages (session_id, role, content, route) VALUES ($1, 'assistant', $2, 'assistant')",
                       sid, "Oke, aku cek dulu ya soal itu, nanti kukabari.")

    async def same(messages, tools=None, **kw):
        assert "jangan diulang kata per kata" in messages[-1]["content"]
        yield {"type": "done", "completion": llm.Completion(text="Oke, aku cek dulu ya soal itu, nanti kukabari.")}

    async def better(messages, **k):
        assert "sama persis" in messages[-1]["content"]
        return "Respon pemerintah belum ada di obrolan kita — mau kucarikan?"
    monkeypatch.setattr(llm, "stream_chat", same)
    monkeypatch.setattr(llm, "complete", better)
    monkeypatch.setattr(assistant, "_promised_without_doing", lambda *a, **k: _false())
    r = await assistant.respond("Lalu apa respon pemerintah terkait hal itu?", sid, "owner")
    assert r.text == "Respon pemerintah belum ada di obrolan kita — mau kucarikan?"


async def _false():
    return False
