"""Seeds a throwaway JARVIS with a little of everything, then screenshots app v2 routes through headless Chrome (CDP).
Runs INSIDE the preview stack's jarvis-core container (see app-preview.sh); writes PNGs to /tmp/shots."""
import asyncio
import base64
import json
import os
import socket
import sys

import httpx
import websockets

ROUTES = sys.argv[1:] or ["beranda", "fitur", "butuh", "misi", "obrolan", "catatan", "ingatan", "kontrol", "halaman"]
W, H = int(os.getenv("PREVIEW_W", "390")), int(os.getenv("PREVIEW_H", "844"))


async def seed() -> str:
    from app import db, devices, notes
    await db.connect(os.environ["DATABASE_URL"])
    _, token = await devices.create("Preview HP", "preview", scope="owner")
    p = db.pool()
    await p.execute("""INSERT INTO tasks (session_id, title, instruction, kind, status, runtime, runtime_note, started_at, plan, cost_usd, progress)
        VALUES ('app-x', 'Riset laptop desain di bawah Rp15 jt', 'bandingkan 3 laptop', 'owner', 'running', 'openjarvis', 'tugas berat', now() - interval '161 seconds',
        '{"goal": "laptop", "steps": ["Pahami kebutuhan", "Cari di 3 toko", "Kumpulkan spesifikasi", "Bandingkan & beri nilai", "Cek ulasan", "Susun laporan"]}', 0.011, 'membandingkan 3 model')""")
    await p.execute("""INSERT INTO tasks (session_id, title, instruction, kind, status, runtime, finished_at, result)
        VALUES ('app-x', 'Ringkas 18 email baru', 'ringkas email', 'owner', 'completed', 'ringan', now(), 'Selesai')""")
    await p.execute("""INSERT INTO phone_runs (app, goal, requested_by) VALUES ('gojek', 'Pesan GoRide ke Stasiun Bogor', 'obrolan')""")
    await notes.add_task("Kirim revisi timeline ke Dimas", None, 3)
    await notes.add_task("Lampirkan struk reimburse", None, None)
    await p.execute("INSERT INTO flow_runs (feature, action, goal, lane, status, finished_at) VALUES ('bisnis', 'poll', 'x', 'skill', 'done', now()), ('brief', 'compose', 'x', 'ringan', 'done', now())")
    # wave 3: one list of email + WhatsApp (the same matter across sources), an errand, the next meeting, a meeting being recorded
    await p.execute("""INSERT INTO inbox_items (source, ext_id, thread, sender, sender_addr, subject, snippet, received_at, triage, reason, topic, due, replies, task, draft) VALUES
        ('outlook', 'O1', 'C1', 'Sari Wulandari', 'sari@kantor.co.id', 'Persetujuan laporan Q3', 'Pak, mohon persetujuan laporan Q3 sebelum jam 3 sore ya. Lampiran sudah saya revisi sesuai masukan kemarin.', now() - interval '40 minutes', 'needs', 'Sari menunggu persetujuanmu sebelum 15.00', 'Sari · laporan Q3', '15.00', '[]', '',
         '{"body": "Halo Mbak Sari,\\n\\nTerima kasih revisinya. Laporan Q3 sudah saya cek dan saya setujui.\\n\\nSalam,\\nIlham", "style": "kamu", "lane": "ringan"}'),
        ('whatsapp', 'n1', 'wa:sari wulandari', 'Sari Wulandari', '', '', 'Pak, sudah sempat lihat email laporan Q3? 🙏', now() - interval '12 minutes', 'needs', 'Sari menunggu persetujuanmu sebelum 15.00', 'Sari · laporan Q3', '', '["Sudah, saya setujui siang ini", "Saya cek 10 menit lagi"]', '', null),
        ('whatsapp', 'n2', 'wa:istri', 'Istri', '', '', 'Yah nanti pulang mampir beli susu si Kecil ya, yang biasa', now() - interval '25 minutes', 'needs', 'Titipan untuk perjalanan pulang', 'Istri · titipan', '', '["Siap, nanti Ayah beliin", "Oke"]', 'beli susu si Kecil', null),
        ('outlook', 'O2', 'C2', 'HR Kantor', 'hr@kantor.co.id', 'Jadwal medical check-up', 'Medical check-up tahunan dijadwalkan Kamis 6 Nov pukul 08.00 di klinik lantai 2.', now() - interval '2 hours', 'fyi', 'Info jadwal MCU Kamis', 'HR · MCU', '', '[]', '', null),
        ('gmail', 'G1', 'G1', 'Tokopedia', 'promo@tokopedia.com', 'Flash sale 11.11', 'Diskon sampai 90%', now() - interval '3 hours', 'ignore', 'promosi', '', '', '[]', '', null)""")
    await p.execute("""INSERT INTO settings_kv (key, value) VALUES ('commute:errands', jsonb_build_object('day', to_char(now() AT TIME ZONE 'Asia/Jakarta', 'YYYY-MM-DD'), 'items', '["beli susu si Kecil"]'::jsonb))""")
    await p.execute("""INSERT INTO calendar_events (source, ext_id, title, start_at, end_at, location, attendees, online) VALUES
        ('outlook', 'E1', 'Weekly Tim Produk', now() + interval '20 minutes', now() + interval '80 minutes', 'R. Rapat 3', '["Sari", "Dimas", "Ayu"]', false)""")
    if "rapat" in ROUTES:
        await p.execute("""INSERT INTO meetings (title, confidential, consent, status, chunks, started_at, live) VALUES ('Weekly Tim Produk', false, true, 'recording', 7, now() - interval '7 minutes 12 seconds',
            '{"transcript": [{"n": 4, "text": "Oke, untuk rilis versi dua kita sepakat hari Jumat ya, QA selesai Kamis sore."}, {"n": 5, "text": "Mas Ilham tolong kirim timeline revisi ke Dimas besok pagi."}, {"n": 6, "text": "Ayu siapkan materi demo untuk klien minggu depan."}],
              "keputusan": ["Rilis versi 2 hari Jumat; QA selesai Kamis sore"], "tugas": [{"siapa": "Ilham", "apa": "kirim timeline revisi ke Dimas", "kapan": "besok pagi", "pemilik": true}, {"siapa": "Ayu", "apa": "siapkan materi demo klien", "kapan": "minggu depan", "pemilik": false}], "topik": "rilis v2"}')""")
    if {"bisnis", "tren", "peluang", "sumber"} & {r.split("?")[0].split("/")[0] for r in ROUTES}:
        await seed_bisnis(p)
    if {"gaji", "invest", "kopi"} & {r.split("?")[0].split("/")[0] for r in ROUTES}:
        await seed_money(p)
    await db.close()
    return token


