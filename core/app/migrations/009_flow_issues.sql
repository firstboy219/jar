-- Flow watcher ("Pengawas Alur", ADR-028): problems found in how JARVIS handled the owner's requests —
-- answers out of context, promises without action, repeats, slow or failed work. The owner is told; a
-- fix task (self-improvement scope) works on them.
CREATE TABLE flow_issues (
    id          bigserial PRIMARY KEY,
    at          timestamptz NOT NULL DEFAULT now(),
    kind        text NOT NULL CHECK (kind IN ('off_context', 'promise_unkept', 'repeated', 'error_reply', 'slow_reply',
                                              'task_failed', 'task_slow', 'report_unheard', 'other')),
    severity    text NOT NULL DEFAULT 'medium' CHECK (severity IN ('low', 'medium', 'high')),
    session_id  text,
    message_id  bigint,
    task_id     bigint,
    owner_said  text,
    jarvis_said text,
    detail      text NOT NULL DEFAULT '',
    status      text NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'fixing', 'fixed', 'ignored')),
    fix_task_id bigint REFERENCES tasks(id) ON DELETE SET NULL,
    UNIQUE (kind, message_id),
    UNIQUE (kind, task_id)
);
CREATE INDEX flow_issues_status_idx ON flow_issues (status, id DESC);

ALTER TABLE tasks DROP CONSTRAINT IF EXISTS tasks_kind_check;
ALTER TABLE tasks ADD CONSTRAINT tasks_kind_check
    CHECK (kind IN ('owner', 'situation', 'routine', 'selfcheck', 'meeting', 'selfimprove', 'flowcheck'));
