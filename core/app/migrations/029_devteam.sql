-- Blueprint v4 Fase 12 (ADR-059): the dev team — three named workers for JARVIS' own development. bisan (business/system analyst) turns
-- the owner's request into a spec with acceptance criteria, coder builds it and proposes the change, qaqa (QA) reviews the real diff and
-- the runner's test result against the spec and sends it back to coder until it is clean. Each has its own model category.
ALTER TABLE tasks DROP CONSTRAINT IF EXISTS tasks_kind_check;
ALTER TABLE tasks ADD CONSTRAINT tasks_kind_check
    CHECK (kind IN ('owner', 'situation', 'routine', 'selfcheck', 'meeting', 'selfimprove', 'flowcheck', 'watcher', 'devteam'));

CREATE TABLE dev_jobs (
    id          serial PRIMARY KEY,
    request     text NOT NULL,
    status      text NOT NULL DEFAULT 'analysing'
                CHECK (status IN ('analysing', 'coding', 'testing', 'reviewing', 'awaiting_owner', 'done', 'failed', 'cancelled')),
    spec        text,
    branch      text,
    change_id   int,
    round       int NOT NULL DEFAULT 0,       -- how many times coder has built it (a QA "perbaiki" sends it back)
    review      text,                         -- qaqa's latest review
    note        text,                         -- why it stopped, or what the owner should do
    created_by  text NOT NULL DEFAULT 'owner',
    created_at  timestamptz NOT NULL DEFAULT now(),
    updated_at  timestamptz NOT NULL DEFAULT now()
);

ALTER TABLE tasks ADD COLUMN dev_job int REFERENCES dev_jobs(id) ON DELETE SET NULL;
ALTER TABLE tasks ADD COLUMN dev_role text CHECK (dev_role IS NULL OR dev_role IN ('bisan', 'coder', 'qaqa'));
CREATE INDEX tasks_dev_job ON tasks (dev_job) WHERE dev_job IS NOT NULL;

-- one model category per member, starting from what the coding workers use (the owner switches each on the desk)
INSERT INTO llm_categories (name, title, description, routes, budget_usd, allow_free, confirm_cloud, worker, sort, paid_attempt_limit, max_retries)
SELECT v.name, v.title, v.description, c.routes, c.budget_usd, c.allow_free, c.confirm_cloud, true, c.sort + v.n, c.paid_attempt_limit, c.max_retries
FROM llm_categories c,
     (VALUES ('dev-bisan', 'Tim dev · bisan', 'Analis bisnis/sistem tim dev: memahami permintaan, menulis spesifikasi dan kriteria terima', 1),
             ('dev-coder', 'Tim dev · coder', 'Developer ahli tim dev: menulis kode, menguji, mengusulkan perubahan', 2),
             ('dev-qaqa',  'Tim dev · qaqa',  'QA tim dev: memeriksa diff dan hasil tes terhadap spesifikasi', 3)) AS v(name, title, description, n)
WHERE c.name = 'coding'
ON CONFLICT (name) DO NOTHING;
