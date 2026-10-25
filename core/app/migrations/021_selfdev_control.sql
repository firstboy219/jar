-- Blueprint v4 Fase 0 (ADR-047): the control point. What the runner found in the real diff, and T2 designs.
ALTER TABLE dev_changes
    ADD COLUMN tier      int,
    ADD COLUMN verdict   jsonb,      -- selfdev_policy's judgement of the real diff (files, lines, tier, reasons)
    ADD COLUMN tests     text,       -- test summary written by the runner, not by JARVIS
    ADD COLUMN design_id bigint;
-- T2: a design is approved at the admin page BEFORE the work; the result is approved again (two approvals, K2).
CREATE TABLE dev_designs (
    id          bigserial PRIMARY KEY,
    title       text NOT NULL,
    plan        text NOT NULL,
    scope       text[] NOT NULL DEFAULT '{}',   -- files/areas JARVIS intends to change
    status      text NOT NULL DEFAULT 'awaiting_approval'
                CHECK (status IN ('awaiting_approval', 'approved', 'rejected', 'used')),
    approval_id bigint,
    task_id     bigint,
    created_at  timestamptz NOT NULL DEFAULT now(),
    updated_at  timestamptz NOT NULL DEFAULT now()
);
