-- The local chat model (Qwen3.5-2B) now runs with its vision projector (infra/docker-compose.yml: --mmproj):
-- pictures reach it instead of being stripped (ADR-032).
UPDATE llm_providers SET vision = true WHERE name = 'lokal';
