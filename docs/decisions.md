# Architecture Decision Record

Spec hierarchy: `BRD.docx` is primary; `JARVIS_KNOWLEDGE_BASE (1).md` is reference.

## ADR-001 — n8n is installed fresh in Docker (2026-10-17)
The KB says to reuse an existing n8n, but the target server had none. Per the BRD, n8n + PostgreSQL
run in the JARVIS compose stack.

## ADR-002 — Hermes Agent only; OpenClaw dropped (2026-10-17, updated 2026-10-21)
BRD runs both. OpenClaw was never installed; on 2026-10-21 the owner decided to drop it. Its role
(gateway, WSS, admin) is covered by jarvis-core + the web admin; Hermes is the brain.

## ADR-003 — Generated n8n workflows need owner approval (2026-10-17)
Deviation from BR-002 "100% autonomous". Workflows Hermes generates are created **inactive** in n8n
and activated only after approval in the Action Approval Queue.

## ADR-004 — Models (2026-10-17)
BRD's `nousresearch/hermes-3-llama-3.1-70b` has **no tool-calling** on OpenRouter, and
Qwen 2.5 Coder 72B is no longer listed. Hermes Agent needs tool calling, so defaults are:
- general: `deepseek/deepseek-v4-flash` (≈$0.09/M in, $0.18/M out, 1M ctx)
- coding / n8n JSON: `qwen/qwen3-coder-next`

Both are `.env` settings (`JARVIS_DEFAULT_MODEL`, `JARVIS_CODER_MODEL`), so they can change without code.

## ADR-005 — Security deviations from the BRD compose
| BRD | Here | Why |
|---|---|---|
| Passwords/API keys inline | `.env` (mode 600, git-ignored), random secrets from `scripts/init-env.sh` | No secrets in git |
| `:latest` tags | Pinned versions | Reproducible, no surprise upgrades |
| 81, 1024, 5678, 6333, 18789 published on 0.0.0.0 | Only 80/443 public; 81/5678/6333 bound to 127.0.0.1 | Admin UIs and DBs not on the internet |
| Qdrant without auth | `QDRANT__SERVICE__API_KEY` | Defense in depth |
| `hermes-agent:latest-playwright`, `/app/config` mounts | `hermes-agent:v0.22.2` (tag in BRD does not exist), `/opt/data` | Match the real image |
| `ipc: host` | `shm_size: 1gb` | Chromium shared memory without sharing host IPC |
| `/var/www/...`, `/var/log/nginx` mounts | NPM logs mounted `:ro` | Those host paths don't exist on this server |
| Deepgram key in the APK (FS-101) | Backend will mint short-lived Deepgram tokens | A key in an APK is extractable (Milestone: APK) |

## ADR-006 — Web admin applies settings without a Docker socket (2026-10-17)
The owner wants to enter keys from the browser (jar1.cosger.online). The admin container only gets
`infra/.env` (rw) and `data/admin` (ro); a host systemd path unit runs `docker compose up -d` on change.
Giving the admin the Docker socket would make a web login equivalent to root on the host.
Auth: scrypt password hash in `.env`, HMAC-signed HttpOnly/Secure/SameSite=Strict cookie (12 h,
invalidated on password change), Origin check on POSTs, 5 failed logins / 15 min per IP.
Secrets are write-only in the UI (only the last 4 chars are shown).

## ADR-007 — Tiered routing; no local LLM on this server (2026-10-17) — superseded by ADR-017
The owner does not want every chat sent straight to OpenRouter. A local model was benchmarked here
(qwen3:4b, Ollama, 4 vCPU Xeon 8175M, no GPU): ~13 tok/s prompt processing, 4.5 tok/s generation —
a single Hermes turn (≈13k-token prompt) would take ~17 minutes. So, chosen by the owner:
1. **Tier 1 — jarvis-core rules**: quick commands answered with no model at all.
2. **Privacy gate**: messages with secrets (API keys, passwords, private keys, Luhn-valid card numbers)
   or prefixed `/privat` are never sent to a cloud model; the stored log is redacted.
3. **Tier 2 — Hermes on a cheap model** (`JARVIS_DEFAULT_MODEL`).
4. **Tier 3 — `delegate_task`** to `JARVIS_EXPERT_MODEL`, only when Hermes judges it necessary (SOUL.md).
Embeddings for memory run locally on CPU (fastembed multilingual MiniLM), so memory text is not sent
out just to be indexed. A GPU host can later be plugged in as Hermes' main provider.

## ADR-008 — jarvis-core owns state; Hermes acts through MCP tools (2026-10-17)
KB: the agent runtime must not be the source of truth. jarvis-core (FastAPI, `jarvis` Postgres db)
stores devices, messages, approvals, memories and the audit log. Hermes gets tools only via the
`jarvis-tools` MCP server and holds no n8n/Qdrant credentials, so every side effect is policy-checked:
risky actions become approval requests, and n8n workflows are created inactive with an activation
approval (ADR-003). Hermes' API is no longer public; `vis1` points to jarvis-core.

## ADR-009 — Native Android app (Kotlin + Compose) (2026-10-17)
Owner asked for a native APK (KB suggested Flutter). Stack: Kotlin 2.0, Jetpack Compose (BOM 2024.12),
OkHttp WebSockets, EncryptedSharedPreferences for the device token, minSdk 26 / target 35.
- Walkie-talkie screen shows JARVIS' live "thought stream": jarvis-core relays Hermes' streamed reasoning,
  tool lifecycle and answer deltas over WSS, and re-runs Hermes' memory queries locally to show which
  memories it is looking at (context cards).
- Voice: AudioRecord Linear16 16 kHz mono, 100 ms chunks → Deepgram `nova-3` (`language=id`) with a
  60-second token from jarvis-core; KeepAlive every 5 s (FS-101). Replies are spoken with on-device
  Android TTS (id-ID) — free and no extra round trip, unlike the BRD's OpenAI TTS.
- Built in Docker (`infra/android-builder`), signed with a server-side keystore, published to the web admin.

## ADR-010 — Hermes built-in memory disabled (2026-10-17) — superseded by ADR-018
Hermes was writing its own MEMORY.md/USER.md entries alongside the jarvis memory. Two unmanaged stores
violate "memory is visible/editable by the owner", so `memory.memory_enabled` and
`user_profile_enabled` are off; all long-term memory goes through the jarvis MCP tools.

## ADR-011 — Speech recognition: Deepgram nova-2 for Indonesian; location as opt-in context (2026-10-17)
Owner reported words being missed. Benchmark (6 realistic Indonesian commands × 2 voices × clean/noisy,
streamed exactly like the APK): **nova-2 `id` WER 12.3% clean / 14.8% noisy vs nova-3 `id` 21.7% / 18.9%**;
nova-3 also dropped trailing words; `multi` was unusable (~94%). Much of nova-2's residual "error" is
numerals ("2" vs "dua"). Keyword boosting fixed domain terms (UAT, Autotoko). The APK also lost audio:
it started recording only after fetching a token, stopped the instant the button was released, and closed
the stream after a fixed 700 ms. Now: token prefetched, mic opens on press with audio buffered until the
socket is up, 300 ms tail after release, and the stream closes only after Deepgram's `from_finalize`.
Model/language/keywords come from the server (`DEEPGRAM_*`, editable in the web admin) so tuning needs
no app release.

Location: the owner asked JARVIS to know where they are. The app sends position + on-phone reverse-
geocoded address with each command when "Bagikan lokasi" is on (default on, asks permission; denying
turns it off). jarvis-core prepends it (with WIB time) as a context block for Hermes only — the message
log keeps the raw text — answers `di mana saya` without AI, and keeps only the latest fix
(`settings_kv.last_location`) for future proactive features. Note: it is sent to the cloud model as part
of the prompt when Hermes handles the message.

## ADR-012 — Main agent vs workers; mute/unmute listening (2026-10-17)
Owner: the agent that talks must not wait for the agent that works; workers unlimited; results must be
told and confirmed as heard, like a human assistant.
- **Main agent** (`assistant.py`): fast model (`JARVIS_CHAT_MODEL`, default `anthropic/claude-haiku-5.5`,
  chosen by benchmark: ~0.7 s to first token, reliable delegation, natural Indonesian; gpt-5-nano and
  glm-5.3-flash rejected — mandatory reasoning) with a small prompt: history, active tasks, unconfirmed
  reports, top memory hits, device context. Tools: spawn_task, acknowledge_reports, cancel_task, remember.
  Measured live: replies in 1.2–2.5 s while workers run.
- **Workers** (`workers.py`): one Hermes session per task (`task-<id>`), unlimited queue in Postgres,
  `WORKER_CONCURRENCY` (default 6) at once, independent of the phone connection, resumed after restart.
  Live progress is broadcast to all owner devices (`hub.py`).
- **Reports** (`reports.py`): result → reworded for speech → pushed; the phone confirms it was spoken
  (`report_spoken`); if not acknowledged (tap, or the main agent recognising "oke/sip/makasih…") within
  `REPORT_ACK_TIMEOUT_S` (90 s) it is repeated, max 3×, then marked 'unheard' and kept visible.
- **Listening**: push-to-talk replaced by mute/unmute continuous streaming (Deepgram VAD: endpointing
  700 ms, UtteranceEnd 1.5 s). Readiness indicator: Mic mati / Menyiapkan / Siap — silakan bicara /
  Mendengarkan / JARVIS bicara. Audio is buffered while preparing; input is dropped while JARVIS speaks
  (no self-transcription); a foreground service keeps the mic alive with the screen off; auto-mute after
  5 min of silence. Cost: Deepgram bills streamed audio (~$0.26/hour unmuted).

## ADR-013 — Showing media and screen sharing (2026-10-17)
- Workers get MCP tools `find_images` (Openverse: free, no key, openly-licensed — weak for Indonesian
  queries, so workers may also use images from pages they read), `find_videos` (YouTube search via
  yt-dlp, no API key) and `show_media`. jarvis-core validates every item (https only; images checked to be
  `image/*` ≤ 15 MB; YouTube thumbnails derived) before pushing `media` events to the owner's devices.
- Screen share: Android MediaProjection at 720 px wide; only the latest frame is kept, and it is sent
  **only together with an utterance** (~40–150 KB JPEG), never streamed. The main agent sees it as an
  image part (vision). FLAG_SECURE apps (banking etc.) appear black. Measured: answer about the shared
  screen in 2.4 s.

## ADR-014 — Proactive notifications (2026-10-17)
Opt-in twice: Android "Akses notifikasi" (only the owner can grant it) + "Baca notifikasi" in the app.
The phone forwards non-ongoing, non-system notifications, deduplicated, with one-time codes replaced on
the phone; the server redacts again (OTP/password/card patterns) before anything reaches the model.
Notifications within 5 s are batched and triaged by the main-agent model: skip / announce (spoken once,
`announce` event) / urgent (a report — repeated until acknowledged). Quiet hours (`QUIET_HOURS`,
default 22:00–06:00 WIB) let only urgent ones through. Stored 7 days (`notifications` table) so the main
agent can answer "tadi notif apa aja?"; purged every 6 h. Note: notification content (minus codes) is
sent to the cloud model for triage.

## ADR-015 — A "living" main agent: self-knowledge, situational awareness, clarifying, silence (2026-10-17)
Owner: JARVIS should know where they are, what they are doing and what they usually want, delegate that
understanding to workers, ask back when unclear, and know itself (it had denied using Deepgram while the
owner was talking to it through Deepgram; a worker "confirmed" by inspecting the wrong container).
- `self_model.py` generates the self-description from the running config (STT model/keywords,
  models, features, limits incl. "cannot identify the owner's voice yet", health, balance) — in every
  main-agent prompt and via the MCP tool `self_info` for workers.
- `awareness.py`: the app sends a context heartbeat (place, movement from GPS speed, battery/charging,
  headset, screen, network, optional calendar). Triggers (moved > 400 m, started walking/driving,
  agenda within 30 min, 90 min periodic) spawn a *situation worker* (Hermes) that returns
  where/doing/likely_need/prepared + whether to speak. At most one proactive line per 45 min, not in
  quiet hours, not within 60 s of the owner talking. A daily *routine worker* turns 14 days of coarse
  context (`context_log`, ~100 m, 30-day retention) into habit memories.
- Speech: STT confidence and Deepgram diarization speaker count travel with each utterance; endpointing
  raised to 1000 ms / UtteranceEnd 1800 ms (700 ms cut sentences mid-thought in real use). The main agent
  may `stay_silent` (speech not for it — real logs had bystander talk — or unfinished) and must ask back
  when unsure. The server enforces silence when the model merely *announces* it.
- Camera: CameraX preview; a frame goes with each utterance (`image_source: camera`). Delegated tasks can
  carry the image; because the worker model is text-only, the main (vision) model writes a description
  into the worker's instructions, and Hermes' own vision tool uses `google/gemma-4-26b-a4b-it`.

## ADR-016 — Self-improvement policy (2026-10-17)
Daily (03:00 WIB) or on request, a self-check worker gets diagnostics (errors, failed tasks, unheard
reports, low-confidence speech, "didn't understand" replies, owner corrections, applied improvements)
and proposes: `stt_keyword` and `lesson` → applied automatically (≤5/run, versioned, revertible in the
admin "Diri JARVIS" tab); `setting` (whitelist: deepgram_model, endpointing_ms, utterance_end_ms,
quiet_hours) → owner approval, then a runtime override; `code` → recorded proposal for the developer.
First real run learned: Deepgram/"Deep Drum", UAT, capability questions, and the names Ashar/Opik/Aby
(misheard as "UAT"/"Shopee" — the configured boost words were pulling them).

## Incident 2026-10-17 → 10-21 — OpenRouter balance at $0
The account is free tier with $0 credits; after $0.20 of use every call returned HTTP 402 from
10-17 20:23. The main agent replied with raw error text ("hi" → "OpenRouter HTTP 402: …"), workers'
402 text was treated as a successful result, and three self-check reports said only "Aku sudah mengecek
diriku." Fixes (`billing.py`): balance is a health check and part of the self-description; 402s are
recognised in the main agent and workers; the owner gets one plain report per 12 h; worker 402s count as
failures; unreadable self-checks say so. A self-check also misread planned restarts (logged as
`exit_nonzero`) as a "crash loop" — that proposal was rejected and the fact added to the self-description.
Since ADR-017 an empty balance only means "local models, slower" — JARVIS keeps working.

## Ops note — never run two `docker compose up` at once
Editing `.env` triggers the watcher, which runs `docker compose up -d`. A concurrent manual `up` once
left a container renamed `<id>_jarvis-core`. Both now take `data/admin/compose.lock`; deploy with
`sudo infra/scripts/compose.sh up -d --build <service>`.

## Known gap — latency vs BR-001 (see ADR-019 for what changed)
Measured end-to-end: tier-1 commands ~0.1 s; Hermes turns 6–23 s (cloud model + 13k-token agent prompt +
tool calls). BR-001's < 1.5 s target is not met for agent answers. Since streaming (ADR-009) the first
visible sign of thinking arrives in ~3 s and the answer streams as it is written. Since ADR-012 the owner
talks to a fast main agent (1–2.5 s end-to-end); only delegated work takes longer, in the background. Options to evaluate with the APK:
stream partial text over WSS, a faster tier-2 model, prompt caching, trimming Hermes toolsets.

