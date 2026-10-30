-- ADR-087 wave 4: the owner's businesses (Autotoko, Renature, …) read from their own APIs — the sources he enters in the app (keys kept
-- encrypted), what each poll read (snapshots, for "how far along are we by this hour"), one number per business, metric and day (the
-- trends), and what JARVIS concluded (alerts, strategies, opportunities).
CREATE TABLE biz_sources (
    id          bigserial PRIMARY KEY,
    business    text NOT NULL,                              -- 'Autotoko', 'Renature', …
    name        text NOT NULL,                              -- 'Autotoko API', 'Shopee Partner', …
    base_url    text NOT NULL,
    auth        jsonb NOT NULL DEFAULT '{"type": "none"}'::jsonb,   -- {type: none|bearer|header|query|basic, name}; the key itself is in `secret`
    secret      bytea,                                      -- vault-encrypted key / token / "user:password"
    headers     jsonb NOT NULL DEFAULT '{}'::jsonb,         -- extra fixed headers (no secrets)
    endpoints   jsonb NOT NULL DEFAULT '[]'::jsonb,         -- [{metric, unit, method, path, params, items, value, filter, agg, mode, date, split, page}]
    poll_min    int NOT NULL DEFAULT 15 CHECK (poll_min BETWEEN 5 AND 1440),
    status      text NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'paused')),
    last_poll   timestamptz,
    last_ok     timestamptz,
    last_error  text,
    fails       int NOT NULL DEFAULT 0,
    backfilled  timestamptz,
    created_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE biz_snapshots (
    id         bigserial PRIMARY KEY,
    source_id  bigint NOT NULL REFERENCES biz_sources(id) ON DELETE CASCADE,
    business   text NOT NULL,
    metric     text NOT NULL,                               -- 'penjualan', 'pesanan', 'dikemas', 'pencairan', 'penjualan@Shopee', custom …
    value      numeric NOT NULL,
    at         timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX biz_snapshots_lookup ON biz_snapshots (business, metric, at DESC);

CREATE TABLE biz_daily (
    business   text NOT NULL,
    metric     text NOT NULL,
    day        date NOT NULL,
    value      numeric NOT NULL,
    unit       text NOT NULL DEFAULT 'n',
    source_id  bigint REFERENCES biz_sources(id) ON DELETE SET NULL,
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (business, metric, day)
);

CREATE TABLE biz_insights (
    id          bigserial PRIMARY KEY,
    kind        text NOT NULL CHECK (kind IN ('alert', 'strategy', 'opportunity')),
    business    text NOT NULL DEFAULT '',
    key         text NOT NULL DEFAULT '',                   -- an alert's once-a-day key
    data        jsonb NOT NULL,
    run_id      bigint,
    status      text NOT NULL DEFAULT 'new' CHECK (status IN ('new', 'seen', 'saved', 'dismissed')),
    created_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX biz_insights_kind ON biz_insights (kind, created_at DESC);
CREATE UNIQUE INDEX biz_insights_alert_once ON biz_insights (key) WHERE key <> '';
