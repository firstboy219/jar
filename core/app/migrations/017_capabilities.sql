-- Blueprint v2 Sprint 2 (ADR-040): a searchable catalog of what JARVIS can do, with how well it has worked.
CREATE TABLE capabilities (
    id           text PRIMARY KEY,                 -- 'skill:<name>' | 'tool:<name>' | 'worker:<name>'
    kind         text NOT NULL CHECK (kind IN ('skill', 'tool', 'worker')),
    name         text NOT NULL,
    description  text NOT NULL DEFAULT '',
    task_types   text[] NOT NULL DEFAULT '{}',
    category     text,                             -- the model category that does this best
    tools        text[] NOT NULL DEFAULT '{}',
    permissions  text[] NOT NULL DEFAULT '{}',
    status       text NOT NULL DEFAULT 'published' CHECK (status IN ('draft', 'tested', 'published', 'deprecated')),
    tested       boolean NOT NULL DEFAULT false,   -- has it passed a test (sandbox or a verified task)?
    runs         int NOT NULL DEFAULT 0,
    success_n    int NOT NULL DEFAULT 0,
    fail_n       int NOT NULL DEFAULT 0,
    cost_usd     numeric(10,6) NOT NULL DEFAULT 0, -- total spent in tasks that used it
    version      int NOT NULL DEFAULT 1,
    content_hash text,
    created_at   timestamptz NOT NULL DEFAULT now(),
    updated_at   timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE capability_versions (
    capability_id text NOT NULL REFERENCES capabilities(id) ON DELETE CASCADE,
    version       int NOT NULL,
    content       text NOT NULL,
    changelog     text NOT NULL DEFAULT '',
    tests         jsonb,
    created_at    timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (capability_id, version)
);
-- one automatic second attempt for an owner task that failed for a reason another approach might fix
ALTER TABLE tasks ADD COLUMN recovered int NOT NULL DEFAULT 0;
