-- Owner 2026-10-31: "setiap minta putarkan lagu, usahakan kasih list ke saya lalu saya diminta pilih mana saja yg saya ceklis, lalu kamu
-- proses untuk convert dari YouTube music ke mp3". A request for music becomes a list of YouTube results he ticks; the ticked ones are
-- made MP3 (his converter) one by one, the first played as soon as it is ready, all kept in his playlist.
CREATE TABLE music_picks (
    id          bigserial PRIMARY KEY,
    query       text NOT NULL,
    options     jsonb NOT NULL,
    status      text NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'working', 'done', 'dismissed', 'expired')),
    chosen      jsonb,
    results     jsonb NOT NULL DEFAULT '[]'::jsonb,
    created_by  text NOT NULL DEFAULT 'owner',
    created_at  timestamptz NOT NULL DEFAULT now(),
    updated_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX music_picks_open ON music_picks (status) WHERE status = 'open';
