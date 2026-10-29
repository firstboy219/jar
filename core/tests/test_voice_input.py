"""ADR-085: 🔤 the transcript only / 🎧 the AI also hears the owner's recording — a switch on the desk."""
import os

import pytest

from tests.test_integration import _no_memory, pool  # noqa: F401  (fixture)

needs_db = pytest.mark.skipif(not os.getenv("TEST_DATABASE_URL"), reason="needs TEST_DATABASE_URL")


def test_the_recording_goes_next_to_the_words_and_can_be_taken_out():
    from app import assistant
    parts = assistant.with_audio("UCAPAN PEMILIK: halo", "QUJD")
    assert parts[0]["type"] == "text" and "transkrip otomatis" in parts[0]["text"]
    assert parts[1] == {"type": "input_audio", "input_audio": {"data": "QUJD", "format": "wav"}}
    with_pic = assistant.with_audio([{"type": "text", "text": "x"}, {"type": "image_url", "image_url": {"url": "data:"}}], "QUJD")
    assert [p["type"] for p in with_pic] == ["text", "image_url", "input_audio"]
    assert assistant.with_audio("halo", None) == "halo"
    assert assistant.without_audio(parts).startswith("UCAPAN PEMILIK: halo")
    assert [p["type"] for p in assistant.without_audio(with_pic)] == ["text", "image_url"]


@needs_db
async def test_the_switch_and_the_ai_hearing_the_owner(pool, monkeypatch):
    from app import assistant, chat, live, llm, main, memory, voice
    monkeypatch.setattr(memory, "search", _no_memory)
    dev = {"name": "HP pemilik", "scope": "owner"}
    assert await voice.input_mode() == "stt"
    assert (await main.voice_input(main.VoiceInputIn(mode="audio"), device=dev))["mode"] == "audio"
    assert (await live.snapshot("utama"))["voice_input"] == "audio"
    with pytest.raises(main.HTTPException):
        await main.voice_input(main.VoiceInputIn(mode="telepati"), device=dev)
    calls = []

    async def stream(messages, tools=None, **kw):
        content = messages[-1]["content"]
        calls.append((kw["category"], [p["type"] for p in content] if isinstance(content, list) else "text"))
        if kw["category"] == "dengar" and len(calls) == 3:
            raise llm.LLMError("semua model gagal")
        yield {"type": "done", "completion": llm.Completion(text="Oke, aku dengar.")}
    monkeypatch.setattr(llm, "stream_chat", stream)
    t = await chat.handle("aku lagi capek banget hari ini", "s-dengar", actor="test", audio="UklGRg==")
    assert t.reply == "Oke, aku dengar." and calls[-1] == ("dengar", ["text", "input_audio"])
    await chat.handle("/privat rahasia", "s-dengar", actor="test", audio="UklGRg==")       # refused before any model
    await chat.handle("simpan ini ya, password: hunter2", "s-dengar", actor="test", audio="UklGRg==")
    assert calls[-1] == ("ngobrol", "text")                                                    # sensitive: never the recording
    calls.clear()
    t = await assistant.respond("cerita dong", "s-dengar", "owner", audio="UklGRg==")
    assert [c[0] for c in calls] == ["dengar"]
    calls.clear()

    async def failing_once(messages, tools=None, **kw):
        content = messages[-1]["content"]
        calls.append((kw["category"], [p["type"] for p in content] if isinstance(content, list) else "text"))
        if kw["category"] == "dengar":
            raise llm.LLMError("tidak ada model yang bisa mendengar")
        yield {"type": "done", "completion": llm.Completion(text="Dari teksnya saja.")}
    monkeypatch.setattr(llm, "stream_chat", failing_once)
    a = await assistant.respond("cerita dong", "s-dengar", "owner", audio="UklGRg==")
    assert a.text == "Dari teksnya saja." and calls == [("dengar", ["text", "input_audio"]), ("ngobrol", "text")]   # falls back to the transcript
    await voice.set_input_mode("stt", "test")
