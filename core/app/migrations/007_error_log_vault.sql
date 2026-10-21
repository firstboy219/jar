-- Errors JARVIS' own services raise: visible to the owner and to the daily self-check (diagnosis).
CREATE TABLE error_log (
    id        bigserial PRIMARY KEY,
    at        timestamptz NOT NULL DEFAULT now(),
    source    text NOT NULL,
    logger    text,
    message   text NOT NULL,
    traceback text,
    signature text NOT NULL
);
CREATE INDEX error_log_sig_idx ON error_log (signature, at DESC);

-- Password manager (ADR-023): encrypted at rest with VAULT_KEY (AES-GCM); the owner's phone reads them
-- behind fingerprint; entries marked allow_agent are synced into Hermes' model-blind browser vault.
CREATE TABLE vault_entries (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    origin      text NOT NULL,                  -- https://host[:port]
    label       text NOT NULL,
    username    text NOT NULL,
    secret      bytea NOT NULL,                 -- nonce || AES-GCM(password)
    note        text NOT NULL DEFAULT '',
    allow_agent boolean NOT NULL DEFAULT false,
    created_at  timestamptz NOT NULL DEFAULT now(),
    updated_at  timestamptz NOT NULL DEFAULT now(),
    last_used   timestamptz
);
CREATE INDEX vault_origin_idx ON vault_entries (origin);
