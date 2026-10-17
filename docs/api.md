# JARVIS core API (for the APK)

Base URL: `https://vis1.cosger.online`. Every call needs a device token, created in the web admin
(**Perangkat** tab, shown once) and sent as `Authorization: Bearer jdv_…`.

## WebSocket — `wss://vis1.cosger.online/ws` (FS-101 downstream)

Auth: the `Authorization` header on the upgrade request. Clients that cannot set headers may instead
send `{"type":"auth","token":"jdv_…"}` as the first frame (answered with `{"type":"auth_ok"}`).
A bad token gets `{"type":"error","message":"unauthorized"}` and close code **4401** — do not auto-reconnect on 4401.

Client → server
```json
{"user_command": "status", "session_id": "3f2c…"}
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
| GET | `/api/v1/deepgram/token` | → `{"access_token","expires_in"}` short-lived token for Deepgram streaming STT; 503 if no Deepgram key configured |
| GET | `/healthz` | → `{"ok":true}` (no auth) |

Errors: `401` bad/revoked token, `422` validation, `503` dependency not configured.

## Quick commands (tier 1, answered by core without any model)
`bantuan`, `status`, `persetujuan`, `setujui <id>`, `tolak <id>`, `ingat: <teks>`, `memori <kata kunci>`,
`lupakan <id memori>`, `workflow`. Prefix `/privat` keeps a message off the cloud.
