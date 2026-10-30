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
    if {"musik", "video", "berkas", "dongeng", "ukur", "bimbing"} & {r.split("?")[0].split("/")[0] for r in ROUTES}:
        await seed_media(p)
    if {"alur", "bengkel"} & {r.split("?")[0].split("/")[0] for r in ROUTES}:
        await seed_flow(p)
    if {"karier"} & {r.split("?")[0].split("/")[0] for r in ROUTES}:
        await seed_jobs(p)
    await db.close()
    return token


async def seed_jobs(p):
    """The job hunt mid-week: scored postings, applications at every stage, an invitation answered inside its undo window."""
    await p.execute("INSERT INTO settings_kv (key, value) VALUES ('app:jobs', $1)", {"roles": ["Product Manager", "Business Analyst"], "locations": ["Jakarta Raya"], "min_salary": 18000000,
                    "min_match": 80, "auto_apply": True, "max_per_day": 5, "auto_reply_invites": True, "undo_min": 5, "profile": "8 tahun produk & analitik e-commerce; pendiri SaaS Autotoko", "times": ["07:00", "19:00"]})
    posts = [("95600001", "Senior Product Manager — Marketplace", "PT Toko Nusantara Digital", "Jakarta Selatan", "Rp 28.000.000 – Rp 35.000.000", 92, ["8 th produk e-commerce", "SQL & analitik", "pengalaman marketplace"], ["OKR enterprise"], "scored"),
             ("95600002", "Business Analyst Lead", "PT Bank Contoh Tbk", "Jakarta Pusat", "", 84, ["analisis proses", "stakeholder"], ["sertifikasi CBAP"], "scored"),
             ("95600003", "Product Manager (Fintech)", "Dompet Kita", "Jakarta Barat (Hybrid)", "Rp 25 jt – 32 jt", 81, ["produk pembayaran", "data"], ["regulasi OJK"], "scored"),
             ("95600010", "Head of Product", "Sayur Segar Group", "Jakarta Selatan", "", 90, [], [], "applied"),
             ("95600011", "Product Owner", "PT Logistik Cepat", "Jakarta Utara", "", 86, [], [], "applied"),
             ("95600012", "Product Analyst", "PT Media Kreatif", "Jakarta", "", 82, [], [], "applied")]
    for pid, t, c, loc, sal, sc, ok, gap, st in posts:
        await p.execute("INSERT INTO job_posts (id, title, company, location, salary, score, score_data, status, url, listed_at, questions, arrangement) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, now() - interval '1 day', $10, 'Hybrid')",
                        pid, t, c, loc, sal, sc, {"cocok": ok, "kurang": gap, "alasan": "pengalaman e-commerce & SaaS-mu sangat relevan"}, st, f"https://id.jobstreet.com/id/job/{pid}",
                        ["Berapa tahun pengalaman Anda sebagai Product Manager?", "Berapa ekspektasi gaji bulanan Anda?"] if pid == "95600001" else [])
    a1 = await p.fetchval("""INSERT INTO job_applications (post_id, status, via, applied_at, events, cover_letter) VALUES ('95600010', 'interview', 'jarvis', now() - interval '3 days', $1, 'Dengan hormat, …') RETURNING id""",
                          [{"at": "2026-10-27T01:00:00+00:00", "kind": "terkirim", "text": "Lamaran terkirim lewat Lamar Cepat"}, {"at": "2026-10-29T03:00:00+00:00", "kind": "undangan", "text": "email dari HR Sayur Segar: Undangan Interview User"}])
    await p.execute("""INSERT INTO job_applications (post_id, status, via, applied_at, events) VALUES ('95600011', 'viewed', 'jarvis', now() - interval '2 days', '[]'), ('95600012', 'applied', 'owner', now() - interval '1 day', '[]')""")
    iid = await p.fetchval("INSERT INTO inbox_items (source, ext_id, sender, subject, snippet, received_at) VALUES ('outlook', 'X1', 'HR Sayur Segar', 'Undangan Interview User — Head of Product', 'Kami mengundang…', now()) RETURNING id")
    await p.execute("""INSERT INTO job_replies (application_id, inbox_item_id, body, proposal, send_at, status) VALUES ($1, $2, $3, $4, now() + interval '3 minutes 40 seconds', 'pending')""",
                    a1, iid, "Yth. Tim HR Sayur Segar,\n\nTerima kasih atas undangannya. Saya bersedia hadir pada Selasa, 3 November pukul 10.00 WIB.\n\nSalam,\nIlham",
                    {"accept": "2026-11-03T10:00", "slots": [], "summary": "Menerima Selasa 3 Nov 10.00 — kalender kosong", "location": "Kantor Sayur Segar, Kemang", "online": False})


