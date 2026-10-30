-- JARVIS app v2 (ADR-087): one app for the phone and the web, every screen of the owner's mockup on real data.
-- What the owner opens, and when: the front page orders its shortcuts by the hour and the day the owner usually opens each feature.
CREATE TABLE app_usage (
    id         bigserial PRIMARY KEY,
    feature    text NOT NULL,
    opened_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX app_usage_feature ON app_usage (feature, opened_at DESC);

-- Where the phone was (opt-in in the app, as before): the trail that teaches JARVIS where "rumah" and "kantor" are, and when the owner
-- arrives or leaves. Kept 60 days.
CREATE TABLE location_history (
    id          bigserial PRIMARY KEY,
    lat         double precision NOT NULL,
    lon         double precision NOT NULL,
    accuracy_m  real,
    at          timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX location_history_at ON location_history (at DESC);

-- The owner's places: learned from the trail (nights → rumah, weekday office hours → kantor) or set by the owner.
CREATE TABLE places (
    id          serial PRIMARY KEY,
    name        text NOT NULL UNIQUE,          -- 'rumah', 'kantor', or the owner's own name for a place
    label       text NOT NULL DEFAULT '',      -- an address or a description to show
    lat         double precision NOT NULL,
    lon         double precision NOT NULL,
    radius_m    int NOT NULL DEFAULT 200 CHECK (radius_m BETWEEN 50 AND 5000),
    source      text NOT NULL DEFAULT 'learned' CHECK (source IN ('learned', 'owner')),
    updated_at  timestamptz NOT NULL DEFAULT now()
);

-- Arrivals and departures at the owner's places (from the trail): what "sampai kantor" / "sampai rumah" triggers are made of.
CREATE TABLE place_events (
    id        bigserial PRIMARY KEY,
    place     text NOT NULL,
    kind      text NOT NULL CHECK (kind IN ('arrive', 'leave')),
    at        timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX place_events_at ON place_events (at DESC);

-- The master flow (owner 2026-10-29): every process behind the app goes router → Hermes → skill (no AI) | ringan | berat.
-- One row per run: what the router recognised, what Hermes decided and why, how it went. The live flow view and Hermes' own learning
-- (which way works for which job) both read it.
CREATE TABLE flow_runs (
    id           bigserial PRIMARY KEY,
    feature      text NOT NULL,
    action       text NOT NULL,
    goal         text NOT NULL DEFAULT '',
    trigger      text NOT NULL DEFAULT 'owner' CHECK (trigger IN ('owner', 'habit', 'schedule', 'event')),
    router       jsonb NOT NULL DEFAULT '{}'::jsonb,      -- {intent, capability, score}
    lane         text CHECK (lane IN ('skill', 'ringan', 'berat', 'hermes')),
    why          text NOT NULL DEFAULT '',
    status       text NOT NULL DEFAULT 'routing' CHECK (status IN ('routing', 'running', 'waiting', 'done', 'failed')),
    steps        jsonb NOT NULL DEFAULT '[]'::jsonb,      -- [{at, stage, text}]
    task_id      bigint,
    model        text,
    cost_usd     numeric(10,6) NOT NULL DEFAULT 0,
    error        text,
    result       jsonb,
    on_done      text,                                    -- "module:function" the result goes to when a worker job ends
    data         jsonb,
    started_at   timestamptz NOT NULL DEFAULT now(),
    finished_at  timestamptz
);
CREATE INDEX flow_runs_recent ON flow_runs (started_at DESC);
CREATE INDEX flow_runs_job ON flow_runs (feature, action, started_at DESC);
CREATE INDEX flow_runs_task ON flow_runs (task_id) WHERE task_id IS NOT NULL;

-- A worker doing an app feature's job (master flow): its result goes back to the feature, it is not spoken as a report.
ALTER TABLE tasks DROP CONSTRAINT IF EXISTS tasks_kind_check;
ALTER TABLE tasks ADD CONSTRAINT tasks_kind_check
    CHECK (kind IN ('owner', 'situation', 'routine', 'selfcheck', 'meeting', 'selfimprove', 'flowcheck', 'watcher', 'devteam', 'feature'));
