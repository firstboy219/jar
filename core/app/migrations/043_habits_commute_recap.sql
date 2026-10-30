-- ADR-087 wave 2: habits (what JARVIS does on its own, when, and how — automatically, asking first, or not), trips to and from work,
-- and the evening recap as a note page of its own.
CREATE TABLE habits (
    id          serial PRIMARY KEY,
    key         text NOT NULL UNIQUE,                 -- 'pagi.plan', 'learned:bisnis:08' …
    title       text NOT NULL,
    trigger     jsonb NOT NULL,                       -- {type: time|arrive|leave, at, days, place, after, before}
    action      text NOT NULL,                        -- a registered habit action ('commute.plan_out', 'open:bisnis' …)
    mode        text NOT NULL DEFAULT 'ask' CHECK (mode IN ('auto', 'ask', 'off')),
    status      text NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'suggested', 'rejected')),
    source      text NOT NULL DEFAULT 'builtin' CHECK (source IN ('builtin', 'learned', 'owner')),
    seen        int NOT NULL DEFAULT 0,               -- days it happened …
    of_days     int NOT NULL DEFAULT 0,               -- … out of the days it could have
    last_fired  timestamptz,
    created_at  timestamptz NOT NULL DEFAULT now(),
    updated_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE commute_trips (
    id           bigserial PRIMARY KEY,
    direction    text NOT NULL CHECK (direction IN ('out', 'back')),
    plan         jsonb NOT NULL,                      -- the options offered
    chosen       jsonb,                               -- the option the owner took
    status       text NOT NULL DEFAULT 'planned' CHECK (status IN ('planned', 'active', 'done', 'cancelled')),
    events       jsonb NOT NULL DEFAULT '[]'::jsonb,  -- [{at, kind, text}] reminders, rides ordered, replans
    created_at   timestamptz NOT NULL DEFAULT now(),
    started_at   timestamptz,
    finished_at  timestamptz
);
CREATE INDEX commute_trips_recent ON commute_trips (created_at DESC);

ALTER TABLE note_pages DROP CONSTRAINT IF EXISTS note_pages_kind_check;
ALTER TABLE note_pages ADD CONSTRAINT note_pages_kind_check CHECK (kind IN ('page', 'inbox', 'tasks', 'meeting', 'recap'));
