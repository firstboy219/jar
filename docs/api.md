# JARVIS core API (for the APK)

Base URL: `https://vis1.cosger.online`. Every call needs a device token, created in the web admin
(**Perangkat** tab, shown once) and sent as `Authorization: Bearer jdv_…`.

## WebSocket — `wss://vis1.cosger.online/ws` (FS-101 downstream)

Auth: the `Authorization` header on the upgrade request. Clients that cannot set headers may instead
send `{"type":"auth","token":"jdv_…"}` as the first frame (answered with `{"type":"auth_ok"}`).
A bad token gets `{"type":"error","message":"unauthorized"}` and close code **4401** — do not auto-reconnect on 4401.

Client → server
```json
{"user_command": "status", "session_id": "3f2c…",
 "location": {"lat": -6.1587, "lon": 106.9056, "accuracy_m": 15, "age_s": 3,
              "address": "Jl. Boulevard Raya, Kelapa Gading, Jakarta Utara"}}   // optional, owner opt-in
{"type": "ping"}
```
`session_id`: stable per conversation (Hermes keeps history per id). Max 128 chars; `user_command` max 8000.

Server → client (live "thought stream" while Hermes works, then the reply)
```json
{"type": "status",  "state": "thinking|executing|completed|failed", "session_id": "…"}
{"type": "thought", "text": "The user is asking…", "session_id": "…"}            // reasoning delta
{"type": "tool",    "id": "call_…", "name": "memory_search", "title": "Mencari di memori",
                    "label": "proyek autotoko", "emoji": "⚡", "status": "running|completed", "session_id": "…"}
{"type": "context", "source": "memory", "query": "proyek autotoko",
                    "items": [{"text": "…", "category": "project", "score": 0.82}], "session_id": "…"}
{"type": "delta",   "text": "Autotoko minggu…", "session_id": "…"}               // answer delta
{"type": "reply",   "text": "…full answer…", "route": "core|hermes|blocked|error", "session_id": "…"}
{"type": "error",   "message": "…", "session_id": "…"}
{"type": "pong"}
```
Background (any time, not tied to a command):
```json
{"type": "tasks", "items": [{"id": 4, "title": "…", "status": "running"}]}       // on connect
{"type": "task", "id": 4, "title": "Cek harga emas", "status": "queued|running|completed|failed|cancelled"}
{"type": "task_event", "task_id": 4, "event": {"type": "thought|tool|context", …}}  // worker's live thoughts
{"type": "report", "id": 9, "task_id": 4, "text": "…", "attempt": 1, "repeat": false} // say it, then report_spoken
{"type": "report_ack", "id": 9}  {"type": "report_unheard", "id": 9}
{"type": "announce", "text": "Ada WhatsApp dari Budi…"}                           // say once, no ack
{"type": "media", "caption": "…", "items": [{"kind": "image|video|link", "url": "https://…",
                  "title": "…", "thumbnail": "https://…|null", "source": "…"}]}
```
Client control messages:
```json
{"type": "report_spoken", "report_id": 9}   {"type": "ack", "report_id": 9}   {"type": "cancel_task", "task_id": 4}
{"type": "notification", "notification": {"app": "WhatsApp", "package": "com.whatsapp", "title": "…",
                                          "text": "…", "posted_at": 1792212345000}}
```
`user_command` may also carry `"screen": "<base64 JPEG>"` while the owner shares their screen.

### v0.7 additions
Send header `X-App-Caps: say,stage,utterance,brain` to receive the events below.
```json
// client → server
{"type": "utterance", "session_id": "…", "seq": 7, "audio": "<base64 PCM16 mono 16 kHz>",   // one VAD-cut utterance
 "location": {…}, "screen": "<jpeg>", "image_source": "screen|camera", "screen_text": "<text read on the phone>"}
{"type": "stage_event", "id": "<stage id>", "event": "closed|login_done|route_selected|draft_copied|draft_sent|paused",
 "detail": {"index": 1}}
// user_command may also carry "screen_text"
// server → client
{"type": "transcript", "seq": 7, "text": "…", "engine": "whisper|groq|deepgram", "confidence": 0.84, "is_owner": true}
{"type": "say", "text": "Oke, aku cek dulu ya.", "session_id": "…"}     // speak now, sentence by sentence
{"type": "reply", …, "spoken": true}                                        // already said via "say"
{"type": "stage", "id": "…", "panel": "music|audio|video|image|map|web|doc|text|draft|gallery|board", "mode": "show|update|close",
 "payload": {…}, "caption": "…"}
{"type": "brain_pulse", "ids": ["<memory id>"], "kind": "read|write", "labels": ["<memory text, ≤80 chars>"]}
{"type": "approval", "id": 12, "title": "…", "risk": "high"}
```

