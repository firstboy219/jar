-- Owner 2026-10-31: "kamu masukkan ke list storage berikut file hasil download nya, jadi nextnya saya tinggal play dari lokal storage …
-- siapkan management lagunya seperti Spotify". Every song he picks is downloaded once into his own collection and played from there.
CREATE TABLE music_library (
    id          bigserial PRIMARY KEY,
    video_id    text UNIQUE,
    source_url  text NOT NULL DEFAULT '',
    title       text NOT NULL,
    artist      text NOT NULL DEFAULT '',
    duration_s  int,
    cover       text NOT NULL DEFAULT '',
    media_id    text,
    status      text NOT NULL DEFAULT 'antri' CHECK (status IN ('antri', 'unduh', 'siap', 'gagal')),
    error       text,
    size_bytes  bigint NOT NULL DEFAULT 0,
    liked       boolean NOT NULL DEFAULT false,
    plays       int NOT NULL DEFAULT 0,
    last_played timestamptz,
    source      text NOT NULL DEFAULT '',
    added_at    timestamptz NOT NULL DEFAULT now(),
    ready_at    timestamptz
);
CREATE INDEX music_library_status ON music_library (status);
ALTER TABLE playlist_items ADD COLUMN library_id bigint REFERENCES music_library(id) ON DELETE SET NULL;