async def seed_money(p):
    """A pay period half spent (pots, one near its limit), a proposed allocation, a Pluang reading with three options, a coffee offer."""
    await p.execute("""INSERT INTO settings_kv (key, value) VALUES ('app:money', $1), ('app:coffee', $2)""",
                    {"salary": 15_000_000, "payday": 25, "pots": [{"name": "Makan & kopi", "amount": 2_500_000, "categories": ["makan", "kopi"]},
                                                                  {"name": "Transport", "amount": 1_200_000, "categories": ["transport"]},
                                                                  {"name": "Tagihan", "amount": 1_800_000, "categories": ["tagihan"]},
                                                                  {"name": "Belanja rumah", "amount": 3_000_000, "categories": ["belanja", "anak & keluarga"]}]},
                    {"usual": "Kopi Kenangan Mantan", "sugar": "less sugar", "max_price": 75000, "pickup": True, "outlet": "Sudirman", "enabled": True, "apps": ["kopikenangan", "qpon"]})
    rows = [("Kopi Kenangan", "kopi", 28000, "GoPay"), ("GoFood · Bakso Pak Kumis", "makan", 46000, "GoPay"), ("GoRide", "transport", 17000, "GoPay"),
            ("KRL Commuter", "transport", 5000, "GoPay"), ("Indomaret", "belanja", 182500, "BCA"), ("PLN Prabayar", "tagihan", 500000, "BCA"),
            ("Solaria", "makan", 87000, "GoPay"), ("Tokopedia", "belanja", 349000, "GoPay"), ("Kopi Kenangan", "kopi", 18000, "GoPay")]
    for d in range(0, 5):
        for i, (m, c, a, app) in enumerate(rows):
            await p.execute("INSERT INTO money_tx (at, amount, direction, merchant, category, source, app) VALUES (now() - make_interval(days => $1, hours => $2), $3, 'out', $4, $5, 'notif', $6)",
                            d, i, a * (1 + d % 3 * 0.2), m, c, app)
    await p.execute("INSERT INTO money_tx (at, amount, direction, merchant, category, source, app) VALUES (now() - interval '1 day', 1250000, 'out', 'Rumah Makan Padang (keluarga)', 'makan', 'notif', 'BCA')")
    await p.execute("""INSERT INTO money_plans (period_start, data) VALUES (current_date + 26, '{"ringkasan": "Makan & kopi membengkak 18%; tabungan dinaikkan ke 20% dengan memangkas belanja online.", "lane": "berat", "salary": 15000000, "total": 15000000,
        "pos": [{"name": "Zakat & sedekah", "amount": 375000, "categories": ["zakat & sedekah"], "alasan": "2,5% gaji"}, {"name": "Tagihan", "amount": 1800000, "categories": ["tagihan"], "alasan": "PLN, internet, BPJS"},
                {"name": "Tabungan & dana darurat", "amount": 3000000, "categories": [], "alasan": "20% gaji"}, {"name": "Investasi (Pluang)", "amount": 1500000, "categories": ["investasi"], "alasan": "rutin bulanan"},
                {"name": "Makan & kopi", "amount": 2600000, "categories": ["makan", "kopi"], "alasan": "realistis dari 3 bulan"}, {"name": "Transport", "amount": 1100000, "categories": ["transport"], "alasan": "KRL + GoRide"},
                {"name": "Belanja rumah & anak", "amount": 3125000, "categories": ["belanja", "anak & keluarga"], "alasan": ""}, {"name": "Lain-lain", "amount": 1500000, "categories": ["lainnya", "hiburan", "kesehatan"], "alasan": ""}],
        "hemat": ["Masak/bekal 2× seminggu menghemat ±Rp400 rb", "Kopi pakai promo saja (rata-rata Rp18 rb, bukan Rp28 rb)"]}')""")
    sid = await p.fetchval("""INSERT INTO invest_snapshots (data) VALUES ('{"total": 48250000, "kas": 1250000, "aset": [
        {"nama": "Emas", "kode": "", "jenis": "emas", "jumlah": 14.2, "nilai": 23430000, "untung_pct": 12.4, "harga": 1650000},
        {"nama": "Apple", "kode": "AAPL", "jenis": "saham_as", "jumlah": 3.1, "nilai": 11200000, "untung_pct": 6.1, "harga": 3612000},
        {"nama": "Bitcoin", "kode": "BTC", "jenis": "kripto", "jumlah": 0.0072, "nilai": 9870000, "untung_pct": -4.3, "harga": 1370000000},
        {"nama": "Reksa Dana Pasar Uang", "kode": "", "jenis": "reksa_dana", "jumlah": 0, "nilai": 2500000, "untung_pct": 1.9, "harga": 0}]}') RETURNING id""")
    await p.execute("""INSERT INTO settings_kv (key, value) VALUES ('app:invest', '{"targets": {"emas": 40, "saham_as": 30, "kripto": 15, "reksa_dana": 15}}')""")
    await p.execute("""INSERT INTO invest_proposals (snapshot_id, data) VALUES ($1, '{"ringkasan": "Emas sudah 50% portofolio (target 40%) setelah naik 4% sebulan; Bitcoin turun 4% dan masih di bawah target 15%. Rupiah melemah 0,8%.",
        "lane": "berat", "kondisi": ["Emas di atas target alokasi", "Bitcoin terkoreksi 4% sepekan", "S&P 500 naik 1,2% sebulan"],
        "opsi": [{"id": "A", "judul": "Seimbangkan: tambah reksa dana & Bitcoin", "aksi": [{"jenis": "beli", "aset": "Reksa Dana Pasar Uang", "nominal": 1000000}, {"jenis": "beli", "aset": "Bitcoin", "nominal": 500000}], "alasan": "Mendekatkan ke target tanpa menjual emas yang sedang naik.", "risiko": "Bitcoin bisa turun lagi"},
                 {"id": "B", "judul": "Ambil untung emas Rp2 jt", "aksi": [{"jenis": "jual", "aset": "Emas", "nominal": 2000000}], "alasan": "Untung 12,4%; kembalikan ke target 40%.", "risiko": "Emas bisa lanjut naik"},
                 {"id": "C", "judul": "Tahan dulu", "aksi": [], "alasan": "Tidak ada transaksi minggu ini.", "risiko": ""}]}')""", sid)
    await p.execute("""INSERT INTO coffee_offers (status, promos, trigger) VALUES ('offered', '[
        {"app": "kopikenangan", "label": "Kopi Kenangan", "menu": "Kopi Kenangan Mantan", "merchant": "Kopi Kenangan", "harga": 18000, "harga_normal": 28000, "hemat_pct": 36, "voucher": "MANTAN18", "syarat": "hari ini s/d 17.00"},
        {"app": "qpon", "label": "Qpon", "menu": "Es Kopi Susu Gula Aren", "merchant": "Janji Jiwa", "harga": 15000, "harga_normal": 24000, "hemat_pct": 38, "voucher": "", "syarat": "kupon, ambil di outlet"},
        {"app": "kopikenangan", "label": "Kopi Kenangan", "menu": "Americano", "merchant": "Kopi Kenangan", "harga": 22000, "harga_normal": 25000, "hemat_pct": 12, "voucher": "", "syarat": ""}]', 'habit')""")


