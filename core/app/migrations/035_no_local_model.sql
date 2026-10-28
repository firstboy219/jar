-- Blueprint v4 Fase 12 (ADR-080): the local Qwen models (llama-chat, llama-worker) are gone — every model is a cloud model on OpenRouter.
-- 1. no category keeps a local route; 2. "privat" (sensitive content, sensitive mail) now means: paid cloud models only (never a free endpoint,
-- which may log prompts); 3. the local providers disappear; 4. the "lokal" preset is not selectable any more.
UPDATE llm_categories
   SET routes = COALESCE((SELECT jsonb_agg(r) FROM jsonb_array_elements(routes) r WHERE r->>'provider' NOT LIKE 'lokal%'), '[]'::jsonb);

UPDATE llm_categories
   SET routes = '[{"model": "deepseek/deepseek-v4.1-flash", "provider": "openrouter"}, {"model": "qwen/qwen3.7-flash", "provider": "openrouter"}]'::jsonb,
       allow_free = false,
       description = 'Data sensitif (OTP, kata sandi, surel): hanya model berbayar di cloud — tidak pernah model gratis yang bisa mencatat prompt. Tidak ada model lokal lagi.'
 WHERE name = 'privat';

DELETE FROM llm_providers WHERE name IN ('lokal', 'lokal-kerja');
UPDATE settings_kv SET value = '"kustom"'::jsonb WHERE key = 'composition:preset' AND value = '"lokal"'::jsonb;
