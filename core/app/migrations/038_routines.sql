-- Blueprint v4 Fase 12 (ADR-083): how a phone task was done becomes a ROUTINE — a small program of taps, typing, waits, reads and checks
-- that is replayed without AI next time; AI only for the steps that need judgement (which place, what to tell the driver …).
CREATE TABLE routines (
    id          serial PRIMARY KEY,
    app         text NOT NULL,
    name        text NOT NULL,
    intent      text NOT NULL,              -- the request it was learned from
    pattern     text NOT NULL DEFAULT '',   -- that request without its particulars ("Pesan GoRide dari {asal} ke {tujuan}") — matched by meaning
    keys        jsonb NOT NULL DEFAULT '[]'::jsonb,   -- words a request of this kind always has ("goride"): the first, sure way to recognise it
    embedding   real[],                     -- of `pattern`
    params      jsonb NOT NULL DEFAULT '{}'::jsonb,   -- name → what it means ("tujuan": "alamat tujuan")
    steps       jsonb NOT NULL,             -- the program (routines.OPS)
    needs       jsonb NOT NULL DEFAULT '[]'::jsonb,   -- what the owner wants, as learned (also saved as preference memories)
    version     int NOT NULL DEFAULT 1,
    status      text NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'off')),
    runs        int NOT NULL DEFAULT 0,
    ok_runs     int NOT NULL DEFAULT 0,
    fail_streak int NOT NULL DEFAULT 0,
    auto_steps  int NOT NULL DEFAULT 0,     -- over all runs: steps done without AI …
    ai_steps    int NOT NULL DEFAULT 0,     -- … and with AI
    source_task bigint,
    created_at  timestamptz NOT NULL DEFAULT now(),
    updated_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX routines_app ON routines (app, status);
