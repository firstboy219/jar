"""n8n workflow templates for the inbox (Blueprint v4 Fase 6, ADR-045). Built here, created INACTIVE through the n8n API.

Three small flows, each behind a webhook whose path is a random secret (n8n's address is public, the path is the key):
  list      → Gmail: the newest unread messages, as {id, threadId, from, subject, snippet, date}
  send      → Gmail: send ONE email (JARVIS calls this only after the owner approved that exact email)
  calendar  → Google Calendar: create ONE event (same rule)
The Google sign-in (OAuth) cannot be done by JARVIS: the owner picks the credential on each Google node inside n8n once.
BELUM DIVERIFIKASI end to end against a live Google account — the node parameters follow n8n 2.x's Gmail / Google Calendar nodes.
"""

KINDS = ("list", "send", "calendar")
NAMES = {"list": "JARVIS · Gmail baca", "send": "JARVIS · Gmail kirim", "calendar": "JARVIS · Kalender tulis"}


def _webhook(path: str) -> dict:
    return {"id": "w", "name": "Webhook", "type": "n8n-nodes-base.webhook", "typeVersion": 2, "position": [0, 0],
            "parameters": {"httpMethod": "POST", "path": path, "responseMode": "lastNode", "options": {}}}


def build(kind: str, path: str) -> dict:
    if kind not in KINDS:
        raise ValueError(kind)
    hook = _webhook(path)
    if kind == "list":
        nodes = [hook,
                 {"id": "g", "name": "Gmail", "type": "n8n-nodes-base.gmail", "typeVersion": 2.1, "position": [260, 0],
                  "parameters": {"resource": "message", "operation": "getAll", "returnAll": False,
                                 "limit": "={{ $json.body.limit || 15 }}", "simple": True,
                                 "filters": {"readStatus": "unread"}, "options": {}}},
                 {"id": "c", "name": "Ringkas", "type": "n8n-nodes-base.code", "typeVersion": 2, "position": [520, 0],
                  "parameters": {"jsCode": "return [{json: {items: $input.all().map(i => ({id: i.json.id, threadId: i.json.threadId, "
                                           "from: i.json.From || i.json.from || '', subject: i.json.Subject || i.json.subject || '', "
                                           "snippet: String(i.json.snippet || '').slice(0, 300), date: i.json.internalDate || i.json.date || null}))}}];"}}]
        connections = {"Webhook": {"main": [[{"node": "Gmail", "type": "main", "index": 0}]]},
                       "Gmail": {"main": [[{"node": "Ringkas", "type": "main", "index": 0}]]}}
    elif kind == "send":
        nodes = [hook,
                 {"id": "g", "name": "Gmail", "type": "n8n-nodes-base.gmail", "typeVersion": 2.1, "position": [260, 0],
                  "parameters": {"resource": "message", "operation": "send", "sendTo": "={{ $json.body.to }}",
                                 "subject": "={{ $json.body.subject }}", "emailType": "text", "message": "={{ $json.body.body }}",
                                 "options": {"threadId": "={{ $json.body.threadId || '' }}"}}},
                 {"id": "r", "name": "Hasil", "type": "n8n-nodes-base.set", "typeVersion": 3.4, "position": [520, 0],
                  "parameters": {"assignments": {"assignments": [
                      {"id": "1", "name": "sent", "type": "boolean", "value": True},
                      {"id": "2", "name": "id", "type": "string", "value": "={{ $json.id }}"}]}}}]
        connections = {"Webhook": {"main": [[{"node": "Gmail", "type": "main", "index": 0}]]},
                       "Gmail": {"main": [[{"node": "Hasil", "type": "main", "index": 0}]]}}
    else:
        nodes = [hook,
                 {"id": "k", "name": "Kalender", "type": "n8n-nodes-base.googleCalendar", "typeVersion": 1.3, "position": [260, 0],
                  "parameters": {"resource": "event", "operation": "create", "calendar": {"__rl": True, "mode": "list", "value": "primary"},
                                 "start": "={{ $json.body.start }}", "end": "={{ $json.body.end }}",
                                 "additionalFields": {"summary": "={{ $json.body.title }}", "location": "={{ $json.body.location || '' }}",
                                                      "attendees": "={{ ($json.body.attendees || []).join(',') }}"}}},
                 {"id": "r", "name": "Hasil", "type": "n8n-nodes-base.set", "typeVersion": 3.4, "position": [520, 0],
                  "parameters": {"assignments": {"assignments": [
                      {"id": "1", "name": "created", "type": "boolean", "value": True},
                      {"id": "2", "name": "id", "type": "string", "value": "={{ $json.id }}"}]}}}]
        connections = {"Webhook": {"main": [[{"node": "Kalender", "type": "main", "index": 0}]]},
                       "Kalender": {"main": [[{"node": "Hasil", "type": "main", "index": 0}]]}}
    return {"name": NAMES[kind], "nodes": nodes, "connections": connections, "settings": {"executionOrder": "v1"}}