## Known risk
Hermes' terminal backend is `local`, i.e. commands run inside the `jarvis-brain` container. The
container is the sandbox (no Docker socket, no-new-privileges, dropped capabilities, CPU/RAM/pid
limits; ADR-018); dangerous commands still need the owner's approval on the phone.

## ADR-017 — LLM gateway; local by default; the owner composes JARVIS from the APK (2026-10-21)
After the $0-credit outage the owner wanted no single-vendor dependency: **default fully local**
(Qwen + Whisper on this server), cloud only as chosen. Every model call (main agent, Hermes, its
sub-agents/cron/auxiliary tasks, meetings, drafts) goes through `core/app/gateway.py`:
- categories (ngobrol, cepat, penglihatan, web, coding, produktivitas, analisis, balas-pesan, rapat,
  latar-belakang, privat) with ordered routes; presets *Lokal penuh* (default), *Hemat gratis*
  (OpenRouter `:free`), *Seimbang* (recommended), *Kombinasi pemilik* (Haiku / Sonnet / ChatGPT);
- only an owner-scope device (the APK) may change it; Hermes/Qdrant/n8n are the permanent core;
- routes without a key are skipped, failover happens before the first byte, the local model closes
  every list — no key or no credit means slower, never dead;
- `/privat` and sensitive content only ever reach the local model, and are not replayed into later
  cloud prompts; `:free` models are excluded for categories that may carry private content;
- budget (`budget.py`): $20/month soft cap + per-category caps; 80% moves background work to
  free/local, 95% prefers the cheapest route, 100% stops paid models; hard caps stay on openrouter.ai;
- cost hygiene: `session_id` for sticky provider caching, Anthropic cache breakpoints, a static prompt
  prefix with per-turn context last (also what makes the local prompt cache work).
Measured here: Qwen3.5-2B ~42/7 tok/s (read/write) and **1.4–1.7 s replies once the prompt prefix is
cached** (75 s cold); Qwen3.5-4B ~20/4.7 tok/s; Hermes' prompt with all features ≈20.5k tokens → ~1 h
cold on this CPU, ~7 min per step warm. The warm prefix is saved to disk and restored after restarts.
Hermes on local models is therefore a fallback, not a daily driver.

## ADR-018 — Hermes decides its own flow; one shared memory (2026-10-21)
Owner: "let Hermes think and act flexibly … enable all its features". Removed: prescriptive SOUL rules,
`max_turns 30`, the fixed delegation model, disabled memory. Enabled: all API-server toolsets plus
kanban, tts, video, project, debugging; skills (self-created ones scanned), cron (agent may schedule),
delegation (4 children, 30 min child timeout), memory. Kept (the owner's KB rules): approvals for
external/destructive/financial/production actions — Hermes' dangerous-command prompts now reach the
phone through `/v1/runs` approval events; no credentials for n8n/DB/admin; web content is data;
container hardening; budget via the gateway. Memory: Hermes' own MEMORY.md/USER.md are mirrored by the
`jarvis-memory` plugin into JARVIS' single memory (Postgres + Qdrant), which also feeds Hermes' recall —
one brain, visible and editable by the owner, drawn as the 3D brain on the phone. Cron results are
delivered as spoken reports (Hermes has no messaging platform here); `ask_owner` / `notify_owner` reach
the owner by voice. Not enabled by default: inbound messaging gateways and computer-use (needs a desktop).

## ADR-019 — Voice: VAD on the phone, speech engine per composition, voiceprint, live speech (2026-10-21)
Deepgram live streaming bills every second the mic is open (~$60/month at 8 h/day). Now Silero VAD on
the phone sends only speech; the server transcribes with the owner's engine: local Whisper (default;
measured `small` WER ~19%, ~3.5 s; `large-v3-turbo` WER ~10% but ~15 s), Groq turbo (same model, ~0.5 s,
free up to ~8 h/day) or Deepgram. Whisper has no speaker count, so the owner can enrol a voiceprint
(CAM++; same voice ≥ 0.86, other voices ≤ 0.45 measured) — non-owner speech is flagged for the main agent.
The main agent's answer is spoken sentence by sentence while it streams. Wake word and barge-in: see ADR-021.

## ADR-020 — Meetings and reply drafts respect other people's privacy (2026-10-21)
Meetings: recording needs the owner's confirmation that participants consented (Indonesian KUHP art. 258
from 2026-01-02); Android cannot record call audio, so the phone records the room. A "Rahasia" meeting is
processed locally end to end. Diarization is local (sherpa-onnx); minutes are a .docx plus questions over
the transcript; audio is deleted after 30 days. Drafts: the phone reads the chat itself (ML Kit) and
sends text; a cloud model is used only after the owner agrees; JARVIS never sends — the owner copies,
opens the app, or confirms sending through WhatsApp's notification reply.

