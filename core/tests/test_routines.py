"""ADR-083: a phone task done once with AI becomes a routine replayed without AI — AI only for the steps that need judgement."""
import json
import os

import pytest

from tests.test_integration import pool  # noqa: F401  (fixture)

needs_db = pytest.mark.skipif(not os.getenv("TEST_DATABASE_URL"), reason="needs TEST_DATABASE_URL")

GORIDE = [
    {"op": "open"},
    {"op": "tap", "match": {"t": "GoRide"}, "say": "buka GoRide"},
    {"op": "tap", "match": {"h": "mau ke mana"}, "label": "order"},
    {"op": "type", "match": {"e": True}, "text": "{tujuan}", "submit": True},
    {"op": "ai", "goal": "pilih hasil pencarian yang paling cocok dengan {tujuan}", "max_steps": 4},
    {"op": "tap", "match": {"t_has": "hemat"}},
    {"op": "tap", "match": {"t": "Pesan GoRide"}},
    {"op": "wait", "match": {"t_has": "driver"}, "timeout": 5},
    {"op": "read", "match": {"t_has": "driver"}, "regex": r"(\d+)\s*mnt", "into": "jemput"},
    {"op": "if", "var": "jemput", "cmp": "<=", "value": 5, "then": "chat", "else": "batal"},
    {"op": "tap", "match": {"t": "Batalkan"}, "label": "batal"},
    {"op": "goto", "to": "order", "max": 2},
    {"op": "ai", "goal": "kabari driver: jemput di {asal}", "max_steps": 6, "label": "chat"},
    {"op": "done", "result": "GoRide ke {tujuan} dipesan, driver {jemput} menit lagi."},
]
PARAMS = {"tujuan": "alamat tujuan", "asal": "lokasi jemput"}


def node(i, **kw):
    return {"i": i, **kw}


def test_parameters_are_filled_and_elements_found_by_what_they_show():
    from app import routines
    assert routines.fill("ke {tujuan} dari {asal} {x}", {"tujuan": "Ancol", "asal": "rumah"}) == "ke Ancol dari rumah {x}"
    screen = {"nodes": [node(0, t="Beranda"), node(1, t="GoRide", k=1), node(2, c="EditText", e=1, h="Mau ke mana?"),
                        node(3, t="GoRide Hemat · Rp18.000", k=1), node(4, id="btn_order", t="Pesan GoRide")]}
    assert routines.find_node(screen, {"t": "goride"})["i"] == 1                     # text without case
    assert routines.find_node(screen, {"t_has": "hemat"})["i"] == 3
    assert routines.find_node(screen, {"h": "mau ke mana"})["i"] == 2
    assert routines.find_node(screen, {"e": True})["i"] == 2
    assert routines.find_node(screen, {"id": "btn_order"})["i"] == 4
    assert routines.find_node(screen, {"t": "GoCar"}) is None and routines.find_node(screen, {}) is None
    assert routines.find_node(screen, {"t_has": "{opsi}"}, {"opsi": "hemat"})["i"] == 3
    assert routines.compare(4, "<=", 5) and not routines.compare("7", "<=", 5) and routines.compare("Hemat", "==", "hemat")


def test_a_routine_is_recognised_by_its_keywords():
    from app import routines
    assert routines.keys_match(["goride"], "Tolong pesankan Go-Ride ke Ancol") and routines.keys_match(["go food", "martabak"], "order GoFood martabak")
    assert not routines.keys_match(["goride"], "pesan gocar") and not routines.keys_match([], "apa saja")


def test_a_program_is_checked_before_it_is_kept():
    from app import routines
    assert routines.validate(GORIDE, PARAMS) == []
    assert "program kosong" in routines.validate([], {})
    bad = [{"op": "tap", "match": {}}, {"op": "goto", "to": "nowhere"}, {"op": "type", "match": {"e": True}, "text": "{kota}"}, {"op": "fly"}]
    problems = " | ".join(routines.validate(bad, {}))
    for want in ("tanpa elemen", "label nowhere", "variabel {kota}", "op tidak dikenal", "tidak ada langkah done"):
        assert want in problems, want
    assert any("regex" in p for p in routines.validate([{"op": "read", "regex": "(", "into": "x"}, {"op": "done"}], {}))
    prog = routines.parse_program("```json\n" + json.dumps({"nama": "GoRide", "params": PARAMS, "steps": GORIDE, "kebutuhan": ["jemput di rumah"]}) + "\n```")
    assert prog["nama"] == "GoRide" and prog["kebutuhan"] == ["jemput di rumah"]
    with pytest.raises(routines.RoutineError):
        routines.parse_program('{"steps": []}')


