-- The owner's playlists (ADR-034): songs JARVIS found (charts, requests) to play later in order.
CREATE TABLE playlists (
    id         bigserial PRIMARY KEY,
    name       text NOT NULL UNIQUE,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE playlist_items (
    id          bigserial PRIMARY KEY,
    playlist_id bigint NOT NULL REFERENCES playlists(id) ON DELETE CASCADE,
    position    int NOT NULL,
    title       text NOT NULL,
    artist      text NOT NULL DEFAULT '',
    source      text NOT NULL DEFAULT '',   -- where it came from: "iTunes top R&B (US)", "permintaan", …
    added_at    timestamptz NOT NULL DEFAULT now(),
    UNIQUE (playlist_id, title, artist)
);
CREATE INDEX playlist_items_order ON playlist_items (playlist_id, position);
