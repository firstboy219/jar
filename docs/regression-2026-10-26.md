# End-to-end regression — 2026-10-26 (main 1deb053, APK 0.17.0)

Run after Blueprint v4 Fase 0–8 were deployed. Script: `infra/scripts/regress-live.py` (read-mostly: its test rows — two temporary devices, one
watcher, a few chat messages — are removed at the end; nothing is sent outside; the only real calls are one chat turn to the main agent, one
public CoinGecko price request and the utterance round trip).

| Suite | Result |
|---|---|
| Server (pytest, fresh Postgres + Qdrant) | 203 passed |
| Canvas JS (node --test) | 13 passed |
| Android (unit + Paparazzi snapshots + assembleDebug) | passed |
| Live server, 64 checks | 64 / 64 after scoping one criterion (below) |

Live checks by area: security (every new endpoint refuses no/low tokens; admin hidden behind the proxy; wrong WebSocket token refused; viewer
path traversal refused; basic devices read but never change the canvas), the main agent answering after the STT-engine hotfix, voice (settings,
complements, utterance → transcript → reply), companies (mock DGM) and isolation (RLS: company rows invisible without a scope; the company galaxy
holds no personal data), canvas + desk (galaxies, live stations/panels, frames need a token, sensitive requests hidden, every viewer asset
served with a CSP, `/` opens the desk), inbox + watchers (three flows present, periodic check off, bad watcher query refused, CoinGecko
answers, nothing sent), OpenJarvis (up, off), reports (no repeats, nothing "unheard" after the fix), tasks (none stuck), budget ($2.63 of $20 this
month; the spike spent $0.75 of its $1), infrastructure reachability (Hermes, OpenJarvis, the shared browser, n8n, llama, Qdrant).

The first run showed 62/64: three reports and two "unheard" marks in the last 6 hours. All five were created on 2026-10-25 between 23:44 and
23:47 UTC, before the "never repeat a report" fix was deployed (2026-10-26 ≈ 01:00 UTC). After it: 6 reports, 0 repeated, 0 unheard. The check
now only looks at reports created after the fix.

Not covered by this run (needs the owner or an outside account): hand gestures on a real device, the owner's own voice at the desk, screen sharing,
the APK on a phone, Gmail/Calendar with real Google credentials, a form-filling task on a real shop site.