class FakePhone:
    """A Gojek-like phone: the screens follow the taps; the driver is 9 minutes away the first time, 3 the second."""

    def __init__(self, etas=(9, 3)):
        self.etas, self.screen, self.log, self.ai_goals = list(etas), "home", [], []

    def obs(self):
        s = {"home": [node(0, t="GoRide", k=1)],
             "ride": [node(0, h="Mau ke mana?", k=1)],
             "search": [node(0, c="EditText", e=1, h="Cari tujuan")],
             "results": [node(0, t="NIPSEA Ancol", k=1), node(1, t="Ancol Beach", k=1)],
             "price": [node(0, t="GoRide Hemat · Rp18.000", k=1), node(1, t="Pesan GoRide", k=1)],
             "found": [node(0, t=f"Driver tiba {self.etas[0]} mnt"), node(1, t="Batalkan", k=1)]}[self.screen]
        return {"package": "com.gojek.app", "nodes": s}

    async def observe(self, pause=0.0):
        return self.obs()

    async def act(self, kind, **a):
        self.log.append((kind, a.get("index"), a.get("text")))
        o = self.obs()["nodes"]
        t = (o[a["index"]].get("t") or o[a["index"]].get("h") or "") if a.get("index") is not None else ""
        self.screen = {"GoRide": "ride", "Mau ke mana?": "search", "Cari tujuan": "results", "GoRide Hemat · Rp18.000": "price",
                       "Pesan GoRide": "found"}.get(t, self.screen)
        if kind == "type":
            self.screen = "results"
        if t == "Batalkan":
            self.etas.pop(0)
            self.screen = "ride"
        if kind == "open":
            self.screen = "home"
        return self.obs()

    async def ai(self, goal, max_steps):
        self.ai_goals.append(goal)
        if self.screen == "results":
            self.screen = "price"
        return "ok"

    async def ask(self, q):
        return "ya"

    async def emit(self, e):
        pass


async def test_the_ride_is_ordered_again_when_the_driver_is_far_and_ai_is_used_only_where_needed():
    from app import routines
    phone = FakePhone()
    res = await routines.execute(GORIDE, {"tujuan": "NIPSEA Ancol", "asal": "rumah"}, phone)
    assert res["ok"], res
    assert res["result"] == "GoRide ke NIPSEA Ancol dipesan, driver 3.0 menit lagi."
    assert [g for g in phone.ai_goals] == ["pilih hasil pencarian yang paling cocok dengan NIPSEA Ancol"] * 2 + ["kabari driver: jemput di rumah"]
    assert res["ai"] == 3 and res["auto"] >= 14                                          # most of it without AI
    assert ("type", 0, "NIPSEA Ancol") in phone.log and phone.log.count(("tap", 1, None)) >= 1


async def test_a_routine_that_cannot_go_on_says_where_and_why():
    from app import routines
    phone = FakePhone(etas=(9, 9, 9, 9))
    res = await routines.execute(GORIDE, {"tujuan": "x", "asal": "y"}, phone)
    assert not res["ok"] and "diulang 2 kali" in res["why"]                               # re-ordered twice, then the AI decides
    missing = await routines.execute([{"op": "tap", "match": {"t": "GoCar"}}, {"op": "done"}], {}, FakePhone())
    assert not missing["ok"] and missing["at"] == 1 and "tidak menemukan" in missing["why"]

    class Refusing(FakePhone):
        async def act(self, kind, **a):
            raise RuntimeError("isi saldo di luar izin")
    refused = await routines.execute([{"op": "tap", "match": {"t": "GoRide"}}, {"op": "done"}], {}, Refusing())
    assert not refused["ok"] and "di luar izin" in refused["why"]                         # the guards still hold


