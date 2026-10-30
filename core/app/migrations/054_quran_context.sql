-- ADR-087: the context of a verse (owner 2026-10-30: "fitur context knp ayat itu diturunkan dan pada saat apa rasulullah Saw saat itu").
-- The Kemenag tafsir of a surah, cached as fetched (equran.id), and the short summary of a verse's occasion drawn from that tafsir only.
CREATE TABLE quran_tafsir (
    nomor       int PRIMARY KEY CHECK (nomor BETWEEN 1 AND 114),
    data        jsonb NOT NULL,
    fetched_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE quran_context (
    surah       int NOT NULL CHECK (surah BETWEEN 1 AND 114),
    ayah        int NOT NULL CHECK (ayah BETWEEN 1 AND 286),
    data        jsonb NOT NULL,
    run_id      bigint,
    created_at  timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (surah, ayah)
);
