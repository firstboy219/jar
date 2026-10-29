-- Blueprint v4 Fase 12 (ADR-085): the owner can let the AI hear his voice itself (🎧) instead of only reading the transcript (🔤).
INSERT INTO llm_categories (name, title, description, routes, budget_usd, allow_free, confirm_cloud, worker, sort, paid_attempt_limit, max_retries) VALUES
  ('dengar', 'Mendengar suara langsung', 'Agen utama mendengar rekaman suara pemilik (nada, perasaan, nama yang sulit) saat mode 🎧 aktif. Harus model yang menerima audio dan bisa memakai alat.',
   '[{"model": "google/gemini-2.5-flash-lite", "provider": "openrouter"}, {"model": "qwen/qwen3.8-omni-flash", "provider": "openrouter"}, {"model": "mistralai/voxtral-small-24b-2507", "provider": "openrouter"}]'::jsonb,
   NULL, false, false, false, 3, 1, 1)
ON CONFLICT (name) DO NOTHING;
