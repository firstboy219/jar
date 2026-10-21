-- Awareness (proactive main agent) and self-improvement.

-- Workers now run for different purposes; only 'owner' results are spoken as reports.
ALTER TABLE tasks ADD COLUMN kind text NOT NULL DEFAULT 'owner'
    CHECK (kind IN ('owner', 'situation', 'routine', 'selfcheck'));
-- What the owner showed (camera/screen) when the task was given; workers see it too.
ALTER TABLE tasks ADD COLUMN image text;

-- Learned improvements: applied automatically when low-risk, otherwise via the approval queue.
CREATE TABLE improvements (
    id          bigserial PRIMARY KEY,
    kind        text NOT NULL CHECK (kind IN ('stt_keyword', 'lesson', 'setting', 'code')),
    summary     text NOT NULL,           -- what is wrong and why this helps
    payload     jsonb NOT NULL DEFAULT '{}',
    status      text NOT NULL DEFAULT 'proposed'
                CHECK (status IN ('proposed', 'applied', 'awaiting_approval', 'rejected', 'reverted')),
    source_task bigint REFERENCES tasks(id) ON DELETE SET NULL,
    approval_id bigint REFERENCES approvals(id) ON DELETE SET NULL,
    created_at  timestamptz NOT NULL DEFAULT now(),
    applied_at  timestamptz,
    reverted_at timestamptz
);
CREATE INDEX improvements_status_idx ON improvements (status, kind);

-- Messages can now be proactive (JARVIS spoke first) or deliberately unanswered.
ALTER TABLE messages DROP CONSTRAINT messages_route_check;
ALTER TABLE messages ADD CONSTRAINT messages_route_check
    CHECK (route IN ('core', 'hermes', 'assistant', 'report', 'blocked', 'error', 'proactive', 'silent'));
-- How sure speech recognition was about a spoken message (null for typed text).
ALTER TABLE messages ADD COLUMN stt_confidence real;

-- Coarse context history (≈100 m, activity, time) for learning routines; kept 30 days.
CREATE TABLE context_log (
    id         bigserial PRIMARY KEY,
    at         timestamptz NOT NULL DEFAULT now(),
    lat        real,
    lon        real,
    address    text,
    activity   text,
    charging   boolean,
    headset    boolean
);
CREATE INDEX context_log_at_idx ON context_log (at DESC);
