-- Performance self-improvement (ADR-026, enabled by the owner 2026-10-21, scope: speed, cost and task
-- success only). Hermes changes JARVIS' own code on a branch in its workspace; the host runner tests it;
-- the owner approves; the runner merges, deploys, health-checks and rolls back on failure.
CREATE TABLE dev_changes (
    id          bigserial PRIMARY KEY,
    branch      text NOT NULL,
    title       text NOT NULL,
    why         text NOT NULL DEFAULT '',
    task_id     bigint REFERENCES tasks(id) ON DELETE SET NULL,
    status      text NOT NULL DEFAULT 'testing' CHECK (status IN (
                  'testing', 'test_failed', 'awaiting_approval', 'rejected', 'deploying', 'deployed',
                  'deploy_failed', 'rolled_back')),
    commit      text,
    files       jsonb NOT NULL DEFAULT '[]',
    diffstat    text,
    test_log    text,
    deploy_log  text,
    apk_version text,
    approval_id bigint REFERENCES approvals(id) ON DELETE SET NULL,
    created_at  timestamptz NOT NULL DEFAULT now(),
    updated_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX dev_changes_status_idx ON dev_changes (status, id);

-- Recurring errors (they make tasks fail = inefficient) trigger at most one repair task per signature per day.
CREATE TABLE repair_attempts (
    signature text PRIMARY KEY,
    task_id   bigint REFERENCES tasks(id) ON DELETE SET NULL,
    at        timestamptz NOT NULL DEFAULT now()
);

ALTER TABLE tasks DROP CONSTRAINT IF EXISTS tasks_kind_check;
ALTER TABLE tasks ADD CONSTRAINT tasks_kind_check
    CHECK (kind IN ('owner', 'situation', 'routine', 'selfcheck', 'meeting', 'selfimprove'));
