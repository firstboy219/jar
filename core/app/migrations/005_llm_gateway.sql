-- LLM gateway (ADR-017): every model call goes through jarvis-core, which picks the AI per category
-- from the owner's composition, fails over before the first byte, enforces the budget and logs cost.

CREATE TABLE llm_providers (
    name      text PRIMARY KEY,
    base_url  text NOT NULL,
    key_env   text NOT NULL DEFAULT '',      -- name of the .env variable holding the key ('' = none needed)
    cloud     boolean NOT NULL DEFAULT true, -- false: runs on this server (never leaves it)
    enabled   boolean NOT NULL DEFAULT true,
    vision    boolean NOT NULL DEFAULT true  -- can it read images (local llama.cpp without mmproj cannot)
);

INSERT INTO llm_providers (name, base_url, key_env, cloud, vision) VALUES
    ('lokal',       'http://llama-chat:8080/v1',          '',                   false, false),
    ('lokal-kerja', 'http://llama-worker:8080/v1',        '',                   false, false),
    ('openrouter',  'https://openrouter.ai/api/v1',       'OPENROUTER_API_KEY', true,  true),
    ('groq',        'https://api.groq.com/openai/v1',     'GROQ_API_KEY',       true,  false);

-- routes: ordered [{"provider": "...", "model": "..."}]; the last resort is always the local model.
CREATE TABLE llm_categories (
    name          text PRIMARY KEY,
    title         text NOT NULL,
    description   text NOT NULL,             -- the main agent reads this to choose a category
    routes        jsonb NOT NULL DEFAULT '[]',
    budget_usd    numeric(8, 2),             -- monthly cap for this category (null = only the total cap)
    allow_free    boolean NOT NULL DEFAULT true,  -- may use ':free' models (providers may log prompts)
    confirm_cloud boolean NOT NULL DEFAULT false, -- owner confirms before content goes to a cloud model
    worker        boolean NOT NULL DEFAULT false, -- a Hermes task category
    sort          int NOT NULL DEFAULT 100
);

INSERT INTO llm_categories (name, title, description, allow_free, confirm_cloud, worker, sort) VALUES
    ('ngobrol',        'Ngobrol',          'Agen utama: percakapan suara dengan pemilik.', true, false, false, 10),
    ('cepat',          'Cepat',            'Tugas kecil: memilah notifikasi, merangkai kalimat laporan, menilai situasi.', true, false, false, 20),
    ('penglihatan',    'Penglihatan',      'Membaca gambar kamera / layar.', true, false, false, 30),
    ('web',            'Cek web & riset',  'Mencari dan membaca informasi di internet, merangkum sumber.', true, false, true, 40),
    ('coding',         'Coding',           'Menulis/memperbaiki kode, script, workflow n8n.', true, false, true, 50),
    ('produktivitas',  'Produktivitas',    'Dokumen, email, ringkasan, jadwal, notulen.', true, false, true, 60),
    ('analisis',       'Analisis',         'Penalaran berat: membandingkan, merencanakan, memutuskan (Mode Kuat).', true, false, true, 70),
    ('balas-pesan',    'Balas pesan',      'Menyusun draf balasan WhatsApp/email dari layar pemilik.', false, true, false, 80),
    ('rapat',          'Rapat',            'Meringkas rapat menjadi notulen dan action item.', false, false, false, 90),
    ('latar-belakang', 'Latar belakang',   'Cek diri, belajar kebiasaan, konsolidasi memori (boleh lambat).', true, false, true, 100),
    ('privat',         'Privat',           'Pesan /privat dan data sensitif — selalu model lokal.', false, false, true, 110);

-- Factory default = "Lokal penuh" (owner decision 2026-10-21): every category on the local model.
UPDATE llm_categories SET routes = '[{"provider": "lokal", "model": "qwen-lokal"}]'
    WHERE name IN ('ngobrol', 'cepat', 'penglihatan', 'balas-pesan');
UPDATE llm_categories SET routes = '[{"provider": "lokal-kerja", "model": "qwen-lokal"}]'
    WHERE routes = '[]';

CREATE TABLE llm_usage (
    id                bigserial PRIMARY KEY,
    at                timestamptz NOT NULL DEFAULT now(),
    category          text NOT NULL,
    caller            text NOT NULL,          -- chat | hermes | awareness | selfcheck | meeting | ...
    provider          text NOT NULL,
    model             text NOT NULL,
    prompt_tokens     int,
    cached_tokens     int,
    completion_tokens int,
    cost_usd          numeric(12, 6) NOT NULL DEFAULT 0,
    latency_ms        int,
    first_token_ms    int,
    ok                boolean NOT NULL,
    error             text,
    session_id        text
);
CREATE INDEX llm_usage_at_idx ON llm_usage (at DESC);
CREATE INDEX llm_usage_cat_idx ON llm_usage (category, at DESC);

-- Device tokens get a scope: 'owner' devices are the full console (approvals, settings, composition).
ALTER TABLE devices ADD COLUMN scope text NOT NULL DEFAULT 'owner' CHECK (scope IN ('owner', 'basic'));

-- Turns answered by the local model only (/privat, sensitive content): never replayed to a cloud model.
ALTER TABLE messages DROP CONSTRAINT messages_route_check;
ALTER TABLE messages ADD CONSTRAINT messages_route_check
    CHECK (route IN ('core', 'hermes', 'assistant', 'report', 'blocked', 'error', 'proactive', 'silent', 'private'));

-- Per-turn latency trace (BR-001): {"stt_ms", "first_token_ms", "first_say_ms", "total_ms", ...}
ALTER TABLE messages ADD COLUMN trace jsonb;

-- Worker tasks know their category (which AI) and whether they carry private content (local only).
ALTER TABLE tasks ADD COLUMN category text NOT NULL DEFAULT 'web';
ALTER TABLE tasks ADD COLUMN private boolean NOT NULL DEFAULT false;
ALTER TABLE tasks ADD COLUMN hermes_run text;

-- Hermes can ask the owner a question mid-task (ask_owner); the main agent relays the answer.
CREATE TABLE owner_questions (
    id          bigserial PRIMARY KEY,
    task_id     bigint REFERENCES tasks(id) ON DELETE SET NULL,
    question    text NOT NULL,
    answer      text,
    status      text NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'answered', 'expired')),
    report_id   bigint,
    created_at  timestamptz NOT NULL DEFAULT now(),
    answered_at timestamptz
);
CREATE INDEX owner_questions_open_idx ON owner_questions (status, created_at);

-- Files JARVIS made for the owner (docx/xlsx/pdf), kept under data/documents (backed up).
CREATE TABLE documents (
    id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    title      text NOT NULL,
    format     text NOT NULL CHECK (format IN ('docx', 'xlsx', 'pdf', 'md')),
    filename   text NOT NULL,
    size       int NOT NULL,
    task_id    bigint REFERENCES tasks(id) ON DELETE SET NULL,
    created_by text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);
