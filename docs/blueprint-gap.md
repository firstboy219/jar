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
| 0 | Control point & protected zone (§3) | runner forbade only `infra/admin/app/{main,auth}.py` + Dockerfile; `code_change` could be approved from the app and by voice; approval text partly written by JARVIS; no pause; no tiers | whole `infra/admin/` protected, approvals of own-code admin-only, runner-built summary, pause switch, T0–T3 ladder, test-weakening refusal, APK rollback build | done (ADR-047) — merged + deployed 2026-10-25 |
| 1 | Company Federation | — | companies, Company/Decision Vault, entity relations, Jarvis-GM, Hermes-DGM adapter (mock until the real contract) | done (ADR-042, ADR-046) — merged + deployed 2026-10-26 with the mock DGM; real Hermes-DGM contract (K6) still awaited |
| 3 | Voice complements (Whisper/Groq stay) + owner's pick of voice | no utterance log, no error measurement; `correct_terms` only in meetings; hallucination list hard-coded; fixed 0.45 'misheard' line; spoken text = displayed text ("Rp 1.500.000" read as digits); only the phone's TTS; STT engines whisper/groq/deepgram | `voice_events` baseline per engine + taxonomy from the owner's corrections; complements kamus / halusinasi / gema / opini_kedua / ambang, each in SHADOW until the quality gate passes (WER down, false corrections ≤ 1%, ≥ 20 samples) and auto-reverting; spoken copy normalised on the server; cloud voice from OpenRouter (ElevenLabs etc. + character) with private/sensitive/budget fallback to the phone; OpenRouter STT models; audio kept only with K3 consent at the admin page | done (ADR-048) — merged + deployed 2026-10-26 (APK 0.15.0); K3 consent given |
| 4 | Gesture prototype + canvas — **3D, a galaxy per context** (owner, 2026-10-26: "infinite canvas 3D, seperti ada di galaxy") | stage panels on the phone only; no canvas, no gestures | canvases/cards/edges/versions (layout only, references resolved on read; RLS per company; isolation checked on add and on read); JARVIS places finished tasks, documents and what it shows; WebGL viewer at /canvas/ (three.js, MIT, vendored): spiral galaxy, a constellation per kind, glass cards in 3D, fly/orbit/zoom, drag cards anywhere, links, search, version history/restore, deep link #kartu=ID; on-device hand gestures (MediaPipe) as a separate prototype page with latency/false-trigger counters, optional in the viewer, navigation only | done (ADR-049) — merged + deployed 2026-10-26; Gate: the owner tries the gesture prototype on their device; K9 assumed (laptop/phone on a stand) |
| 2 | OpenJarvis spike (K7: self-repair / performance; K8: $1) | — | OpenJarvis as a separate worker on the gateway; a fair benchmark vs Hermes-Brain | spike stopped by the owner after batch 1 (no verdict; OpenJarvis produced no answer with DeepSeek V4.1 Flash); adopted anyway as an OPTIONAL heavy worker, off by default, Hermes the fallback (ADR-043) |
| 5 | Canvas in the APK | web viewer only (Fase 4) | the APK opens the same viewer in a WebView, signed in with its device token (fragment), camera only for gestures with Android's consent, own origin only | done on `v4/fase-5` (ADR-050) |
| 6 | Inbox & watchers | n8n, calendar read | Gmail (Propose), calendar write (approval), ticket/price watchers (notify only) | later |
