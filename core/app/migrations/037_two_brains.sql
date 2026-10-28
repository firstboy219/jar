-- Blueprint v4 Fase 12 (ADR-081): Hermes governs; the two brains it hands work to each have their own OpenRouter model category,
-- so the owner picks their models in Komposisi AI: "ringan" (jar: simple look-ups, seconds) and "berat" (OpenJarvis: heavy thinking).
INSERT INTO llm_categories (name, title, description, routes, budget_usd, allow_free, confirm_cloud, worker, sort, paid_attempt_limit, max_retries) VALUES
  ('ringan', 'Otak ringan (jar)', 'Pencarian sederhana (berita, harga, fakta, jadwal) dijawab detik-an tanpa sesi Hermes dan tanpa antre. Model murah dan cepat.',
   '[{"model": "qwen/qwen3.7-flash", "provider": "openrouter"}, {"model": "deepseek/deepseek-v4.1-flash", "provider": "openrouter"}]'::jsonb,
   NULL, false, false, false, 41, 1, 1),
  ('berat', 'Otak berat (OpenJarvis)', 'Tugas berat yang butuh banyak langkah berpikir, menghitung, atau membaca kode — dikerjakan OpenJarvis. Pakai model yang kuat dan bisa memakai alat.',
   '[{"model": "deepseek/deepseek-v4.1-flash", "provider": "openrouter"}, {"model": "qwen/qwen3.7-flash", "provider": "openrouter"}]'::jsonb,
   NULL, false, false, true, 42, 1, 1)
ON CONFLICT (name) DO NOTHING;
