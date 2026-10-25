# Blueprint "JARVIS AI Coworker v2.0" — gap analysis (2026-10-23)

Owner's decisions: the Android app stays native Kotlin (new screens only, the API contract is unchanged so a React
Native app can follow later); the Local Computer Agent and Blender wait until there is a PC; free-first is *measured*
(free models first only where they pass the checks, chat stays on the proven fast model); this round = Sprints 0–4.
Baseline: git tag `pre-blueprint`, 118 tests, a database dump taken before the work.

| Blueprint | State before | Gap | Done in |
|---|---|---|---|
| §2 stack: Hermes, FastAPI, Postgres, Qdrant, n8n | all present; the main (talking) agent is `assistant.py`, Hermes is the working brain behind the Task Manager | wording only | ADR-040 |
| §4 model registry | DB (`llm_categories`/`llm_providers`), edited from the app or by chat, validated against the catalog + a probe | no per-category paid limit, no `review`, no template | Sprint 1: `core/config/model_registry.yaml` → preset `blueprint` |
| §5 router + budget | ordered chain, any failure → next (paid too); monthly + per-category budget | diagnosis before paying, retries, per-task and daily budget, log of retries/fallback reason | Sprint 1: `modelrouter.py`, `016_router_tasks.sql` |
| §6 self-learning | Hermes skills, self-dev with approval (performance + minor features), `capability_gap` | sandbox tests, versions, rollback, evaluation | Sprint 4 |
| §7 capability registry | static tool lists in code + skill folders | searchable catalog with status / success / cost | Sprint 2 |
| §8 memory | `memories` (kind, source, stale) + Qdrant | confidence, verification, correction, dedup, episodes, goals | Sprint 3 |
| §10 task manager | `tasks` with queued/running/…, resume after restart, stop/retry/close | goal, criteria, plan, phase, budget/cost, artifacts, retries, model | Sprint 1 (fields), Sprint 2 (plan/criteria) |
| §9 workers | Hermes browser, documents (docx/xlsx/pdf), local vision, quick research, drafts | image generation, artifact verification, Blender, Local Agent | Sprint 5 (later) |
| §11 app / web | native app with the full console; web admin | Skills & Learning screen, Task Center with phase/cost | Sprint 6 (later) |
| §13 L0–L4 | approvals, KB rules, sandboxed deploys | per-model data policy | Sprint 1 (free models never get sensitive content) |

Blueprint facts checked against OpenRouter on 2026-10-23: all candidate ids exist; `poolside/laguna-s-2.1:free`
ends 2026-10-31 (experiment only); the blueprint's DeepSeek V4.1 Flash price is wrong (actually $0.30 / $1.20 per
million) and GLM 5.3 Flash is cheaper than stated ($0.005 / $0.20); no image-generation model is free. In real
traffic `nemotron-3-super:free` answered 404, `inkling:free` 403, `gemma-4-31b:free` 429 — hence "measured".

## Blueprint Terpadu v4 (2026-10-25)
Source: "JARVIS Blueprint Terpadu v4: spesifikasi untuk Claude Code" + "Blueprint Terpadu Jarvis v4" (owner, 25–26 Oct).
Executed per phase on branches `v4/fase-N`; each phase stops at its Gate for the owner's approval before merge/deploy.

| Phase | Blueprint v4 | State before | Gap | Status |
|---|---|---|---|---|
| 0 | Control point & protected zone (§3) | runner forbade only `infra/admin/app/{main,auth}.py` + Dockerfile; `code_change` could be approved from the app and by voice; approval text partly written by JARVIS; no pause; no tiers | whole `infra/admin/` protected, approvals of own-code admin-only, runner-built summary, pause switch, T0–T3 ladder, test-weakening refusal, APK rollback build | done on `v4/fase-0` (ADR-047) — Gate: awaiting owner |
| 1 | Company Federation | — | companies, Company/Decision Vault, entity relations, Jarvis-GM, Hermes-DGM adapter (mock until the real contract) | done on `v4/fase-1` (ADR-042, ADR-046) — Gate: real Hermes-DGM contract (K6) still needed |
| 2 | OpenJarvis spike | — | worker service behind core, gateway as its engine, 4-metric benchmark | parallel, needs K7/K8 |
| 3 | Voice complements | `correct_terms` for meetings only; `HALLUCINATIONS` list; no TTS text normalisation | measured baseline, daily-speech term correction, second opinion, server-side TTS normalisation, quality gate; + owner's request: TTS/STT picker from OpenRouter (ElevenLabs voices) | open (D8 vs the owner's ElevenLabs request) |
| 4–5 | Gestures, canvas web → APK | stage panels, 3D brain | canvas model, web viewer, gesture prototype, screenshots for T2 display | needs K4, K9, K10 |
| 6 | Inbox & watchers | n8n, calendar read | Gmail (Propose), calendar write (approval), ticket/price watchers (notify only) | later |
