-- "Simpanan" (ADR-036): everything JARVIS made or showed, in one place.
-- What was shown on the phone's front screen (pictures, videos, web pages, maps, notes, drafts, boards) used to be
-- sent once and forgotten; songs are in /data/media, documents/playlists/meetings in their own tables.
CREATE TABLE stage_history (
    id         bigserial PRIMARY KEY,
    panel      text NOT NULL,
    title      text NOT NULL DEFAULT '',
    payload    jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX stage_history_recent ON stage_history (created_at DESC);
-- Items the owner starred: never purged (songs older than 30 days, history beyond the last 500).
CREATE TABLE library_kept (
    key     text PRIMARY KEY,          -- '<source>:<id>', e.g. 'music:3b86…', 'shown:42'
    kept_at timestamptz NOT NULL DEFAULT now()
);
