-- Blueprint v4 Fase 12 (ADR-073): the owner's projects — a goal, a schedule, and a team of workers by role (how many, which AI model each,
-- whether they operate websites). Every run spawns the workers as ordinary owner tasks (safety rules, desk cards, takeover all apply).
CREATE TABLE projects (
    id          serial PRIMARY KEY,
    name        text NOT NULL,
    goal        text NOT NULL DEFAULT '',
    status      text NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'paused')),
    schedule    text NOT NULL DEFAULT 'manual' CHECK (schedule IN ('manual', 'hourly', 'daily', 'weekdays', 'weekly')),
    at_time     text CHECK (at_time IS NULL OR at_time ~ '^[0-2][0-9]:[0-5][0-9]$'),   -- local time (WIB) for daily / weekdays / weekly
    weekday     int CHECK (weekday IS NULL OR weekday BETWEEN 0 AND 6),            -- 0 = Monday, for weekly
    next_run    timestamptz,
    last_run    timestamptz,
    runs        int NOT NULL DEFAULT 0,
    created_at  timestamptz NOT NULL DEFAULT now(),
    updated_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE project_roles (
    id          serial PRIMARY KEY,
    project_id  int NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    role        text NOT NULL,
    brief       text NOT NULL DEFAULT '',
    workers     int NOT NULL DEFAULT 1 CHECK (workers BETWEEN 1 AND 5),
    model       text,                       -- an OpenRouter model for these workers; NULL = the category's own choice
    web         boolean NOT NULL DEFAULT false,
    sort        int NOT NULL DEFAULT 0
);

ALTER TABLE tasks ADD COLUMN project_id int REFERENCES projects(id) ON DELETE SET NULL;
ALTER TABLE tasks ADD COLUMN project_role int REFERENCES project_roles(id) ON DELETE SET NULL;
ALTER TABLE tasks ADD COLUMN project_run int;
ALTER TABLE tasks ADD COLUMN model_override text;   -- a worker's own model (a project role's pick): the gateway tries it first
CREATE INDEX tasks_project ON tasks (project_id, project_run) WHERE project_id IS NOT NULL;
