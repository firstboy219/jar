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

`reply` is authoritative (it may differ slightly from the concatenated deltas). Closing the socket
mid-turn cancels the agent run on the server.
Several commands may be in flight on one socket; match replies by `session_id`.
Fail-safe auto-reconnect (BRD §4): reconnect with exponential backoff (1 s → 30 s) on any close except 4401,
send `ping` every 20 s, and treat 2 missed `pong`s as a dead connection.

`route` tells the UI who answered: `core` = instant command without AI (tier 1), `hermes` = the agent,
`blocked` = not sent to the cloud (sensitive content or `/privat`), `error` = something failed.

## REST
| Method | Path | Body / result |
|---|---|---|
| POST | `/api/v1/chat` | `{"user_command","session_id"}` → `{"reply","route","session_id"}` |
| GET | `/api/v1/deepgram/token` | → `{"access_token","expires_in","model","language","keywords"}` — 60 s Deepgram token plus the STT settings to use (tuned on the server); 503 if no Deepgram key |
| GET | `/healthz` | → `{"ok":true}` (no auth) |

Errors: `401` bad/revoked token, `422` validation, `503` dependency not configured.

## Quick commands (tier 1, answered by core without any model)
`bantuan`, `status`, `persetujuan`, `setujui <id>`, `tolak <id>`, `ingat: <teks>`, `memori <kata kunci>`,
`lupakan <id memori>`, `workflow`, `di mana saya`. Prefix `/privat` keeps a message off the cloud.
