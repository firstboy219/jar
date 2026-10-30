"""ADR-087 batch I: the web agent on any site — a hotel booked end to end on a pretend site: the form filled at once (personal data put in
here, never sent to the model), a pick card for the hotel, a review before "Pesan sekarang", the sign-in and the payment done by the owner
on the session's own page, the result, a routine learned and replayed; a page that never changes ends in "macet"; secret fields, money
buttons and money sites refused; a review asked from the chat needs the admin password."""
import asyncio
import json
import os
import re

import httpx
import pytest

from tests.test_integration import pool  # noqa: F401  (fixture)

needs_db = pytest.mark.skipif(not os.getenv("TEST_DATABASE_URL"), reason="needs TEST_DATABASE_URL")


def reply(content):
    return {"choices": [{"message": {"content": content if isinstance(content, str) else json.dumps(content)}}]}


# ---------- pure ----------

def test_start_owner_moments_secrets_placeholders_and_routines():
    from app import webagent as w
    assert w.start_url_for("pesan di https://www.traveloka.com/id-id/hotel ya") == "https://www.traveloka.com/id-id/hotel"
    assert w.start_url_for("hotel di traveloka Bandung") == "https://www.traveloka.com/id-id"
    assert w.start_url_for("cari villa murah di Puncak").startswith("https://www.google.com/search?q=cari+villa")
    assert w.start_url_for("transfer di https://ibank.klikbca.com/").startswith("https://www.google.com/search")   # money sites never start a task
    assert w.financial("https://www.indodax.com/") and not w.financial("https://www.tiket.com/")

    assert w.needs_owner({"flags": {"captcha": True}}) == "verifikasi"
    assert w.needs_owner({"flags": {"password": True}, "title": "Masuk ke akun", "text": "Email Kata sandi"}) == "masuk"
    assert w.needs_owner({"flags": {"payment": True, "card": True}}) == "bayar"
    assert w.needs_owner({"flags": {"payment": True}, "els": [{"k": "isian", "t": "text", "l": "Nama", "req": 1, "v": ""}]}) is None   # fill the form first
    assert w.needs_owner({"flags": {}, "title": "Hotel", "text": ""}) is None

    st = {"els": [{"r": 1, "k": "isian", "t": "text", "l": "Nama lengkap"}, {"r": 2, "k": "isian", "t": "password", "l": "Kata sandi"},
                  {"r": 3, "k": "isian", "t": "text", "l": "Nomor kartu"}, {"r": 4, "k": "tombol", "l": "Lanjut"}, {"r": 5, "k": "isian", "t": "email", "l": "Email"}]}
    fill, refused, missing = w.resolve({"1": "{profil.nama}", "2": "rahasia", "3": "4111", "4": "x", "5": "{profil.email}"}, st, {"nama": "Ilham Putra", "email": ""})
    assert fill == [{"r": 1, "v": "Ilham Putra"}] and len(refused) == 3 and missing == ["email"]
    assert "[RAHASIA: pemilik]" in w.elements_text(st)
    assert w.mask("3201234567890001", True) == "••••••••••••0001" and w.mask("Bandung", False) == "Bandung"
    rows = w.review_rows({"els": [{"k": "isian", "t": "text", "l": "No KTP", "v": "3201234567890001"}, {"k": "isian", "t": "text", "l": "Kota", "v": "Bandung"}]},
                         {"3201234567890001"})
    assert rows == [{"label": "No KTP", "value": "••••••••••••0001"}, {"label": "Kota", "value": "Bandung"}]

    a = {"url": "https://x.id/a", "text": "abc", "els": [{"l": "Kota", "v": ""}]}
    assert w.signature(a) == w.signature(dict(a)) and w.signature(a) != w.signature({**a, "els": [{"l": "Kota", "v": "Bandung"}]})
    page = {"els": [{"r": 7, "k": "isian", "l": "Kota tujuan", "t": "text", "n": "city"}, {"r": 8, "k": "tombol", "l": "Cari"}]}
    assert w.find_sig(page, {"k": "isian", "l": "Kota tujuan", "t": "text"}) == 7 and w.find_sig(page, {"k": "tombol", "l": "Pesan"}) is None
    steps, params = w.learn_steps([{"op": "isi", "fields": [{"sig": {"k": "isian", "l": "Kota"}, "raw": "Bandung"}, {"sig": {"k": "isian", "l": "Nama"}, "raw": "{profil.nama}"}]},
                                   {"op": "klik", "sig": {"k": "tombol", "l": "Cari"}}, {"op": "klik", "sig": {"k": "tombol", "l": "Pesan"}, "commit": True}], "hotel")
    assert [(s["op"], s["src"]) for s in steps] == [("isi", "tujuan"), ("isi", "profil"), ("klik", "tetap"), ("klik", "tetap")] and steps[-1]["commit"] and params == ["Kota"]
    assert w.overlap("pesan hotel di Bandung 2 malam", "hotel Bandung untuk 2 orang") >= 0.4

    # found on a real site: an empty page / the site's own error page is the site's problem, not "stuck"
    assert w.page_problem({"els": [], "text": ""}) == "kosong"
    assert w.page_problem({"els": [{"r": 1}], "title": "Error", "text": "Internal Server Error"}) == "error"
    assert w.page_problem({"els": [{"r": 1, "k": "tombol", "l": "Cari"}], "text": "Cari hotel"}) is None
    # seven "Reserve room" buttons are told apart by their card's title and the link's query
    txt = w.elements_text({"els": [{"r": 6, "k": "tautan", "l": "Reserve room", "c": "Staying without meals", "h": "https://x.dev/reserve.html?plan-id=4"}]})
    assert "«Staying without meals»" in txt and "?plan-id=4" in txt


