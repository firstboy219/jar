-- Blueprint v4 Fase 4 (ADR-049): the 3D canvas — one "galaxy" per context (utama, each project, each company).
-- A canvas stores LAYOUT, never knowledge: each card is a reference ('<type>:<id>') to something that lives elsewhere
-- (a memory, a task, a document, something shown, a company vault entry…), resolved when the canvas is read.
-- Company canvases sit under the same row-level security as the company tables (ADR-042): a company's galaxy is only
-- visible inside that company's scope, and a card can only reference that company's own things.

CREATE TABLE canvases (
    id          bigserial PRIMARY KEY,
    context     text NOT NULL UNIQUE CHECK (context ~ '^(utama|project:[a-z0-9][a-z0-9-]{0,59}|company:[a-z][a-z0-9-]{1,40})$'),
    title       text NOT NULL,
    company_id  text REFERENCES companies(id) ON DELETE CASCADE,
    version     int NOT NULL DEFAULT 0,
    focus_node  bigint,                               -- JARVIS asked the viewers to fly here
    created_at  timestamptz NOT NULL DEFAULT now(),
    updated_at  timestamptz NOT NULL DEFAULT now(),
    CHECK ((company_id IS NULL AND context NOT LIKE 'company:%') OR context = 'company:' || company_id)
);

CREATE TABLE canvas_nodes (
    id          bigserial PRIMARY KEY,
    canvas_id   bigint NOT NULL REFERENCES canvases(id) ON DELETE CASCADE,
    company_id  text REFERENCES companies(id) ON DELETE CASCADE,   -- = the canvas's company (for row-level security)
    kind        text NOT NULL,                                     -- the constellation it belongs to (tugas, dokumen, …)
    ref         text NOT NULL CHECK (ref ~ '^[a-z]+:[0-9A-Za-z-]{1,64}$'),
    x           real NOT NULL DEFAULT 0,
    y           real NOT NULL DEFAULT 0,
    z           real NOT NULL DEFAULT 0,
    size        real NOT NULL DEFAULT 1 CHECK (size BETWEEN 0.3 AND 4),
    pinned      boolean NOT NULL DEFAULT false,
    created_by  text NOT NULL DEFAULT 'jarvis',
    created_at  timestamptz NOT NULL DEFAULT now(),
    updated_at  timestamptz NOT NULL DEFAULT now(),
    UNIQUE (canvas_id, ref)
);

CREATE TABLE canvas_edges (
    id          bigserial PRIMARY KEY,
    canvas_id   bigint NOT NULL REFERENCES canvases(id) ON DELETE CASCADE,
    company_id  text REFERENCES companies(id) ON DELETE CASCADE,
    a           bigint NOT NULL REFERENCES canvas_nodes(id) ON DELETE CASCADE,
    b           bigint NOT NULL REFERENCES canvas_nodes(id) ON DELETE CASCADE,
    label       text NOT NULL DEFAULT '' CHECK (length(label) <= 60),
    created_at  timestamptz NOT NULL DEFAULT now(),
    CHECK (a <> b),
    UNIQUE (a, b)
);

-- Layout history: every change is a version; restoring brings positions/links back (cards whose thing is gone stay gone).
CREATE TABLE canvas_versions (
    canvas_id   bigint NOT NULL REFERENCES canvases(id) ON DELETE CASCADE,
    version     int NOT NULL,
    company_id  text REFERENCES companies(id) ON DELETE CASCADE,
    snapshot    jsonb NOT NULL,
    actor       text NOT NULL,
    change      text NOT NULL DEFAULT '',
    at          timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (canvas_id, version)
);

ALTER TABLE canvases ENABLE ROW LEVEL SECURITY;
ALTER TABLE canvases FORCE ROW LEVEL SECURITY;
CREATE POLICY canvases_isolation ON canvases
    USING (company_id IS NULL OR company_id = current_setting('jarvis.company', true))
    WITH CHECK (company_id IS NULL OR company_id = current_setting('jarvis.company', true));
ALTER TABLE canvas_nodes ENABLE ROW LEVEL SECURITY;
ALTER TABLE canvas_nodes FORCE ROW LEVEL SECURITY;
CREATE POLICY canvas_nodes_isolation ON canvas_nodes
    USING (company_id IS NULL OR company_id = current_setting('jarvis.company', true))
    WITH CHECK (company_id IS NULL OR company_id = current_setting('jarvis.company', true));
ALTER TABLE canvas_edges ENABLE ROW LEVEL SECURITY;
ALTER TABLE canvas_edges FORCE ROW LEVEL SECURITY;
CREATE POLICY canvas_edges_isolation ON canvas_edges
    USING (company_id IS NULL OR company_id = current_setting('jarvis.company', true))
    WITH CHECK (company_id IS NULL OR company_id = current_setting('jarvis.company', true));
ALTER TABLE canvas_versions ENABLE ROW LEVEL SECURITY;
ALTER TABLE canvas_versions FORCE ROW LEVEL SECURITY;
CREATE POLICY canvas_versions_isolation ON canvas_versions
    USING (company_id IS NULL OR company_id = current_setting('jarvis.company', true))
    WITH CHECK (company_id IS NULL OR company_id = current_setting('jarvis.company', true));
