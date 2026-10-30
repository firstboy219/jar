-- ADR-087 wave 5: money — what the owner spends (from GoPay/bank notifications, what JARVIS itself bought, what he adds), the salary
-- allocation per pay period; investing in Pluang (what JARVIS read from the app, its options, what he chose and what was done); coffee
-- (the promos JARVIS found, the offer, the order).
CREATE TABLE money_tx (
    id         bigserial PRIMARY KEY,
    at         timestamptz NOT NULL DEFAULT now(),
    amount     numeric NOT NULL CHECK (amount >= 0),
    direction  text NOT NULL CHECK (direction IN ('in', 'out')),
    merchant   text NOT NULL DEFAULT '',
    category   text NOT NULL DEFAULT 'lainnya',
    source     text NOT NULL CHECK (source IN ('notif', 'manual', 'jarvis')),
    app        text NOT NULL DEFAULT '',
    ref        text UNIQUE,                                 -- 'notif:123', 'coffee:5', 'invest:7' — never counted twice
    note       text NOT NULL DEFAULT '',
    labeled_by text NOT NULL DEFAULT 'aturan',              -- aturan | ai | pemilik
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX money_tx_at ON money_tx (at DESC);

CREATE TABLE money_plans (
    id           bigserial PRIMARY KEY,
    period_start date NOT NULL,
    data         jsonb NOT NULL,
    status       text NOT NULL DEFAULT 'proposed' CHECK (status IN ('proposed', 'applied', 'dismissed')),
    run_id       bigint,
    created_at   timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE invest_snapshots (
    id         bigserial PRIMARY KEY,
    at         timestamptz NOT NULL DEFAULT now(),
    data       jsonb NOT NULL,                              -- {total, cash, assets: [{nama, kode, jenis, jumlah, nilai, untung_pct, harga}]}
    run_id     bigint,
    task_id    bigint
);

CREATE TABLE invest_proposals (
    id           bigserial PRIMARY KEY,
    snapshot_id  bigint REFERENCES invest_snapshots(id) ON DELETE SET NULL,
    data         jsonb NOT NULL,                            -- {ringkasan, kondisi, opsi: [{id, judul, aksi: [{jenis, aset, nominal}], alasan, risiko}]}
    status       text NOT NULL DEFAULT 'new' CHECK (status IN ('new', 'running', 'done', 'failed', 'expired', 'dismissed')),
    chosen       text,
    decided_by   text,
    decided_at   timestamptz,
    exec_run_id  bigint,
    result       jsonb,
    run_id       bigint,
    created_at   timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE coffee_offers (
    id            bigserial PRIMARY KEY,
    status        text NOT NULL DEFAULT 'checking' CHECK (status IN ('checking', 'offered', 'ordering', 'ordered', 'declined', 'failed', 'expired')),
    promos        jsonb NOT NULL DEFAULT '[]'::jsonb,       -- [{app, menu, harga, harga_normal, voucher, syarat}]
    choice        jsonb,
    result        jsonb,
    check_run_id  bigint,
    order_run_id  bigint,
    trigger       text NOT NULL DEFAULT 'owner',
    created_at    timestamptz NOT NULL DEFAULT now(),
    updated_at    timestamptz NOT NULL DEFAULT now()
);
