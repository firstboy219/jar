"""ADR-069: "bantu jawab email ini" is a draft at once, and the chat that asked sees its progress — then the draft itself."""
import json

import pytest

from tests.test_integration import pool  # noqa: F401  (fixture)


def test_answering_an_email_is_a_draft_but_a_question_about_it_is_not():
    from app import router
    for said in ("tolong bantu saya menjawab email ini", "balasin chat ini dong", "jawab email dari Steven", "bantu balas pesan WA ini"):
        a = router.parse_action(said)
        assert a and a.name == "write_draft", said
    for said in ("sudah kubalas emailnya?", "apakah dia sudah menjawab email kemarin?", "kapan dia balas pesan saya"):
        a = router.parse_action(said)
        assert not a or a.name != "write_draft", said


def test_a_workers_bar_moves_quickly_first_and_never_reaches_100_by_itself():
    from app import workers
    pcts = [workers.step_pct(n) for n in range(0, 40)]
    assert pcts[0] == 10 and pcts == sorted(pcts) and max(pcts) <= 92 and pcts[3] >= 30


@pytest.mark.asyncio
async def test_the_writer_reports_its_stages_and_ends_with_the_draft(pool, monkeypatch, tmp_path):
    from app import documents, llm, stage, writer
    monkeypatch.setattr(documents, "ROOT", tmp_path)
    seen = []

    async def fake_complete(messages, **kw):
        return json.dumps({"jenis": "email", "kepada": "Steven", "email": "steven@example.com", "subjek": "RE: AI Order Mapping",
                           "ringkas": "terima kasih, setuju rapat 3 Nov", "isi": "Hi Steven,\\n\\nTerima kasih. Saya setuju rapat 3 November.\\n\\nSalam,\\nIlham"})

    async def no_show(*a, **k):
        return {"id": "x", "delivered": 0}

    async def progress(pct, text, extra=None):
        seen.append((pct, text, extra))
    monkeypatch.setattr(llm, "complete", fake_complete)
    monkeypatch.setattr(stage, "show", no_show)
    tid = await pool.fetchval("INSERT INTO tasks (session_id, title, instruction, status) VALUES ('meja-1', 'Draf', 'x', 'running') RETURNING id")
    out = await writer.produce(tid, writer.MARK + "PERMINTAAN PEMILIK: balas email ini", progress=progress)
    pcts = [p for p, _, _ in seen]
    assert pcts[0] == 15 and pcts == sorted(pcts) and pcts[-1] == 100 and "Menyimpan" in seen[-2][1]
    draft = seen[-1][2]["draft"]
    assert draft["subject"] == "RE: AI Order Mapping" and "setuju rapat 3 November" in draft["text"] and draft["doc_url"].startswith("/api/v1/documents/")
    assert "sudah jadi" in out