`reply` is authoritative (it may differ slightly from the concatenated deltas). Closing the socket
mid-turn cancels the agent run on the server.
Several commands may be in flight on one socket; match replies by `session_id`.
Fail-safe auto-reconnect (BRD §4): reconnect with exponential backoff (1 s → 30 s) on any close except 4401,
send `ping` every 20 s, and treat 2 missed `pong`s as a dead connection.

`route` tells the UI who answered: `core` = instant command without AI, `assistant` = the main agent,
`private` = answered by the local model only (sensitive content or `/privat`), `silent` = not for
JARVIS, `error` = something failed.

## REST
| Method | Path | Body / result |
|---|---|---|
| POST | `/api/v1/chat` | `{"user_command","session_id"}` → `{"reply","route","session_id"}` |
| GET | `/api/v1/deepgram/token` | → `{"access_token","expires_in","model","language","keywords"}` — 60 s Deepgram token plus the STT settings to use (tuned on the server); 503 if no Deepgram key |
| GET | `/healthz` | → `{"ok":true}` (no auth) |
| GET/PUT | `/api/v1/composition` | AI per category, speech engine, Mode Kuat; PUT `{"preset"}` or `{"changes"}` (owner devices only) |
| POST | `/api/v1/composition/test` | `{"category"}` → which model answered, ms |
| GET | `/api/v1/brain`, `/api/v1/brain/{id}` | 3D memory graph / one memory |
| GET/POST/DELETE | `/api/v1/voiceprint` | enrolment status / one PCM sample / delete |
| POST | `/api/v1/meetings` | `{"title","confidential","consent":true}` → `{"id"}` |
| PUT | `/api/v1/meetings/{id}/chunks/{n}` | audio chunk (idempotent) |
| POST | `/api/v1/meetings/{id}/marks`, `/finish`, `/ask` | mark, finish `{"duration_s","chunks"}`, question → answer |
| GET/DELETE | `/api/v1/meetings[/{id}]`, `/api/v1/meetings/{id}/chunks/{n}` | list / detail (transcript, summary) / audio |
| GET | `/api/v1/documents/{id}`, `/api/v1/media/{id}` | file JARVIS made / music it fetched (Range) |
| GET/POST/PATCH/DELETE | `/api/v1/vault[/{id}]` | password manager (owner devices; never returns passwords in lists) |
| POST | `/api/v1/vault/{id}/reveal`, `/api/v1/vault/match` | one password / logins for a page URL (autofill) |
| GET | `/api/v1/app/latest`, `/api/v1/app/releases/{file}` | newest APK (every device) + download |
| GET | `/admin/dev-changes` (+ console) | JARVIS' own performance changes: status, files, test/deploy log (ADR-026) |
| POST | `/admin/efficiency-review` (+ console) | start the efficiency review now |
| GET / POST | `/admin/flow-issues`, `/admin/flow-issues/{id}` `{"status"}` (+ console) | flow watcher findings; mark open/ignored/fixed |
| POST | `/admin/flow-check` (+ console) | run the flow watcher now |
| GET | `/admin/server-usage` (+ console) | CPU %, load, RAM/swap/disk (GB, %), uptime, running tasks, AI spend, `containers` (who uses CPU/RAM), `who` (running/waiting work, AI calls by caller) — home-screen strip |
| GET | `/admin/background` (+ console) | behind the scenes: now (tasks, AI calls, 50% rule state), schedule, last 24 h, log |
| POST | `/admin/relieve` (+ console) | Netralkan: stop & keep all tasks, rest background work 15 min, host frees Hermes/worker-model memory |
| POST | `/admin/tasks/{id}/retry`, `/admin/tasks/{id}/close` (+ console) | a stopped/failed task: continue it from its progress, or close it |
| POST | `/api/v1/console/admin-password` | `{"current","new"}` change the web admin password (owner device) |
| * | `/api/v1/console/…` | every web-admin endpoint (`/admin/…`) for owner-scope devices, plus `settings`, `releases` |

Errors: `401` bad/revoked token, `403` device without owner scope, `422` validation, `503` dependency not configured.

## Quick commands (tier 1, answered by core without any model)
`bantuan`, `status`, `persetujuan`, `setujui <id>`, `tolak <id>`, `ingat: <teks>`, `memori <kata kunci>`,
`lupakan <id memori>`, `workflow`, `di mana saya`. Prefix `/privat` keeps a message (and its answer) on
the local model.