async def seed_bisnis(p):
    """Two businesses with four months of numbers, today so far, sales per marketplace, an alert, a strategy and a research batch."""
    import random
    from datetime import date, timedelta
    rnd = random.Random(7)
    eps = '[{"metric": "penjualan", "path": "/v1/orders", "items": "data.orders", "value": "total", "agg": "sum", "mode": "today", "split": "marketplace"}, {"metric": "pesanan", "path": "/v1/orders", "agg": "count", "mode": "today"}, {"metric": "dikemas", "path": "/v1/orders", "filter": "status=packed", "agg": "count", "mode": "today"}, {"metric": "pencairan", "path": "/v1/payouts", "agg": "value", "mode": "today"}]'
    for b, base, url in (("Renature", 4_200_000, "https://api.renature.id"), ("Autotoko", 11_500_000, "https://api.autotoko.id")):
        sid = await p.fetchval("INSERT INTO biz_sources (business, name, base_url, auth, endpoints, last_poll, last_ok, backfilled) VALUES ($1, $2, $3, $4, $5, now(), now() - interval '4 minutes', now()) RETURNING id",
                               b, f"{b} API", url, {"type": "header", "name": "X-API-Key"}, json.loads(eps))
        today = date.today()
        for i in range(1, 125):
            d = today - timedelta(days=i)
            v = base * (1 + 0.25 * (d.weekday() == 5) - 0.15 * (d.weekday() == 6)) * (0.85 + i / 600) * rnd.uniform(0.8, 1.2)
            await p.execute("INSERT INTO biz_daily (business, metric, day, value, unit, source_id) VALUES ($1, 'penjualan', $2, $3, 'rp', $4), ($1, 'pesanan', $2, $5, 'n', $4)", b, d, round(v), sid, round(v / 110_000))
        sales = base * 0.62
        for m, v, u in (("penjualan", sales, "rp"), ("pesanan", round(sales / 110_000), "n"), ("dikemas", round(sales / 110_000 * 0.74), "n"), ("pencairan", base * 0.5, "rp"),
                        ("penjualan@Shopee", sales * 0.46, "rp"), ("penjualan@TikTok Shop", sales * 0.31, "rp"), ("penjualan@Tokopedia", sales * 0.18, "rp"), ("penjualan@Website", sales * 0.05, "rp")):
            await p.execute("INSERT INTO biz_daily (business, metric, day, value, unit, source_id) VALUES ($1, $2, $3, $4, $5, $6)", b, m, today, round(v), u, sid)
        if b == "Autotoko":
            await p.execute("INSERT INTO biz_daily (business, metric, day, value, unit, source_id) VALUES ($1, 'mrr', $2, 48500000, 'rp', $3), ($1, 'toko_aktif', $2, 312, 'n', $3)", b, today, sid)
    await p.execute("""INSERT INTO biz_insights (kind, business, key, data) VALUES ('alert', 'Renature', 'unpacked:Renature:x',
        '{"tone": "amber", "title": "Renature: 6 pesanan belum dikemas", "text": "18 dari 24 pesanan sudah dikemas. Kejar sebelum kurir pick-up."}')""")
    await p.execute("""INSERT INTO biz_insights (kind, business, data) VALUES ('strategy', 'Renature', '{"ringkasan": "Penjualan 30 hari naik 6% didorong TikTok Shop, tapi Minggu selalu turun ±15%. Rata-rata pesanan masih Rp110 rb.", "lane": "berat",
        "minggu_ini": ["Live TikTok Sabtu 19.00 dengan bundling inhaler + mouth spray", "Voucher Minggu khusus pembeli ulang", "Naikkan iklan Shopee untuk inhaler eukaliptus"],
        "strategi": [{"judul": "Bundling inhaler + mouth spray", "kenapa": "Rata-rata pesanan Rp110 rb; bundling mendorong ke Rp150 rb", "langkah": ["Buat paket 2+1", "Pasang di semua kanal lewat Autotoko"], "dampak": "+8–12% omzet", "usaha": "rendah", "ukur": "AOV ≥ Rp140 rb"}],
        "risiko": ["Stok mouth spray menipis"]}')""")
    await p.execute("""INSERT INTO biz_insights (kind, data) VALUES ('opportunity', '{"peluang": [
        {"judul": "Aromaterapi roll-on untuk pekerja kantor", "ringkasan": "Pencarian roll-on aromaterapi naik 40% dalam 3 bulan; cocok dengan rantai pasok Renature.", "kenapa_sekarang": "Tren self-care & musim hujan", "modal": "Rp15–25 jt", "potensi": "Rp20–40 jt/bln", "cocok": "Bahan & maklon sama dengan inhaler; jual lewat Autotoko", "skor": 8, "langkah_pertama": "Uji 100 pcs di TikTok Shop", "sumber": ["https://trends.google.com/trends/explore?q=roll%20on%20aromaterapi"]},
        {"judul": "Modul Autotoko untuk reseller herbal", "ringkasan": "Paket SaaS khusus brand herbal kecil: katalog BPOM, stok multi-gudang.", "kenapa_sekarang": "Banyak UMKM herbal pindah ke marketplace", "modal": "Rp5 jt (pengembangan)", "potensi": "30 toko × Rp299 rb", "cocok": "Memakai Autotoko yang sudah ada", "skor": 7, "langkah_pertama": "Wawancara 5 penjual herbal", "sumber": []}]}')""")


