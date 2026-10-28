-- Blueprint v4 Fase 12 (ADR-077): JARVIS operates apps on the owner's phone (first: Gojek) through the JARVIS app's accessibility service.
-- Every run needs the owner's approval in the app with the admin password — except a run the owner scheduled (a project's schedule).
CREATE TABLE phone_runs (
    id            serial PRIMARY KEY,
    app           text NOT NULL,
    goal          text NOT NULL,
    status        text NOT NULL DEFAULT 'awaiting'
                  CHECK (status IN ('awaiting', 'approved', 'running', 'done', 'failed', 'rejected', 'expired', 'stopped')),
    scheduled     boolean NOT NULL DEFAULT false,      -- started by a schedule the owner made: no approval asked
    requested_by  text NOT NULL,
    approved_by   text,
    approved_at   timestamptz,
    session_id    text,
    task_id       bigint REFERENCES tasks(id) ON DELETE SET NULL,
    project_id    int REFERENCES projects(id) ON DELETE SET NULL,
    project_role  int REFERENCES project_roles(id) ON DELETE SET NULL,
    project_run   int,
    model_override text,
    result        text,
    created_at    timestamptz NOT NULL DEFAULT now(),
    updated_at    timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX phone_runs_open ON phone_runs (status, created_at);

ALTER TABLE project_roles ADD COLUMN app text;    -- a role that operates an app on the phone (e.g. 'gojek'): one worker, the phone has one screen

-- the model that reads the phone's screen and decides the next tap, starting from what the web workers use
INSERT INTO llm_categories (name, title, description, routes, budget_usd, allow_free, confirm_cloud, worker, sort, paid_attempt_limit, max_retries)
SELECT 'hp', 'Operasi aplikasi HP', 'Membaca layar aplikasi di HP pemilik (mis. Gojek) dan memilih langkah berikutnya: ketuk, ketik, gulir',
       c.routes, c.budget_usd, c.allow_free, c.confirm_cloud, true, c.sort + 1, c.paid_attempt_limit, c.max_retries
FROM llm_categories c WHERE c.name = 'web'
ON CONFLICT (name) DO NOTHING;
