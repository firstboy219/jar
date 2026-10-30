-- ADR-087 batch I: JARVIS working on any website (a hotel, a flight, a ticket) — the task, the moments it needs the owner, what it learned.
CREATE TABLE web_tasks (
    id          bigserial PRIMARY KEY,
    goal        text NOT NULL,
    start_url   text NOT NULL DEFAULT '',
    site        text NOT NULL DEFAULT '',
    feature     text NOT NULL DEFAULT 'web',
    origin      text NOT NULL DEFAULT 'app' CHECK (origin IN ('app', 'chat', 'schedule', 'feature')),
    status      text NOT NULL DEFAULT 'queued' CHECK (status IN ('queued', 'running', 'waiting', 'done', 'failed', 'stopped')),
    task_id     bigint,
    backend     text NOT NULL DEFAULT 'hp',
    trace       jsonb NOT NULL DEFAULT '[]'::jsonb,
    result      jsonb,
    routine_id  bigint,
    created_by  text NOT NULL DEFAULT 'owner',
    created_at  timestamptz NOT NULL DEFAULT now(),
    updated_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX web_tasks_recent ON web_tasks (id DESC);
CREATE INDEX web_tasks_task ON web_tasks (task_id);

CREATE TABLE web_waits (
    id          bigserial PRIMARY KEY,
    web_task_id bigint NOT NULL REFERENCES web_tasks(id) ON DELETE CASCADE,
    kind        text NOT NULL CHECK (kind IN ('masuk', 'verifikasi', 'bayar', 'pilih', 'tanya', 'tinjau', 'macet')),
    title       text NOT NULL,
    detail      jsonb NOT NULL DEFAULT '{}'::jsonb,
    status      text NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'done', 'rejected', 'expired')),
    answer      jsonb,
    answered_by text,
    created_at  timestamptz NOT NULL DEFAULT now(),
    answered_at timestamptz
);
CREATE INDEX web_waits_open ON web_waits (status) WHERE status = 'open';

CREATE TABLE web_routines (
    id          bigserial PRIMARY KEY,
    site        text NOT NULL,
    name        text NOT NULL,
    goal        text NOT NULL,
    start_url   text NOT NULL DEFAULT '',
    steps       jsonb NOT NULL,
    params      jsonb NOT NULL DEFAULT '[]'::jsonb,
    runs        int NOT NULL DEFAULT 0,
    ok_runs     int NOT NULL DEFAULT 0,
    status      text NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'off')),
    created_at  timestamptz NOT NULL DEFAULT now(),
    updated_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX web_routines_site ON web_routines (site, status);
