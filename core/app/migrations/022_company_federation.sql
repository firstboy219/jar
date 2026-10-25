-- Blueprint v4 Fase 1 (ADR-042, ADR-046): Company Federation — companies, their vaults, decisions, relations, directives.
-- Isolation is enforced by Postgres itself (row-level security, FORCE'd so the owning role obeys it too): a session sees a
-- company's rows only after `SET LOCAL jarvis.company = '<id>'` inside its transaction (core/app/companies.py does that);
-- without it every company table looks empty. Hermes' read-only SQL role (jarvis_ro) is never granted these tables.

CREATE TABLE companies (
    id                   text PRIMARY KEY CHECK (id ~ '^[a-z][a-z0-9-]{1,40}$'),
    name                 text NOT NULL,
    aliases              text[] NOT NULL DEFAULT '{}',          -- lower-case names the router recognises ("renature", "pt renature")
    active               boolean NOT NULL DEFAULT true,
    adapter              text NOT NULL DEFAULT 'mock' CHECK (adapter IN ('mock', 'http')),
    dgm_url              text,                                   -- Hermes-DGM base URL (contract NOT verified yet)
    dgm_token_enc        bytea,                                  -- AES-GCM (vault key); never shown, never sent to a model
    callback_secret_enc  bytea,                                  -- HMAC key Hermes-DGM signs callbacks with
    contract_verified    boolean NOT NULL DEFAULT false,         -- the owner confirmed the real API matches the adapter
    callback_timeout_s   int NOT NULL DEFAULT 1800 CHECK (callback_timeout_s BETWEEN 60 AND 604800),
    max_retries          int NOT NULL DEFAULT 2 CHECK (max_retries BETWEEN 0 AND 10),
    budget_usd_month     numeric(12,2),                          -- spend a directive may commit per month without asking
    created_at           timestamptz NOT NULL DEFAULT now(),
    updated_at           timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE company_vault (
    id          bigserial PRIMARY KEY,
    company_id  text NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    kind        text NOT NULL CHECK (kind IN ('core_constraint', 'strategic_pivot', 'validated_finding', 'kpi', 'cashflow', 'note')),
    title       text NOT NULL,
    body        text NOT NULL DEFAULT '',
    data        jsonb,                                           -- KPI / cash-flow figures: {"metric","value","unit","period"} …
    source      text NOT NULL DEFAULT 'owner',
    verified    boolean NOT NULL DEFAULT false,
    created_at  timestamptz NOT NULL DEFAULT now(),
    updated_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX company_vault_company ON company_vault (company_id, kind, updated_at DESC);

-- Decision Vault: per project or company (entity_type + entity_id), the four categories of the blueprint.
CREATE TABLE decision_vault (
    id             bigserial PRIMARY KEY,
    entity_type    text NOT NULL CHECK (entity_type IN ('project', 'company')),
    entity_id      text NOT NULL CHECK (entity_id <> ''),
    company_id     text REFERENCES companies(id) ON DELETE CASCADE,   -- = entity_id for companies; NULL for personal projects
    kind           text NOT NULL CHECK (kind IN ('core_constraint', 'correction_pivot', 'validated_finding', 'tech_preference')),
    text           text NOT NULL,
    source         text NOT NULL DEFAULT 'owner',
    superseded_by  bigint,
    created_at     timestamptz NOT NULL DEFAULT now(),
    CHECK (entity_type <> 'company' OR company_id = entity_id)
);
CREATE INDEX decision_vault_entity ON decision_vault (entity_type, entity_id, created_at DESC);

-- Relations between entities (owner, brand, company, product, project, person). A graph database only if this proves short (ADR-046).
CREATE TABLE entity_relations (
    id            bigserial PRIMARY KEY,
    subject_type  text NOT NULL,
    subject_id    text NOT NULL,
    relation      text NOT NULL,
    object_type   text NOT NULL,
    object_id     text NOT NULL,
    company_id    text REFERENCES companies(id) ON DELETE CASCADE,  -- set when the relation belongs to one company
    source        text NOT NULL DEFAULT 'owner',
    created_at    timestamptz NOT NULL DEFAULT now(),
    UNIQUE (subject_type, subject_id, relation, object_type, object_id)
);

-- Jarvis-GM's directives to a company's Hermes-DGM. task_key is the idempotency key sent along every (re)try.
CREATE TABLE gm_directives (
    id                       bigserial PRIMARY KEY,
    company_id               text NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    task_key                 uuid NOT NULL UNIQUE,
    action                   text NOT NULL,
    instruction              text NOT NULL,
    constraints              jsonb NOT NULL DEFAULT '{}'::jsonb,
    external_effect          boolean NOT NULL DEFAULT false,    -- spends money, publishes, or messages someone outside
    requires_owner_approval  boolean NOT NULL DEFAULT false,
    status                   text NOT NULL DEFAULT 'draft' CHECK (status IN (
                                 'draft', 'awaiting_owner', 'queued', 'sent', 'acknowledged', 'callback_received',
                                 'awaiting_owner_result', 'completed', 'rejected', 'failed', 'timed_out', 'cancelled')),
    attempts                 int NOT NULL DEFAULT 0,
    next_attempt_at          timestamptz,
    deadline                 timestamptz,
    response                 jsonb,
    callback                 jsonb,
    seen_callbacks           text[] NOT NULL DEFAULT '{}',      -- callback ids already processed (replays are ignored)
    approval_id              bigint,
    error                    text,
    session_id               text,
    created_at               timestamptz NOT NULL DEFAULT now(),
    updated_at               timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX gm_directives_due ON gm_directives (status, next_attempt_at);

-- A task done for one company carries it, so the worker only ever sees that company's context.
ALTER TABLE tasks ADD COLUMN company_id text;
ALTER TABLE episodes ADD COLUMN company_id text;   -- a company's experience never feeds another company's task

-- Row-level security: the company comes from the transaction setting, nothing else.
ALTER TABLE company_vault ENABLE ROW LEVEL SECURITY;
ALTER TABLE company_vault FORCE ROW LEVEL SECURITY;
CREATE POLICY company_vault_isolation ON company_vault
    USING (company_id = current_setting('jarvis.company', true))
    WITH CHECK (company_id = current_setting('jarvis.company', true));

ALTER TABLE decision_vault ENABLE ROW LEVEL SECURITY;
ALTER TABLE decision_vault FORCE ROW LEVEL SECURITY;
CREATE POLICY decision_vault_isolation ON decision_vault
    USING (company_id IS NULL OR company_id = current_setting('jarvis.company', true))
    WITH CHECK (company_id IS NULL OR company_id = current_setting('jarvis.company', true));

ALTER TABLE entity_relations ENABLE ROW LEVEL SECURITY;
ALTER TABLE entity_relations FORCE ROW LEVEL SECURITY;
CREATE POLICY entity_relations_isolation ON entity_relations
    USING (company_id IS NULL OR company_id = current_setting('jarvis.company', true))
    WITH CHECK (company_id IS NULL OR company_id = current_setting('jarvis.company', true));

ALTER TABLE gm_directives ENABLE ROW LEVEL SECURITY;
ALTER TABLE gm_directives FORCE ROW LEVEL SECURITY;
CREATE POLICY gm_directives_isolation ON gm_directives
    USING (company_id = current_setting('jarvis.company', true))
    WITH CHECK (company_id = current_setting('jarvis.company', true));
