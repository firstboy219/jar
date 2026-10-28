"""What a worker hands back, in a form the desk can show (ADR-075): a fenced ```hasil block of JSON — summary, points, tables, charts,
images, links — followed by the plain text. The block is checked and trimmed here (the desk draws from it), and left out of what is spoken."""

import json
import re

BLOCK = re.compile(r"```hasil[ \t]*\r?\n(.*?)```", re.DOTALL)
MAX_TABLES, MAX_ROWS, MAX_COLS, MAX_CHARTS, MAX_POINTS, MAX_IMAGES, MAX_LINKS, MAX_POINTS_LIST, MAX_PICKS = 6, 200, 12, 6, 40, 12, 20, 30, 8
CHART_KINDS = ("bar", "line", "pie")

FORMAT_HELP = """Tulis hasilmu terstruktur supaya pemilik bisa membukanya sebagai tabel, grafik, dan gambar. Setelah penjelasan singkat, akhiri dengan SATU blok seperti ini
(JSON valid; hapus bagian yang tidak relevan; angka di grafik berupa angka, bukan teks):
```hasil
{"ringkasan": "1–3 kalimat inti hasil run ini",
 "poin": ["temuan penting", "..."],
 "tabel": [{"judul": "Lowongan ditemukan", "kolom": ["Perusahaan", "Posisi", "Gaji", "Status"], "baris": [["PT A", "IT Manager", "25 jt", "siap dilamar"]]}],
 "grafik": [{"judul": "Gaji per perusahaan", "jenis": "bar", "label": ["PT A", "PT B"], "nilai": [25, 30], "satuan": "jt"}],
 "gambar": [{"url": "https://…", "keterangan": "apa isi gambar ini"}],
 "tautan": [{"teks": "Lowongan PT A", "url": "https://…"}],
 "pilihan": [{"label": "KRL 06:27 → tiba kantor 07:05", "waktu": "06:02", "detail": "berangkat dari rumah 06:02"}]}
```
("pilihan" hanya bila pemilik harus memilih salah satu opsi hasilmu untuk langkah berikutnya: 3–6 opsi; "waktu" = jam HH:MM WIB yang menentukan kapan langkah berikutnya jalan, bila ada.)
(grafik jenis: bar, line, atau pie.) Pakai tabel untuk daftar/perbandingan, grafik untuk angka yang bisa dibandingkan, gambar hanya dari URL https yang benar-benar kamu lihat."""


def _s(v, n: int) -> str:
    return " ".join(str(v if v is not None else "").split())[:n]


def _url(v) -> str | None:
    u = str(v or "").strip()
    return u[:600] if re.match(r"^https?://[^\s<>\"']+$", u, re.IGNORECASE) else None


def _num(v):
    if isinstance(v, bool) or not isinstance(v, (int, float, str)):
        return None
    try:
        f = float(v)
    except ValueError:
        return None
    return f if f == f and abs(f) != float("inf") else None


def clean(data) -> dict:
    """The structured result, kept to what can be drawn (pure; unit-tested): bad parts are dropped, never raised."""
    if not isinstance(data, dict):
        return {}
    out: dict = {}
    if s := _s(data.get("ringkasan"), 1200):
        out["ringkasan"] = s
    if isinstance(data.get("poin"), list):
        if poin := [p for p in (_s(x, 400) for x in data["poin"][:MAX_POINTS_LIST]) if p]:
            out["poin"] = poin
    tables = []
    for t in (data.get("tabel") if isinstance(data.get("tabel"), list) else [])[:MAX_TABLES]:
        if not isinstance(t, dict) or not isinstance(t.get("kolom"), list) or not isinstance(t.get("baris"), list):
            continue
        cols = [_s(c, 60) for c in t["kolom"][:MAX_COLS]]
        rows = [[_s(c, 300) for c in (r + [""] * len(cols))[:len(cols)]] for r in t["baris"][:MAX_ROWS] if isinstance(r, list)]
        if cols and rows:
            tables.append({"judul": _s(t.get("judul"), 120), "kolom": cols, "baris": rows})
    if tables:
        out["tabel"] = tables
    charts = []
    for g in (data.get("grafik") if isinstance(data.get("grafik"), list) else [])[:MAX_CHARTS]:
        if not isinstance(g, dict) or not isinstance(g.get("label"), list) or not isinstance(g.get("nilai"), list):
            continue
        pts = [(_s(a, 40), _num(b)) for a, b in zip(g["label"], g["nilai"])][:MAX_POINTS]
        pts = [(a, b) for a, b in pts if b is not None]
        if len(pts) >= 2:
            charts.append({"judul": _s(g.get("judul"), 120), "jenis": g.get("jenis") if g.get("jenis") in CHART_KINDS else "bar",
                           "label": [a for a, _ in pts], "nilai": [b for _, b in pts], "satuan": _s(g.get("satuan"), 16)})
    if charts:
        out["grafik"] = charts
    picks = []
    for o in (data.get("pilihan") if isinstance(data.get("pilihan"), list) else [])[:MAX_PICKS]:
        if isinstance(o, dict) and (label := _s(o.get("label"), 200)):
            w = re.match(r"^([01]?\d|2[0-3])[:.]([0-5]\d)$", str(o.get("waktu") or "").strip())
            picks.append({"label": label, "waktu": f"{int(w[1]):02d}:{w[2]}" if w else "", "detail": _s(o.get("detail"), 300)})
    if picks:
        out["pilihan"] = picks
    images = [{"url": u, "keterangan": _s(i.get("keterangan"), 200)} for i in (data.get("gambar") if isinstance(data.get("gambar"), list) else [])[:MAX_IMAGES]
              if isinstance(i, dict) and (u := _url(i.get("url")))]
    if images:
        out["gambar"] = images
    links = [{"teks": _s(i.get("teks"), 120) or u, "url": u} for i in (data.get("tautan") if isinstance(data.get("tautan"), list) else [])[:MAX_LINKS]
             if isinstance(i, dict) and (u := _url(i.get("url")))]
    if links:
        out["tautan"] = links
    return out


def split(text: str) -> tuple[dict, str]:
    """(the cleaned structured result, the text without the block). A block that is not valid JSON stays in the text. Pure; unit-tested."""
    text = text or ""
    for m in reversed(list(BLOCK.finditer(text))):
        try:
            data = json.loads(m.group(1))
        except ValueError:
            continue
        doc = clean(data)
        if doc:
            return doc, (text[:m.start()] + text[m.end():]).strip()
    return {}, text.strip()


def spoken(text: str) -> str:
    """The result as it is told to the owner: without the JSON block (its summary stands in when nothing else was written)."""
    doc, rest = split(text)
    return rest or doc.get("ringkasan", "") or (text or "")
