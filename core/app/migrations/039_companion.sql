-- Blueprint v4 Fase 12 (ADR-084): JARVIS as a companion — a stronger model for discussion, and the conversation's longer memory.
INSERT INTO llm_categories (name, title, description, routes, budget_usd, allow_free, confirm_cloud, worker, sort, paid_attempt_limit, max_retries) VALUES
  ('diskusi', 'Diskusi & teman ngobrol', 'Bertukar pikiran, menimbang pilihan, curhat, menjelaskan, kreatif — giliran obrolan yang butuh pemikiran. Pakai model yang pandai bernalar dan berbahasa Indonesia.',
   '[{"model": "deepseek/deepseek-v4.1-flash", "provider": "openrouter"}, {"model": "qwen/qwen3.7-flash", "provider": "openrouter"}]'::jsonb,
   NULL, false, false, false, 2, 1, 1)
ON CONFLICT (name) DO NOTHING;

-- what a long conversation was about, beyond the last turns the model sees word for word
CREATE TABLE session_summaries (
    session_id  text PRIMARY KEY,
    summary     text NOT NULL,
    upto_id     bigint NOT NULL,         -- messages up to this id are in the summary
    updated_at  timestamptz NOT NULL DEFAULT now()
);
