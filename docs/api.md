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

Server → client
```json
{"type": "status", "state": "thinking|executing|completed|failed", "session_id": "…"}
{"type": "reply", "text": "…", "route": "core|hermes|blocked|error", "session_id": "…"}
{"type": "error", "message": "…", "session_id": "…"}
{"type": "pong"}
```
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
