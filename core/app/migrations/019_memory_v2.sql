-- Blueprint v2 Sprint 3 (ADR-040): memory with provenance and correction, what was tried before (episodes), what matters now (goals).
ALTER TABLE memories
    ADD COLUMN confidence    real NOT NULL DEFAULT 0.7 CHECK (confidence BETWEEN 0 AND 1),
    ADD COLUMN verified      boolean NOT NULL DEFAULT false,   -- checked against a source or confirmed by the owner
    ADD COLUMN evidence      text,                             -- where it comes from (a URL, "kata pemilik", a task)
    ADD COLUMN superseded_by uuid,                             -- set when a correction replaced it (it is kept, marked stale)
    ADD COLUMN last_used     timestamptz;
UPDATE memories SET confidence = CASE kind WHEN 'assumption' THEN 0.4 WHEN 'preference' THEN 0.8 ELSE 0.7 END;

-- Episodic memory: what each finished task was about, how it was done, how it ended — so a repeated task starts from it.
CREATE TABLE episodes (
    id         bigserial PRIMARY KEY,
    task_id    bigint,
    goal       text NOT NULL,
    approach   text NOT NULL DEFAULT '',
    result     text NOT NULL DEFAULT '',
    success    boolean NOT NULL,
    cost_usd   numeric(10,6) NOT NULL DEFAULT 0,
    model      text,
    lesson     text,
    embedding  real[],
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX episodes_recent ON episodes (created_at DESC);

-- Goals and state: what the owner wants done over time (separate from one-off tasks).
CREATE TABLE goals (
    id         bigserial PRIMARY KEY,
    text       text NOT NULL,
    status     text NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'paused', 'done')),
    priority   int NOT NULL DEFAULT 3 CHECK (priority BETWEEN 1 AND 5),   -- 1 = most important
    due        date,
    source     text NOT NULL DEFAULT 'owner',
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);
