"""ADR-066: a draft from a screen shared in the browser — the email on the picture is read, one question may come first, the answer
(or the whole email pasted into the chat) goes into the draft."""
import pytest

from tests.test_integration import pool  # noqa: F401  (fixture)



def test_the_question_is_read_strictly():
    from app import screen_reader
    assert screen_reader.parse_question('{"tanya": "Mau menyetujui atau menolak tawarannya?"}') == "Mau menyetujui atau menolak tawarannya?"
    assert screen_reader.parse_question('ok {"tanya": ""}') == ""
    assert screen_reader.parse_question("bukan json") == ""
    assert screen_reader.truncated("Dari: Rina\n...\n[TERPOTONG]") and not screen_reader.truncated("Dari: Rina")


@pytest.mark.asyncio
async def test_a_shared_email_is_read_asked_about_and_drafted_with_the_answer(pool, monkeypatch):
    from app import assistant, screen_reader
    drafts = []

    async def fake_read(image, private=False):
        assert image == "SCREEN"
        return "Dari: Rina\nSubjek: Undangan rapat Kamis\nBisakah Bapak hadir Kamis jam 10?"

    async def fake_question(request, text, private=False):
        return "Bapak bisa hadir Kamis jam 10, atau minta jadwal lain?"

    async def fake_draft(request, session_id, actor, device_id, location, private, screen_text="", attachments=None):
        drafts.append((request, screen_text))
        return {"task_id": 1, "status": "queued"}
    monkeypatch.setattr(screen_reader, "read", fake_read)
    monkeypatch.setattr(screen_reader, "question", fake_question)
    monkeypatch.setattr(assistant, "start_draft", fake_draft)
    a = await assistant.respond("buatkan balasan email ini", "meja-1", "device:web", screen="SCREEN", image_source="screen")
    assert "Kamis jam 10" in a.text and not drafts                                       # one question first, nothing written yet
    await assistant.respond("bisa hadir, tapi minta jam 11", "meja-1", "device:web")
    req, material = drafts[0]
    assert "Jawaban pemilik: bisa hadir, tapi minta jam 11" in req and "Subjek: Undangan rapat Kamis" in material
    assert not assistant._pending_drafts                                                 # the question is answered once

    async def no_question(request, text, private=False):
        return ""
    monkeypatch.setattr(screen_reader, "question", no_question)
    await assistant.respond("buatkan balasan email ini", "meja-2", "device:web", screen="SCREEN", image_source="screen")
    assert "Bisakah Bapak hadir" in drafts[-1][1]                                        # clear enough: written at once, from the screen


@pytest.mark.asyncio
async def test_a_pasted_email_completes_what_the_screen_cut_off(pool, monkeypatch):
    from app import assistant, screen_reader
    drafts = []

    async def fake_read(image, private=False):
        return "Dari: Budi\nSubjek: Penawaran\nKami menawarkan harga [TERPOTONG]"

    async def fake_draft(request, session_id, actor, device_id, location, private, screen_text="", attachments=None):
        drafts.append((request, screen_text))
        return {"task_id": 1, "status": "queued"}
    monkeypatch.setattr(screen_reader, "read", fake_read)
    monkeypatch.setattr(assistant, "start_draft", fake_draft)
    a = await assistant.respond("tolong buatkan draft balasan email ini", "meja-3", "device:web", screen="SCREEN", image_source="screen")
    assert "terpotong" in a.text.lower() and not drafts
    pasted = "Kami menawarkan harga Rp 12.000.000 untuk 40 unit,\nberlaku sampai 30 November. Mohon konfirmasi.\n" * 3
    await assistant.respond(pasted, "meja-3", "device:web")
    req, material = drafts[0]
    assert "Rp 12.000.000" in material and "TEKS YANG DITEMPEL PEMILIK" in material and "Jawaban pemilik" not in req
