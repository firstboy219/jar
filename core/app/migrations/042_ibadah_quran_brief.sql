-- ADR-087 wave 1: prayer times (Kemenag, cached per city and day), the Qur'an (equran.id, cached per surah) and where the owner read
-- up to, and the morning brief.
CREATE TABLE prayer_days (
    city_id  text NOT NULL,
    day      date NOT NULL,
    times    jsonb NOT NULL,
    PRIMARY KEY (city_id, day)
);

CREATE TABLE quran_surah (
    nomor       int PRIMARY KEY CHECK (nomor BETWEEN 0 AND 114),   -- 0 = the list of all surahs
    data        jsonb NOT NULL,
    fetched_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE quran_reads (
    id      bigserial PRIMARY KEY,
    surah   int NOT NULL CHECK (surah BETWEEN 1 AND 114),
    ayah    int NOT NULL CHECK (ayah >= 1),
    at      timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX quran_reads_at ON quran_reads (at DESC);

CREATE TABLE briefs (
    day         date PRIMARY KEY,
    data        jsonb NOT NULL,
    sources     jsonb NOT NULL DEFAULT '[]'::jsonb,
    run_id      bigint,
    created_at  timestamptz NOT NULL DEFAULT now()
);
