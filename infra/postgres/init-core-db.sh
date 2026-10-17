#!/bin/sh
# Idempotently create the least-privilege role + database for jarvis-core.
# Run by the one-shot `core-db-init` service before jarvis-core/jarvis-tools start.
set -eu
export PGPASSWORD="$POSTGRES_PASSWORD"
psql_admin() { psql -v ON_ERROR_STOP=1 -h jarvis-db -U "$POSTGRES_USER" -d postgres -tA "$@"; }

if [ "$(psql_admin -c "SELECT 1 FROM pg_roles WHERE rolname = 'jarvis_core'")" != 1 ]; then
  psql_admin -c "CREATE ROLE jarvis_core LOGIN PASSWORD '$JARVIS_DB_PASSWORD'"
else
  psql_admin -c "ALTER ROLE jarvis_core PASSWORD '$JARVIS_DB_PASSWORD'"
fi
if [ "$(psql_admin -c "SELECT 1 FROM pg_database WHERE datname = 'jarvis'")" != 1 ]; then
  psql_admin -c "CREATE DATABASE jarvis OWNER jarvis_core"
fi
psql_admin -c "REVOKE ALL ON DATABASE jarvis FROM PUBLIC"
echo "jarvis database ready"