# ---------- a pretend hotel site ----------

class FakeSite:
    """Pages and their elements; clicks move between pages; the owner's "Selesai" is a flag the test sets."""
    backend = "hp"

    def __init__(self, pages: dict, start: str):
        self.pages, self.page, self.filled, self.status_flags, self.log = pages, start, {}, {}, []

    async def open(self, url):
        return {"url": url}

    def state(self):
        p = self.pages[self.page]
        els = [dict(e, v=self.filled.get((self.page, e["r"]), e.get("v", ""))) for e in p["els"]]
        return {"url": p["url"], "title": p["title"], "text": p.get("text", p["title"]), "els": els, "flags": p.get("flags", {})}

    async def run(self, js, settle_ms=0):
        from app import webagent as w
        if js == w.STATE_JS:
            return json.dumps(self.state())
        if js.startswith(w.FILL_JS.split("%s")[0]):
            fields = json.loads(re.search(r"\}\)\((\[.*\])\)$", js, re.S).group(1))
            for f in fields:
                self.filled[(self.page, f["r"])] = f["v"]
            self.log.append(("isi", self.page, fields))
            return json.dumps({"ok": [f["r"] for f in fields], "bad": []})
        if js.startswith(w.CLICK_JS.split("%d")[0]):
            ref = int(re.search(r"\}\)\((\d+)\)$", js).group(1))
            label = next(e["l"] for e in self.pages[self.page]["els"] if e["r"] == ref)
            self.log.append(("klik", self.page, label))
            self.page = self.pages[self.page].get("go", {}).get(label, self.page)
            return json.dumps({"ok": True, "label": label})
        if js == w.DISMISS_JS:
            return json.dumps({"clicked": []})
        return json.dumps({"ok": True})

    async def status(self):
        return dict(self.status_flags)

    async def show(self, reason):
        pass

    async def close(self):
        pass