async def seed_flow(p):
    """A day of the master flow: fixed procedures, light and heavy brain jobs, Hermes missions, one running now, a brain version on test."""
    import random
    rnd = random.Random(3)
    jobs = [("bisnis", "sinkron", "skill", 0.99), ("inbox", "sync", "skill", 1.0), ("inbox", "triage", "ringan", 0.93), ("inbox", "draf", "ringan", 0.9),
            ("sholat", "pengingat", "skill", 1.0), ("brief", "compose", "ringan", 0.95), ("bisnis", "strategi", "berat", 0.9), ("rekap", "compose", "ringan", 1.0),
            ("kopi", "cek-promo-kopikenangan", "hermes", 0.8), ("uang", "catat", "skill", 1.0), ("rapat", "catat-langsung", "ringan", 0.92), ("invest", "analisa", "berat", 1.0)]
    vid = await p.fetchval("INSERT INTO brain_versions (job, config, request, note, status, canary_pct, activated_at) VALUES ('inbox:draf', $1, 'selalu sebut tenggat di kalimat pertama dan lebih singkat', 'Permintaan pemilik: tenggat disebut di awal.', 'canary', 10, now() - interval '3 hours') RETURNING id",
                           {"lane": "auto", "instruction": "Selalu sebut tenggat di kalimat pertama. Maksimal 5 kalimat."})
    for h in range(0, 24 * 3):
        for f, a, lane, okp in jobs:
            if rnd.random() > (0.9 if lane == "skill" else 0.35):
                continue
            ok = rnd.random() < okp
            secs = {"skill": 0.4, "ringan": 4.5, "berat": 14, "hermes": 70}[lane] * rnd.uniform(0.6, 1.6)
            steps = [{"at": "2026-10-30T06:00:00+00:00", "stage": "router", "text": f"dikenali sebagai {f}:{a}"},
                     {"at": "2026-10-30T06:00:01+00:00", "stage": "hermes", "text": {"skill": "skill tanpa AI — ada cara tetap: tanpa AI", "ringan": "otak ringan — cukup otak ringan",
                                                                                      "berat": "otak berat — butuh pertimbangan/analisa: otak berat", "hermes": "Hermes + alat — aplikasi HP"}[lane]},
                     {"at": "2026-10-30T06:00:05+00:00", "stage": "selesai" if ok else "gagal", "text": "selesai" if ok else "AI tidak menjawab"}]
            await p.execute("""INSERT INTO flow_runs (feature, action, goal, trigger, lane, why, status, steps, cost_usd, model, error, started_at, finished_at, brain_version)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, now() - make_interval(hours => $12), now() - make_interval(hours => $12) + make_interval(secs => $13), $14)""",
                f, a, f"{f} {a}", "schedule" if lane == "skill" else "owner", lane, steps[1]["text"], "done" if ok else "failed", steps,
                0 if lane == "skill" else round(secs * 0.0004, 5), None if lane == "skill" else ("deepseek-v4-flash" if lane == "ringan" else "deepseek-v4-pro"),
                None if ok else "AI tidak menjawab", h + rnd.random(), secs, vid if (f, a) == ("inbox", "draf") and rnd.random() < 0.1 else None)
    await p.execute("""INSERT INTO flow_runs (feature, action, goal, trigger, lane, why, status, steps, started_at) VALUES
        ('bisnis', 'peluang', 'riset peluang bisnis online baru', 'schedule', 'hermes', 'butuh alat (browser/dokumen/HP): Hermes yang mengerjakan', 'waiting',
         '[{"at": "2026-10-30T06:00:00+00:00", "stage": "router", "text": "dikenali sebagai bisnis:peluang"}, {"at": "2026-10-30T06:00:01+00:00", "stage": "lane", "text": "membuka Google Trends…"}]', now() - interval '2 minutes'),
        ('brief', 'compose', 'tulis brief pagi', 'schedule', 'ringan', 'cukup otak ringan', 'running', '[{"at": "2026-10-30T06:00:00+00:00", "stage": "hermes", "text": "otak ringan — cukup otak ringan"}]', now() - interval '6 seconds')""")
    await p.execute("INSERT INTO flow_samples (run_id, feature, action, messages) SELECT id, feature, action, '[{\"role\": \"user\", \"content\": \"x\"}]' FROM flow_runs WHERE feature = 'inbox' AND action = 'draf' LIMIT 6")


