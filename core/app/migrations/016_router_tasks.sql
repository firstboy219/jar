-- Blueprint v2 Sprint 1 (ADR-040): the model router's bookkeeping and the task manager's fuller picture of a task.
ALTER TABLE llm_categories
    ADD COLUMN paid_attempt_limit int NOT NULL DEFAULT 1,   -- paid models tried AFTER a free one failed, per request
    ADD COLUMN max_retries        int NOT NULL DEFAULT 1;   -- retries of a transient failure (5xx/network) on the same model
ALTER TABLE llm_usage
    ADD COLUMN task_id         bigint,
    ADD COLUMN retry           int NOT NULL DEFAULT 0,
    ADD COLUMN fallback_reason text;                        -- why this answer came from a later route ("kena batas permintaan (429)")
CREATE INDEX llm_usage_task ON llm_usage (task_id) WHERE task_id IS NOT NULL;
ALTER TABLE tasks
    ADD COLUMN goal       text,
    ADD COLUMN criteria   jsonb,                            -- acceptance criteria the result is checked against
    ADD COLUMN plan       jsonb,
    ADD COLUMN phase      text,                             -- planning | researching | executing | testing | waiting_approval
    ADD COLUMN budget_usd numeric(8,4),
    ADD COLUMN cost_usd   numeric(10,6) NOT NULL DEFAULT 0,
    ADD COLUMN artifacts  jsonb NOT NULL DEFAULT '[]'::jsonb,
    ADD COLUMN retries    int NOT NULL DEFAULT 0,
    ADD COLUMN model_used text;