async def cdp(ws, method, params=None, _id=[0]):
    _id[0] += 1
    mid = _id[0]
    await ws.send(json.dumps({"id": mid, "method": method, "params": params or {}}))
    while True:
        m = json.loads(await ws.recv())
        if m.get("id") == mid:
            if "error" in m:
                raise RuntimeError(f"{method}: {m['error']}")
            return m.get("result", {})


async def main():
    token = await seed()
    ip = socket.gethostbyname("chrome")
    core = socket.gethostbyname("core")
    async with httpx.AsyncClient() as c:
        t = (await c.put(f"http://{ip}:9222/json/new?about:blank")).json()
    async with websockets.connect(t["webSocketDebuggerUrl"], max_size=50_000_000) as ws:
        await cdp(ws, "Page.enable")
        await cdp(ws, "Emulation.setDeviceMetricsOverride", {"width": W, "height": H, "deviceScaleFactor": 2, "mobile": W < 800})
        await cdp(ws, "Page.navigate", {"url": f"http://{core}:8000/app/#t={token}"})
        await asyncio.sleep(4)
        os.makedirs("/tmp/shots", exist_ok=True)
        for r in ROUTES:
            await cdp(ws, "Runtime.evaluate", {"expression": f"location.hash = '#/{r}'"})
            await asyncio.sleep(float(os.getenv("PREVIEW_WAIT", "2.5")))
            shot = await cdp(ws, "Page.captureScreenshot", {"format": "png", "captureBeyondViewport": False})
            name = r.replace("/", "_").replace("?", "_") or "beranda"
            with open(f"/tmp/shots/{name}.png", "wb") as f:
                f.write(base64.b64decode(shot["data"]))
            errs = await cdp(ws, "Runtime.evaluate", {"expression": "document.querySelector('#view')?.innerText.slice(0, 160)", "returnByValue": True})
            print(f"{r}: {str(errs.get('result', {}).get('value', ''))[:150]!r}")


asyncio.run(main())