async def seed_media(p):
    """What wave 6 screens show: music played (the usual mood), a summarised video, files made, a story, measurements, a guidance session."""
    from datetime import datetime
    from app import home
    from app.location import WIB
    now = datetime.now(WIB)
    for i, (mood, title) in enumerate([("semangat", "Bangkit — Rizky Febian"), ("semangat", "Laskar Pelangi — Nidji"), ("fokus", "Lofi Hujan Jakarta — Kopi Senja")]):
        await p.execute("INSERT INTO media_log (kind, mood, query, title, slot, weekday, at) VALUES ('music', $1, $1, $2, $3, $4, now() - make_interval(days => $5))",
                        mood, title, home.slot_of(now), now.weekday(), i)
    await p.execute("""INSERT INTO video_notes (video_id, title, channel, duration_s, lang, transcript, source, summary) VALUES ('SfLhKxznVQI', 'Resep Es Kopi Susu Gula Aren | Ide Jualan', 'KitchenDaily', 260, 'id',
        '[{"t": 0, "text": "Halo semua"}]', 'phone', '{"ringkasan": "Cara membuat es kopi susu gula aren botolan untuk jualan: takaran espresso, susu, dan gula aren, serta hitungan modal per botol (±Rp6.500).", "lane": "ringan",
        "poin": ["Espresso 30 ml per botol", "Gula aren cair 25 ml", "Susu UHT full cream 150 ml", "Botol 250 ml, tahan 3 hari di kulkas"], "untuk_siapa": "Cocok kalau mau jualan minuman dari rumah",
        "bab": [{"t": 0, "judul": "Pembuka & bahan"}, {"t": 38, "judul": "Membuat gula aren cair"}, {"t": 104, "judul": "Racikan per botol"}, {"t": 196, "judul": "Hitung modal & harga jual"}]}')""")
    await p.execute("INSERT INTO stories (title, theme, data) VALUES ('Kancil dan Bintang yang Hilang', 'hewan', $1)", {"menit": 5, "lane": "ringan",
        "pesan": "Menolong teman membuat hati kita terang.",
        "paragraf": ["Di tepi hutan yang sejuk, hiduplah seekor kancil kecil bernama Cilo. Setiap malam, Cilo suka berbaring di atas rumput sambil menghitung bintang. Satu, dua, tiga…",
                     "Suatu malam, Cilo melihat ada satu bintang yang hilang dari tempatnya. “Ke mana ya bintang kecil itu?” bisik Cilo.",
                     "Krek-krek… terdengar suara dari semak. Ternyata itu Kunang, si kunang-kunang yang tersesat dan menangis karena tidak bisa pulang.",
                     "Cilo tersenyum. “Ayo, aku antar pulang,” katanya lembut. Mereka berjalan pelan menyusuri sungai sampai tiba di pohon besar tempat keluarga Kunang tinggal."]})
    await p.execute("""INSERT INTO measures (label, kind, data) VALUES ('Lebar meja kerja', 'ar', '{"segmen": [1.42, 0.68], "total": 2.1, "unit": "m"}'),
        ('Dinding ruang tamu', 'ar', '{"segmen": [4.2], "total": 4.2, "tinggi": 2.9, "luas": 12.2, "unit": "m"}'),
        ('Depan rumah tetangga', 'foto', '{"objek": "rumah 2 lantai", "ukuran": {"lebar": {"perkiraan": 8.5, "min": 7.5, "max": 9.5}, "tinggi": {"perkiraan": 6.8, "min": 6.0, "max": 7.5}}, "acuan": ["pintu", "motor di carport"], "yakin": "sedang", "catatan": "Dua lantai ≈ 3 m per lantai + atap."}')""")
    await p.execute("INSERT INTO guide_sessions (goal, status, steps) VALUES ('aktifkan notifikasi tagihan di BCA mobile', 'active', $1)", [
        {"n": 1, "instruksi": "Ketuk ikon profil di kanan atas", "target": "Akun", "posisi": "kanan atas", "status": "lanjut", "lane": "ringan"},
        {"n": 2, "instruksi": "Pilih “Pengaturan Notifikasi”", "target": "Pengaturan Notifikasi", "posisi": "tengah", "status": "lanjut", "lane": "ringan"}])


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