HOTEL = {
    "cari": {"url": "https://hotel.contoh.id/", "title": "Cari hotel", "els": [
        {"r": 1, "k": "isian", "t": "text", "l": "Kota", "req": 1}, {"r": 2, "k": "isian", "t": "date", "l": "Check-in", "req": 1},
        {"r": 3, "k": "isian", "t": "date", "l": "Check-out", "req": 1}, {"r": 4, "k": "isian", "t": "number", "l": "Tamu"},
        {"r": 5, "k": "tombol", "l": "Cari"}], "go": {"Cari": "hasil"}},
    "hasil": {"url": "https://hotel.contoh.id/hasil", "title": "Hasil", "text": "Hotel A Rp550.000 rating 8,6. Hotel B Rp700.000 rating 9,0.", "els": [
        {"r": 1, "k": "tombol", "l": "Pilih Hotel A"}, {"r": 2, "k": "tombol", "l": "Pilih Hotel B"}], "go": {"Pilih Hotel A": "tamu", "Pilih Hotel B": "tamu"}},
    "tamu": {"url": "https://hotel.contoh.id/tamu", "title": "Data tamu", "els": [
        {"r": 1, "k": "isian", "t": "text", "l": "Nama tamu", "req": 1}, {"r": 2, "k": "isian", "t": "email", "l": "Email", "req": 1},
        {"r": 3, "k": "isian", "t": "tel", "l": "No HP", "req": 1}, {"r": 4, "k": "tombol", "l": "Pesan sekarang"}], "go": {"Pesan sekarang": "masuk"}},
    "masuk": {"url": "https://hotel.contoh.id/masuk", "title": "Masuk", "text": "Masuk ke akun. Kata sandi", "flags": {"password": True}, "els": [
        {"r": 1, "k": "isian", "t": "email", "l": "Email"}, {"r": 2, "k": "isian", "t": "password", "l": "Kata sandi"}]},
    "bayar": {"url": "https://hotel.contoh.id/bayar", "title": "Pembayaran", "text": "Total pembayaran Rp550.000. Metode pembayaran", "flags": {"payment": True, "card": True},
              "els": [{"r": 1, "k": "isian", "t": "text", "l": "Nomor kartu", "ac": "cc-number"}]},
    "beres": {"url": "https://hotel.contoh.id/beres", "title": "Pesanan berhasil", "text": "Kode booking HB-12345. Hotel A, 5–6 Nov.", "els": []},
}


