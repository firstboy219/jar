# Hidden test for problem p1 (spike, ADR-043). Never shown to the runtimes; added at grading time.


def test_self_model_describes_every_stt_engine(monkeypatch):
    import asyncio
    from app import composition, gateway, self_model
    monkeypatch.setattr(self_model, "stt_config", lambda: asyncio.sleep(0, {"model": "nova-3", "keywords": []}))
    monkeypatch.setattr(gateway, "categories", lambda: asyncio.sleep(0, {}))
    monkeypatch.setattr(self_model.hub, "clients", lambda: [])
    monkeypatch.setattr(self_model, "lessons", lambda: asyncio.sleep(0, []))
    for engine in list(composition.STT_ENGINES) + ["engine-baru"]:
        monkeypatch.setattr(composition, "stt_engine", lambda e=engine: asyncio.sleep(0, e))
        text = asyncio.run(self_model.describe())
        assert "Pendengaran:" in text
