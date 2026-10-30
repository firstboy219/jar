-- ADR-087 wave 6: media & tools — what was played (to learn the morning mood), YouTube notes (transcript, summary, chapters), cinema
-- schedules of the day, bedtime stories, measurements (AR on the phone, or estimated from a photo), screen guidance sessions, file jobs.
CREATE TABLE media_log (
    id       bigserial PRIMARY KEY,
    kind     text NOT NULL,                      -- music | video
    mood     text NOT NULL DEFAULT '',
    query    text NOT NULL DEFAULT '',
    title    text NOT NULL DEFAULT '',
    slot     text NOT NULL DEFAULT '',
    weekday  int,
    place    text NOT NULL DEFAULT '',
    at       timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX media_log_kind ON media_log (kind, at DESC);

CREATE TABLE video_notes (
    video_id    text PRIMARY KEY,
    title       text NOT NULL DEFAULT '',
    channel     text NOT NULL DEFAULT '',
    duration_s  int,
    lang        text NOT NULL DEFAULT '',
    transcript  jsonb,                           -- [{t: seconds, text}]
    source      text NOT NULL DEFAULT '',        -- server | phone
    summary     jsonb,                           -- {ringkasan, poin, bab: [{t, judul}]}
    created_at  timestamptz NOT NULL DEFAULT now(),
    updated_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE cinema_cache (
    key         text PRIMARY KEY,                -- '<city>:<YYYY-MM-DD>'
    data        jsonb NOT NULL,
    fetched_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE stories (
    id          bigserial PRIMARY KEY,
    title       text NOT NULL,
    theme       text NOT NULL DEFAULT '',
    data        jsonb NOT NULL,                  -- {paragraf: [], pesan, menit, tokoh}
    status      text NOT NULL DEFAULT 'new' CHECK (status IN ('new', 'read', 'liked', 'skipped')),
    run_id      bigint,
    created_at  timestamptz NOT NULL DEFAULT now(),
    read_at     timestamptz
);

CREATE TABLE measures (
    id             bigserial PRIMARY KEY,
    label          text NOT NULL DEFAULT '',
    kind           text NOT NULL CHECK (kind IN ('ar', 'foto')),
    data           jsonb NOT NULL,               -- {lebar, tinggi, panjang, jarak, unit, yakin, catatan, titik}
    attachment_id  text,
    run_id         bigint,
    created_at     timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE guide_sessions (
    id          bigserial PRIMARY KEY,
    goal        text NOT NULL,
    status      text NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'done', 'stopped')),
    steps       jsonb NOT NULL DEFAULT '[]'::jsonb,   -- [{at, screen, instruction, target, done}]
    created_at  timestamptz NOT NULL DEFAULT now(),
    updated_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE file_jobs (
    id          bigserial PRIMARY KEY,
    op          text NOT NULL,
    inputs      jsonb NOT NULL,
    result      jsonb,
    document_id uuid,
    run_id      bigint,
    created_at  timestamptz NOT NULL DEFAULT now()
);

-- files the tools make are documents too (merged PDF, page images as ZIP, extracted text)
ALTER TABLE documents DROP CONSTRAINT IF EXISTS documents_format_check;
ALTER TABLE documents ADD CONSTRAINT documents_format_check CHECK (format IN ('docx', 'xlsx', 'pdf', 'md', 'zip', 'png', 'jpg', 'txt'));
