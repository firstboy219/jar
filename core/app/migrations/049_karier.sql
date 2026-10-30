-- ADR-087 wave 8: the job hunt on JobStreet — postings found on schedule and scored against the owner's CV, applications sent (by JARVIS
-- within his rules, or by his tap), their progress, and replies to interview invitations (sent after an undo window).
CREATE TABLE job_posts (
    id           text PRIMARY KEY,                       -- JobStreet's job id
    source       text NOT NULL DEFAULT 'jobstreet',
    title        text NOT NULL,
    company      text NOT NULL DEFAULT '',
    location     text NOT NULL DEFAULT '',
    salary       text NOT NULL DEFAULT '',
    work_type    text NOT NULL DEFAULT '',
    arrangement  text NOT NULL DEFAULT '',
    listed_at    timestamptz,
    url          text NOT NULL DEFAULT '',
    teaser       text NOT NULL DEFAULT '',
    description  text,
    questions    jsonb NOT NULL DEFAULT '[]'::jsonb,
    link_out     boolean NOT NULL DEFAULT false,         -- applied for on the company's own site
    expires_at   timestamptz,
    query        text NOT NULL DEFAULT '',
    score        int,
    score_data   jsonb,
    status       text NOT NULL DEFAULT 'new' CHECK (status IN ('new', 'scored', 'skipped', 'applying', 'applied', 'failed', 'expired')),
    fetched_at   timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX job_posts_status ON job_posts (status, score DESC NULLS LAST);

CREATE TABLE job_applications (
    id           bigserial PRIMARY KEY,
    post_id      text NOT NULL UNIQUE REFERENCES job_posts(id) ON DELETE CASCADE,
    status       text NOT NULL DEFAULT 'applying' CHECK (status IN ('applying', 'applied', 'failed', 'viewed', 'interview', 'offer', 'rejected', 'withdrawn')),
    via          text NOT NULL DEFAULT 'owner',          -- 'jarvis' (his rules) | 'owner' (his tap)
    cover_letter text NOT NULL DEFAULT '',
    answers      jsonb NOT NULL DEFAULT '[]'::jsonb,
    run_id       bigint,
    events       jsonb NOT NULL DEFAULT '[]'::jsonb,     -- [{at, kind, text}]
    interview    jsonb,                                  -- {at, place, online, event_id, reply_id}
    applied_at   timestamptz,
    updated_at   timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE job_replies (
    id             bigserial PRIMARY KEY,
    application_id bigint REFERENCES job_applications(id) ON DELETE CASCADE,
    inbox_item_id  bigint NOT NULL,
    body           text NOT NULL,
    proposal       jsonb NOT NULL DEFAULT '{}'::jsonb,   -- {accept: iso | null, slots: [iso], summary}
    send_at        timestamptz,
    status         text NOT NULL DEFAULT 'pending' CHECK (status IN ('draft', 'pending', 'sent', 'cancelled', 'failed')),
    error          text,
    created_at     timestamptz NOT NULL DEFAULT now(),
    UNIQUE (inbox_item_id)
);