@needs_db
async def test_a_hotel_booked_end_to_end_and_learned(pool, monkeypatch):
    from app import appsettings, gateway, webagent
    monkeypatch.setattr(webagent, "POLL_S", 0.05)
    await pool.execute("TRUNCATE web_tasks, web_waits, web_routines, flow_runs, settings_kv, tasks RESTART IDENTITY CASCADE")
    await appsettings.put("webprofile", {"nama": "Ilham Putra", "email": "ilham@contoh.id", "hp": "081234567890"}, "test")
    site = FakeSite(HOTEL, "cari")

    async def session(sid, url):
        return site
    monkeypatch.setattr(webagent, "_session", session)
    prompts = []
    plan = iter([
        {"aksi": "isi", "isi": {"1": "Bandung", "2": "2026-11-05", "3": "2026-11-06", "4": "2"}, "lalu_klik": 5, "alasan": "isi pencarian"},
        {"aksi": "tanya", "tanya": {"pertanyaan": "Pilih hotel", "pilihan": ["Hotel A · Rp550 rb · 8,6", "Hotel B · Rp700 rb · 9,0"]}},
        {"aksi": "klik", "klik": 1},
        {"aksi": "isi", "isi": {"1": "{profil.nama}", "2": "{profil.email}", "3": "{profil.hp}"}, "lalu_klik": 4, "kirim": True},
        {"aksi": "klik", "ringkasan": "Membayar Hotel A Rp550.000"},
        {"aksi": "selesai", "ringkasan": "Hotel A dipesan", "hasil": {"kode": "HB-12345", "total": "Rp550.000"}},
    ])

    async def fake(lane, body, **kw):
        prompts.append(json.dumps(body["messages"]))
        return reply(next(plan))
    monkeypatch.setattr(gateway, "complete", fake)
    wid = await pool.fetchval("INSERT INTO web_tasks (goal, start_url, site, origin, task_id) VALUES ('pesan hotel di Bandung 5-6 Nov 2 orang', 'https://hotel.contoh.id/', 'hotel.contoh.id', 'app', 901) RETURNING id")
    seen_waits = []

    async def owner():
        while True:
            await asyncio.sleep(0.05)
            for w in await webagent.open_waits():
                if w["id"] in [x[0] for x in seen_waits]:
                    continue
                seen_waits.append((w["id"], w["kind"]))
                if w["kind"] == "pilih":
                    await webagent.answer_wait(w["id"], "test", option=0)
                elif w["kind"] == "tinjau":
                    rows = {r["label"]: r["value"] for r in w["detail"]["rows"]}
                    assert rows["Nama tamu"] == "Ilham Putra" and w["detail"]["button"] == "Pesan sekarang"
                    await webagent.answer_wait(w["id"], "test", approve=True)
                elif w["kind"] == "masuk":
                    site.page = "bayar"                        # he signed in on the shown page; the site moved on
                    site.status_flags = {"owner_done": True}
                elif w["kind"] == "bayar":
                    site.page = "beres"
                    site.status_flags = {"owner_done": True}
            if site.page == "beres" and len(seen_waits) >= 4:
                return
    helper = asyncio.create_task(owner())

    async def progress(pct, text, extra=None):
        pass

    async def emit(e):
        pass
    out = await asyncio.wait_for(webagent.produce(901, {}, progress, emit), 30)
    await asyncio.wait_for(helper, 5)
    assert [k for _, k in seen_waits] == ["pilih", "tinjau", "masuk", "bayar"]
    assert "HB-12345" in out and "lewat HP" in out
    guest = next(f for op, page, f in site.log if op == "isi" and page == "tamu")
    assert {f["v"] for f in guest} == {"Ilham Putra", "ilham@contoh.id", "081234567890"}               # real values on the page …
    assert not any("ilham@contoh.id" in p or "081234567890" in p for p in prompts)                      # … never in a prompt
    assert ("klik", "hasil", "Pilih Hotel A") in site.log
    row = await pool.fetchrow("SELECT status, result FROM web_tasks WHERE id = $1", wid)
    assert row["status"] == "done" and row["result"]["hasil"]["kode"] == "HB-12345"
    r = await pool.fetchrow("SELECT * FROM web_routines")
    assert r["site"] == "hotel.contoh.id" and r["params"] == ["Kota", "Check-in", "Check-out", "Tamu"]
    flows = {x["action"] for x in await pool.fetch("SELECT action FROM flow_runs")}
    assert "web-langkah" in flows

    # the second time: the routine fills the search with one call and presses Cari without the model
    site2 = FakeSite(HOTEL, "cari")

    async def session2(sid, url):
        return site2
    monkeypatch.setattr(webagent, "_session", session2)
    calls = []

    async def fake2(lane, body, **kw):
        calls.append(body["messages"][0]["content"][:40])
        if "Isi nilai kolom" in body["messages"][0]["content"]:
            return reply({"Kota": "Bandung", "Check-in": "2026-12-01", "Check-out": "2026-12-02", "Tamu": "2"})
        return reply({"aksi": "selesai", "ringkasan": "berhenti di hasil untuk tes"})
    monkeypatch.setattr(gateway, "complete", fake2)
    await pool.fetchval("INSERT INTO web_tasks (goal, start_url, site, origin, task_id) VALUES ('pesan hotel di Bandung 1-2 Des 2 orang', 'https://hotel.contoh.id/', 'hotel.contoh.id', 'app', 902) RETURNING id")
    await asyncio.wait_for(webagent.produce(902, {}, progress, emit), 30)
    first = site2.log[0]
    assert first[0] == "isi" and [f["v"] for f in first[2]] == ["Bandung"] and ("klik", "cari", "Cari") in site2.log
    assert len(calls) == 2 and calls[0].startswith("Isi nilai kolom")                                 # one call for the values, one step after


