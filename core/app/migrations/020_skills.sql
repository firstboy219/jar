-- Blueprint v2 Sprint 4 (ADR-040): skills JARVIS learns — drafted, validated, tested, then published, versioned and reversible.
CREATE TABLE skill_drafts (
    id          bigserial PRIMARY KEY,
    name        text NOT NULL,
    version     int NOT NULL,
    description text NOT NULL,
    content     text NOT NULL,                       -- the skill body (SKILL.md without front matter)
    scripts     jsonb NOT NULL DEFAULT '{}'::jsonb,  -- {"scripts/main.py": "…"}: pure helpers, stdlib only, run in the sandbox
    cases       jsonb NOT NULL DEFAULT '[]'::jsonb,  -- test cases
    status      text NOT NULL DEFAULT 'validating'
                CHECK (status IN ('validating', 'rejected', 'evaluating', 'sandbox_testing', 'failed_tests',
                                  'awaiting_approval', 'published', 'retired')),
    problems    jsonb NOT NULL DEFAULT '[]'::jsonb,  -- why it was rejected / which cases failed
    results     jsonb,                               -- evaluator / sandbox outcome per case
    author      text NOT NULL DEFAULT 'hermes',
    approval_id bigint,
    created_at  timestamptz NOT NULL DEFAULT now(),
    updated_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX skill_drafts_name ON skill_drafts (name, id DESC);

-- A reviewer that is not the author (cheap and different from the models that write skills and code); the owner can change it.
INSERT INTO llm_categories (name, title, description, routes, allow_free, confirm_cloud, worker, sort)
VALUES ('review', 'Peninjau (model berbeda)', 'Memeriksa kode, skill dan hasil kerja model lain.',
        '[{"provider": "openrouter", "model": "z-ai/glm-5.3-flash"}, {"provider": "lokal-kerja", "model": "qwen-lokal"}]'::jsonb,
        true, false, false, 150)
ON CONFLICT (name) DO NOTHING;
