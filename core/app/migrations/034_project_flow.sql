-- Blueprint v4 Fase 12 (ADR-079): the order a project's workers work in, and the owner's pick in between.
-- A role starts WITH the previous role (parallel, the default) or AFTER it finished; an "ask owner" role first shows the owner the options the
-- previous stage found (a notification + popup in the app / on the desk) and starts when one is picked — optionally N minutes before its time.
ALTER TABLE project_roles ADD COLUMN stage int NOT NULL DEFAULT 0;            -- computed on save: 0, 1, 2 … roles of one stage run together
ALTER TABLE project_roles ADD COLUMN after_prev boolean NOT NULL DEFAULT false;
ALTER TABLE project_roles ADD COLUMN ask_owner boolean NOT NULL DEFAULT false;
ALTER TABLE project_roles ADD COLUMN start_offset_min int CHECK (start_offset_min IS NULL OR start_offset_min BETWEEN 0 AND 180);
ALTER TABLE projects ADD COLUMN notified_run int NOT NULL DEFAULT 0;           -- the last run the owner was told the end of

CREATE TABLE owner_choices (
    id          serial PRIMARY KEY,
    project_id  int REFERENCES projects(id) ON DELETE CASCADE,
    project_run int,
    title       text NOT NULL,
    prompt      text NOT NULL,
    options     jsonb NOT NULL,                  -- [{label, detail, waktu}]
    status      text NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'answered', 'expired', 'cancelled')),
    answer      jsonb,
    created_at  timestamptz NOT NULL DEFAULT now(),
    answered_at timestamptz,
    expires_at  timestamptz NOT NULL
);
CREATE INDEX owner_choices_open ON owner_choices (status, created_at);

-- the run of a project that still has stages to start: running (waits for the stage's workers), choice (waits for the owner), timer (waits for the start time)
CREATE TABLE project_chain (
    project_id  int PRIMARY KEY REFERENCES projects(id) ON DELETE CASCADE,
    run         int NOT NULL,
    next_stage  int NOT NULL,
    state       text NOT NULL DEFAULT 'running' CHECK (state IN ('running', 'choice', 'timer')),
    choice_id   int REFERENCES owner_choices(id) ON DELETE SET NULL,
    pick        jsonb,
    start_at    timestamptz,
    updated_at  timestamptz NOT NULL DEFAULT now()
);