@needs_db
async def test_stuck_refusals_money_sites_and_chat_review_password(pool, monkeypatch):
    from app import appauth, devices, gateway, main, webagent
    monkeypatch.setattr(webagent, "POLL_S", 0.05)
    await pool.execute("TRUNCATE web_tasks, web_waits, web_routines, flow_runs, settings_kv, tasks RESTART IDENTITY CASCADE")
    still = {"diam": {"url": "https://contoh.id/", "title": "Diam", "els": [{"r": 1, "k": "tombol", "l": "Top up saldo"}, {"r": 2, "k": "isian", "t": "password", "l": "PIN"},
                                                                               {"r": 3, "k": "tombol", "l": "Lanjut"}]}}
    site = FakeSite(still, "diam")

    async def session(sid, url):
        return site
    monkeypatch.setattr(webagent, "_session", session)
    plan = iter([{"aksi": "klik", "klik": 1}, {"aksi": "isi", "isi": {"2": "123456"}}, {"aksi": "klik", "klik": 3}, {"aksi": "klik", "klik": 3}, {"aksi": "klik", "klik": 3}] * 4)

    async def fake(lane, body, **kw):
        return reply(next(plan))
    monkeypatch.setattr(gateway, "complete", fake)
    await pool.execute("INSERT INTO web_tasks (goal, start_url, site, origin, task_id) VALUES ('coba', 'https://contoh.id/', 'contoh.id', 'chat', 903)")

    async def owner():
        while True:
            await asyncio.sleep(0.05)
            for w in await webagent.open_waits():
                if w["kind"] == "macet":
                    await webagent.answer_wait(w["id"], "test", approve=False)
                    return
    helper = asyncio.create_task(owner())

    async def noop(*a, **k):
        pass
    with pytest.raises(webagent.WebError) as e:
        await asyncio.wait_for(webagent.produce(903, {}, noop, noop), 30)
    await helper
    assert "macet" in str(e.value)
    assert not any(op == "klik" and label.startswith("Top up") for op, _, label in [x for x in site.log if x[0] == "klik"])
    assert not any(op == "isi" for op, *_ in site.log)                                                 # the PIN was never typed
    with pytest.raises(webagent.WebError):
        await webagent.request("transfer ke rekening", "https://ibank.klikbca.com/", "test")

    wid = await pool.fetchval("INSERT INTO web_tasks (goal, start_url, site, origin) VALUES ('kirim formulir', 'https://contoh.id/', 'contoh.id', 'chat') RETURNING id")
    wait = await pool.fetchval("INSERT INTO web_waits (web_task_id, kind, title, detail) VALUES ($1, 'tinjau', 'Periksa', '{\"password\": true, \"button\": \"Kirim\"}') RETURNING id", wid)

    async def check(pw):
        return 200 if pw == "pw-admin" else 401
    monkeypatch.setattr(appauth, "_check", check)
    monkeypatch.setenv("VAULT_KEY", "33" * 32)
    _, token = await devices.create("HP", "test", scope="owner")
    h = {"Authorization": f"Bearer {token}"}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url="http://t") as c:
        items = (await c.get("/api/v1/app/needs", headers=h)).json()["items"]
        assert any(i["kind"] == "web" and i["wait"] == "tinjau" and i["password"] for i in items)
        assert (await c.post(f"/api/v1/app/needs/web/{wait}", json={"approve": True}, headers=h)).status_code == 422
        assert (await c.post(f"/api/v1/app/needs/web/{wait}", json={"approve": True, "password": "pw-admin"}, headers=h)).json()["status"] == "done"
        p = (await c.put("/api/v1/app/web/profile", json={"nama": "Ilham", "no_ktp": "3201234567890001"}, headers=h))
        assert p.status_code == 200 and p.json()["no_ktp"].endswith("0001") and "•" in p.json()["no_ktp"] and p.json()["nama"] == "Ilham"
        prof, secret_vals = await webagent._profile()
        assert prof["no_ktp"] == "3201234567890001" and prof["nama_depan"] == "Ilham" and "3201234567890001" in secret_vals
        d = (await c.get("/api/v1/app/web", headers=h)).json()
        assert d["tasks"] and "routines" in d