@needs_db
async def test_a_routine_is_learned_found_by_meaning_and_switched_off_after_failures(pool, monkeypatch):
    from app import llm, memory, routines
    await pool.execute("TRUNCATE routines")
    saved = []

    async def compile_(messages, **k):
        assert k["category"] == "hp" and "PERMINTAAN PEMILIK" in messages[1]["content"]
        return json.dumps({"nama": "GoRide ke tujuan", "pola": "Pesan GoRide dari {asal} ke {tujuan}", "kata_kunci": ["goride"],
                           "params": PARAMS, "steps": GORIDE, "kebutuhan": ["Pemilik memilih GoRide hemat"]})

    async def remember(text, category, source, kind="fact", **k):
        saved.append((text, kind))
        return {}
    monkeypatch.setattr(llm, "complete", compile_)
    monkeypatch.setattr(memory, "save", remember)
    trace = [{"aksi": "ketuk", "elemen": {"t": "GoRide"}}, {"aksi": "ketik", "elemen": {"e": 1}, "teks": "NIPSEA Ancol"}]
    r = await routines.learn("gojek", "Gojek", "pesan goride ke NIPSEA Ancol dari rumah", trace, "dipesan", 7)
    assert r["name"] == "GoRide ke tujuan" and r["version"] == 1 and saved == [("Pemilik memilih GoRide hemat", "preference")]
    assert r["keys"] == ["goride"] and r["pattern"] == "Pesan GoRide dari {asal} ke {tujuan}"
    assert (await routines.find("gojek", "tolong pesankan Go-Ride ke Stasiun Angke"))["id"] == r["id"]   # another destination: the same routine
    assert await routines.find("gojek", "pesan gofood martabak manis") is None                           # another service: not this one
    assert await routines.find("grab", "pesan goride ke NIPSEA Ancol") is None

    async def fill_params(messages, **k):
        assert k["category"] == "ringan"
        return '{"tujuan": "Stasiun Angke", "asal": "rumah"}'
    monkeypatch.setattr(llm, "complete", fill_params)
    assert await routines.params_for(r, "goride ke stasiun angke") == {"tujuan": "Stasiun Angke", "asal": "rumah"}
    for _ in range(3):
        await routines.record(r["id"], False, 4, 1)
    row = await pool.fetchrow("SELECT status, runs, fail_streak, auto_steps, ai_steps FROM routines WHERE id = $1", r["id"])
    assert row["status"] == "off" and row["runs"] == 3 and row["auto_steps"] == 12 and row["ai_steps"] == 3
    monkeypatch.setattr(llm, "complete", compile_)
    v2 = await routines.learn("gojek", "Gojek", "pesan goride", trace, "ok", 8, replaces=r)          # the AI finished it: the next version
    assert v2["version"] == 2 and v2["status"] == "active" and v2["fail_streak"] == 0
    assert [x["name"] for x in await routines.listing()] == ["GoRide ke tujuan"]


@needs_db
async def test_the_phone_uses_a_learned_routine_instead_of_asking_the_ai_every_step(pool, monkeypatch):
    from app import hub, llm, phone_agent, routines, workers
    monkeypatch.setattr(workers, "_start", lambda task_id, context="": None)

    async def quiet(ev):
        return 1
    monkeypatch.setattr(hub, "broadcast", quiet)
    await pool.execute("TRUNCATE phone_runs, routines")
    fake = FakePhone(etas=(3,))

    async def op(name, **a):
        if name in ("begin", "end"):
            return {"ok": True}
        if name == "observe":
            return fake.obs()
        return await fake.act({"open": "open", "tap": "tap", "type": "type", "scroll": "scroll", "back": "back"}[name], **a)
    monkeypatch.setattr(phone_agent, "op", op)
    monkeypatch.setattr(phone_agent, "phone_online", lambda: True)   # the fake phone is connected

    async def never(*a, **k):
        raise AssertionError("no AI loop while the routine runs")
        yield
    async def ai_step(self, goal, max_steps):
        return await fake.ai(goal, max_steps)
    monkeypatch.setattr(llm, "stream_chat", never)
    monkeypatch.setattr(phone_agent._PhoneIO, "ai", ai_step)

    async def found(app, goal):
        return {"id": 1, "name": "GoRide ke tujuan", "version": 1, "steps": GORIDE, "params": PARAMS}

    async def params(r, goal):
        return {"tujuan": "NIPSEA Ancol", "asal": "rumah"}
    recorded = []

    async def record(rid, ok, auto, ai):
        recorded.append((rid, ok, ai))
    monkeypatch.setattr(routines, "find", found)
    monkeypatch.setattr(routines, "params_for", params)
    monkeypatch.setattr(routines, "record", record)
    run = await phone_agent.request("Pesan GoRide ke NIPSEA Ancol", "gojek", "owner")
    run = await phone_agent.approve(run["id"], "owner")
    row = await pool.fetchrow("SELECT id, instruction FROM tasks WHERE id = $1", run["task_id"])

    async def nothing(*a, **k):
        return None
    out = await phone_agent.produce(row["id"], dict(row), nothing, nothing)
    assert out.startswith("GoRide ke NIPSEA Ancol dipesan, driver 3.0 menit lagi.") and "langkah tanpa AI" in out and "2 langkah dengan AI" in out
    assert recorded == [(1, True, 2)]
