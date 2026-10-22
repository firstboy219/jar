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
