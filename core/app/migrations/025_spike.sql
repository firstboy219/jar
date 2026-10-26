-- Blueprint v4 Fase 2 (ADR-043): the OpenJarvis spike — OpenJarvis and Hermes-Brain on the same model, measured.
-- Its own category with the owner's cap ($1, 2026-10-26): the model the owner picks for the spike and nothing
-- else (no safety net, no local fallback: a failure is a measured failure, not a slow success).
INSERT INTO llm_categories (name, title, description, routes, allow_free, confirm_cloud, worker, sort, budget_usd)
VALUES ('spike', 'Uji OpenJarvis (spike)', 'Uji banding OpenJarvis vs Hermes pada tugas berat yang sama (Fase 2). Berhenti di batas anggaran.',
        '[{"provider": "openrouter", "model": "deepseek/deepseek-v4.1-flash"}]'::jsonb,
        false, false, true, 160, 1.00)
ON CONFLICT (name) DO NOTHING;

-- One attempt of one runtime on one problem. Written by the harness (infra/spike), graded on the host.
CREATE TABLE spike_runs (
    id          bigserial PRIMARY KEY,
    batch       text NOT NULL,                       -- one spike session
    problem     text NOT NULL,
    runtime     text NOT NULL CHECK (runtime IN ('hermes', 'openjarvis')),
    attempt     int NOT NULL,
    status      text NOT NULL DEFAULT 'running' CHECK (status IN ('running', 'done', 'failed', 'skipped')),
    started_at  timestamptz NOT NULL DEFAULT now(),
    finished_at timestamptz,
    seconds     real,
    cost_usd    numeric(10, 6),
    calls       int,                                 -- model calls seen by the gateway
    quality     real,                                -- 0..1 from the hidden test / the report check
    grade       jsonb,                               -- what the grader saw
    violations  jsonb NOT NULL DEFAULT '[]'::jsonb,  -- privacy / approval / protected-zone breaches
    tools       jsonb NOT NULL DEFAULT '[]'::jsonb,  -- tools the runtime used, in order
    output      text,
    error       text,
    UNIQUE (batch, problem, runtime, attempt)
);
