"""ADR-075: a project worker's result is structured (table, chart, picture, links) for the desk; the voice never reads the JSON."""
import os

import pytest

from tests.test_integration import pool  # noqa: F401  (fixture)

needs_db = pytest.mark.skipif(not os.getenv("TEST_DATABASE_URL"), reason="needs TEST_DATABASE_URL")

BLOCK = '''Saya menemukan dua lowongan.
```hasil
{"ringkasan": "2 lowongan cocok", "poin": ["PT A paling cocok", ""],
 "tabel": [{"judul": "Lowongan", "kolom": ["PT", "Gaji"], "baris": [["A", "25 jt"], ["B"]]}],
 "grafik": [{"judul": "Gaji", "jenis": "radar", "label": ["A", "B", "C"], "nilai": [25, "30", "x"], "satuan": "jt"}],
 "gambar": [{"url": "javascript:alert(1)"}, {"url": "https://a.b/logo.png", "keterangan": "logo"}],
 "tautan": [{"teks": "Lowongan A", "url": "https://a.b/1"}, {"teks": "x", "url": "ftp://x"}]}
```
Selesai.'''


def test_a_result_block_is_checked_and_trimmed_for_the_desk():
    from app import results
    doc, rest = results.split(BLOCK)
    assert doc["ringkasan"] == "2 lowongan cocok" and doc["poin"] == ["PT A paling cocok"]
    assert doc["tabel"] == [{"judul": "Lowongan", "kolom": ["PT", "Gaji"], "baris": [["A", "25 jt"], ["B", ""]]}]      # a short row is padded
    assert doc["grafik"] == [{"judul": "Gaji", "jenis": "bar", "label": ["A", "B"], "nilai": [25.0, 30.0], "satuan": "jt"}]   # unknown kind → bar, a non-number is dropped
    assert doc["gambar"] == [{"url": "https://a.b/logo.png", "keterangan": "logo"}]                                      # never a javascript: url
    assert doc["tautan"] == [{"teks": "Lowongan A", "url": "https://a.b/1"}]
    assert rest == "Saya menemukan dua lowongan.\n\nSelesai." and "```" not in rest


def test_a_broken_or_absent_block_leaves_the_text_alone():
    from app import results
    broken = "Hasil:\n```hasil\n{bukan json}\n```\nakhir"
    assert results.split(broken) == ({}, broken) and results.split("teks biasa") == ({}, "teks biasa") and results.split(None) == ({}, "")
    assert results.clean("x") == {} and results.clean({"tabel": [{"kolom": [], "baris": [[1]]}], "grafik": [{"label": ["a"], "nilai": [1]}]}) == {}
    huge = results.clean({"tabel": [{"kolom": [f"c{i}" for i in range(30)], "baris": [[str(i)] * 30 for i in range(500)]}]})["tabel"][0]
    assert len(huge["kolom"]) == results.MAX_COLS and len(huge["baris"]) == results.MAX_ROWS


def test_the_voice_hears_the_text_not_the_json():
    from app import results
    assert results.spoken(BLOCK) == "Saya menemukan dua lowongan.\n\nSelesai."
    assert results.spoken('```hasil\n{"ringkasan": "ada 2 lowongan"}\n```') == "ada 2 lowongan"
    assert results.spoken("biasa saja") == "biasa saja"


def test_project_workers_are_told_how_to_write_their_result():
    from app import projects, results
    assert "```hasil" in results.FORMAT_HELP and "```hasil" in projects.BRIEF.format(
        name="n", run=1, role="r", n=1, total=1, goal="g", brief="b", context="", split="", web="", format=results.FORMAT_HELP)


@needs_db
async def test_the_desk_opens_a_runs_results_in_full(pool, monkeypatch):
    from app import main, projects, workers
    monkeypatch.setattr(workers, "_start", lambda task_id, context="": None)
    await pool.execute("TRUNCATE projects CASCADE")
    dev = {"name": "HP pemilik", "scope": "owner"}
    p = await main.projects_create(main.ProjectIn(name="Cari kerja", goal="IT", roles=[{"role": "Pencari", "workers": 1}]), device=dev)
    await main.projects_run(p["id"], device=dev)
    tid = await pool.fetchval("SELECT id FROM tasks WHERE project_id = $1", p["id"])
    await pool.execute("UPDATE tasks SET status = 'completed', result = $2 WHERE id = $1", tid, BLOCK)
    doc = await pool.fetchval("INSERT INTO documents (title, format, filename, size, task_id, created_by) VALUES ('Daftar', 'xlsx', 'x.xlsx', 1, $1, 'test') RETURNING id::text", tid)
    got = await main.projects_results(p["id"], device=dev)
    w = got["workers"][0]
    assert got["run"] == 1 and got["runs"] == [1] and w["role"] == "Pencari" and w["doc"]["tabel"][0]["kolom"] == ["PT", "Gaji"]
    assert w["text"].startswith("Saya menemukan") and "```" not in w["text"] and w["documents"] == [{"id": doc, "title": "Daftar", "format": "xlsx"}]
    assert (await main.projects_results(p["id"], 99, device=dev))["run"] == 1                   # an unknown run → the latest
    card = (await projects.get(p["id"]))["workers"][0]["result"]
    assert "```" not in card and card.startswith("Saya menemukan")                              # the card's preview is plain
    with pytest.raises(main.HTTPException):
        await main.projects_results(999999, device=dev)
