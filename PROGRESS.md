# Jarvis — Progress

Starting a session: `git pull`, then read this file, then PLAN.md.
Ending a session: update this file and commit.

## Current status

- **Phase:** All phases 0–8 are built and merged into `main` (2026-10-10). 494 offline tests pass. Live checks on Claude (subscription) passed for Phases 0–2; Phase 3 live checks are being rerun after quality fixes (see "Phase 3"). Phases 4–8 are tested offline with fakes; their live checks wait for items in "Waiting for Sachin". Final testing on Claude Fable comes last (Sachin's rule).
- **How the work was done:** Phase 3 by the lead session; Phases 4, 5, 6, 7, 8 by parallel agents in git worktrees (`.claude/worktrees/`, git-ignored), each owning its own files, then merged and wired in by the lead.
- **AI provider now:** Claude through Sachin's Claude Max subscription, via the local Claude Code CLI (`claude -p`), adapter `jarvis/providers/claude_code.py`. No API key, no per-call billing; calls count against the plan's usage limits. Main chat Opus 5.5 (medium); memory, quarantine, summaries Haiku 5.5 (low); planner and checker Opus 5.5 (high); workers per profile (`config/tasks.yaml`). The Anthropic API adapter (`claude.py`) stays but is not approved in `config/routing.yaml`.
- **Needs on each machine:** Python 3.12+, `pip install -e ".[dev]"`, Claude Code CLI 2.1.280 or newer logged in with the subscription (`jarvis health`), Tavily key (`jarvis secret set tavily_api_key`). Optional extras: `[voice]`, `[voice-cloud]`, `[wakeword]`, `[google]`, `[browser]`. Dashboard frontend: `cd dashboard; npm install; npm run build`.
- **Half-done work (handoff 2026-10-10, office laptop -> home):**
  - On `main` and tested (902 pass): everything through Phases 0–8, research fixes (prompt-injection hardening, price tiers, memory retrieval), one-click app, event triggers, approval previews + grouped and standing approvals + memory sources/trash + "why" panel.
  - Stopped mid-work, saved on branches (pushed, NOT merged, not tested): `wip/india-features` (AMFI NAV, IMD/Sachet feeds, bills tracker, document wallet, UPI link; tests partly written) and `wip/verify-repeat` (verify-after-act, `/repeat`). Resume each: check out the branch, run the whole suite, finish the brief in this file's "Next step", then merge.
  - Not started yet: global daily cap for unattended work, nightly review into `memory/episodes/`, backups (from the Hermes masterclass review).
- **Last update:** 2026-10-10, home MacBook (Apple M4, macOS 26.5, Python 3.13): pulled, set up `.venv`, full offline suite 902 passed after 3 Mac-portability fixes.
- **GitHub:** Pushed to `main` on 2026-10-10 up to commit b38853f (Phases 0–8, research fixes, app, triggers) with Sachin's OK.

### What each phase delivered

- **Phase 0 — setup:** provider interface (`jarvis/providers/base.py`), fake provider, adapters, routing policy, SQLite (migrations), audit log, keyring secrets, CLI, setup scripts.
- **Phase 1 — brain + memory:** markdown memories + SQLite FTS5 (words + trigrams, RRF), `/remember`, two-step extractor with quotes, context builder, Jarvis-owned agent loop, privacy gate v1 (P0–P3, P3 filters), skills loader, session search, emergency stop, interview, eval scaffold. Live: memory test 10/10, eval baseline 8/8.
- **Phase 2 — tools + safety:** T0–T4 gate with approvals, taint flag, quarantine for web pages, workspace-only file tools, Tavily search, page fetch, weather, apps/notify/media/brightness, verifiers, private tool registry. Live: 10/10 tasks, injection blocked, 0 T4 runs.
- **Phase 3 — tasks + agent team:** task queue and states, planner, parallel researchers, writer, deterministic link-grounding check + independent checker, follow-up research and one revision, receipts from logs, budgets (calls, tokens, notional USD), checkpoints and resume, projects, teach-by-demonstration (chat, tool runs, file changes, terminal transcript, browser steps, notes → SKILL.md draft → approval), worker profiles opus/sonnet.
- **Phase 4 — Telegram + proactive:** APScheduler schedules (missed runs, no overlap, unattended = T0/T1 only), heartbeat, morning brief (weather, calendar, reminders, goals, tasks, schedules), reminders, Telegram bot (only Sachin's user ID, Approve/Deny buttons, `/stop`, `/cloud off`), `jarvis daemon`.
- **Phase 5 — connectors:** document library (md/txt/pdf/docx, page citations, P2 by default), `doc_search`, active project context, Google Calendar + Gmail via OAuth desktop flow (create event T2 with read-back verify, send T3), time parser (English + Marathi), EventKit (Mac only), connector health.
- **Phase 6 — voice:** push-to-talk loop, Windows System.Speech and macOS `say`, faster-whisper speech-to-text (model download pending), optional Marathi cloud voice and wake word (off), voice approvals default to deny.
- **Phase 7 — dashboard:** FastAPI on 127.0.0.1 with a token, strict origin checks, approvals queue with argument hash, emergency stop; Next.js static export with Chat, Memory, Tasks & Approvals, Agents, Connectors, Schedules, Settings & Usage. `jarvis dashboard`.
- **Phase 8 — extras:** isolated Playwright browser (domain allowlist, fresh context, T3 submit with exact fields, passwords never logged, download checks), browser step recording, Operator and Coder agents, `run_tests` allowlist. Not built: OCR, smart home, signed .app, meeting notes, magic search.

### Phase 3 live results

- **First run (2026-10-10), before fixes:** both worker profiles FAILED verification twice. Opus workers: 4 min, 24 calls, $1.34 notional. Sonnet workers: 5 min, 30 calls, $1.10 notional. The pipeline and receipts worked; the causes were criteria nobody can prove online (live stock), researchers stopping at an aggregator, and revisions that could not add facts. Fixed in commit "Make team tasks pass on real research".
- **Second run (after fixes, still 1 fix round):** both FAILED, but closer: Opus workers 8 min, 44 calls, $2.90 notional, round 2 passed 4 of 5 criteria (one availability detail left). Sonnet workers 12 min, 45 calls, $2.03 notional; the checker caught a real error (one laptop at Rs 82,990, above the limit). Change made: 2 fix rounds, budget 90 calls / $5 notional.
- **Demo -> skill replay (done-when part 2):** PASS on Opus (skill `create-weekly-plan-note` drafted, approved, replayed for a new week in a new session).
- **Worker model comparison so far:** Opus workers cost more but got closer to passing; Sonnet workers were slower here. Recommendation: Opus (low) for now.

### Final testing on Claude Fable (2026-10-10)

- Live suites with `JARVIS_TEST_MODEL=claude-fable-5-1`: greeting PASS, memory test 10/10, tools 10/10 with injection blocked and 0 T4 runs, demo -> skill PASS (API-key test skipped: no key, by decision).
- Eval suite: 12/12 (Marathi/English, memory, structured output, tool calling).
- Laptop compare team task on Fable: FAILED twice (first $5 budget hit; then 3 rounds, 62 calls, $11.65 notional): no price could be confirmed on an Indian retailer page. Research shows Amazon/Flipkart terms forbid automated price collection, so the verifier needs source tiers (see Next step).

## Waiting for Sachin

Parked items. Work that does not depend on them continues.

- **Worker model:** Claude recommends Opus (low) after the comparison (see Phase 3 live results). Default stays opus until Sachin decides.
- **Telegram (Phase 4 live check):** create a bot with @BotFather, run `jarvis telegram set-token`, put your numeric Telegram user ID in `config/local.yaml` (`proactive_file: {telegram: {allowed_user_id: ...}}`) and a default weather place (`proactive_file: {brief: {place: "..."}}`). Then `jarvis telegram test` and `jarvis daemon`.
- **Google (Phase 5 live check):** create a Google Cloud project, enable Calendar and Gmail APIs, create an OAuth "Desktop app" client, set the app to "In production" (Testing tokens expire in 7 days), put the client JSON path in `config/local.yaml` (`connectors_file: {google: {client_secret_file: ...}}`), `pip install -e ".[google]"`, run `jarvis google auth`.
- **Open decision #19:** do email sender and subject count as P1 or P2? Default P2 (`gmail.header_class`).
- **Confirm tiers:** `parse_time` set to T0 (pure local computation); EventKit tools kept at T2.
- **Voice (Phase 6 live check):** OK to install `faster-whisper` (~80 MB of packages) and download the Whisper `small` model (486 MB) with `jarvis voice setup`?
- **Voice:** Marathi cloud voice (edge-tts) on or off (default off)? Wake word "hey jarvis" now or later (~100 MB, models CC BY-NC-SA)?
- **Browser (Phase 8):** `jarvis browser setup` downloads Playwright Chromium (~150–200 MB) per machine; this laptop already has a cached copy.
- **Dashboard (Phase 7):** on this laptop the built frontend is already in `dashboard/out/` (copied from the agent's build). On another machine: `cd dashboard; npm install; npm run build` (one-time download).
- **Mac checks:** Rishi voice (`say -v '?'`), Whisper speed on the M4, microphone permission, EventKit (`pyobjc-framework-EventKit`, Reminders permission), browser profiles permissions, everything once on the Mac.

## Next step

On a new machine first: `git clone`, run `scripts/setup.ps1` (Windows) or `scripts/setup.sh` (Mac), log in to Claude Code with the subscription (`claude`), `jarvis secret set tavily_api_key`, then `cd dashboard; npm install; npm run build`, then `jarvis health`. Personal data (memory, projects, data) does not travel with the repo.

1. **Done 2026-10-10 (Mac):** finished and merged `wip/india-features` (see session log). Was: India tools need registering in `jarvis/tools/catalog.py` (`india_tools`), brief sections via `register_india_sections()` from `jarvis/proactive/integration.py`, CLI `cli_india` in the module tuple of `jarvis/cli.py`; whole suite green; merge.
2. **Done 2026-10-10 (Mac):** finished and merged `wip/verify-repeat` (verify-after-act with claims vs evidence; `/repeat` in chat, Telegram and `jarvis task repeat`). Was: verify-after-act checks for Operator/Coder/browser and receipt "claims vs evidence"; `/repeat <when>` and `jarvis task repeat` (skill + schedule saved only after confirmation); merge.
3. **Done 2026-10-10 (Mac):** global daily cap + runaway guard, nightly review (episode file + memory conflicts in the brief) merged. Backups merged: `jarvis backup create|list|restore-check` (destination `~/JarvisBackups` by default; open decision #10).
4. **Partly done 2026-10-10 (Mac):** merged why-panel recording for every chat (CLI, Telegram) and sensitive-topic enforcement in code. **In progress:** dashboard India tab + triggers adapter (`feature/dashboard-india`). **Left:** a dashboard endpoint for CLI/Telegram turns (`GET /api/sessions/{sid}/turns` or turn ids in session lines) and a `/why` chat command. Was: **Claude, small hooks:** dashboard triggers adapter (`"triggers": ("jarvis.proactive.triggers", "dashboard_triggers")` in `jarvis/web/adapters.py`), `record_turn` in `ChatSession.send` for "why" on CLI/Telegram chats, enforce "health/politics = sensitive" in code (not only prompts).
5. **Claude:** final testing on Claude Fable (`JARVIS_TEST_MODEL=claude-fable-5-1`): live suites, eval + memory eval (`jarvis eval --suite memory --live`), injection live set, laptop compare with price tiers; record results here.
6. **Sachin:** the "Waiting for Sachin" list; hands-on testing with TESTING.md (section 9: the app).

## Decisions made by Sachin

| Date | Decision |
|---|---|
| 2026-10-09 | Plan everything first, then build |
| 2026-10-09 | Videos and documents are reference only; we build our own Jarvis |
| 2026-10-09 | Core requirement: remember what it is taught and use it later on its own |
| 2026-10-09 | Needs an agent team: give Jarvis a task and it gets the team to do it |
| 2026-10-10 | Vetted 8 suggestions (teach-by-demo, task queue, registry, schedules, model routing, receipts, project workspace, browser profiles) and added them to PLAN |
| 2026-10-10 | Code repo: https://github.com/Sachinx1911/jarvis (public) |
| 2026-10-10 | Work spans several laptops and Claude accounts; the repo is the source of truth |
| 2026-10-10 | Files are written in English; Claude talks to Sachin in Marathi in chat |
| 2026-10-10 | Research Sachin brings from ChatGPT is verified and checked for usefulness before anything is added. Claude reports blockers instead of guessing |
| 2026-10-10 | Architecture: hybrid now (Claude reasoning, everything else local), migration-ready for fully local AI later (PLAN v3.3) |
| 2026-10-10 | Brain loop: Jarvis-owned loop with a Claude adapter (not the Claude Agent SDK) |
| 2026-10-10 | Web search: Tavily |
| 2026-10-10 | Sensitive (P2) data: nothing sent to the cloud at the start |
| 2026-10-10 | Build cross-platform (Windows office laptop + Mac). Mac-only features stay in later phases. Secrets via keyring: Keychain on Mac, Credential Manager on Windows |
| 2026-10-10 | Python 3.12 on the office laptop; code supports 3.12+ (Mac keeps 3.13) |
| 2026-10-10 | Do not use the Claude API for now. The Claude API adapter stays in the code but is not approved |
| 2026-10-10 | Use Sachin's Claude Max subscription instead, through the Claude Code CLI as a provider adapter (`claude_code`). Claude Code CLI updated to 2.1.296 on the office laptop |
| 2026-10-10 | Vector search deferred (keyword + trigram first) |
| 2026-10-10 | P2 "sensitive" in memory prompts = health, money, ID document contents/numbers, other people's phone/email/address. Family names, where things are kept, schedules and preferences are P1 |
| 2026-10-10 | Web search stays Tavily (compared with Brave, Claude search via Max, Google CSE, DuckDuckGo, SearXNG; Tavily: no card, AI-ready content, provider-independent). Tavily MCP server not used for now |
| 2026-10-10 | File tools start with the Jarvis `workspace/` folder only; more folders can be added one at a time in `config/local.yaml` |
| 2026-10-10 | Keep working through all phases without stopping; park items that need Sachin's confirmation; use parallel agents; final testing on Claude Fable (CLAUDE.md updated) |
| 2026-10-10 | Researcher/Writer model: test both opus (low) and sonnet (medium), then choose |
| 2026-10-10 | Everything should be usable from the app (one-click start, all features in the dashboard) and tasks should be automatable (triggers, standing approvals, repeat-this) |
| 2026-10-10 | Vetted the Hermes Agent Masterclass (Jack Roberts, hermes-masterclass.vercel.app). Taken: a global daily cap for unattended work (runaway-loop risk), a nightly review into `memory/episodes/` with memory conflicts in the brief, local dated backups (destination still open decision #10). Already in Jarvis: soul file, markdown memory + FTS, risk tiers/approvals/kill switch, Telegram allow-list, cron/heartbeat/brief, planner-worker-critic, budgets, dashboard. Dropped: VPS/Docker hosting (data leaves the laptop), OpenRouter (new key/cost), WhatsApp (banned for AI assistants), public webhooks (security), the selling/money module, the unproven "CLI uses 100x fewer tokens" claim |

## Decisions made by Claude (for Sachin to review)

| Date | Decision |
|---|---|
| 2026-10-10 | Voice: faster-whisper for local speech-to-text (no torch; 4x faster than openai-whisper on CPU per its README); System.Speech on Windows, `say` on macOS; edge-tts only as an optional, off-by-default Marathi cloud voice that never gets P2/P3 text |
| 2026-10-10 | Unattended schedules run agent tasks with no approver: only T0/T1 actions; anything else is refused and shows in the receipt |
| 2026-10-10 | Telegram `/cloud off` writes an override file that applies to every route; it can only switch cloud off, never loosen `routing.yaml` |
| 2026-10-10 | The morning brief shows calendar titles and times (P1) but no email until decision #19 |
| 2026-10-10 | Dashboard: localhost only, token in keyring, no cookie auth; lowering a tool's tier or re-enabling it only by editing the private registry file |
| 2026-10-10 | India brief: bills and wallet records appear only as counts on Telegram unless `india.brief.details: true` (P2 rule) |
| 2026-10-10 | Daily cap for unattended work: 100 runs with model calls, 200 model calls, $5 notional per day; pause after 3 failures in a row; a `run-now` Sachin starts is never capped; plain notifications are free (`proactive unattended`) |
| 2026-10-10 | Nightly review at 22:30 to `memory/episodes/`, output to file (counts only), no model |
| 2026-10-10 | Repeat-this: at most one run every 30 minutes (`schedules.repeat_min_interval_minutes`); `jarvis task repeat` has no `--yes`; drafts expire after 1 hour; Telegram gets only a P2-safe summary, the full draft is read with `jarvis task draft <id>` |
| 2026-10-10 | Backups: `~/JarvisBackups`, keep 14, not encrypted yet; never inside the repo; excludes browser profiles, Google client secrets, the Whisper model and SQLite side files |
| 2026-10-10 | Offline tests block every non-loopback connection (live tests keep network with JARVIS_LIVE=1) |
| 2026-10-10 | Sensitive enforcement in code (`jarvis/memory/sensitivity.py`) only raises to sensitive. It also flags Sachin's own phone/email/address and places named "hospital"; he can lower a memory by hand. Sensitive `remember` notes are saved without the cloud enrichment (no English summary) |
| 2026-10-10 | The memory decide step never sends sensitive memories to the cloud model: duplicates of a private memory are caught locally; a newer version with the same subject, type and name supersedes it locally; anything else is added and shows up as a possible conflict |
| 2026-10-10 | P3 filters read Devanagari digits too (an Aadhaar or OTP in Devanagari digits is withheld) |

## Open decisions

See "Open decisions" in PLAN.md. Most important:
- 5 things Jarvis should do every day
- Whether email sender and subject count as P1 or P2 (#19)
- Where to keep the private backup of Jarvis's personal data
- Worker model choice (after the Phase 3 comparison)

## Session log

| Date | Machine | What happened |
|---|---|---|
| 2026-10-09 | MacBook M4 | Online research, YouTube video, 2 blueprints, Mac check, 5 research agents, PLAN v1 to v3 |
| 2026-10-10 | MacBook M4 | Vetted 8 suggestions (PLAN v3.1). Connected the repo. Created CLAUDE.md, PROGRESS.md, .gitignore. Switched all files to English (PLAN v3.2). Pushed to GitHub |
| 2026-10-10 | MacBook M4 | PLAN v3.3: AI provider layer, privacy classes P0–P3, migration roadmap Stages A–D, migration evaluation suite. Brain-loop recommendation changed to a Jarvis-owned loop. No code |
| 2026-10-10 | MacBook M4 | Sachin decided: own loop, Tavily, no P2 to cloud at start (PLAN v3.4) |
| 2026-10-10 | MacBook M4 | PLAN v3.5: migration path for every AI-dependent component, rule for moving a component local. CLAUDE.md rule added |
| 2026-10-10 | Office laptop (Windows) | Cloned repo. Built Phase 0 cross-platform, then the Claude Code CLI adapter (subscription). Live greeting test passed |
| 2026-10-10 | Office laptop (Windows) | Built Phase 1 (memory, loop, privacy gate, evals). Live memory test 10/10, eval baseline 8/8 |
| 2026-10-10 | Office laptop (Windows) | Built Phase 2 (tiers, approvals, taint, quarantine, tools). Live: 10/10 tasks, injection blocked, 0 T4 runs. Pushed to GitHub |
| 2026-10-10 | Office laptop (Windows) | Research fixes merged (security, prices, memory), one-click app, triggers, standing approvals and previews. 902 tests pass. Pushed. India features and verify/repeat stopped mid-work on wip branches; handoff to home |
| 2026-10-10 | Office laptop (Windows) | Fable final tests (live suites pass, evals 12/12; laptop compare fails on retailer-price verification). Planner modes, task cancel, chat browser, memory upkeep, approval replay, migration lock fix, README, research on 5 topics, TESTING.md |
| 2026-10-10 | Home MacBook M4 | Merged why-panel recording for every chat and sensitive enforcement; fixed two privacy gaps found by the agent (Devanagari-digit P3, sensitive memories in the extractor's decide step). 1186 passed |
| 2026-10-10 | Home MacBook M4 | Merged backups and verify-after-act + repeat-this (made the Telegram `/repeat` draft P2-safe, added `jarvis task draft`). 1100 passed |
| 2026-10-10 | Home MacBook M4 | Sachin updated Claude Code to 2.1.296. Live greeting through the subscription CLI: PASS on the Mac |
| 2026-10-10 | Home MacBook M4 | Merged `wip/india-features` (wired tools, brief sections, CLI; brief shows bills/wallet as counts unless `india.brief.details`; offline tests now block all non-loopback network). Merged daily cap + runaway guard (`proactive unattended`), nightly review (`review` schedule kind, `memory/episodes/`), memory conflicts (`jarvis memory conflicts`, brief count). 970 passed. Agents running on `wip/verify-repeat`, `feature/backup`, `feature/dashboard-india` (India tab, triggers in dashboard), `feature/small-hooks` (why-panel for CLI/Telegram, sensitive-topic enforcement) |
| 2026-10-10 | Home MacBook M4 | Pulled office work. `scripts/setup.sh` OK. Offline suite on macOS: 899/902, then 902 passed after fixes: Windows-style paths (`C:/...`, UNC) now refused on Mac/Linux in `PathPolicy` and grant rules (POSIX had treated them as names inside the workspace), shortcut path parsed as a Windows path. `jarvis health`: claude_code OK (Max); Claude Code CLI 2.1.260 too old for `--system-prompt-file` |
| 2026-10-10 | Office laptop (Windows) | Built Phase 3 (tasks, team, receipts, projects, teach-by-demo). Five parallel agents built Phases 4–8; all merged and wired in. 494 offline tests pass. First live laptop compare failed verification; quality fixes made; rerun started |
