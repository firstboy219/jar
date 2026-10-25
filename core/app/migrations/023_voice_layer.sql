-- Blueprint v4 Fase 3 (ADR-048): complements around the speech engines (Whisper/Groq/Deepgram/OpenRouter stay).
-- Every utterance leaves one row here, so the error rate can be measured before anything is "improved", and every
-- complement (dictionary, learned hallucinations, echo filter, second opinion, calibrated threshold) is judged on the
-- owner's own corrections. Audio is kept ONLY with the owner's consent (K3, admin page) and never leaves this server.

CREATE TABLE voice_events (
    id               bigserial PRIMARY KEY,
    at               timestamptz NOT NULL DEFAULT now(),
    session_id       text,
    engine           text NOT NULL,                  -- whisper | groq | deepgram | openrouter
    model            text,                           -- the OpenRouter model, when engine = openrouter
    confidence       real,
    stt_ms           int,
    raw_text         text NOT NULL DEFAULT '',       -- what the engine heard ("[disensor]" when it held a secret)
    final_text       text NOT NULL DEFAULT '',       -- what JARVIS acted on, after the complements that are ON
    applied          jsonb NOT NULL DEFAULT '[]',    -- [{complement, before, after}] that changed final_text
    shadow           jsonb NOT NULL DEFAULT '[]',    -- what complements still under test WOULD have done
    second_opinion   jsonb,                          -- {engine, text, confidence, chosen}
    dropped          text,                           -- why the utterance was dropped (hallucination, echo, …)
    reference        text,                           -- what the owner really said (from a correction)
    reference_source text,                           -- owner_chat | owner_app | admin
    error_kind       text,                           -- taxonomy: nama | angka | istilah | gema | halusinasi | derau | lainnya
    audio_kept       boolean NOT NULL DEFAULT false  -- /data/voice/<id>.pcm exists (consent K3)
);
CREATE INDEX voice_events_at ON voice_events (at DESC);
CREATE INDEX voice_events_reference ON voice_events (id) WHERE reference IS NOT NULL;

-- Learned data, versioned row by row: a change is a new row, an undo marks it inactive (never a silent overwrite).
CREATE TABLE voice_data (
    id          bigserial PRIMARY KEY,
    kind        text NOT NULL CHECK (kind IN ('lexicon', 'pronounce', 'hallucination')),
    key         text NOT NULL CHECK (key <> ''),    -- lexicon: the misheard words · pronounce: the written word · hallucination: the phrase
    value       text NOT NULL DEFAULT '',           -- lexicon: the meant words · pronounce: how to say it
    source      text NOT NULL DEFAULT 'owner',      -- owner_chat | admin | learned
    active      boolean NOT NULL DEFAULT true,
    hits        int NOT NULL DEFAULT 0,
    event_id    bigint,                             -- the corrected utterance it was learned from (left out when judging it)
    created_at  timestamptz NOT NULL DEFAULT now(),
    removed_at  timestamptz,
    removed_by  text
);
CREATE UNIQUE INDEX voice_data_active ON voice_data (kind, lower(key)) WHERE active;
