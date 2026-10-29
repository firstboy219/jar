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
