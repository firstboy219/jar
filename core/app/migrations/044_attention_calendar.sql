-- ADR-087 wave 3: "Perlu perhatian" — email (Outlook, Gmail) and WhatsApp in one list, triaged; the owner's calendar; a meeting's live
-- transcript and what it decided so far.
CREATE TABLE inbox_items (
    id           bigserial PRIMARY KEY,
    source       text NOT NULL CHECK (source IN ('outlook', 'gmail', 'whatsapp')),
    ext_id       text NOT NULL,
    thread       text NOT NULL DEFAULT '',
    sender       text NOT NULL DEFAULT '',
    sender_addr  text NOT NULL DEFAULT '',
    subject      text NOT NULL DEFAULT '',
    snippet      text NOT NULL DEFAULT '',
    received_at  timestamptz,
    triage       text NOT NULL DEFAULT 'new' CHECK (triage IN ('new', 'needs', 'fyi', 'ignore')),
    reason       text NOT NULL DEFAULT '',
    topic        text NOT NULL DEFAULT '',        -- the same matter across sources ("Sari · vendor event") groups them
    due          text NOT NULL DEFAULT '',
    replies      jsonb NOT NULL DEFAULT '[]'::jsonb,
    task         text NOT NULL DEFAULT '',
    flagged      boolean NOT NULL DEFAULT false,
    link         text NOT NULL DEFAULT '',
    status       text NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'done', 'snoozed')),
    draft        jsonb,
    data         jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at   timestamptz NOT NULL DEFAULT now(),
    UNIQUE (source, ext_id)
);
CREATE INDEX inbox_items_recent ON inbox_items (received_at DESC);
CREATE INDEX inbox_items_triage ON inbox_items (triage, status);

CREATE TABLE calendar_events (
    id         bigserial PRIMARY KEY,
    source     text NOT NULL,
    ext_id     text NOT NULL,
    title      text NOT NULL,
    start_at   timestamptz NOT NULL,
    end_at     timestamptz NOT NULL,
    location   text NOT NULL DEFAULT '',
    attendees  jsonb NOT NULL DEFAULT '[]'::jsonb,
    online     boolean NOT NULL DEFAULT false,
    data       jsonb NOT NULL DEFAULT '{}'::jsonb,
    UNIQUE (source, ext_id)
);
CREATE INDEX calendar_events_start ON calendar_events (start_at);

ALTER TABLE meetings ADD COLUMN live jsonb NOT NULL DEFAULT '{}'::jsonb;   -- {transcript: [{n, text}], keputusan: [], tugas: [], at}
