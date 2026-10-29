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
    await db.close()
    return token


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