## ADR-021 — "Hey Jarvis" and barge-in, both opt-in (2026-10-21)
Wake word: openWakeWord (ONNX via the onnxruntime already in the APK; pretrained models CC BY-NC-SA,
acceptable for this personal assistant; Porcupine's free tier ended 2026-06-30). It runs on the phone
only while the main mic is muted; after 60 s without speech JARVIS goes back to waiting. Validated with
synthetic speech: English-pronounced "Hey Jarvis" 0.999, ordinary Indonesian sentences < 0.01, an
Indonesian-accented voice 0.25 — hence a "lebih peka" (0.25) setting. Barge-in: speaking while JARVIS
talks stops it, only with a headset (phone-speaker echo would trigger it), mic in VOICE_COMMUNICATION
mode for the phone's echo canceller. Both cost battery on the Infinix; off by default.

## ADR-022 — Self-improvement scope: skills yes, self-deploying code no (2026-10-21)
The owner asked JARVIS to fix its own bugs and build missing features itself. Delivered: Hermes can create
and refine its own skills (already on since ADR-018), draft n8n workflows (activation by approval) and
schedules; service errors are captured in `error_log` (redacted) and read by the daily self-check; the
skills `jarvis-self-repair` / `jarvis-self-development` make Hermes diagnose problems and, when code must
change, write a concrete proposal (document + notification) for the developer. A pipeline in which Hermes
edits JARVIS' own code and the host merges and deploys it (even with tests + owner approval) was designed
but NOT built: the development session's safety policy blocked creating an agent that modifies and
redeploys itself. It needs an explicit decision by the owner before it is reconsidered.

## ADR-023 — Password manager, model-blind agent logins, remembered web sessions (2026-10-21)
Logins live in `vault_entries`, encrypted with AES-256-GCM under `VAULT_KEY` (.env, part of the encrypted
backups). Only owner-scope devices reach them, and the app asks for the fingerprint/PIN before opening the
list, revealing a password or autofilling. The web panel fills a saved login (values injected; still no
JavaScript bridge), offers to save one the owner typed, and keeps cookies so sessions survive. Entries the
owner marks "boleh dipakai JARVIS" are synced by the jarvis plugin into Hermes' browser vault, which fills
the password server-side — the model only ever sees an opaque handle. Passwords never enter prompts,
memory, logs or the audit trail.

## ADR-024 — Skills from the Claude ecosystem (2026-10-21)
`infra/scripts/install-skills.sh` (pinned commits) installs 89 skills next to Hermes' 59 bundled ones:
18 JARVIS skills (Indonesian context: replies, minutes, price comparison, finance math, routes, documents,
diagnostics, safe web login…), 13 Apache-2.0 skills from anthropics/skills (skill-creator, mcp-builder,
frontend-design, webapp-testing, doc-coauthoring, …), 13 MIT skills from obra/superpowers (systematic
debugging, TDD, planning, code review, …) and 45 curated optional Hermes skills. Not installed: Anthropic's
docx/pdf/pptx/xlsx skills (proprietary licence forbids copying), "use before every reply" meta-skills
(token cost), jailbreak, GPU-training and paid-account skills.

## ADR-025 — In-app updates (2026-10-21)
From v0.9.0 the app checks `/api/v1/app/latest` on connect and every ~3 h; a newer version opens a dialog
"Update sekarang" (download, SHA-256 check, Android installer) or "Tunda" (asked again after 24 h).

## ADR-026 — Self-improvement: performance + minor features, owner-approved (2026-10-21)
Supersedes the "not built" note in ADR-022. The owner allowed JARVIS to change its own code **to do what
the owner asks faster, cheaper or with fewer failures, and (same day, later) to add MINOR missing
abilities** — e.g. a new music source after a requested song could not be played. No big features, nothing
touching security, permissions, approvals, secrets, the AI composition, budgets, Android permissions or
tests. New Python packages only in `core/requirements.txt`, pinned `name==version`; the approval and the
report list them. Legal/terms-of-service risks must be stated in the proposal; the owner decides.
- Capability gaps: when a direct action (e.g. play music) or an owner task fails, `perf.capability_gap`
  starts one task per kind of gap per day in which JARVIS analyses the cause and finds its own way.
- Triggers: a weekly efficiency review (Sunday 02:00 WIB, digest of task duration/failures, model cost,
  cache hits, voice latency, errors), the same error ≥ 3× in an hour (one repair task per signature per
  day), the daily self-check's "code" proposals, or `POST /admin/efficiency-review`.
- Hermes works on `jarvis/<topic>` in its workspace `/opt/data/workspace/jar` (current main comes from a
  root-owned mirror mounted read-only), then calls `propose_code_change` / `check_code_change`.
- `infra/scripts/self-dev.sh` (root, `jarvis-dev.path` → `jarvis-dev.service`) fetches the branch into
  the live repo (git never runs inside the workspace), refuses forbidden paths (security modules,
  `main.py`, `approvals.py`, `dev.py`, `perf.py`, infra scripts, systemd, compose, .env, Dockerfiles,
  requirements, gradle/manifest), edits to existing migrations and diffs > 1500 lines, merges onto main
  in a throwaway worktree and runs the core (and Android) test suites.
- Passing tests → high-risk approval `code_change` (fingerprint). Only the approved, tested commit is
  merged; the changed services are rebuilt and health-checked; failure → main is reset and redeployed
  (`rolled_back`); success → push to GitHub, refresh the mirror, and a new APK if android/ changed.
- jarvis-core never runs git or docker; it only exchanges JSON files in `data/dev/{requests,results}`.

## ADR-027 — Main agent talks, workers work; reliable on the small local model (2026-10-21)
Concept (owner): only the MAIN AGENT talks with the owner — it understands, builds the context, delegates
and reports results. WORKERS only do the work and report back to the main agent (reports), which tells
the owner. Findings from the chat log of 2026-10-21 (no cloud credit → main agent on Qwen3.5-2B, workers
on the 4B through full Hermes sessions):
- The 2B often SAID it would check/find/play something without calling spawn_task, so no worker ran
  (1 delegation in 15 owner turns); it parroted phone notifications and its own previous reply
  ("berita crypto … Prabowo" six times); a local Hermes session (≈26k-token prompt) took 40–90 min.
Changes:
- Clear actions (play X, route to X, news) are recognised without a model (`router.parse_action`) and
  executed directly (music/route) or delegated (news) by the main agent.
- A reply that promises work without starting any spawns a worker with the owner's words + context.
- Workers always get the last turns of the conversation (after `---KONTEKS OBROLAN---`).
- Local model context: notifications only when asked about them; duplicate replies removed from history.
- Fast worker (`quick.py`): while workers run locally, simple look-ups are answered in seconds from Google
  News RSS / DuckDuckGo + a short summary; anything else (or no answer) goes to Hermes as before.
- While workers are local, situation preparation does not start a Hermes session (keeps the CPU for the owner).
- "pakai model apa" is answered from the composition without a model.
The real fix for quality is a cloud model for the main agent (Groq free key or OpenRouter credit).

## ADR-028 — Flow watcher, flexible home screen, console parity (2026-10-21)
- **Pengawas Alur** (`core/app/auditor.py`, table `flow_issues`): a dedicated worker that runs after a
  conversation pauses (≥ 2 min, at most every 20 min) or on demand. Deterministic checks (promise without
  a task, repeated reply, error/very slow reply, failed/very slow task, unheard report) plus a judge model
  over the new non-private owner ↔ main agent turns ("does the answer fit what the owner said and the
  conversation?"). The owner hears a short summary (≤ every 3 h); one fix task a day (self-improvement
  scope, skill `jarvis-flow-audit`) works on the open issues. Each run is listed as a task (kind
  `flowcheck`). `auditor.py` is out of bounds for self-modification (the watcher must not weaken itself).
- **Home = anything + the brain**: new panels `audio`, `image`, `text` and `board` (several blocks of any
  kind stacked; first player autoplays only); `show_anything` (MCP) picks the panel from a URL's type, a
  text or a place. The 3D brain fills the home background (dimmed under panels/camera); `brain_pulse`
  carries memory texts so the phone labels the nodes in use and lists "MEMORI TERLIBAT".
- **Console parity**: the APK gained Pengawas alur, Pengembangan diri (code changes), Error layanan,
  Tinjauan efisiensi and admin-password change (`/api/v1/console/admin-password` → jarvis-admin); the
  "Lainnya" menu is grouped like the web admin's tabs and shows the installed version.

## ADR-029 — Songs as MP3, "Netralkan", who uses the server (2026-10-21)
- **MP3 (owner's decision, aware of the YouTube-terms/copyright risk, personal use):** a named song that is
  not in the openly-licensed library is fetched as MP3 and played in JARVIS' own music player. JARVIS never
  downloads from YouTube itself (the owner asked: share link → an online converter). Public converters
  (cobalt) now require a browser challenge, so the converter is configurable (`MP3_CONVERTER_URL`/`KEY`,
  cobalt API); without one, the song comes from SoundCloud (yt-dlp + ffmpeg → MP3, ≤ 15 min, verified).
  The official YouTube player stays the last fallback. Downloaded songs are removed after 30 days.
- **Netralkan** (`POST /admin/relieve`, voice "netralkan server", button on the home strip/dashboard):
  every running/queued task becomes `stopped` with its progress (tools used, last thinking) — the owner
  retries it (it continues from there) or closes it; background work rests 15 min; the host part
  (`infra/scripts/ops.sh`, `jarvis-ops.path`, root) restarts Hermes, restarts the local worker model only
  if it is still busy (then the warm prompt cache is restored), and moves swap back into RAM when there is
  room. No data is touched.
- **Who uses the server:** `infra/scripts/usage-collector.sh` (`jarvis-usage.service`, docker stats every
  10 s → `data/ops/containers.json`) + the gateway's in-flight AI calls by caller + running/waiting tasks →
  the home strip says which service uses the CPU/RAM and for whose work (owner first, background waits).

## ADR-030 — Background work only under 50% CPU, orphan watchdog, "Di balik layar" (2026-10-21)
Bug: the local worker model kept computing for minutes after its request was cancelled (286% CPU with no
task) — llama.cpp only checks for cancellation between batches, and a 2048-token batch took 2–4 minutes on
this CPU. Fixes: `-b 512` (a cancelled request stops within ~30 s) and a watchdog (core/app/ops.py) that
restarts the worker model when it keeps computing while no call is waiting for it (3 checks ≈ 60 s; then the
prompt cache is restored). Owner's rule: JARVIS' own work (self-improvement, flow watcher, self-check,
situations, habits) only STARTS when the server CPU is < 50% and none of the owner's work runs; while only
background work runs the worker model is limited to 2 of 4 threads (`docker update --cpus`, applied by
usage-collector.sh from data/ops/policy.json), the owner's work gets all 4. Transparency: `/admin/background`
and the APK screen "Di balik layar" list what runs now and for whom, why background work waits, the schedule,
the last 24 hours (AI minutes per purpose, background tasks) and a log of everything started or stopped.
`ops.py` is out of bounds for self-modification.

## ADR-031 — Make the local worker fast: fix its cache, shrink Hermes' prompt (2026-10-21)
Measured instead of guessed (scratchpad benchmark, both models with 2 CPU threads, Hermes-like pattern):
| | Qwen3.5-4B (kept) | Qwen3-4B-2507 |
|---|---|---|
| cold read ±5k tokens | 692 s (7.2 tok/s) | 1,963 s (2.6 tok/s) |
| same session + 400 tokens | 89 s | 392 s |
| back to a session after another one | 74 s (319 tokens re-read) | 425 s |
| new session, same system prompt | 52 s (241 re-read) | 280 s |
| memory | 2.5 GB | 4.7 GB |
So the hybrid model's prompt cache works and it is 3–5× faster here; switching models would hurt. The
production slowness came from (1) the gateway saving the worker slot after ANY local call — a 279-token
call overwrote Hermes' 22k-token prefix and every restore (core start, Netralkan) forced a full re-read —
now only Hermes calls ≥ 4,000 prompt tokens are saved; (2) a 2 GB RAM prompt cache, now 4 GB (worker
memory limit 6 → 8 GB); (3) Hermes' prompt itself: of 22.6k tokens, 16.4k were tool schemas (kanban 6.1k,
manage_connections, delegate_task, skill_manage, browser_exec, tts) and 3.4k the index of 149 skills.
`HERMES_PROFILE=lean` (default while Hermes runs locally; jarvis-core switches it to `full` when the
composition moves Hermes to a cloud model) defers those tools behind tool_search (still usable), lists
only JARVIS' own skills, sends Hermes' side tasks to the chat model and runs one sub-agent at a time.
Result in production (task #72 retried): prompt 11,801 tokens (was 20–26k); after one cold read the next
step re-read 4 tokens. Also fixed: Hermes saw the gateway as a cloud provider (180 s patience) and re-sent
the same request while the CPU was still reading it, giving up after 5 "stale attempts" — the lean profile
sets `providers.jarvis.stale_timeout_seconds: 2700`.
Ideas not taken: more parallel workers (same 4 threads, every worker re-reads its own ~20k-token prompt).

**Update (same day, owner):** the 50% CPU start gate and the 2-thread cap on the worker model were removed.
Background work still waits for the owner's own work and runs one task at a time; the worker model uses all
4 threads at idle priority (it never slows other services), and the orphan watchdog stays.

## ADR-032 — Chat attachments, local vision, better meeting recording (2026-10-22)
- **Attachments in the chat** (paper-clip: gallery photo, camera, PDF/Word/Excel/PowerPoint/text/CSV/JSON/HTML):
  the phone uploads each file once (`POST /api/v1/attachments`, ≤ 12 MB, kept 30 days in `data/attachments`);
  pictures are shrunk to ≤ 1600 px and their words read by ML Kit ON the phone (free, exact). The server extracts
  the text (pypdf, python-docx, openpyxl, python-pptx; Office files are zip-bomb checked), the chat message carries
  only ids. The main agent sees names + as much text as fits (3.5k chars on the local model, 14k on a cloud one);
  long documents say "dipotong" and any worker it starts receives the ids and reads the rest with the MCP tools
  `read_attachment` / `see_attachment`. Document text is data, never instructions; sensitive content inside keeps
  the whole turn on the local model. A scanned PDF is reported as a scan, not as an empty file.
- **Local vision:** Qwen3.5-2B runs with its vision projector (`--mmproj`, +0.7 GB, `llm_providers.vision = true`).
  Measured: a 450×1000 picture = 459 tokens ≈ 55 s; text in the picture is read almost perfectly; descriptions can
  embellish, so the phone's OCR text always travels with the picture. The 4B with a projector gave the same quality
  at 5× the time. Local pictures are held to 768 px (≈ 0.5k tokens); a cloud model gets 1280 px.
- **Meetings:** (1) the phone captures CONTINUOUSLY (AudioRecord → AAC encoder → ADTS files cut on a frame
  boundary): the old MediaRecorder stop/start lost ~0.2 s of speech every minute; (2) live level meter + warning
  when the room is silent for 20 s; chunks left on the phone are uploaded at the next start; (3) the owner can type
  participants and agenda: they feed Whisper's prompt/hotwords, a fuzzy corrector for misheard names/terms
  ("Bu Rinah" → "Bu Rina"), and the minutes' prompts together with related memories; (4) a wider Whisper beam (default 2, `WHISPER_MEETING_BEAM`) with VAD
  padding — measured on 12 noisy TTS sentences, beam 3 lowered WER by 1.0–2.6 points (17.8→16.8, 18.7→16.1) but costs
  2–3× the time (30 s of audio: 29 s at beam 1, 95 s at beam 3 under load), beam 2 was NOT measured; while a
  high-pass + dynamic-normaliser/denoise chain did not help (16–19 % either way, also at −22 dB), so that filter is an
  opt-in (`MEETING_ENHANCE`), not on; (5) unsure segments are
  marked `[?]` and never become decisions or tasks; (6) "Pembicara 2" can be renamed in the app (minutes, search
  index rebuilt); (7) a recording abandoned for 20 minutes is processed automatically.

## ADR-033 — The chat model is now Qwen3.5-4B Q4_K_M (2026-10-22)
Owner's decision after a replay of 12 real requests through the main agent's own prompt and tools: 4B chose the
right action 9/12 (2B: 7/12 — its misses were promises without action, small talk where a task was due, a missed
"stay silent"), at ~41 s warm median instead of ~16 s; first turn after a restart ~4–5 min. Pictures: 4B + projector
~4–5 min per picture under load (2B: ~1 min). Both llama servers load the same GGUF (mmap'd once). The 2B file stays
on disk as a fallback (switch back in docker-compose.yml).

## ADR-034 — YouTube from JARVIS' own origin; charts and playlists (2026-10-22)
- **YouTube in the app:** the owner's v0.11.0 still showed no playable video. A page created inside the WebView
  (`loadDataWithBaseURL`) has no real origin/referrer and YouTube refuses the embed (error 152/153). The player page
  is now served by jarvis-core at `https://vis1.cosger.online/embed/youtube/<id>` (IFrame API, public, no data) and
  loaded with `loadUrl`; its document title reports playing/paused/ended/error, so the app knows when a video ended
  (no JavaScript bridge) and explains blocked videos ("owner does not allow embedding" → "Putar di YouTube").
- **Charts:** `charts.py` — Deezer genre charts (current, most-played; no key) for R&B, pop, rap, rock, dance,
  electro, jazz, alternative, reggae, blues, latin, classical, metal, "Asian" (K-pop); the Indonesian iTunes Store for
  "lagu Indonesia" and as fallback. iTunes genre charts were rejected as primary: its R&B list was mostly classics.
- **Playlists:** `playlists.py` (tables `playlists`, `playlist_items`; default "Playlist saya"). Songs are stored as
  title + artist and fetched at play time like any song (licensed → MP3 → official YouTube). "carikan lagu RnB top 10
  dan masukkan ke playlist saya" and "putar playlist saya" are direct actions; the main agent also has
  `playlist_add` / `play_playlist`, Hermes `music_chart` / `playlist_add` / `playlist_show`. The music and video
  panels show position and next songs, previous/next buttons, and report "ended" so the next song starts.

## ADR-035 — Drafts are written by core, shown copyable and saved as .docx (2026-10-22)
The owner asked for an email reply draft (two screenshots attached) and got only "saya akan bantu buatkan draft…":
the promise guard took the long promise for an answer, and earlier attempts went to Hermes (tens of minutes on this
CPU, often cancelled). Now:
- `router.parse_action` recognises "bikin/buatkan/draftkan/tulis … draf/balasan/reply … email/surat/pesan/ini" (and
  "balas(kan) email") as `write_draft` — also when files or screen text are attached.
- `assistant.start_draft` puts everything in the task's instruction: the owner's words, the attachments' text (the
  phone's OCR of screenshots), the screen text and the last 6 turns. The main agent also has a `write_draft` tool, and
  `draft_reply` without screen text falls back to it.
- `writer.produce` (worker task, no Hermes): one `balas-pesan` call → JSON (to, subject, email, body); unknown facts
  become `[isi: …]` placeholders. It shows a board with a draft block (Salin / Buka email — already in APK 0.11.0) and
  the .docx (Buka / Bagikan, also in menu Dokumen). `stage.validate(..., drafts=True)` lets only core put a draft in a
  board. JARVIS still never sends anything.
- Measured on the real request: 101 s locally, English as in the original email, signed "Ilham".

## ADR-036 — Simpanan: one menu for everything JARVIS made or showed (2026-10-22)
The owner asked for one place to find what the AI produced. `core/app/library.py` lists, newest first, documents
(drafts separately), playlists, songs fetched as MP3 (`/data/media`), finished meetings' minutes, and — new —
everything shown on the front screen: `stage.show` records each panel (not song panels) in `stage_history`
(migration 014, last 500 kept). Keys are `<source>:<id>`. Endpoints `/admin/library` (+ `/show`, `/keep`, DELETE),
served to the phone under `/api/v1/console`. Starred items (`library_kept`) are never purged: songs survive
`musiclib.purge_old`, history entries survive the 500 cap. The main agent has `show_saved` ("tampilkan lagi gambar
tadi"), Hermes `saved_items` / `show_saved`. APK 0.12.0: Lainnya → Simpanan (filters, search, Putar/Tampilkan,
Buka/Bagikan, ★ Simpan, Hapus with confirmation). Meetings are deleted from the Rapat menu only.

## ADR-037 — Phone signs in with the admin password; YouTube player without autoplay (2026-10-22)
- `POST /api/v1/devices/pair {password, device_name}`: core asks the web admin (`/internal/check-admin-password`,
  internal network only) to verify the password against `ADMIN_PASSWORD_HASH`, then makes an owner-scope device
  token for that phone. The password is never stored, logged or audited. Lockout: 5 wrong per IP / 15 min (core),
  10 wrong per hour overall (admin). APK 0.12.1 Pengaturan: "Password admin" (token entry stays under "lanjutan").
- YouTube in the app was a black box: the embed page autoplayed, and an autoplaying player inside the WebView
  showed nothing (reproduced headless; without autoplay the thumbnail + play button appear). The page no longer
  autoplays, fills the frame, is served `no-cache`, and reports its state to `/embed/youtube/{id}/state`
  (logged only) so playback on the phone can be diagnosed. APK: a new video gets a new WebView (`key(url)`),
  hardware layer, no clip on the video surface.

## ADR-038 — Models are picked from OpenRouter's live catalog, and settings are changed by chat (2026-10-22)
Owner: "jangan tulis tangan, kasih pilihan yang ada di OpenRouter"; only Qdrant and n8n are permanent (this
supersedes "Hermes permanent": Hermes keeps running as the worker, but its model is a free choice); JARVIS must
change settings on request ("dia bingung mengerjakan sesuatu yang belum pernah diset").
- `openrouter.py`: the public catalog (`/api/v1/models`, ~470 models, cached 1 h): price per 1M tokens, context,
  tools/vision/audio, free. `/admin/openrouter/models` (search, filters, sort) feeds the app's picker.
- `composition.set_model/set_total_budget/create_category/delete_category/summary/check_openrouter`. A model id
  must exist in the catalog (typo → "maksudmu …?"); chat/Hermes categories need tool calling, vision needs images;
  output price > $15/M asks for confirmation. Presets drop ids OpenRouter does not have (the old "hemat" preset
  had written `minimax/…:free` → HTTP 404 on every chat turn). CORE = Qdrant, n8n.
- Main agent tools `find_models` + `ai_settings` (show, set_model, set_budget, set_stt, set_strong_mode,
  apply_preset, create_category, delete_category, check_openrouter, list_settings, change_setting). The agent used
  to have none, and its self-description said the composition "can only be changed from the app". Guards
  (`chat_settings.guard`): owner-scope device, recognised voice, and never in a turn with attachments or screen text
  (outside text is data); secrets never via chat; all audited. Workers accept any category with `worker = true`.
- OpenRouter health (`billing.judge`): a 402 stays final until a real paid call (cost ≥ $0.0005) works. Tiny
  probes proved nothing — with ~$0 left a 16-token call passes while a 400-token one is refused ("can only afford
  104") — so `check_openrouter` probes with max_tokens 400 and the credits number counts too.
- APK 0.13.0: Komposisi AI shows each category's chain with name and price, "Ganti model utama" / "+ Cadangan"
  open the full-screen picker (search, Gratis / Bisa alat / Bisa lihat gambar, sort by price/newest/context/name),
  "Cek OpenRouter", editable monthly budget.
- **Addendum (2026-10-23): a dead pick must never mean the slow local model.** The owner picked
  `thinkingmachines/inkling:free` for chat: OpenRouter lists it but answers HTTP 403 ("only available on agentic
  harnesses"); with a one-route chain every message failed in 50 ms and then waited 2–7 min on the local CPU (web and
  productivity also had a 404 model, vision a rate-limited one). Now: `composition.set_model` sends one real request
  (`_probe`) and refuses a model OpenRouter rejects outright (400/403/404/422); the gateway skips such a model for
  10 minutes (`gateway._mark_failed`); and when the chosen models fail, a cheap cloud safety net
  (`gateway.SAFETY_MODEL`, setting `composition:safety_model`, never for /privat or vision) answers before the
  local model. Chat replies went from minutes to 1.4–3.6 s.

## ADR-039 — Choosing a model with the facts: pros, cons, failure rate and speed per model (2026-10-23)
Owner: "pilih model secara advance … tahu kelebihan dan kekurangan, mana yang sering error, berapa kecepatan response".
- `modelinsight.py` joins four sources, kept apart in the UI: the catalog (price, context, abilities), OpenRouter's
  public per-provider stats (`/models/{id}/endpoints`: uptime, latency p50/p90, throughput, quantization), JARVIS' own
  calls (`llm_usage`, real traffic only: success rate, median/p95 time, first token, cost per call, errors by cause)
  and the owner's live check (`model_bench`, migration 015: first token, tokens/s, does it call a tool).
  Failures from missing credit (402) are the account's fault and are left out of a model's success rate.
- `assess()` turns the numbers into pros / cons / "good for", each with its figure. It measures price, speed,
  reliability and abilities — not how smart the answers are, and the app says so. A model that fails in practice is
  not "good for" anything.
- Endpoints `/admin/models/{id}/insight`, `/admin/models/stats`, `POST /admin/models/bench` (two requests ≈ $0.0001),
  and the picker's list carries a per-model badge of JARVIS' own results.
- APK 0.14.0: tapping a model in the picker opens its detail (pros/cons, OpenRouter numbers, JARVIS numbers, "Uji
  sekarang", "Pakai sebagai utama/cadangan"); Lainnya → Statistik model lists every model used, by usage, error rate or speed.
- Questions about models are answered by code, not by the chat model (`model_answers.py`, router intents
  `openrouter_check`, `model_stats`, `model_compare`): asked to compare two models the chat model invented prices,
  context sizes and abilities, and for "cek saldo" it only promised. The router recognises them, resolves the names
  against the catalog (preferring models JARVIS already uses, never `:batch`/alias variants, free only when asked) and
  the answer is built from the data. An unknown name falls through to the chat model. The prompt now also forbids
  quoting model numbers from memory, and spawn_task is for research, not for settings questions.

## ADR-040 — Blueprint v2: free-first model router with diagnosis, per-task budget, richer tasks (2026-10-23)
The owner's blueprint (self-learning, multi-model, free-first) is adopted on top of the running system, not as a
rewrite (see docs/blueprint-gap.md). Decisions: the app stays native Kotlin; Local Agent/Blender wait for a PC; free-first
is measured; this round is Sprints 0–4. Roles: the main agent (`assistant.py`) talks to the owner, Hermes plans and works
behind the Task Manager.
Sprint 1 — `modelrouter.py` around the gateway: requirements (tool calling), measured health (a model failing in
practice goes behind healthy ones; `model_bench` tool checks count), verified free alternatives (proven free models,
then `openrouter/free`) when the owner's first choice is free, diagnosis before paying (a 5xx/network failure is retried
once; 429/403/404 go to the next free option; only `paid_attempt_limit` paid models are tried after a free one failed;
402 ends the paid path), a per-task budget (default $0.50; over it → no paid calls, phase `waiting_approval`, an approval
`task_budget` adds budget) and an optional daily cap. Free endpoints may log prompts, so attachments/screen text and
drafts never reach them (`NO_FREE`). Every `llm_usage` row now carries `task_id`, `retry`, `fallback_reason`; `tasks` carries
goal, criteria, plan, phase, budget, cost, artifacts, retries, model_used. `core/config/model_registry.yaml` is a template
(preset `blueprint`, ids validated, a missing id is dropped), not the source of truth. New category `review` (a reviewer
other than the author). Bug found by the tests: `openrouter/free` was counted as a paid model.
- **Sprint 2 (2026-10-23) — capability registry and a planning worker.** `capabilities.py` + migrations 017/018: a
  searchable catalog (by meaning, local embeddings, + keywords) of skills (every `SKILL.md` under Hermes' skills folder),
  tools (assistant.TOOLS) and the built-in workers, each with status, tested flag, runs/successes/failures, cost and
  version (a changed skill gets a new version, the old text kept, `tested` reset). Filled automatically at startup
  and hourly; JARVIS' own (`skills/jarvis*`, workers, tools) rank above third-party skills (which need a ≥0.65 match).
  Before an owner task starts, the worker is shown the relevant capabilities with their record ("teruji, berhasil 8 dari
  9") — reuse before research. Hermes got three MCP tools: `capability_search`, `task_plan` (criteria + steps, phase →
  executing) and `task_verify` (evidence, scores the capabilities it used; verified success marks one tested). A planned
  task never verified gets a note in its report; a failed owner task gets ONE automatic second attempt with the diagnosis
  in front of the worker (`tasks.recovered`). Found by tests and live: jsonb values must be passed as Python objects
  (the db codec encodes them), and main.py used `assistant` without importing it (the sync failed and the
  self-improvement loop broke for a few minutes) — a static undefined-name test now guards every module.
- **Sprint 3 (2026-10-23) — memory with provenance and a memory of experience.** Migration 019. `memories` gained
  confidence, verified, evidence, superseded_by, last_used: a statement carries where it comes from and how far it is
  trusted (assumptions 0.4, facts 0.7, preferences 0.8, verified ones rank higher; prompts mark assumptions and
  unverified inferences). Near-identical text (≥0.95) is merged instead of stored twice. `memory.correct` saves the
  corrected statement and marks the old one stale, pointing at its replacement (kept, so a correction can be undone);
  the main agent has `memory_correct`, Hermes `memory_correct` / `memory_save(evidence, verified)`. Nightly upkeep (03:00
  WIB, when the server is calm): merge duplicates, retire unused unverified assumptions after 60 days, delete replaced
  unverified memories after 90 days; verified facts and preferences are never retired automatically. Secrets were already
  refused by `sensitive.scan`. New episodic memory (`episodes`: goal, approach, result, success, cost, model, lesson,
  with the goal's embedding): written when an owner task ends (a failure leaves its lesson); a task that resembles an
  earlier one starts with "TUGAS SERUPA PERNAH DIKERJAKAN" (older than 30 days: marked possibly outdated); failures older
  than 180 days are pruned. New `goals` (active/paused/done, priority 1–5, due date): the main agent tool `goal`, active
  goals shown every turn, `/admin/goals`.
- **Sprint 4 (2026-10-23) — learning skills safely.** `skills_pipeline.py`, migration 020, `skill-sandbox.sh` +
  `jarvis-skill.path/.service`. Three kinds of learning stay apart: knowledge → memory with source; PROCEDURE → a skill
  through `skill_submit` (Hermes is told in `jarvis-self-development` to use it instead of `skill_manage`); system changes →
  approvals / `dev.py` as before. A submitted skill is validated deterministically (name, required sections — kapan
  dipakai, input/output, langkah, kriteria berhasil, jika gagal, izin, kasus uji —, size, no secrets, no policy-changing
  or dangerous instructions such as "abaikan aturan" / "matikan persetujuan" / `curl | sh`, scripts limited to an
  import allowlist with no `open`/`eval`/network), then judged case by case by a model that is not the author (category
  `review`, created by migration with GLM 5.3 Flash — cheap and different — plus the local fallback; a model that cannot
  answer counts as a failed case). Skills with scripts are run in a throwaway container (no network, 128 MB, ½ CPU, 64
  processes, read-only filesystem, no capabilities, user 65534, 20 s; verified live: network blocked, writes refused,
  memory hog killed, no credentials) by a root runner on the host — core never holds the docker socket. Instruction-only
  skills that pass are published (written to `data/hermes/skills/jarvis-learned`, which Hermes reads) and the owner is
  told; skills with scripts also wait for the owner's approval (kind `skill_publish`, with the test summary). Each published
  version is kept (`capability_versions`, with cases/results/scripts); `rollback` restores the previous one as a new version,
  `retire` removes the folder. A failed use marks a capability untested again. Limits: 12 submissions a day. Hermes' lean profile
  now treats every folder starting with `jarvis` as its own. Main agent tool `skill_manage` (list/rollback/retire), `/admin/skills`.
- **Hardening found by running it for real (2026-10-23).** (1) Hermes does not send its session id to the gateway, so per-task
  cost and budget never worked for its calls: a call is now tied to its task by the `[tugas #N]` marker in the first
  user message (`modelrouter.task_id_from_body`); a real task now shows its cost and model. (2) A cancel arriving after a
  task finished (report delivery, shutdown) no longer overwrites `completed` with `cancelled`. (3) After a core restart the old
  Hermes runs kept going while the tasks were started again — every deploy doubled the runs until Hermes refused ("max 10"):
  `resume_after_restart` now stops the old run first, and a full Hermes is waited for instead of failing the task.
  (4) `capabilities.record`: a failed use marks a capability untested. Acceptance: `core/tests/test_acceptance.py` (Blueprint §15,
  one test per criterion + the hardening above) and `/admin/kpi` (task success, evidence-checked results, recovery, skill reuse,
  cost, manual interventions, latency). Real run: the same gold-price task took 112 s and, repeated, 37 s starting from the
  earlier episode ("masih sama dengan pengecekan sebelumnya"). Not done this round (owner's decision): Sprints 5–7 (image
  generation, Local Agent/Blender, app screens for Skills & Learning / task phase+cost, proactive n8n). The `blueprint` preset
  exists but is not applied; the owner's current composition already matches most of it.

## ADR-041 — Unified framework: Blueprint v3's six layers on top of `jar` (2026-10-25)
The owner's "Blueprint Terpadu v4" adopts v3's map (L1 interface, L2 sensors, L3 gate, L4 Hermes brain, L5 knowledge,
L6 proactive) WITHOUT a rewrite: every v3 module maps onto what `jar` runs (docs/blueprint-gap.md), only the difference
is built. One Hermes (Hermes-Brain) with three work profiles (Regular, Project, Company); the security gate (PII scan, vault,
budget, router, `/privat`) stays separate in front of it; one memory (Postgres + Qdrant, ADR-018). Not taken from v3:
Flutter, Neo4j/SQLite, unreviewed skill registration, automatic crypto transactions, unofficial WhatsApp, many parallel
agents. Deferred: CCTV/RTSP/Tailscale. Work proceeds per phase with a Gate the owner approves; nothing reaches `main`
before that.

## ADR-047 — Self-change ladder and the admin page as the control point (2026-10-25)
Extends ADR-026. The owner decided JARVIS may change the app and the web, so the app can no longer be the place where
JARVIS' own changes are approved. Fase 0:
- **Protected zone (T3, humans only)** is decided by `core/app/selfdev_policy.py` as it is on `main` (the runner calls the
  main checkout's copy, never the branch's; the file protects itself): the WHOLE `infra/admin/` (it held the approve
  button and `envfile.py`, the `.env` writer, which were not protected), the runners, systemd, compose, `.env`, Hermes'
  SOUL/config/plugins, the build chain, and the guards (`approvals`, `vault`, `sensitive`, `dev`, `selfdev_policy`,
  `modelrouter`, `chat_settings`, `skills_pipeline`, `gateway`, `composition`, `budget`, `main`, …, `core/config/`).
- **Tests are never weakened**: the runner refuses a diff that deletes a test file or removes/rewrites a test or
  assertion line (adding tests is fine). Old migrations still may not be edited.
- **Approvals of own code are admin-page only** (`approvals.ADMIN_ONLY` = code_change, code_design, skill_publish):
  approving from the app console, chat or voice → 403 with "setujui di halaman admin"; rejecting stays possible
  everywhere (always safe). The app shows the note instead of the approve button.
- **The approval request is built by the runner from the real diff**: tier, changed lines, files, test summary (counts
  from the actual test run), diffstat, new packages; JARVIS' `why` is shown labelled "tidak diverifikasi".
- **Pause switch** at the admin page (Diri JARVIS → Pengembangan diri): stops every new code proposal and skill
  submission at once. It and the T2 switch can only be flipped from the admin page (the app console gets 403).
- **Ladder**: T0 skills/n8n/schedules; T1 backend ≤1500 lines (as before); T2 Android code or ≤6000 lines — only
  when the owner opened T2 at the admin page, after a design (`propose_design`) was approved there, then the result is
  approved again (two approvals, K2); T2 *display* changes (app screens, web views) stay locked until before/after
  screenshots exist (Fase 4); T3 refused. T2 is CLOSED by default.
- **APK rollback** (design + mechanism): Android refuses a lower versionCode, so going back = rebuilding the android tree
  of an earlier release (`build-apk.sh <ver> <notes> --android-from <commit>`) as a new version the updater offers
  normally; releases.json now records the full commit and whether the build was reproducible (no uncommitted android/).
  A one-tap button at the admin page is a later step (needs a host request path like jarvis-apply).
Acceptance (core/tests/test_acceptance.py `test_v4_f0_*`): admin-page-only approvals (app 403, admin 200, app may reject,
switches 403 from the app), chat/voice cannot approve code, the pause stops proposals and skills, T2 needs the switch and an
approved design (and closing T2 stops it), the approval shows the runner's findings; unit tests for the policy; a live check
of the runner's policy step against a real git commit (admin file + weakened assertion → both refused).

## ADR-042 — Company Federation: one Jarvis-GM, Hermes-DGM as a remote member (2026-10-25)
Owner confirmed Company Federation as the first priority (K5). One component, not one service per company:
- **Data** (migration 022): `companies` (id, aliases, adapter, Hermes-DGM URL, AES-GCM-encrypted token and callback secret,
  `contract_verified`, callback timeout, max retries, monthly budget), `company_vault` (core constraints, strategic pivots,
  validated findings, KPI, cash flow with structured `data`, notes), `gm_directives`, plus `tasks.company_id` and
  `episodes.company_id`.
- **Isolation in three layers**: (1) every access function takes a `company_id` and refuses an empty/unknown one;
  (2) every query runs in a transaction with `SET LOCAL jarvis.company` and Postgres row-level security (FORCE'd, so the
  owning role `jarvis_core` — not a superuser — obeys it): outside a scope every company table looks empty, and a row for
  another company cannot even be inserted; queries ALSO carry an explicit `company_id` predicate; (3) company knowledge has
  its own Qdrant collection and every search carries a mandatory `company_id` filter, results re-read under the scope.
  Hermes' read-only SQL role is never granted these tables. A company task's worker sees only that company's vault and
  that company's earlier episodes.
- **Routing (2×3 Company row)**: a turn naming ONE company → fast lane (KPI, cash flow, constraints, directive status from
  stored data, no model) or heavy lane (the main agent's `company_directive` / `company_knowledge` / `decision_record`
  tools, or a company-scoped task); prefix "riset:" / "cepat:" wins. A turn naming two companies gets no company data
  and the agent asks which one.
- **Jarvis-GM (`gm.py`)**: directive → classified; anything that spends money, publishes or messages outsiders (known
  action, any budget, or the words used) or exceeds the company's monthly budget waits for the owner's approval BEFORE it is
  sent (`company_directive`); otherwise it goes out at once. `task_key` (UUID) is the idempotency key on every (re)send; a
  repeated key returns the existing directive. Callbacks: `POST /api/v1/gm/callback/{company}`, HMAC-SHA256 of
  "<timestamp>.<body>" with the company's secret, ±5 min, deduplicated by `callback_id`, bound to the company in the URL;
  `needs_approval` → approval `company_action` whose decision is relayed back. No callback by the deadline → resend with the
  same key up to `max_retries` (backoff 30 s, 2 min, 8 min…), then `timed_out` and the owner is told. Jarvis-GM may cancel.
- **Hermes-DGM contract: BELUM DIVERIFIKASI.** `MockDGM` simulates a DGM through the REAL signed callback path; `HttpDGM`
  follows blueprint v3's draft (POST /directives, /directives/{task_id}/decision, /cancel, Bearer token) and refuses to
  call out until the owner ticks "kontrak sudah kucocokkan" at the admin page. Adapter, URL, token, secret rotation and the
  verified flag can only be set at the admin page (Perusahaan tab).

## ADR-046 — Relational memory in Postgres: Decision Vault and entity relations (2026-10-25)
`decision_vault` (per project or company: core constraint, correction/pivot, validated finding, technical preference;
company rows under the same row-level security) and `entity_relations` (subject —relation→ object, optionally owned by one
company). The main agent records decisions with `decision_record`; Hermes with `decision_record(task_id, …)`, scoped to its
task's company. Company decisions are part of the company context given to its tasks. A graph database only if a relation
query cannot be served here (none so far).
Acceptance (`test_v4_f1_*`): Renature never reads Jack Healer (context, vault, Qdrant search, credentials, and Postgres RLS as a
non-superuser role, including a refused cross-company insert), a company task sees only its company, the same task_key never
runs twice, missing callbacks → bounded resends with the same key then the owner is told, external-effect directives stop at
approval (including one disguised as a plan), callbacks are signed/deduplicated/company-bound and an approval request is
relayed back, the mock round trip completes and the fast lane answers from stored data without a model.

## ADR-048 — Voice complements around the engines, and the owner's choice of voice (2026-10-26)
Blueprint v4 Fase 3 + the owner's request (2026-10-25) to switch JARVIS's voice and ears to OpenRouter models, ElevenLabs
included, with its character. The engines stay (Whisper local / Groq / Deepgram, and now any OpenRouter STT model); JARVIS
closes their gaps. Nothing that already works was removed: the phone's own voice stays the default.
- **Measure first (3.1)**: every utterance → `voice_events` (engine, model, confidence, latency, raw and final text, what each
  complement did or would do). A secret or `/privat` utterance is stored as "[disensor]". The owner's corrections label them —
  by voice ("bukan UAT, maksudku Ashar", "itu bukan aku yang ngomong" → `voice_correction`), in the admin page's Suara tab,
  or `POST /api/v1/voice/correct` — and each is classified: nama, angka, istilah, gema, halusinasi, derau, lainnya. Baseline
  per engine (utterances, confidence, p50/p90 latency, low-confidence, dropped, WER on corrected ones) at the Suara tab.
- **Complements (3.2)**: `kamus` (the owner's misheard→meant pairs, then near-miss names: companies + aliases, learned pairs,
  configured keywords — `meetings.correct_terms` now also for everyday speech), `halusinasi` (phrases the owner disowned twice
  become learned hallucinations), `gema` (JARVIS hearing its own last sentences), `opini_kedua` (a doubtful utterance also
  heard by a second engine; "auto" never sends audio to a cloud the owner did not choose — a cloud primary is checked by local
  Whisper), `ambang` (the 'possibly misheard' line calibrated per engine). Money in a spoken command: the agent repeats the
  figure and asks before acting (rule, always on).
- **Quality gate (3.4, `voice_quality.py`)**: a complement starts in SHADOW — it logs what it would change and changes nothing.
  It goes ON only when, on the corrected utterances, WER drops AND false corrections (a right utterance made wrong, or a real
  one dropped) stay ≤ 1%, with ≥ 20 samples; a pair learned from an utterance is left out when judging that utterance. An ON
  complement that stops passing returns to shadow by itself (audited). Runs nightly (04:00) and on demand. The owner can force a
  mode at the admin page (then it is manual). Learned data (`voice_data`) is versioned row by row: undo keeps the history.
- **Spoken copy (3.3, `speech.py`)**: what is SAID is normalised on the server — rupiah/dollar amounts, percentages, dates,
  times after "pukul/jam", units, phone numbers digit by digit, versions, abbreviations (yg/dgn/tdk/dll…), the owner's
  pronunciations ("Renature" → "ri-ne-cer", `voice_pronounce`), very long sentences cut at a comma. "say" events carry the
  spoken copy; replies/reports/announcements keep their text for the screen and gain `speech`.
- **Cloud voice**: Komposisi → "Suara JARVIS" in the app lists OpenRouter's TTS models (ElevenLabs first) with price and
  characters, "Coba" plays a sample, "Pakai" chooses it (also by chat: `voice_settings`). The phone fetches each sentence from
  `POST /api/v1/voice/speak` while the previous one plays and falls back to its own voice whenever the server refuses: private
  or sensitive text, a turn with attachments/screen text (`local_voice`), budget used up (402), no key/unreachable. Audio is
  cached on the server; cost comes from OpenRouter's generation record and counts in category `suara` of the monthly budget.
- **Consent (K3)**: utterance audio is kept (doubtful ones + 1 in 5, ≤ 500 MB, 60 days, never sent anywhere) only after the
  owner allows it at the admin page; the switch and the complements' modes are admin-page only.
- `voice.py`, `voice_quality.py` (and Fase 1's `companies.py`, `gm.py`) joined the protected zone: JARVIS may improve
  `speech.py` and teach data, never loosen the gate, the privacy checks or company isolation.
Acceptance (`test_v4_f3_*`): baseline per engine without storing a secret, a correction classified and taught; a complement stays
in shadow until 20 corrected samples pass, goes live, and returns to shadow by itself when a bad entry causes false corrections;
JARVIS's own echo and a twice-disowned phrase are filtered only once allowed; the cloud voice speaks the normalised copy,
caches, records the exact cost, refuses private/sensitive text and an exhausted budget; voice settings by chat (refused for a
non-owner voice), consent and modes only at the admin page, audio kept only with consent.

## ADR-049 — The canvas is 3D: a galaxy per context; gestures on the device, navigation only (2026-10-26)
Blueprint v4 Fase 4. The owner changed the plan from a 2D infinite canvas to a **3D** one: "seperti ada di galaxy ruang
kerjanya". K4 (library) and K10 (web first) were left to us ("ok"): three.js r160 (MIT, vendored with its licence — no CDN at
runtime, no watermark), web first; the APK can load the same page later (Fase 5).
- **Model (migration 024)**: `canvases` (one per context: `utama`, `project:<slug>`, `company:<id>`), `canvas_nodes` (kind, a
  reference `<type>:<id>`, x/y/z, size, pinned), `canvas_edges`, `canvas_versions` (every change; last 60 kept; restore brings
  positions and links back, cards whose thing is gone stay gone). No column holds text: a card's title/snippet is read from
  where the thing lives (tasks, documents, stage_history, memories, goals, meetings, playlists, songs, company vault,
  directives, decisions) every time the canvas is read — the canvas stores layout, not knowledge.
- **Isolation (§4.4)**: a company galaxy accepts only that company's own vault entries, directives, decisions, tasks and those
  tasks' documents; a personal galaxy nothing that belongs to a company and never vault/directive refs. Checked on add AND on
  read; the four tables carry `company_id` under the same FORCE'd row-level security as ADR-042 (tested as a non-superuser role).
  A company galaxy also has only company constellations (tugas, data perusahaan, arahan, dokumen, keputusan).
- **JARVIS places its work**: a finished owner task (not private) → its company's galaxy or Utama; a document → the galaxy of
  the task that made it; whatever JARVIS shows on the phone → Utama. Tool `canvas` (place / focus / link / list) for the main
  agent; "focus" makes every open viewer fly to a card. Placement: each kind is a constellation on a spiral arm; cards spiral
  around it by the golden angle; the owner can move them anywhere (the space is unbounded).
- **Viewer** (`/canvas/`, static, same origin as the API, strict CSP, served by jarvis-core): a spiral galaxy of particles,
  background stars, one glowing constellation per kind, cards as glass panels that grow as you approach and turn into stars far
  away (the 140 nearest are drawn as cards). Orbit/pan/zoom with mouse, touch (two-finger pinch) or WASD/QE; drag a card through
  space; double-click flies to it; search; "+ Kartu" (only things allowed in this galaxy); version history; deep link
  `#kartu=<id>`; reduced-motion → jumps instead of flights. Sign-in with the admin password creates the browser's own device
  token (revocable in Perangkat). It can take a card off the canvas (confirmed, never through a gesture) — never delete data,
  approve, send or pay.
- **Gestures (4.0)**: MediaPipe hand landmarks in the browser (code from jsdelivr, model from Google storage); the camera runs
  only while the mode is on, with a visible preview and a red frame, nothing stored or sent. Pinch is computed from fingertip
  distance with hysteresis; a pose acts only after 3 stable frames; open palm held still 1 s turns the lock on/off; fist pauses;
  a minute without hands switches it off. `gesture.html` is the separate prototype with live FPS, camera-to-cursor latency and a
  false-trigger counter (targets: ≤ 100 ms, ≤ 1 per 10 minutes) for the Gate; in the viewer the mode is optional and a gesture
  "click" only reaches navigation controls (data-gesture="ok"), never "Lepas" or a confirmation.
- `canvas.py` and `gestures.js` joined the protected zone (isolation; what a gesture may do); the viewer files are "display"
  (T2-locked for JARVIS beyond T1). Pure JS (gesture machine, galaxy geometry, search/diff) is tested with node in
  `infra/scripts/test-core.sh`.
Acceptance (`test_v4_f4_*`): each context is its own galaxy and companies never mix (refused cross refs; RLS as a non-superuser
role, including a refused insert); JARVIS places a finished task end to end, a document and what it showed, idempotently,
and the canvas holds references only (a renamed task shows its new title; a private task never appears); moves anywhere,
links, focus, version restore, and hiding a card never deletes the task; the viewer is served with its CSP, path traversal is
refused, and changes need the owner's device while any paired device may look.


## ADR-043 — OpenJarvis spike: measured against Hermes-Brain, same problems, same model (2026-10-26)
Blueprint v4 Fase 2 (D3: OpenJarvis inside Hermes as a heavy worker — a proposal pending this spike). The owner chose the
test task ("rekonstruksi / peningkatan performa diri", K7) and capped the spike at **$1** (K8, 2026-10-26).
- **Fairness.** Both runtimes get the same three problems, the same prompt, the same caps (60 turns, 25 min) and the same
  model — category `spike` (migration 025: `deepseek/deepseek-v4.1-flash`, the cheapest tool-capable model that fits $1 for
  18 agent runs at the catalog price of 26 Oct; changeable in Komposisi AI) — reached through JARVIS' gateway, so the
  budget, the model rules and the usage log hold. `spike` is a STRICT category: no safety model, no budget reordering, no
  local fallback (a failure is a measured failure, not a slow success), refused once its $1 is spent (fresh budget state).
- **Isolation.** Each runtime has its own gateway key, valid for `spike` only (403 elsewhere; `/v1/models` lists only
  `jarvis-spike`); the DB keeps only their SHA-256 (`settings_kv spike:key:<runtime>`), which also attributes cost per runtime
  (`llm_usage.caller = spike-hermes | spike-openjarvis`). "Hermes" is a second container from jarvis-brain's image and init
  script with `JARVIS_SPIKE=1`: no JARVIS tools (MCP), no shared memory, no schedules, toolsets file + code + todo — the same
  agent loop with none of JARVIS' reach (the real jarvis-brain could message the owner mid-test). OpenJarvis (commit 40092da,
  Apache-2.0; built with Rust 1.89 — upstream's image pins 1.88 and fails) runs `orchestrator` on engine `vllm` pointed at the
  gateway, tools `file_read,file_write,apply_patch,code_interpreter,think`, `allowed_dirs=/work`, no memory context, analytics
  off. Both containers are started by `infra/spike/spike.sh` with `docker run` (never from docker-compose.yml), no published
  ports, 2 GB, no-new-privileges, and see only the workspace. Neither touches the repo: they work on a snapshot copy.
- **Problems** (real, from `error_log`), each graded by a test the runtimes never see, validated first (`spike.sh reference`:
  the real fix scores 1, the untouched snapshot 0):
  p1 chat failing with KeyError 'openrouter' (25 Oct; snapshot 2f300ca, fix 88e8cce);
  p2 owner tasks failing with Hermes 429 "max 10 runs" after deploys — two causes: orphaned runs after a core restart and no
  wait when Hermes is full (23 Oct; snapshot a4c8a10, fix dc0dfb1; hidden tests split per cause, Hermes full 3× so the one
  automatic second attempt does not pass for a fix);
  p3 the weekly efficiency review of 7 days of `llm_usage` (no prompts, answers or sessions): costliest model, slowest category
  (median), most failing model + a concrete recommendation, checked against values computed from the same export.
  Patch quality = hidden tests passed × (1 if the snapshot's own suite still passes, flaky failures rerun once, else 0.5);
  the runtime's `core/app` is graded on the snapshot with the ORIGINAL tests, so a test it weakened cannot help it.
- **Metrics** (blueprint): quality, cost (gateway), time, failure rate (failed or quality < 1); violations: writes outside its
  own run folder, tools outside its list, model calls outside `spike`; Hermes approval requests are denied and noted.
  OpenJarvis passes only with ≥ 2 of 4 metrics better AND zero violations. 3 attempts × 3 problems × 2 runtimes, sequential,
  interleaved (who goes first alternates); a run never starts when the month's `spike` spend is ≥ $0.95.
- `spike.py`, `infra/spike/`, `infra/openjarvis/` are in the protected zone (JARVIS must not grade itself).
- **Batch 1 (spike1, 2026-10-26) is void as a comparison; recorded as is.** 6 runs, $0.75 of the $1. Hermes lost every run to
  the harness, not its ability: `HERMES_WRITE_SAFE_ROOT` pointed at its own data dir (writes to /work refused — p3's numbers
  were right but could not be saved), code execution waited for an approval nobody could give, and p1 started before the
  container was ready (0 s, $0). Fixed (`HERMES_WRITE_SAFE_ROOT=/work`, approvals off inside the spike, readiness wait;
  `tool_search` only loads schemas and is allowed — its "violation" in p2 was a false alarm). A real finding about OpenJarvis
  with this model: all three runs ended after 24–41 s with the model's tool calls as raw text (`<｜DSML｜ ... >`) that
  OpenJarvis did not execute (it does send native `tools`; Hermes got structured calls from the same model), so OpenJarvis
  scored 0 on p1, p2 and p3 — but cheaper and ~10× faster per attempt ($0.02–0.05, 30–40 s vs $0.12–0.34, 5–17 min).
- **Decision (owner, 2026-10-26): no further testing — implement.** The spike stops after batch 1 ($0.75 of $1 spent; no
  OpenJarvis-vs-Hermes verdict on quality exists, and none of the four metrics is claimed). OpenJarvis is adopted as an
  **optional heavy worker with Hermes-Brain as default and fallback** (D3 as proposed, minus the proof):
  - `openjarvis.py` + service `openjarvis` (compose profile `openjarvis`, set up with `infra/scripts/openjarvis-setup.sh`,
    jarvis-network only, 2 GB, no published port, sees `/work` and nothing else). It thinks through the LLM gateway with its own
    key (SHA-256 in `settings_kv worker:key:openjarvis`, caller `openjarvis`): worker categories only — never `privat`/`ngobrol`
    — so budget, model rules and cost-per-task (`[tugas #N]`) hold; it has no JARVIS tools, no memory, no repo.
  - A task runs there only if (a) the owner switched it on (admin → "Pekerja berat", **off by default**), (b) the main agent
    marked it `berat` (spawn_task), (c) it is an owner task, not private, with no picture. Handover: in = `[tugas #N]` + a short
    brief (not Hermes' WORKER_BRIEF) + the instruction; out = the answer text. `tasks.runtime` / `runtime_note` show who did it.
  - **Fallback:** anything but a usable answer (unreachable, HTTP error, empty, or the model's raw tool-call markup as seen
    in 3 of 3 spike runs) → `runtime='hermes'`, the reason in `runtime_note`, an audit event, and Hermes does the task as if
    nothing happened. The owner always gets an answer; the cost of a failed attempt is the price of finding out.
  - Why off by default: with DeepSeek V4.1 Flash OpenJarvis produced no answer in any of 3 attempts, so with that model most heavy
    tasks would pay for a failed try first. Turn it on when a worker-category model that returns structured tool calls to it is
    chosen (Komposisi AI) — or leave it off; nothing else depends on it.
  - `spike.py`, `openjarvis.py`, `infra/spike/`, `infra/openjarvis/` are in the protected zone.
Acceptance (`test_v4_f2_*`): a heavy task goes to OpenJarvis when it is on and Hermes is never asked; a failed OpenJarvis hands
the task to Hermes with the reason and an audit event; off by default, and private / not-heavy tasks never reach it; its gateway
key reaches worker categories only (403 for privat/ngobrol, 401 for others) and its cost is attributed to it.

## ADR-050 — The canvas in the APK: the same web viewer in a WebView (2026-10-26)
Blueprint v4 Fase 5 (K10: web first, then the APK; the blueprint's suggested option, now taken).
- **One viewer, two shells.** A new menu "Galaksi 3D" (Lainnya → JARVIS) opens `<server>/canvas/` in a WebView. The same code runs
  on the web and here, so there is nothing to keep in step. What the phone adds stays native and outside this screen — microphone
  and VAD, camera, notifications, location, meetings, the console — all unchanged in their own tabs (no regression: nothing in them
  was touched). The web side keeps what a phone does not need (keyboard/trackpad use, the sign-in form, "Keluar").
- **Sign-in without a password.** The app passes its existing device token in the URL fragment (`/canvas/#t=<token>&app=1`); a
  fragment is never sent to a server, and the viewer takes it out of the address at once (`takeAppParams`, tested). The token is
  the same one the app already uses, so it is revoked in Perangkat like any other.
- **Contained.** Only the JARVIS server's own origin is shown in the screen (`sameOrigin`: scheme + host + port; anything else
  opens in the browser); no file or content access; mixed content refused. The page may ask for the **camera** only for hand
  gestures, only from our origin, and only after Android's own camera consent (the CAMERA permission the app already declares —
  no new Android permission, no new Gradle dependency, so K1 is not touched; MediaPipe runs in the page, from the web).
- Gestures stay navigation-only and on-device inside the WebView exactly as on the web (ADR-049).

## ADR-044 — Financial actions: watchers only notify; nothing is bought, booked or traded (2026-10-26)
Blueprint v4 Fase 6. Price, ticket, crypto and gold watchers (`watchers.py`) are **L1 Observe**: they tell the owner something and do
nothing else.
- **No transactions of assets, ever.** No watcher, tool or worker buys, books, pays, logs in to an account or trades. A ticket check
  stops before payment — its message says so ("belum membeli atau memesan apa pun — kamu yang memutuskan dan membayar"); the web
  worker is told in its brief, with hard rules (read only, no checkout, no login, no advice to buy or sell), and the main agent has
  no tool that could pay (a test pins that the tool list has no send/buy/pay).
- **Crypto and gold are information, not investment advice.** The closing sentence is fixed in code, not left to a model.
- **Cheap and quiet.** Crypto is read straight from CoinGecko's free price API (no AI, ≥ 15 min apart); the others are looked up by a
  background worker (kind `watcher`, answers with one `HASIL: {...}` line; ≥ 1–2 h apart because it costs AI, and only while the
  server is idle enough for background work). A message goes out when the condition BECOMES true or the price moved ≥ 2% since the
  last message — never at every check, at most once in 6 hours per watcher; a failing source says nothing. Max 10 active watchers.
- No unofficial WhatsApp, anywhere (nothing in this phase touches it).

## ADR-045 — Gmail and calendar through n8n: Propose, send with approval (2026-10-26)
Blueprint v4 Fase 6; builds on the n8n the owner already has (ADR-017, "workflows are created inactive").
- **Three flows**, created inactive by `inbox.install()` (admin → Inbox & Pantau) and activated only through the usual approval:
  Gmail read (newest unread), Gmail send (ONE email), Google Calendar create (ONE event). Each sits behind a webhook whose path is a
  random 128-bit secret (n8n's address is public). The Google OAuth sign-in is the owner's, inside n8n, on each Google node:
  JARVIS never holds a Google credential. **Templates are BELUM DIVERIFIKASI against a live Google account** (node parameters follow
  n8n 2.x); the admin page says so.
- **L1 read.** `inbox check` (and, if the owner switches it on, a check every 20 minutes) keeps sender, subject and a ≤ 300-char snippet —
  never the whole mail; anything that looks sensitive (OTP, card, password) is not kept at all. Sorting (penting/biasa/abaikan + a
  one-line summary) is done by the **local model only** (category privat, `private=True`); important mail is told once.
- **L2 propose.** A reply or an event is a DRAFT in `outbox`. To leave JARVIS it must be proposed as an approval (kinds `mail_send`,
  `calendar_create`, phone or admin) showing the exact recipient/subject/text or time; only the approved row is posted, once
  (idempotency per outbox row, a row already sent is never posted again; a refused one is closed; an edit after it went out is
  refused; a failed post is recorded and visible). The main agent's tool `inbox` has `send`/`event` that only PROPOSE, and its
  rules say never to claim "terkirim" before approval. Reply drafts use the same rule as drafts elsewhere: not for endpoints that may
  log prompts.
- `inbox.py`, `inbox_flows.py`, `watchers.py` are in the protected zone: what may leave JARVIS is not self-editable.
Acceptance (`test_v4_f6_*`): mail is sorted by the local model only and an OTP is not even stored; a reply is drafted, proposed and
only after approval posted — once; a refused or failed send never goes out; the calendar needs approval and a time zone; the flows are
created inactive, once, behind random paths; watchers notify once, with the fixed wording, never buy; the agent can read, draft and
propose but has no way to send.

## ADR-051 — The canvas is the owner's main desk: everything JARVIS does, visible and live (2026-10-26)
The owner (2026-10-26): the infinite canvas must not be decoration but the main table that shows everything JARVIS does — what the
workers do, n8n, the results of the owner's requests, the list of storage — and when asked to check a website, JARVIS goes to a place
on the canvas where one sees it operating the page: opening it, scrolling, filling in a form. Built on ADR-049/050.
- **A station per task.** A worker task gets its card on the canvas the moment it exists (not when it ends) and, while it runs, the card
  becomes a station: status and time, the page it is on, the screenshot of that page, the last steps ("🌐 Membuka …", "↕️ Menggulir",
  "⌨️ Mengetik: …", read/write file, calculate…) and its current thought. When the owner's own task starts, the camera flies to
  its station (toggle "Ikuti"; once per task; never while the owner touched the screen in the last 4 s; background chores never
  steal the view). When it ends the card keeps the result (a version bump makes open viewers re-read it).
- **Seeing the page for real: one shared browser.** Hermes now browses in a dedicated Chromium (`jarvis-browser`, pinned image
  digest, internal network only, 2 GB) through its documented `BROWSER_CDP_URL`, and core attaches to the SAME browser over DevTools
  to take screenshots (JPEG, about one a second, only while the task used a browser tool in the last 25 s, plus a last look when it
  ends). Chromium refuses DevTools requests whose Host is not localhost or an IP, so a small nginx gateway (`jarvis-browser-gw`)
  presents "localhost" and rewrites the advertised websocket address. The station's tab is the one on the host it was told to open
  (else where it was last seen, else the newest real page) — with two browsing tasks at once the heuristic can pick a wrong tab.
  Clicks and typing are not drawn on the screenshot; the step list says what was clicked or typed.
- **The rest of the desk**, three panels around the core: *Permintaanmu* (the latest requests and JARVIS' answers; anything that looks
  sensitive — OTP, password, card, a /privat message — is hidden), *Otomasi (n8n)* (the latest executions, read from n8n's API) and
  *Simpanan* (counts by kind, the newest items, and a button that lays the whole library out as cards, idempotently).
- **Privacy.** Private tasks never appear; a company's tasks only on that company's galaxy (and its frames only with that context);
  the company desk has none of the owner's panels; frames live in memory only, are served with `no-store` to paired devices only,
  and are dropped 10 minutes after the task ends. The desk only watches: it cannot act (the same rule as the canvas).
- Mechanics: `hub.tap` (server-side listeners get every event the phone gets), `live.py` (stations, screenshots, panels data),
  `GET /api/v1/canvas/live`, `GET /api/v1/canvas/live/{task}/frame`, `POST /api/v1/canvases/{id}/fill`. `live.py` is protected zone.
Acceptance (`test_v4_f7_*`): a task becomes a station with its steps, thought, tab and growing screenshots, served only to paired
devices and only to its own galaxy; private and company work never leaks onto the wrong desk and requests are masked; a new task is a
card at once and storage can be laid out.
- **Verified live (2026-10-26)** on the running server, after Hermes was restarted onto the shared browser: two real requests to the main
  agent ("buka example.com/.org pakai browser, scroll, laporkan judulnya") each became a station within a second; the camera flew to it;
  14 screenshots were served while it worked; the page title ("Example Domain"), URL and steps followed the real page; the task
  completed and its card kept the result. Found and fixed in that run: Hermes' completion events carry their own ids and the tool's
  result as label (now paired with the call that started and never shown as an action), repeated identical calls collapse into one
  counted line, and the desk was invisible from the home view (panels and live cards are drawn from farther away now). Hermes in the
  "full" profile browses through one `browser_exec` tool, so steps read "Menjalankan di halaman: <what it was asked to do>" rather than
  separate click/scroll lines; separate lines appear when it uses the individual browser tools. Not covered: fonts for some scripts (Thai
  shows as boxes in screenshots), clicks drawn on the screenshot, two browsing tasks at once.

## ADR-052 — The desk is the main page: drafting-style 3D tools, and the conversation panels on it (2026-10-26)
The owner (2026-10-26): make the infinite canvas the main page of the web AND the app, complete with chat, screen sharing, camera and
audio panels, and a tools panel like AutoCAD's so the 3D can be explored with the mouse.
- **Front door.** `/` on the server opens the desk (`/canvas/`); the app starts on it (new first tab "Meja", the start destination when
  signed in; the other tabs are unchanged, the older console entry "Galaksi 3D" stays). The admin page stays the control point; the desk
  has an "Admin" link (hidden in the app).
- **Drafting toolkit (`cad.js`, tested in `lib.js`).** Mouse as in a drafting program: wheel zooms toward the cursor, middle button pans,
  Shift + middle orbits, right button pans; the left button follows the active tool — a palette (Pilih, Orbit, Geser, Zoom seret, Ukur,
  Hubungkan; one-letter keys V O P Z M L). A **view cube** (top right) turns to the face you click (Atas, Bawah, Depan, Belakang, Kanan, Kiri,
  isometric, ±90° turns; its orientation is checked numerically for every standard view), a navigation bar (Home, Zoom semua, Zoom ke
  pilihan, perspective/orthographic, grid, snap), **layers** (every constellation, live stations, desk panels, links, card stars, galaxy
  particles, floor grid), a **properties** palette (a card's X/Y/Z, size, pin — edited numerically; or the view's), a **measure** tool (two
  cards → distance and ΔX/ΔY/ΔZ), snap-to-50 while dragging a card (F9), a floor grid (F7), saved views, and a **command line** with a status
  bar (`top`, `front`, `iso`, `ortho`, `ze`, `layer tugas off`, `view save A`, `cari …`, `?`). Orthographic mode swaps the camera with the
  frustum of the same picture at the target's depth, and points get a pixel size (they have no distance to shrink by). Successive view
  commands keep the aim of the flight in progress. All of it changes how the owner LOOKS or moves a card the owner drags — it never
  approves, deletes, sends or pays.
- **Panels (`dock.js`)** over the phone's own WebSocket (`/ws`, authenticated by a first message since browsers cannot set headers): a chat
  (streamed answers, tool/thought status, reports and proactive messages, the conversation kept in this browser), a **microphone** (Web Audio →
  16 kHz → an adaptive voice-activity detector → one utterance per phrase, the server does the hearing — same path as the phone, so the
  voice complements and the owner's engine choice apply; the mic is ignored while Jarvis talks), a **camera** and a **screen share**
  (the latest frame, ≤ 1024 px JPEG, travels with what is typed or said — exactly the app's protocol; a red-framed preview tile with
  "dibagikan ke Jarvis" and a stop button is always visible while sharing), and spoken replies with the browser's own voice (toggle). The
  site now sends `Permissions-Policy: camera=(self), microphone=(self), display-capture=(self)` for the desk only.
- **In the app** the page runs embedded: only chat and the drafting tools, because the phone's native microphone (on-phone VAD, wake word),
  camera and screen sharing are better and must not be captured twice; three native buttons (mic, camera with a small preview, screen) sit
  over the page and drive the same engine as the Bicara tab. Android WebView has no screen capture anyway.
Acceptance (`test_v4_f8_*`): `/` opens the desk, the desk may use its own microphone/camera/screen and nothing else; a wrong token on the
WebSocket is refused with 4401; a chat message with a camera frame reaches the brain with the frame and source and streams back to its
session; an utterance is transcribed, answered and carries a shared screen; too-short audio is refused. JS tests cover the views, command
parsing, fitting, the cube's orientation, resampling, PCM16 and the voice detector.

## ADR-053 — The owner takes the wheel of a worker's browser (Fase 9, 2026-10-26)
Context: the worker meets a login or a captcha it cannot (and must not) solve; the owner watches it on the desk but could only watch.
- **"Ambil alih" on every live station.** It opens a full-window view of the same live video; mouse (move, press, release, double click,
  right button), the wheel, a touch tap (= click) or drag (= scroll), physical keys and pasted text are sent over the desk's WebSocket
  (`take` / `input` / `release`) and played into the very tab on screen with DevTools `Input.dispatchMouseEvent`, `dispatchKeyEvent`,
  `insertText`. Positions travel as fractions of the picture and are multiplied by the page size from the screencast metadata, so the view
  may be any size. Phones type through a hidden field (`beforeinput`) and a "Tempel teks" row (masked) for codes and passwords.
- **Only the owner's own device** (scope `owner`) may take the wheel; a company galaxy only steers its own stations; a station that ended
  cannot be steered. The wheel returns by itself after 90 s without input, when the viewer closes or its socket drops, or on the buttons.
- **Nothing typed is kept.** Keys and text go from the socket to the page and are not logged, stored or put in an event; the audit holds only
  `live.takeover` and `live.handback` (whether the worker was told). Shortcuts (copy, cut, Ctrl+anything but select-all, function keys) are
  not forwarded; text is capped at 500 characters per send.
- **The worker waits, then carries on.** The worker brief says: on a login, captcha, OTP or a human-only step, do not guess — `ask_owner`
  ("Buka Meja, klik Ambil alih, selesaikan, tekan Selesai"), wait without touching the page, then take a fresh look and continue. The card shows
  the question as an amber line and a pulsing button (and a toast); **"Selesai — lanjutkan Jarvis"** answers that open question for the
  worker; "Kembalikan tanpa memberi tahu" only hands the wheel back. The page's overlay marks the pointer **ANDA** (amber) instead of JARVIS
  while the owner steers, so a shared screen never confuses the two.
- Limit: the worker is not frozen by core. If the owner takes over without the worker having asked, both may act in the same tab; the brief and
  the main agent's reply steer towards asking first.
Acceptance (`test_v4_f9_*`): a basic device is refused; the owner's click lands at the right pixel, text and wheel reach the page, the page is
stamped as the owner's, audit holds no typed text; "Selesai" answers the worker's question; after handing back, input is refused; a viewer that
vanishes hands the wheel back. Unit: the mapping from owner input to DevTools commands (clamping, caps, no shortcuts, no blind click). JS: the
position, fitting, key, touch and scroll helpers.
Found while testing it live (2026-10-26): `mcp_server.py` defined `_core` twice and the second replaced the first, so a worker's `ask_owner`,
`notify_owner`, stage, music and route tools had been failing ("Invalid port") since Sprint 2 — a worker could never ask the owner anything.
Renamed the second to `_core_call`; `test_v4_f9_no_module_has_two_functions_of_the_same_name` now guards every module. Verified end to end in a
second headless browser: the worker asked, the card showed the question and the pulsing button, the owner's click, keys and Backspace reached the
worker's page, "Selesai" answered the question.

## ADR-054 — Player and meeting recorder are cards on the desk (Blueprint v4 Fase 10)
Owner (2026-10-26): "mulai rapat" showed nothing clear on the canvas; "putar lagu" must put the player on it and fly there. Every feature now has its
card at a fixed place on the desk, driven by the server's state (the desk poll), so a reload, the app and a browser show the same thing.
- **Player.** The stage's music / sound / video panel is `player` in the desk snapshot (`stage.desk_player()`); the card plays it itself — an
  `<audio>`/`<video>` fed with the device token (a tag cannot send a header), or JARVIS' own `/embed/youtube/<id>` page (it reports `ended` in its
  title, which the card reads, as the phone does). Previous / next / close go back as `stage_event`, so playlists keep working. In the app the
  native stage no longer plays these panels (no double sound); other panels (map, document, draft…) still open the Bicara sheet.
- **Meeting.** `mulai rapat [tentang X]` / `selesai rapat` are deterministic router intents (and an LLM tool `meeting`). Start does NOT record:
  recording others needs everyone's consent, so it opens the card (`meetings.want_to_record`) with a consent tick and **Mulai rekam**. In the app the
  card asks the phone (`POST /meetings/start-request` → `meeting_cmd` event → the phone's recorder, the usual flow); in a browser it records
  itself (WebM/Opus, one independent file a minute, uploaded as made; the server now accepts `webm`). The card follows the meeting's row
  (waiting → recording with a running clock and "Tandai penting" → processing → done with the .docx) whichever device holds the microphone.
  "Selesai rapat" by voice raises `stop_seq` and sends `meeting_cmd stop`; the holder stops and the minutes are made as before.
- The camera flies to a card when it appears (follow mode, not while the owner is touching the screen). Acceptance `test_v4_f10_*`.

## ADR-055 — The canvas is a 2D board, like Miro / Figma (Blueprint v4 Fase 11)
Owner (2026-10-26): replace the 3D infinite canvas with a 2D one "seperti Miro/Figma", toolkit adjusted, interactive and professional.
- **Same data, flat view.** The board plane is the server's `x` (right) and `z` (down); `y` (the old height) is kept and ignored. No migration of
  positions: the galaxy's disk becomes a map, its constellations become faint named areas. The three.js viewer, the view cube and the CAD command
  line are gone (`vendor/`, `cad.js`); `lib.js` keeps only pure 2D helpers (world↔screen, fit, snap/guides, align/distribute, resize, connectors).
- **Free objects.** The owner can draw notes, text, shapes (rect / rounded / ellipse / diamond) and frames. They are nodes `obj:<token>` whose
  content lives in `canvas_nodes.props` (whitelisted keys and values — `canvas.clean_props`), with their own `w`/`h`. Deleting one really
  deletes it (it is the owner's drawing; undo brings it back); a card that points at a task/document/memory only leaves the board — the thing
  is never deleted from here. Any board (also a company's) may hold drawings; boards stay separate. Connectors carry a label, an arrow
  (`style.to`), dash and colour. Multi-selection moves are ONE change (`POST /canvases/{id}/layout`), so the history stays readable.
- **Interaction.** Pan (space / hand / middle / two fingers), zoom to the cursor (wheel, pinch, ± , fit all / selection, 100%), marquee,
  shift-select, drag with smart guides (or grid snap), resize from eight handles (Shift keeps the shape, Alt grows from the middle), frames carry
  what is inside, align / distribute, bring front / back, lock, duplicate / copy / paste, in-place text editing, connectors by dragging from the
  side dots (or the C tool; dropping on empty paper makes a new note), right-click menu (long press on a touch screen), Ctrl+K search /
  add-from-storage palette, minimap, undo / redo (client-side, each step is an API call; the history panel still restores whole versions).
- The desk (stations with live video and takeover, n8n, requests, storage, player, meeting) is unchanged in behaviour; its panels sit on the
  board as fixed widgets. Hand-tracking drives the same pointer events. Phone: tools on the left, zoom on the right, properties as a bottom sheet.

## ADR-056 — Every thing JARVIS shows has its own card on the desk; the owner can step in any time (Blueprint v4 Fase 12)
Owner (2026-10-26): not only meetings and songs — video, YouTube, documents, pictures, etc. must appear on the desk, which already holds a card
for every feature; and "Ambil alih" must not wait for Jarvis to ask: one click and the owner is in.
- **One card per kind, always on the board.** `stage.place()` files what is shown into a desk slot (music, video, image incl. gallery, doc, map,
  web, text, draft); a board's blocks go to their own cards. The slots outlive the phone's current panel, so a picture never stops the music.
  The desk snapshot carries `player` (music) and `cards` (the rest); a card's ✕ is a `stage_event closed` that empties only that card.
  Empty cards stay in place, dashed, saying what to say to fill them; the meeting card gets **Siapkan rapat** (`POST /meetings/want`).
  Documents are read on the card through `GET /documents/{id}/preview` (text extracted as for attachments — a phone WebView cannot show a PDF);
  maps use MapLibre + OpenFreeMap like the app. The camera flies to a card when new content lands on it.
- **Intervensi.** The station button is now shown whenever the worker browses. Taking the wheel steers the worker's running Hermes turn
  (`POST /v1/runs/{id}/steer`) to keep its hands off the browser and call the new MCP tool `wait_for_owner(task_id)`, which waits until
  the owner hands back (`GET /internal/control/{id}`). Hermes reads a steer before its next step, so one action already in flight may still
  land. OpenJarvis tasks cannot be steered; the overlay then says the worker was not paused.
- OpenJarvis (ADR-043) was switched ON by the owner without a further trial. Acceptance `test_v4_f12_*`.

## ADR-057 — The owner's Google account is connected by logging in from the phone (Blueprint v4 Fase 12)
Owner (2026-10-26): "cukup berikan akses via login dari HP, otomatis kamu bisa gunakan kredensial tersebut untuk n8n".
- Desk card **Akun Google** → `POST /google/start` (one-time state, 15 min) → Google's consent page in the phone's browser (the app sends
  outside addresses there; Google refuses embedded WebViews) → `GET /google/callback` trades the code (offline + consent → refresh token).
- Core writes two n8n credentials (`gmailOAuth2`, `googleCalendarOAuth2Api`, with `oauthTokenData`; n8n refreshes from then on), puts them on
  the inbox flows and activates them: the owner's own login is the consent for those three flows. Sending an email or creating an event still
  needs the owner's approval of that exact item (ADR-045). The refresh token and the client secret are stored encrypted (vault key).
- Google requires an OAuth client the owner registers once (Web application, redirect `https://<BACKEND_DOMAIN>/api/v1/google/callback`,
  Gmail + Calendar APIs on, consent screen "In production" so tokens do not expire after 7 days). Its id/secret come from `.env` or are pasted on
  the card. **Putuskan** revokes the token, deletes the credentials and stops the flows.

## ADR-058 — A workers area on the desk (Blueprint v4 Fase 12)
Owner (2026-10-26): an area on the canvas to watch the workers — which model each uses — switch the model, start / stop a worker, and chat to it.
- `workers.overview()` is `workers` in the desk snapshot: running/queued tasks, then what finished in the last hour; each row has the model that
  really answered (`tasks.model_used`, else the category's main route) and its fallback chain.
- **Model.** Workers do not own a model: the category does (`llm_categories.routes`, resolved per request by the gateway, which Hermes reaches as
  `jarvis-<category>`). So "⚙ Model" makes the chosen model the MAIN route of that category (`composition.set_model`, same checks and cost
  confirmation as the app's picker) and applies from the next LLM call, also to workers already running. `privat` stays local. The model list
  is OpenRouter's catalog, tool-capable models only, free first (`GET /workers/models`).
- **Stop / Start.** `POST /workers/{id}/stop` (`workers.stop`: the task is kept as 'stopped') and `/start` (`workers.retry`, continues from its progress).
- **Chat.** `POST /workers/{id}/say` slips the owner's words into the worker's running Hermes turn (`/v1/runs/{id}/steer`); it reads them before its
  next step. Only Hermes runs that are running can be spoken to; OpenJarvis tasks and finished ones cannot (the card says so). Audited by length only.

## ADR-059 — The dev team: bisan, coder, qaqa (Blueprint v4 Fase 12)
Owner (2026-10-26): three workers just for development, each taught for its position — bisan (business/system analyst), qaqa (QA),
coder (expert developer) — and their activity visible on the canvas in a dashed area holding the three.
- **Flow (core drives the hand-offs; members never pass work themselves).** `devteam.request` → bisan writes SPESIFIKASI (goal, files,
  behaviour, numbered acceptance criteria, out of scope, risks; reads origin/main, never edits) → coder builds on `jarvis/devjob-<id>`,
  self-checks, commits only its files and calls `propose_code_change` → the runner tests it (self-dev.sh) → qaqa reviews the REAL diff and
  the runner's result against the spec, first line LULUS or PERBAIKI → PERBAIKI goes back to coder with the findings (≤ MAX_ROUNDS = 3 builds).
  LULUS counts only when the runner also passed it (`awaiting_approval`); then the owner approves at the admin page as for any T1 change.
  A coder that forgets to propose is asked again; a member whose run fails gets one retry, then the job stops and the owner is told.
- **Teaching.** Each member's brief (`devteam.BISAN/CODER/QAQA`) is the review experience of the first panel-chat attempts written down:
  read the code first, meet every criterion, no dead code, check CSS for stray characters, mobile media queries, state restored on load,
  `git add <files>`, never claim before evidence; qaqa checks selectors against the real elements and never passes when in doubt.
- **Models.** One category each (`dev-bisan`, `dev-coder`, `dev-qaqa`, seeded from `coding`, registered with Hermes' model routes), so
  the owner sees and switches each member's model (workers area ⚙ Model).
- **Desk.** `devteam` in the desk snapshot; the Tim Dev widget is a dashed frame with the three members (live steps of their current task,
  model, 💬 to the running one), a request box, and the latest jobs (status, round, change, qaqa's review, cancel). The main agent hands
  "develop JARVIS itself" requests to the team with the tool `tim_dev` instead of a generic worker.
- Tables: `dev_jobs`; `tasks.dev_job`, `tasks.dev_role`; task kind `devteam` (migration 029).

## ADR-060 — Catatan & Tugas replaces the app's Chat tab (Blueprint v4 Fase 12)
Owner (2026-10-26): the chat panel on the desk sends files (image/PDF/ZIP); the app's Chat menu becomes "notes & my task list", advanced like
Notion, where the owner writes notes, ticks tasks and manages meeting minutes. Also: the app may rotate to landscape for the desk.
- **Data.** `note_pages` (migration 030): title, icon, parent (sub-pages), pinned/archived (trash), `blocks` jsonb, `version`. Blocks: p, h1–h3,
  bullet, number, todo (checked, due, priority 1–3, who), toggle, quote, callout, code, divider; `notes.clean_block` bounds every field.
  A to-do block IS a task: the task views (today, 7 days, all, overdue, done) query every page. Two pages always exist: 📥 Inbox, ✅ Tugas saya.
- **Conflicts.** Every save carries the version it started from; a newer save from another device answers 409 with the current page and
  the editor offers "muat versi terbaru" or "simpan versiku" — never a silent overwrite.
- **Meetings.** A finished meeting becomes a page by itself (`notes.from_meeting`, from `meetings` after the minutes): summary, decisions,
  action items as to-dos (who, due date when it is a date), open questions; older ones via "Impor notulen".
- **Voice/chat.** Deterministic intents: "catat …" → Inbox, "tambah tugas … besok" → Tugas saya with the due date said ("catat: …" with a
  colon still goes to memory, as before). The REST add-task endpoint understands the same words.
- **Web app** `/notes/` (`web/notes/`: lib.js pure + node tests, editor.js, app.js): page tree, slash menu, Markdown shortcuts, Enter /
  Backspace / Tab like a writer expects, drag by the handle, paste of multi-line text as blocks, task groups like a planner, trash, search
  (Ctrl K), toolbar over the phone keyboard. Plain text per block (no inline bold yet). Its CSP allows only its own origin.
- **App.** The Chat tab is replaced by Catatan (a WebView of /notes/, token in the fragment like the desk); the activity may rotate
  (`fullUser`) and handles the configuration change itself so the desk's WebView and the recorder survive a turn.
- Attachments: ZIP is accepted (listing + the readable documents inside; no nested archives or pictures, bomb-safe).

## ADR-061 — Teaching JARVIS to code fast and right (Blueprint v4 Fase 12)
Owner (2026-10-27): "ajarin Jarvis cara coding yang cepat dan benar". Taken from what actually went wrong: a CSS file with stray `|` that every
test passed (panel-chat attempt 1), a mirror of `main` that was days old, an approved change that failed to deploy on a merge conflict in a
shared test file (job 1 / #7), a model that stalled (bisan #2: two calls held 92–154 s, Hermes gave up), 34% of coding tasks failing in a week.
- **`core/app/preflight.py`** — one command, run from the repo/worktree, that coder and qaqa use: the runner's own policy on the real diff
  (tier, protected zone, weakened tests), "does it merge cleanly with origin/main" (`git merge-tree`, the check that would have caught #7),
  CSS sanity (stray leading characters, braces, open comment), `node --check` / `py_compile`, leftovers in the added lines (debug output, merge
  markers, commented-out code, empty blocks), uncommitted files, "code changed but no test", "tests added to a shared test file", and the JS
  tests of the folders touched. PASS / WARN / FAIL; exit 1 on FAIL. Server tests still run in the runner (they need Postgres).
- **Habits in the briefs** (devteam.BISAN/CODER/QAQA, workers.CODE_HABITS): fresh `origin/main`, a git worktree per job (jobs never share a
  working tree), read by range (`git grep`, `sed -n`), one script per file with asserted replacements, new tests in a NEW test file, preflight
  twice (after writing, and after the last rebase), read your own diff once as a suspicious reviewer, `git add <files>`; bisan has a step budget
  and must name the new test file; qaqa runs preflight first and treats every FAIL as a finding.
- **Fresh mirror.** `dev.sync_mirror()` makes the runner refresh Hermes' read-only copy of main (a `0-sync` request that the runner just
  moves aside after refreshing); bisan and coder are never spawned before it.
- **Deploy failure is not the end.** `devteam.check_deploys()` (every 60 s): an owner-approved change that failed to deploy sends the job back to coder
  with the deploy log (rebase, keep both sides, propose again; the owner approves once more); deployed → done; rejected → cancelled.
- Not changed, owner's call (cost): the dev team's categories start from `coding`, whose first model is a free one that stalls now and then;
  switching them to a cheap paid model is a click on the desk (⚙ Model).

## ADR-062 — Desk areas the owner sizes, locks and opens full screen (Blueprint v4 Fase 12)
Owner (2026-10-27): an area (a group of cards, like Tim Dev) can be resized from the canvas by dragging with a finger, except when locked;
it has a full-screen button that fills the phone, fitted to it; Keluar leaves.
- Every desk widget (n8n, Simpanan, Pemutar, Rapat, Video…, Pekerja, Tim Dev) gets three grips (right edge, bottom edge, corner) and a small bar
  (🔓/🔒, ⛶) outside its top-right corner. Grips and bar keep their screen size at any zoom (`--inv`); a locked area has no grips. Width 220–2600,
  height 140–2600 or "grows with its content" (`lib.clampArea`); a fixed height scrolls inside.
- The layout (`settings_kv` `desk:areas`, `canvas.clean_area`) is the owner's and shared by every device: `GET /canvas/areas`, `PUT /canvas/areas/{name}`.
- Full screen moves the area itself (with everything it is doing — live steps, player, map) into a layer over the page at the screen's own size,
  with a title bar and "✕ Keluar" (Escape too); the board hears no shortcuts meanwhile. In a browser the page also asks for real full screen.
  In the app the page tells it through the JS bridge (`JarvisHost.fullscreen`): the app hides its bottom tabs, the native strip and the system
  bars (swipe from the edge shows them briefly), and the phone's Back leaves full screen.

## ADR-063 — Catatan and Rapat on the web (Blueprint v4 Fase 12)
Owner (2026-10-27): the notes and the meetings must be reachable on the web too (the app has its own tabs).
- The desk's top bar on the web gets **Catatan** (/notes/) and **Rapat** (/notes/#meetings); hidden inside the app, which has its own tabs.
  Catatan gets "← Meja" back.
- **Rapat** lives in the Catatan app (`web/notes/meetings.js`): the list (status, date, length, action items, confidential), and per meeting
  the minutes (summary, decisions, action items with who/due, open questions, topics), "Tanya rapat ini" (the existing `/meetings/{id}/ask`,
  each source plays from its moment), the transcript as speaker turns with search and a play button per turn (the minute-long audio pieces),
  renaming a speaker (rebuilds the minutes), the .docx, "Buka di Catatan" (the meeting's page with its to-dos), delete, and "Mulai rapat"
  (opens the desk's meeting card, which records in the browser after the consent tick). No new server API; the notes CSP allows `media-src blob:`.

## ADR-064 — The app's tool strip on the web desk (Blueprint v4 Fase 12)
Owner (2026-10-27): the web gets the app's tool panel — share screen, camera, mute/unmute and the rest.
- On the web (not inside the app) the dock's media buttons move out of its header into a column of round buttons at the bottom left, like the
  app's native strip: 💬 chat (open / minimize, red dot for unread), 🎤/🔇 microphone (pulses while listening), 📷 camera, 🖥 share screen,
  🔊 Jarvis' voice in this browser. Same functions as before (browser microphone with voice detection, camera / screen frames to Jarvis).
- The round chat bubble on the right is not used on the web any more (the strip's 💬 replaces it); the minimap moves right of the strip; on short
  screens the strip lies flat; on a phone browser the open chat leaves room for it. Inside the app nothing changes (the native strip has these).

## ADR-065 — The dev team can say "this needs a human" (Blueprint v4 Fase 12)
Seen in job 6 ("hide finished task cards"): the change needs core/app/canvas.py and live.py, which are the protected zone (humans only). coder
found it and rightly did not propose half of it, but the orchestrator kept asking it to "propose again" for three rounds.
- bisan checks every file it would change against `selfdev_policy.FORBIDDEN` before writing a spec; when the request cannot be done without the
  protected zone, its first line is `BUTUH MANUSIA — <files, why>` and it still writes the full spec for a human developer. coder may end the
  same way when preflight shows the protected-zone FAIL. `devteam.needs_human` reads it; the job stops as `needs_human` (migration 031), the
  spec is kept, and the owner is told — no coder loop, no tokens burnt.

## ADR-066 — Talking to Jarvis about a screen shared in the browser, and drafts from it (Blueprint v4 Fase 12)
Owner (2026-10-27): while sharing the screen on the web, talk with Jarvis — e.g. share an email and ask for a draft right away; Jarvis may confirm
something to fit the context; if the screen does not show the whole email, the owner pastes it into the chat.
- Voice and typed messages already carried the latest screen frame. What was missing: the draft writer only reads "screen text", which only the
  phone sends (ML Kit). `screen_reader.read` now reads the frame once with the vision model (never a free endpoint: a shared screen counts as the
  owner's document; local only for a private turn), cached per frame; the direct "buatkan balasan/draf…" path and the model's own
  write_draft/draft_reply tools use it.
- Before writing, `screen_reader.question` may ask ONE question (agree or decline, a figure or date to state, who it goes to); an email cut off
  at the screen's edge (`[TERPOTONG]`) asks for the full text instead. The owner's next words answer it (kept 15 minutes per conversation):
  a short answer joins the request, a long paste joins the material as "TEKS YANG DITEMPEL PEMILIK", "lanjut" writes from what is visible.
- The draft brief now carries the owner's earlier messages whole (an email pasted before the request is no longer cut to 240 characters).
- Sharing the screen on the desk says in the chat what to do next.

## ADR-067 — The desk shows only work in progress (dev job 6, built by a human from bisan's spec)
Owner (2026-10-27): "hapus semua card tugas yang sudah completed dari Meja… cukup tampilkan yang aktif saja". The dev team could not do it (it needs
canvas.py / live.py, the protected zone — ADR-065), so a human built it from bisan's spec, criteria and test plan as written.
- `canvas.view()` first sweeps: task cards whose task ended (`completed`, `failed`, `cancelled`, `stopped`; an unknown status counts as going)
  are deleted from `canvas_nodes` — links go with them — unless the owner pinned the card; one version bump per sweep, audited. The sweep runs
  before the "unchanged" answer, so a viewer polling with `?since=` sees the cards go. Tasks, results, reports, documents and Simpanan are untouched.
- A finished task no longer re-adds its card (`workers`: only `canvas.touch`), so nothing churns; results stay reachable in reports, Catatan and Tugas.

## ADR-068 — The chat floats above a shared screen (Blueprint v4 Fase 12)
Owner (2026-10-27): when sharing the screen on the web, the browser only shows its "stop sharing" bar; the chat must be there too.
- While another tab, window or app is shared, the desk page is not on screen. With Document Picture-in-Picture (Chrome / Edge) the dock itself
  moves into a small always-on-top window — messages, typing, paste, attachments, and a microphone button — and moves back when it closes.
- 📌 in the chat's header opens it; starting a screen share tries to open it at once (the browser may refuse without a fresh click — then 📌
  pulses). Browsers without the API keep the chat on the desk page as before.

## ADR-069 — Progress and the result in the chat that asked (Blueprint v4 Fase 12)
Owner (2026-10-27, sharing an Outlook email in the floating chat): "tolong bantu saya menjawab email ini" got "Oke, aku buat 3 draf…" twice and
no draft at all — the phrase was not a draft intent, and with a screen shared the turn went to the vision model, which cannot call tools. He asked
for a percentage loader in the chat and the result shown there.
- "jawab/balas(in/kan)/menjawab/membalas … email/pesan/chat/WA" is now the direct draft intent (questions like "sudah kubalas emailnya?" are not).
- `workers._tell_progress` broadcasts `{"type": "progress", session_id, task_id, pct, text}` for the owner's tasks: 5% at start; the writer's
  real stages (15 reading, 30–85 writing — the bar creeps while the single model call runs, 90 saving the .docx, 100 with the draft itself);
  Hermes workers by their steps (`step_pct`: fast at first, never past 92 before done); `pct: null` when it fails.
- The desk chat (also in the floating window) shows a bar per task it asked for, and at 100% the draft — to, subject, text, 📋 Salin, ⬇ .docx.
- Guard test widened: a module function may not take a module variable's name (the new helper first shadowed the `_progress` dict).

## ADR-070 — "Is the draft done?" (Blueprint v4 Fase 12)
The owner asked "apakah sudah jadi? draftnya" after Jarvis had promised a draft it never started; the vision model repeated its promise word for word.
- "sudah jadi/mana/belum … draf(nya)/balasannya" is a direct intent: a draft being written → "masih kutulis" (the bar is in the chat); a written one
  is shown again in the chat (writer keeps the latest drafts per task); a failed one says why; NONE started → the latest request of this
  conversation that asked for a draft is started now, with the screen being shared — a broken promise is kept instead of repeated.

## ADR-071 — The tool rail shows select and hand; the rest folds (Blueprint v4 Fase 12)
Owner (2026-10-27): by default only the hand and the cursor; the rest collapsed behind an expand icon. ⌄ unfolds note, text, shape, frame,
connector, add-from-storage, undo/redo (remembered per browser/phone); a keyboard shortcut that picks a folded tool unfolds it.

## ADR-072 — "🕘 Terakhir": where the latest request landed (Blueprint v4 Fase 12)
The desk's top bar takes the camera to where the owner's latest request left its mark on the main board — the newest of the latest owner
task's card (still on the board) and the feature cards (player, video, picture, document, map, web, notes, draft) — and makes it glow; the
request itself is named. `live.last_activity()` in the desk snapshot.

## ADR-073 — Projects: a team of workers by role, a model each, a schedule, web work (Blueprint v4 Fase 12)
Owner (2026-10-27): a menu to watch the projects / schedules he makes; per project the workers' roles and how many, an AI model per worker,
and activity that operates websites (e.g. helping to apply for jobs).
- `projects`, `project_roles` (migration 032): name, goal, schedule (manual / hourly / daily / weekdays / weekly at a WIB time), roles with a
  brief, 1–5 workers, an optional OpenRouter model (tool-capable, checked against the catalog), and "operates websites". ≤ 6 workers per run.
- A run spawns each worker as an ordinary owner task (all worker rules, desk cards, live stations, takeover, reports); same-role workers split the
  work by number; web roles get the browser brief (work visibly, stop before sending anything personal and ask). One run at a time per project;
  `projects.tick()` every minute starts the due ones.
- **A model per worker**: `tasks.model_override`; the gateway knows a Hermes call's task (session `task-<id>`) and puts that model first
  (`gateway.override_route` / `with_override`), the category's routes stay behind it as fallbacks; never for a private turn.
- The desk's **Proyek** area (and "🗂 Proyek" in the top bar, opening it full screen): projects with schedule, next run, roles × workers × model,
  ▶ run now, pause/activate, edit, delete; the latest run's workers with status, model, result or error and "Lihat" (fly to the worker's card);
  and the schedules Jarvis made in chat (Hermes' cron jobs), read only.

## ADR-074 — The main agent oversees every task and learns its pattern (Blueprint v4 Fase 12)
Owner (2026-10-27): every task known to and watched by Hermes (the main chat) — projects included — so it learns from what the workers did and
recognises the pattern when the same kind of work comes again.
- **Episodes for all real work**: owner tasks (project workers are owner tasks) and the dev team's (goal = the member + the owner's request),
  successes too — not only failures. Each keeps its *pattern*: how long, how many steps and which tools (the worker's live step list), the model,
  and whether the owner had to help (questions + takeovers: "prepare that from the start"). Without a plan the steps are the approach.
  Background chores (situation, routine, …) stay out. The dev team's briefs now get their own earlier jobs too.
- **The main chat's situation** (not for the compact local model): `POLA SERUPA` — the two closest past episodes, one line each with their pattern;
  `PROYEK PEMILIK` — active projects and any with busy workers, with the latest run's workers; `TIM DEV` — open / recent jobs. The prompt says
  to use the pattern: estimate time and approach, warn when the owner had to help or when the same way failed, pass the lesson to the worker.
- **Projects from the chat**: tool `proyek` (list / status / run / pause / resume / create with roles) and plain commands handled before the
  model ("jalankan proyek lamar kerja", "jeda/lanjutkan proyek X", "status proyek", "proyek saya apa saja?"); the name is matched loosely
  (`projects.find`); an unknown name goes to the chat model, which has the list.

## ADR-075 — Project results you can open: tables, charts, pictures (Blueprint v4 Fase 12)
Owner (2026-10-27): the result of a project could not be clicked for detail and was only text; show it as a table, picture, chart or similar.
- **Workers write structured results.** The project brief now ends with a fenced ```hasil JSON block (`results.FORMAT_HELP`): summary, points,
  tables, charts (bar / line / pie), pictures (https URLs), links — followed by the plain text. `results.split` checks and trims it (≤ 6 tables ×
  200 rows × 12 columns, ≤ 6 charts × 40 points, http(s) URLs only); bad JSON stays as text. The report that is spoken (`results.spoken`) and the
  card's preview never contain the block.
- **`GET /api/v1/projects/{id}/results?run=N`**: every worker of a run (latest by default) in full — structured part, text, documents it made,
  and the list of runs.
- **The desk opens it full screen** (`resultview.js`; "📑 Hasil" on a project, "Buka hasil ›" on a worker, tap the preview): per worker a summary,
  points, tables (scrollable; any numeric column can be drawn as a bar / line / pie chart with one tap — Indonesian numbers like "Rp1.900.000" and
  "25 jt" are read), charts as inline SVG (no library), pictures, links, downloadable documents, and the worker's full text (also markdown:
  headings, lists, tables, images) folded behind the structure. A run picker shows earlier runs. Nothing from a worker is inserted as HTML.
- Not covered: pictures a worker only saved as a file (not a URL); results of ordinary (non-project) tasks keep their current report/card.

## ADR-076 — Dev team tasks: live stations stay, the phone's worker list stays clean (Blueprint v4 Fase 12)
Dev job #5 (hide the dev team's tasks from the Pekerja card) stopped at QA: holding back the `task` hub event for kind `devteam` also removed
their live stations on the desk (the Tim Dev area draws its live view from them) — a trade-off for the owner. Owner chose A (2026-10-27).
`workers._announce` now sends a dev-team task as event `devtask` (same payload); `live.on_event` treats it like `task` (station made), while the
phone, which builds its worker list from `task` events and ignores unknown types, never sees it — also true for already installed APKs.
The Pekerja card keeps filtering by `dev_role` (`desk_list`), `active()/stopped()` by kind.

## ADR-077 — JARVIS operates Gojek on the owner's phone, with approval by admin password (Blueprint v4 Fase 12)
Owner (2026-10-28): JARVIS can operate the Gojek app, but every run needs his permission — shown in the app and secured by the admin
password — except runs he scheduled.
- **How**: the JARVIS app's accessibility service (`phone/PhoneAgentService`, off until the owner enables it in Android's settings; Setelan HP
  → 5) reads the app's screen as an element list and taps / types / scrolls / goes back on instruction. Core runs the loop
  (`phone_agent.produce`, category `hp`): show the model the current screen, take ONE tool call (ketuk, ketik, gulir, kembali, buka_aplikasi,
  tunggu, lihat_gambar → screenshot read by the vision model, tanya_pemilik, selesai, gagal), look again; ≤ 45 steps, ≤ 15 minutes, one phone
  run at a time. It is an ordinary worker task (desk card, steps, progress, stop, report, episode); a project role's model applies.
- **Approval**: a run starts as `awaiting` (`phone_runs`, migration 033): the phone shows a dialog (and a notification) with the goal; Setujui
  needs the **admin password**, checked by the web admin (`/internal/check-admin-password`), 5 wrong per device per 15 min; it expires
  after 15 min. Only a project's **schedule** (`projects.tick`) starts one unasked; ▶ Jalankan on the desk asks too.
- **Never**, scheduled or not, enforced on the server (`check_action`) AND on the phone: acting outside the approved app's package (the phone
  does not even read another app's screen), typing into a password / PIN / OTP field (a secret screen pauses the run until the owner typed it,
  ≤ 4 min), tapping top-up / transfer / account / card / pay-later buttons. No automatic second attempt after a failure (an order may be
  half done). A banner "🤖 JARVIS mengoperasikan Gojek · Hentikan" shows while it works; Hentikan stops the task.
- **Asked from**: the chat ("pesankan goride ke kantor" → plain intent; tool `operasi_hp`), a project role "📱 Operasikan aplikasi di HP"
  (one worker), never from Hermes workers directly. Apps: `phone_agent.APPS` (Gojek; package com.gojek.app).
