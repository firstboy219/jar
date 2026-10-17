-- Main agent ("agen utama") delegates work to background workers; results come back as reports
-- that must be confirmed as heard by the owner.

CREATE TABLE tasks (
    id          bigserial PRIMARY KEY,
    session_id  text NOT NULL,
    device_id   uuid REFERENCES devices(id) ON DELETE SET NULL,
    title       text NOT NULL,
    instruction text NOT NULL,
    status      text NOT NULL DEFAULT 'queued'
                CHECK (status IN ('queued', 'running', 'completed', 'failed', 'cancelled')),
    result      text,
    error       text,
    prompt_tokens     integer,
    completion_tokens integer,
    created_at  timestamptz NOT NULL DEFAULT now(),
    started_at  timestamptz,
    finished_at timestamptz
);
CREATE INDEX tasks_status_idx ON tasks (status, id);

CREATE TABLE reports (
    id           bigserial PRIMARY KEY,
    task_id      bigint REFERENCES tasks(id) ON DELETE CASCADE,
    session_id   text NOT NULL,
    text         text NOT NULL,        -- what JARVIS says out loud
    status       text NOT NULL DEFAULT 'pending'
                 CHECK (status IN ('pending', 'delivered', 'acknowledged', 'unheard')),
    attempts     integer NOT NULL DEFAULT 0,
    created_at   timestamptz NOT NULL DEFAULT now(),
    delivered_at timestamptz,         -- last time the phone confirmed it was spoken/shown
    acked_at     timestamptz,
    acked_by     text                  -- 'tap' | 'voice' | 'admin'
);
CREATE INDEX reports_status_idx ON reports (status, id);

-- messages now also come from the main agent and from spoken worker reports
ALTER TABLE messages DROP CONSTRAINT messages_route_check;
ALTER TABLE messages ADD CONSTRAINT messages_route_check
    CHECK (route IN ('core', 'hermes', 'assistant', 'report', 'blocked', 'error'));
