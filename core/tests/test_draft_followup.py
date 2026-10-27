"""ADR-070: "sudah jadi drafnya?" — the draft that was only promised is started; a written one is shown again in the chat."""
import pytest

from tests.test_integration import pool  # noqa: F401  (fixture)


def test_a_question_about_the_draft_is_understood():
    from app import router
    for said in ("apakah sudah jadi? draftnya", "mana drafnya", "draft balasannya sudah?", "udah jadi belum draftnya"):
        a = router.parse_action(said)
        assert a and a.name == "draft_status", said
    assert router.parse_action("buatkan draft balasan email ini").name == "write_draft"            # asking for one is still asking


@pytest.mark.asyncio
async def test_a_promised_draft_that_never_started_is_started_from_the_earlier_request(pool, monkeypatch):
    from app import assistant, screen_reader
    started = []

    async def fake_read(image, private=False):
        return "Dari: Steven\nSubjek: RE: AI Order Mapping\nWe can start project status meeting next week 3rd Nov."

    async def no_question(request, text, private=False):
        return ""

    async def fake_draft(request, session_id, actor, device_id, location, private, screen_text="", attachments=None):
        started.append((request, screen_text))
        return {"task_id": 1, "status": "queued"}
    monkeypatch.setattr(screen_reader, "read", fake_read)
    monkeypatch.setattr(screen_reader, "question", no_question)
    monkeypatch.setattr(assistant, "start_draft", fake_draft)
    for role, text in (("user", "tolong bantu saya menjawab email ini"), ("assistant", "Oke, aku buat 3 draf balasan untuk email ini ya.")):
        await pool.execute("INSERT INTO messages (session_id, role, content, route) VALUES ('meja-x', $1, $2, 'assistant')", role, text)
    a = await assistant.respond("apakah sudah jadi? draftnya", "meja-x", "device:web", screen="SCREEN", image_source="screen")
    assert started and started[0][0] == "tolong bantu saya menjawab email ini" and "3rd Nov" in started[0][1]
    assert "draf" in a.text.lower()

    started.clear()
    a = await assistant.respond("mana drafnya", "meja-empty", "device:web")
    assert not started and "Belum ada draf" in a.text                                    # nothing was ever asked: nothing invented
