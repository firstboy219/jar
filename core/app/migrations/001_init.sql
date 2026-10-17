-- JARVIS core schema v1

CREATE TABLE devices (
    id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name         text NOT NULL,
    token_hash   text NOT NULL UNIQUE,           -- sha256 of the bearer token; token itself is never stored
    created_at   timestamptz NOT NULL DEFAULT now(),
    last_seen_at timestamptz,
    revoked_at   timestamptz
);

CREATE TABLE messages (
    id                bigserial PRIMARY KEY,
    session_id        text NOT NULL,
    device_id         uuid REFERENCES devices(id) ON DELETE SET NULL,
    role              text NOT NULL CHECK (role IN ('user', 'assistant')),
    content           text NOT NULL,
    route             text NOT NULL CHECK (route IN ('core', 'hermes', 'blocked', 'error')),
    model             text,
    prompt_tokens     integer,
    completion_tokens integer,
    latency_ms        integer,
    created_at        timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX messages_session_idx ON messages (session_id, created_at);
CREATE INDEX messages_created_idx ON messages (created_at);

CREATE TABLE approvals (
    id              bigserial PRIMARY KEY,
    kind            text NOT NULL,                -- executor name, e.g. n8n_activate_workflow, manual
    title           text NOT NULL,
    detail          jsonb NOT NULL DEFAULT '{}',
    risk            text NOT NULL DEFAULT 'medium' CHECK (risk IN ('low', 'medium', 'high')),
    status          text NOT NULL DEFAULT 'awaiting_approval' CHECK (status IN (
                        'awaiting_approval', 'approved', 'rejected', 'executing',
                        'completed', 'failed', 'cancelled', 'expired')),
    requested_by    text NOT NULL,
    idempotency_key text UNIQUE,
    created_at      timestamptz NOT NULL DEFAULT now(),
    expires_at      timestamptz NOT NULL DEFAULT now() + interval '7 days',
    decided_at      timestamptz,
    decided_by      text,
    executed_at     timestamptz,
    result          jsonb,
    error           text
);
CREATE INDEX approvals_status_idx ON approvals (status, created_at);

CREATE TABLE memories (
    id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),  -- also the Qdrant point id
    text       text NOT NULL,
    category   text NOT NULL CHECK (category IN ('personal', 'project', 'knowledge', 'experience', 'operational')),
    kind       text NOT NULL DEFAULT 'fact' CHECK (kind IN ('fact', 'assumption', 'preference')),
    source     text NOT NULL,
    stale      boolean NOT NULL DEFAULT false,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE audit_events (
    id     bigserial PRIMARY KEY,
    at     timestamptz NOT NULL DEFAULT now(),
    actor  text NOT NULL,
    action text NOT NULL,
    target text,
    detail jsonb NOT NULL DEFAULT '{}'
);
CREATE INDEX audit_events_at_idx ON audit_events (at DESC);

CREATE TABLE settings_kv (
    key   text PRIMARY KEY,
    value jsonb NOT NULL
);
