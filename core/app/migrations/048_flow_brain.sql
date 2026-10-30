-- ADR-087 wave 7: the live flow (which brain version ran each job) and the brain workshop — versions of how a job is done (the lane, an
-- extra rule for its prompt, length, temperature; global thresholds), tried on real past inputs, rolled out to 10% first, rolled back
-- automatically when worse. Samples: the prompts of recent AI runs (not private ones), for replaying.
ALTER TABLE flow_runs ADD COLUMN brain_version bigint;

CREATE TABLE flow_samples (
    run_id      bigint PRIMARY KEY,                       -- no foreign key: kept per job by rotation, thinned with the runs
    feature     text NOT NULL,
    action      text NOT NULL,
    messages    jsonb NOT NULL,
    json_out    boolean NOT NULL DEFAULT false,
    result      jsonb,
    created_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX flow_samples_job ON flow_samples (feature, action, created_at DESC);

CREATE TABLE brain_versions (
    id           bigserial PRIMARY KEY,
    job          text NOT NULL DEFAULT '',                -- 'feature:action', or '' for the global thresholds
    config       jsonb NOT NULL,
    request      text NOT NULL DEFAULT '',                -- what the owner asked for, in his words
    note         text NOT NULL DEFAULT '',                -- why (the heavy brain's reasoning, or the owner's note)
    status       text NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'canary', 'active', 'retired', 'rolled_back')),
    canary_pct   int NOT NULL DEFAULT 10 CHECK (canary_pct BETWEEN 1 AND 100),
    parent_id    bigint,
    eval         jsonb,
    created_by   text NOT NULL DEFAULT 'owner',
    created_at   timestamptz NOT NULL DEFAULT now(),
    activated_at timestamptz,
    decided_at   timestamptz
);
CREATE UNIQUE INDEX brain_versions_one_active ON brain_versions (job) WHERE status = 'active';
CREATE UNIQUE INDEX brain_versions_one_canary ON brain_versions (job) WHERE status = 'canary';
