-- Blueprint v4 Fase 6 (ADR-044, ADR-045): Gmail + calendar through n8n (Propose; sending / writing needs the owner's approval)
-- and watchers (prices, tickets, crypto, gold: notify only, never buy, never advice).
ALTER TABLE tasks DROP CONSTRAINT IF EXISTS tasks_kind_check;
ALTER TABLE tasks ADD CONSTRAINT tasks_kind_check
    CHECK (kind IN ('owner', 'situation', 'routine', 'selfcheck', 'meeting', 'selfimprove', 'flowcheck', 'watcher'));

-- What the inbox check saw: sender, subject and a short snippet only (never the whole mail); anything that looks sensitive is not kept.
CREATE TABLE mail_items (
    id          bigserial PRIMARY KEY,
    ext_id      text NOT NULL UNIQUE,                 -- Gmail message id
    thread_id   text,
    sender      text NOT NULL DEFAULT '',
    sender_addr text NOT NULL DEFAULT '',
    subject     text NOT NULL DEFAULT '',
    snippet     text NOT NULL DEFAULT '',
    sensitive   boolean NOT NULL DEFAULT false,
    received_at timestamptz,
    importance  text NOT NULL DEFAULT 'biasa' CHECK (importance IN ('penting', 'biasa', 'abaikan')),
    summary     text,
    status      text NOT NULL DEFAULT 'new' CHECK (status IN ('new', 'told', 'replied', 'dismissed')),
    fetched_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX mail_items_status ON mail_items (status, id DESC);

-- Everything that would leave JARVIS: an email to send, an event to write. A draft waits; only an approved one is posted, once.
CREATE TABLE outbox (
    id              bigserial PRIMARY KEY,
    kind            text NOT NULL CHECK (kind IN ('email', 'event')),
    status          text NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'awaiting_approval', 'sent', 'failed', 'rejected')),
    to_addr         text,
    subject         text,
    body            text,
    in_reply_to     text,                              -- mail_items.ext_id
    thread_id       text,
    title           text,                              -- event
    start_at        timestamptz,
    end_at          timestamptz,
    attendees       jsonb NOT NULL DEFAULT '[]'::jsonb,
    location        text,
    approval_id     bigint,
    result          jsonb,
    error           text,
    created_at      timestamptz NOT NULL DEFAULT now(),
    sent_at         timestamptz
);

CREATE TABLE watchers (
    id            bigserial PRIMARY KEY,
    kind          text NOT NULL CHECK (kind IN ('kripto', 'emas', 'harga', 'tiket')),
    label         text NOT NULL,
    query         text NOT NULL,                       -- kripto: a CoinGecko id; others: what to look up
    op            text NOT NULL CHECK (op IN ('<=', '>=', 'berubah')),
    threshold     numeric NOT NULL,                    -- a price, or for 'berubah' a percentage
    every_min     int NOT NULL,
    active        boolean NOT NULL DEFAULT true,
    last_checked  timestamptz,
    last_value    numeric,
    last_state    boolean,                             -- was the condition met at the last check
    last_alert_at timestamptz,
    last_alert_value numeric,
    last_note     text,
    pending_task  bigint,                              -- a web check in flight
    created_at    timestamptz NOT NULL DEFAULT now()
);
