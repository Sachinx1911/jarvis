# Jarvis — Progress

Starting a session: `git pull`, then read this file, then PLAN.md.
Ending a session: update this file and commit.

## Current status

- **Phase:** All phases 0–8 are built and merged into `main` (2026-10-10). 494 offline tests pass. Live checks on Claude (subscription) passed for Phases 0–2; Phase 3 live checks are being rerun after quality fixes (see "Phase 3"). Phases 4–8 are tested offline with fakes; their live checks wait for items in "Waiting for Sachin". Final testing on Claude Fable comes last (Sachin's rule).
- **How the work was done:** Phase 3 by the lead session; Phases 4, 5, 6, 7, 8 by parallel agents in git worktrees (`.claude/worktrees/`, git-ignored), each owning its own files, then merged and wired in by the lead.
- **AI provider now:** Claude through Sachin's Claude Max subscription, via the local Claude Code CLI (`claude -p`), adapter `jarvis/providers/claude_code.py`. No API key, no per-call billing; calls count against the plan's usage limits. Main chat Opus 5.5 (medium); memory, quarantine, summaries Haiku 5.5 (low); planner and checker Opus 5.5 (high); workers per profile (`config/tasks.yaml`). The Anthropic API adapter (`claude.py`) stays but is not approved in `config/routing.yaml`.
- **Needs on each machine:** Python 3.12+, `pip install -e ".[dev]"`, Claude Code CLI 2.1.280 or newer logged in with the subscription (`jarvis health`), Tavily key (`jarvis secret set tavily_api_key`). Optional extras: `[voice]`, `[voice-cloud]`, `[wakeword]`, `[google]`, `[browser]`. Dashboard frontend: `cd dashboard; npm install; npm run build`.
- **Half-done work:** Phase 3 live rerun (laptop compare with opus and sonnet workers; demo-to-skill replay) — results to be recorded below.
- **Last update:** 2026-10-10, office laptop (Windows 11, Python 3.12).
- **GitHub:** Pushed to `main` on 2026-10-10 up to Phase 2 with Sachin's OK. Everything after that is local until he OKs a push.

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
- **Second run:** in progress.

## Waiting for Sachin

Parked items. Work that does not depend on them continues.

- **Push to GitHub:** Phases 3–8 are local only until Sachin OKs a push.
- **Worker model:** pick opus or sonnet for Researcher/Writer after the Phase 3 rerun comparison.
- **Telegram (Phase 4 live check):** create a bot with @BotFather, run `jarvis telegram set-token`, put your numeric Telegram user ID in `config/local.yaml` (`proactive_file: {telegram: {allowed_user_id: ...}}`) and a default weather place (`proactive_file: {brief: {place: "..."}}`). Then `jarvis telegram test` and `jarvis daemon`.
- **Google (Phase 5 live check):** create a Google Cloud project, enable Calendar and Gmail APIs, create an OAuth "Desktop app" client, set the app to "In production" (Testing tokens expire in 7 days), put the client JSON path in `config/local.yaml` (`connectors_file: {google: {client_secret_file: ...}}`), `pip install -e ".[google]"`, run `jarvis google auth`.
- **Open decision #19:** do email sender and subject count as P1 or P2? Default P2 (`gmail.header_class`).
- **Confirm tiers:** `parse_time` set to T0 (pure local computation); EventKit tools kept at T2.
- **Voice (Phase 6 live check):** OK to install `faster-whisper` (~80 MB of packages) and download the Whisper `small` model (486 MB) with `jarvis voice setup`?
- **Voice:** Marathi cloud voice (edge-tts) on or off (default off)? Wake word "hey jarvis" now or later (~100 MB, models CC BY-NC-SA)?
- **Browser (Phase 8):** `jarvis browser setup` downloads Playwright Chromium (~150–200 MB) per machine; this laptop already has a cached copy.
- **Dashboard (Phase 7):** `cd dashboard; npm install; npm run build` downloads the Next.js packages (one time).
- **Mac checks:** Rishi voice (`say -v '?'`), Whisper speed on the M4, microphone permission, EventKit (`pyobjc-framework-EventKit`, Reminders permission), browser profiles permissions, everything once on the Mac.

## Next step

1. **Claude:** Record the Phase 3 rerun results; compare opus vs sonnet workers.
2. **Claude:** Final testing on Claude Fable across all phases (live suites, eval suite, laptop compare), then record results.
3. **Sachin:** Work through "Waiting for Sachin".

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

## Decisions made by Claude (for Sachin to review)

| Date | Decision |
|---|---|
| 2026-10-10 | Voice: faster-whisper for local speech-to-text (no torch; 4x faster than openai-whisper on CPU per its README); System.Speech on Windows, `say` on macOS; edge-tts only as an optional, off-by-default Marathi cloud voice that never gets P2/P3 text |
| 2026-10-10 | Unattended schedules run agent tasks with no approver: only T0/T1 actions; anything else is refused and shows in the receipt |
| 2026-10-10 | Telegram `/cloud off` writes an override file that applies to every route; it can only switch cloud off, never loosen `routing.yaml` |
| 2026-10-10 | The morning brief shows calendar titles and times (P1) but no email until decision #19 |
| 2026-10-10 | Dashboard: localhost only, token in keyring, no cookie auth; lowering a tool's tier or re-enabling it only by editing the private registry file |

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
| 2026-10-10 | Office laptop (Windows) | Built Phase 3 (tasks, team, receipts, projects, teach-by-demo). Five parallel agents built Phases 4–8; all merged and wired in. 494 offline tests pass. First live laptop compare failed verification; quality fixes made; rerun started |
