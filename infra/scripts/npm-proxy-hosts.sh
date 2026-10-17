#!/usr/bin/env bash
# Create/refresh Nginx Proxy Manager proxy hosts via its API (idempotent per domain).
# Requests a Let's Encrypt cert per domain if none exists (NPM 2.16 registers it with the NPM admin's email).
# WebSocket upgrade is enabled (BRD §4: proxy_set_header Upgrade/Connection).
set -euo pipefail
cd "$(dirname "$0")/.."
set -a; . ./.env; set +a

API=http://127.0.0.1:81/api
TOKEN=$(curl -sf -X POST "$API/tokens" -H 'Content-Type: application/json' \
  -d "{\"identity\":\"$NPM_ADMIN_EMAIL\",\"secret\":\"$NPM_ADMIN_PASSWORD\"}" | python3 -c 'import sys,json;print(json.load(sys.stdin)["token"])')
auth=(-H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json')

# domain -> container:port
upsert() {
  local domain=$1 host=$2 port=$3 ssl=true cert_id
  cert_id=$(curl -sf "${auth[@]}" "$API/nginx/certificates" | python3 -c "
import sys,json
print(next((c['id'] for c in json.load(sys.stdin) if '$domain' in c['domain_names']), ''))")
  if [[ -z "$cert_id" ]]; then
    echo "requesting Let's Encrypt cert for $domain"
    cert_id=$(curl -sf "${auth[@]}" -X POST "$API/nginx/certificates" -d "{
      \"provider\":\"letsencrypt\",\"domain_names\":[\"$domain\"],\"meta\":{}}" \
      | python3 -c 'import sys,json;print(json.load(sys.stdin)["id"])')
  fi

  local body="{
    \"domain_names\":[\"$domain\"],\"forward_scheme\":\"http\",
    \"forward_host\":\"$host\",\"forward_port\":$port,
    \"allow_websocket_upgrade\":true,\"block_exploits\":true,\"caching_enabled\":false,
    \"access_list_id\":0,\"certificate_id\":$cert_id,
    \"ssl_forced\":$ssl,\"http2_support\":$ssl,\"hsts_enabled\":false,\"hsts_subdomains\":false,
    \"advanced_config\":\"proxy_read_timeout 3600s;\\nproxy_send_timeout 3600s;\",\"meta\":{},\"locations\":[]}"

  local id
  id=$(curl -sf "${auth[@]}" "$API/nginx/proxy-hosts" | python3 -c "
import sys,json
print(next((h['id'] for h in json.load(sys.stdin) if '$domain' in h['domain_names']), ''))")
  if [[ -n "$id" ]]; then
    curl -sf "${auth[@]}" -X PUT "$API/nginx/proxy-hosts/$id" -d "$body" >/dev/null
  else
    curl -sf "${auth[@]}" -X POST "$API/nginx/proxy-hosts" -d "$body" >/dev/null
  fi
  echo "$domain -> $host:$port (ssl=$ssl)"
}

# Backend: jarvis-core (device tokens; Hermes itself stays internal)
upsert "$BACKEND_DOMAIN" jarvis-core 8000
# Frontend: web admin panel (FS-105)
upsert "$FRONTEND_DOMAIN" jarvis-admin 8000
# n8n editor + webhooks (n8n's own owner login protects the UI)
upsert "$FLOW_DOMAIN" jarvis-executor 5678
