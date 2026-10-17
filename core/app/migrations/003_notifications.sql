-- Phone notifications forwarded by the app (opt-in) and how JARVIS triaged them. Kept 7 days.
CREATE TABLE notifications (
    id         bigserial PRIMARY KEY,
    device_id  uuid REFERENCES devices(id) ON DELETE SET NULL,
    app        text NOT NULL,
    package    text NOT NULL,
    title      text NOT NULL DEFAULT '',
    text       text NOT NULL DEFAULT '',
    sensitive  boolean NOT NULL DEFAULT false,   -- content withheld from the cloud model
    posted_at  timestamptz NOT NULL,
    received_at timestamptz NOT NULL DEFAULT now(),
    decision   text CHECK (decision IN ('skip', 'announce', 'urgent')),
    spoken     text
);
CREATE INDEX notifications_received_idx ON notifications (received_at DESC);
