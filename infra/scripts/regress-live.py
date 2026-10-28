"""Run: docker exec -i -e PYTHONPATH=/srv jarvis-core python -u - < infra/scripts/regress-live.py
End-to-end regression on the LIVE server (read-mostly; every write is a test row removed at the end; nothing is sent outside)."""
import asyncio, base64, json, math, struct, time
import httpx, websockets
from app import db, devices
from app.config import settings

RES = []
def rec(phase, name, ok, detail=""):
    RES.append((phase, name, bool(ok), str(detail)[:160]))
    print(("PASS" if ok else "FAIL"), f"[{phase}]", name, ("— " + str(detail)[:160]) if detail else "", flush=True)

async def main():
    await db.connect(settings.database_url)
    dev, token = await devices.create("uji-regresi", "claude-test", scope="owner")
    basic, btoken = await devices.create("uji-regresi-basic", "claude-test", scope="basic")
    H, B = {"Authorization": f"Bearer {token}"}, {"Authorization": f"Bearer {btoken}"}
    A = {"X-Admin-Token": settings.admin_token}
    made = {"watchers": [], "tasks": []}
    try:
        async with httpx.AsyncClient(base_url="http://127.0.0.1:8000", timeout=60) as c:
            async def get(p, h=None, **kw): return await c.get(p, headers=h or {}, **kw)
            # ---- security: nothing opens without its key ----
            for p in ("/api/v1/canvases", "/api/v1/canvas/live", "/api/v1/voice", "/api/v1/console/server-usage"):
                r = await get(p); rec("keamanan", f"tanpa token ditolak: {p}", r.status_code in (401, 403, 404), r.status_code)
            for p in ("/admin/status", "/admin/inbox", "/admin/openjarvis", "/admin/voice", "/admin/companies", "/admin/approvals"):
                r = await get(p); rec("keamanan", f"admin tanpa token ditolak: {p}", r.status_code in (401, 403, 404), r.status_code)
                r = await get(p, A); rec("admin", f"admin dengan token: {p}", r.status_code == 200, r.status_code)
            r = await get("/llm/v1/models"); rec("keamanan", "gerbang LLM tanpa kunci ditolak", r.status_code in (401, 404), r.status_code)
            r = await c.get("/admin/status", headers={**A, "X-Forwarded-For": "1.2.3.4"}); rec("keamanan", "admin lewat proxy publik disembunyikan (404)", r.status_code == 404, r.status_code)
            r = await get("/api/v1/canvases", B); rec("keamanan", "perangkat dasar boleh melihat kanvas", r.status_code == 200, r.status_code)
            r = await c.post("/api/v1/canvases", headers=B, json={"context": "utama"}); rec("keamanan", "perangkat dasar TIDAK boleh mengubah kanvas", r.status_code == 403, r.status_code)
            r = await get("/api/v1/console/approvals", B); rec("keamanan", "perangkat dasar tidak masuk konsol pemilik", r.status_code == 403, r.status_code)
            # ---- core / chat (the hotfix regression: every chat turn used to fail) ----
            r = await c.post("/api/v1/chat", headers=H, json={"user_command": "Berapa 7 ditambah 5? Jawab angkanya saja.", "session_id": "uji-regresi-1"})
            rec("obrolan", "agen utama menjawab (self_model/hotfix)", r.status_code == 200 and "12" in r.text, r.text[:100])
            # ---- fase 3 voice ----
            r = await get("/api/v1/voice", H); j = r.json() if r.status_code == 200 else {}
            rec("fase3-suara", "setelan suara terbaca", r.status_code == 200 and "tts" in j, list(j)[:5])
            r = await get("/admin/voice", A); j = r.json() if r.status_code == 200 else {}
            rec("fase3-suara", "pelengkap suara + baseline terbaca", {"baseline", "complements"} <= set(j), list(j)[:6])
            # ---- fase 1 companies ----
            r = await get("/admin/companies", A); j = r.json() if r.status_code == 200 else {}
            rec("fase1-perusahaan", "daftar perusahaan (mock DGM)", r.status_code == 200 and "companies" in j, [x.get("id") for x in j.get("companies", [])])
            # ---- fase 4/5/7/8 canvas + desk ----
            ctxs = (await get("/api/v1/canvases", H)).json()
            rec("fase4-kanvas", "daftar galaksi", any(x["context"] == "utama" for x in ctxs), [x["context"] for x in ctxs])
            cv = (await c.post("/api/v1/canvases", headers=H, json={"context": "utama"})).json()
            v = (await get(f"/api/v1/canvases/{cv['id']}", H)).json()
            rec("fase4-kanvas", "galaksi utama terbaca (kartu + rasi)", len(v["constellations"]) >= 6 and "cards" in v, f"{len(v['cards'])} kartu")
            company = next((x["context"] for x in ctxs if x["context"].startswith("company:")), None)
            if company:
                vc = (await get(f"/api/v1/canvases/{(await c.post('/api/v1/canvases', headers=H, json={'context': company})).json()['id']}", H)).json()
                refs = {k["ref"].split(":")[0] for k in vc["cards"]}
                rec("fase1-isolasi", "galaksi perusahaan tanpa data pribadi", not (refs & {"memory", "goal", "playlist", "music", "shown", "meeting"}), refs)
            live = (await get("/api/v1/canvas/live", H)).json()
            rec("fase7-meja", "meja hidup: stasiun + panel", {"stations", "n8n", "prompts", "storage"} <= set(live), list(live))
            rec("fase7-meja", "tangkapan layar tanpa token ditolak", (await get("/api/v1/canvas/live/1/frame")).status_code == 401)
            leak = [p for p in live["prompts"] if "OTP" in p["asked"] and any(ch.isdigit() for ch in p["asked"])]
            rec("fase7-meja", "permintaan sensitif disembunyikan", not leak, len(leak))
            for f in ("index.html", "app.js", "cad.js", "dock.js", "lib.js", "worklet.js", "gestures.js", "vendor/three.module.min.js"):
                r = await get(f"/canvas/{f}"); rec("fase8-halaman", f"aset {f}", r.status_code == 200 and "content-security-policy" in r.headers, r.status_code)
            r = await c.get("/", follow_redirects=False); rec("fase8-halaman", "/ membuka meja", r.status_code in (302, 307) and r.headers.get("location") == "/canvas/")
            r = await c.get("/canvas/../main.py"); rec("keamanan", "path traversal di penampil ditolak", r.status_code in (404, 400))
            # ---- websocket: wrong token refused, right token chats with a frame ----
            try:
                async with websockets.connect("ws://127.0.0.1:8000/ws") as ws:
                    await ws.send(json.dumps({"type": "auth", "token": "salah"}))
                    msgs = []
                    try:
                        while True: msgs.append(json.loads(await asyncio.wait_for(ws.recv(), 3)))
                    except Exception: pass
                    rec("keamanan", "WebSocket token salah ditolak", any(m.get("type") == "error" for m in msgs), msgs[:1])
            except Exception as e: rec("keamanan", "WebSocket token salah ditolak", True, type(e).__name__)
            async with websockets.connect("ws://127.0.0.1:8000/ws", max_size=2**24) as ws:
                await ws.send(json.dumps({"type": "auth", "token": token}))
                ok_auth = json.loads(await asyncio.wait_for(ws.recv(), 5)).get("type") == "auth_ok"
                rec("fase8-panel", "WebSocket auth pesan pertama", ok_auth)
                pcm = struct.pack("<%dh" % 32000, *[int(0.35 * 32767 * math.sin(2 * math.pi * 220 * i / 16000)) for i in range(32000)])
                await ws.send(json.dumps({"type": "utterance", "audio": base64.b64encode(pcm).decode(), "seq": 1, "session_id": "uji-regresi-2"}))
                t0, got = time.time(), []
                while time.time() - t0 < 20 and not any(m.get("type") == "reply" for m in got):
                    try: got.append(json.loads(await asyncio.wait_for(ws.recv(), 3)))
                    except asyncio.TimeoutError: pass
                rec("fase3-suara", "ucapan → transkrip → balasan diam (jalur dengar)", any(m.get("type") == "transcript" for m in got) and any(m.get("type") == "reply" for m in got), [m.get("type") for m in got])
            # ---- fase 6 inbox + watchers (nothing leaves the server) ----
            st = (await get("/admin/inbox", A)).json()
            rec("fase6-inbox", "status inbox + 3 alur n8n", len(st["flows"]) == 3, [(f["kind"], f["installed"]) for f in st["flows"]])
            rec("fase6-inbox", "pemeriksaan otomatis mati secara bawaan", st["auto"] is False)
            r = await c.post("/admin/watchers", headers=A, json={"kind": "kripto", "label": "UJI Bitcoin", "query": "bitcoin", "op": "<=", "threshold": 1000})
            w = r.json(); made["watchers"].append(w.get("id"))
            rec("fase6-pantau", "pantauan kripto bisa dibuat (≥ 15 menit)", r.status_code == 200 and w.get("every_min", 0) >= 15, w.get("every_min"))
            r = await c.post("/admin/watchers", headers=A, json={"kind": "kripto", "label": "x", "query": "Bitcoin; DROP", "op": "<=", "threshold": 1}); rec("fase6-pantau", "query berbahaya ditolak", r.status_code == 400, r.status_code)
            from app import watchers
            val = await watchers._coingecko("bitcoin"); rec("fase6-pantau", "CoinGecko menjawab (harga kripto)", val is not None and val > 0, val)
            sent = await db.pool().fetchval("SELECT count(*) FROM outbox WHERE status = 'sent'"); rec("fase6-inbox", "tidak ada email/acara terkirim sendiri", sent == 0, sent)
            # ---- fase 2 openjarvis ----
            oj = (await get("/admin/openjarvis", A)).json()
            rec("fase2-openjarvis", "kontainer menjawab, mati secara bawaan", oj["reachable"] and oj["configured"] and oj["enabled"] is False, oj["enabled"])
            # ---- workers, reports, budget ----
            rep = await db.pool().fetchval("SELECT count(*) FROM reports WHERE attempts > 2 AND created_at > greatest(now() - interval '6 hours', timestamptz '2026-10-26 01:00+00')"); rec("laporan", "tidak ada laporan yang diulang (>2x; 2 = HP + meja web yang membacakannya masing-masing sekali)", rep == 0, rep)
            unheard = await db.pool().fetchval("SELECT count(*) FROM reports WHERE status = 'unheard' AND created_at > greatest(now() - interval '6 hours', timestamptz '2026-10-26 01:00+00')"); rec("laporan", "tidak ada status 'tak terdengar' baru", unheard == 0, unheard)
            stuck = await db.pool().fetchval("SELECT count(*) FROM tasks WHERE status IN ('running','queued') AND coalesce(started_at, created_at) < now() - interval '2 hours'"); rec("pekerja", "tidak ada tugas macet >2 jam", stuck == 0, stuck)
            b = (await get("/admin/status", A)).json() if False else None
            spent = float(await db.pool().fetchval("SELECT coalesce(sum(cost_usd),0) FROM llm_usage WHERE at >= date_trunc('month', now())")); rec("anggaran", "pengeluaran AI bulan ini < $20", spent < 20, f"${spent:.2f}")
            sp = float(await db.pool().fetchval("SELECT coalesce(sum(cost_usd),0) FROM llm_usage WHERE category = 'spike'")); rec("anggaran", "uji OpenJarvis ≤ $1", sp <= 1.0, f"${sp:.2f}")
            errs = await db.pool().fetch("SELECT left(message,60) m, count(*) FROM error_log WHERE at > now() - interval '3 hours' GROUP BY 1 ORDER BY 2 DESC LIMIT 5")
            rec("log-error", "error_log 3 jam terakhir", True, [(e["m"], e["count"]) for e in errs])
            # ---- isolation on the live DB role (RLS) ----
            n = await db.pool().fetchval("SELECT count(*) FROM canvas_nodes WHERE company_id IS NOT NULL"); rec("fase1-isolasi", "RLS: tanpa lingkup perusahaan, baris perusahaan tak terlihat", n == 0, n)
            n = await db.pool().fetchval("SELECT count(*) FROM company_vault"); rec("fase1-isolasi", "RLS: brankas perusahaan tak terlihat tanpa lingkup", n == 0, n)
            # ---- infra reachability ----
            for name, url in (("Hermes", "http://jarvis-brain:8642/health"), ("OpenJarvis", "http://jarvis-openjarvis:8765/health"), ("Browser bersama", "http://jarvis-browser-gw:9222/json/version"),
                              ("n8n", f"{settings.n8n_url}/healthz"), ("Qdrant", "http://qdrant:6333/healthz")):
                try: r = await c.get(url, timeout=8); rec("infra", f"{name} menjawab", r.status_code == 200, r.status_code)
                except Exception as e: rec("infra", f"{name} menjawab", False, type(e).__name__)
    finally:
        for wid in made["watchers"]:
            if wid: await db.pool().execute("DELETE FROM watchers WHERE id = $1", wid)
        await db.pool().execute("DELETE FROM devices WHERE id = ANY($1::uuid[])", [dev["id"], basic["id"]])
        await db.pool().execute("DELETE FROM messages WHERE session_id LIKE 'uji-regresi-%'")
    bad = [r for r in RES if not r[2]]
    print(f"\nRINGKAS: {len(RES) - len(bad)}/{len(RES)} lulus", flush=True)
    for r in bad: print("GAGAL:", r[0], r[1], r[3])
asyncio.run(main())
