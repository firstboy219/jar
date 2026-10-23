-- Speed/ability checks the owner runs on a model from the app ("Uji sekarang"), ADR-039.
CREATE TABLE model_bench (
    id         bigserial PRIMARY KEY,
    model      text NOT NULL,
    at         timestamptz NOT NULL DEFAULT now(),
    ok         boolean NOT NULL,
    first_ms   int,            -- until the first token arrived
    total_ms   int,
    tokens     int,
    tok_s      real,           -- writing speed after the first token
    tools_ok   boolean,        -- did it call a tool when asked (chat and Hermes need that)
    cost_usd   real NOT NULL DEFAULT 0,
    error      text
);
CREATE INDEX model_bench_model ON model_bench (model, at DESC);
-- statistics over llm_usage by model
CREATE INDEX IF NOT EXISTS llm_usage_model_at ON llm_usage (model, at DESC);
