"""ADR-087 wave 9 gap batch A: needs answered on the front page (the route and the learned routine's record on a phone run, the rules it
keeps, ★ the option he usually picks), running missions and today's agenda and scheduled projects on the front page."""
import os
from datetime import datetime, timedelta

import pytest

from tests.test_integration import pool  # noqa: F401  (fixture)

needs_db = pytest.mark.skipif(not os.getenv("TEST_DATABASE_URL"), reason="needs TEST_DATABASE_URL")


def test_route_rules_and_the_usual_pick():
    from app import needs
    assert needs.route_of("Pesan GoRide dari Stasiun Bogor ke Kantor Sudirman, bayar GoPay") == {"dari": "Stasiun Bogor", "ke": "Kantor Sudirman"}
    assert needs.route_of("Cek promo kopi") == {}
    r = needs.rules_of("kopikenangan")
    assert r[0] == "Hanya Kopi Kenangan (dan layar bayar GoPay)" and any("PIN" in x for x in r)
    opts = [{"i": 0, "label": "KRL 17.05", "waktu": "17:05"}, {"i": 1, "label": "KRL 17.40", "waktu": "17:40"}, {"i": 2, "label": "KRL 18.15", "waktu": "18:15"}]
    assert needs.recommend(opts, [{"label": "KRL 17.40", "waktu": "17:40"}, {"label": "KRL 17.40"}, {"label": "KRL 18.15"}]) == 1
    assert needs.recommend(opts, []) is None


@needs_db
async def test_the_front_page_answers_needs_and_lists_missions_agenda_and_schedules(pool, monkeypatch):
    from app import features, home  # noqa: F401  (every feature's front-page provider)
    from app.location import WIB
    await pool.execute("TRUNCATE phone_runs, routines, calendar_events, projects, owner_choices RESTART IDENTITY CASCADE")
    await pool.execute("INSERT INTO phone_runs (app, goal, requested_by) VALUES ('gojek', 'Pesan GoRide dari Stasiun Bogor ke Kantor Sudirman', 'obrolan')")
    await pool.execute("""INSERT INTO routines (app, name, intent, keys, steps, runs, ok_runs) VALUES ('gojek', 'GoRide ke kantor', 'x', '["goride"]', '[{"op": "open"}, {"op": "tap"}]', 12, 11)""")
    now = datetime.now(WIB)
    await pool.execute("INSERT INTO calendar_events (source, ext_id, title, start_at, end_at) VALUES ('outlook', 'a', 'Weekly', $1, $2), ('outlook', 'b', 'Review', $3, $4)",
                       now + timedelta(minutes=30), now + timedelta(minutes=90), now + timedelta(minutes=150), now + timedelta(minutes=180))
    await pool.execute("INSERT INTO projects (name, goal, schedule, next_run) VALUES ('Laporan emas', 'harga emas', 'hourly', now() + interval '40 minutes')")
    f = await home.feed("kerja")
    need = next(c for c in f["all"] if c["kind"] == "needs")["need"]
    assert need["route"] == {"dari": "Stasiun Bogor", "ke": "Kantor Sudirman"} and need["routine"] == {"name": "GoRide ke kantor", "runs": 12, "ok": 11, "steps": 2}
    assert f["hero"]["kind"] == "needs"                                                        # answered right on the front page
    agenda = next(c for c in f["all"] if c["id"] == "agenda")
    if (now + timedelta(minutes=180)).date() == now.date():
        assert [x["title"] for x in agenda["list"]] == ["Weekly", "Review"]
    sched = next(c for c in f["all"] if c["id"] == "scheduled")
    assert sched["list"][0]["title"] == "Laporan emas" and sched["list"][0]["repeat"] == "Tiap jam"
