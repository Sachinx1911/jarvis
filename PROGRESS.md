# Jarvis — Progress

Starting a session: `git pull`, then read this file, then PLAN.md.
Ending a session: update this file and commit.

## Current status

- **Phase:** Phase 0 complete. Phase 1 approved by Sachin (vectors deferred); not started yet.
- **AI provider now:** Claude through Sachin's Claude Max subscription, via the local Claude Code CLI (`claude -p`), adapter `jarvis/providers/claude_code.py`. No API key, no per-call billing; calls count against the plan's usage limits. The Anthropic API adapter (`claude.py`) stays but is not approved in `config/routing.yaml`.
- **Code:** `jarvis/` package: provider interface (`providers/base.py`), fake provider, Claude Code CLI adapter (main), Claude API adapter (unused), routing policy, SQLite store, audit log, keyring secrets, CLI (`init`, `chat`, `secret`, `health`). Config in `config/`, system prompt in `prompts/`, setup scripts in `scripts/`.
- **Tests:** 43 pass offline, 2 live tests opt-in. Run: `.venv\Scripts\python.exe -m pytest` (Windows) or `.venv/bin/python -m pytest` (Mac). Live: set `JARVIS_LIVE=1`, then `pytest -m live` (subscription test passed on 2026-10-10; API test skipped, no key).
- **Needs on each machine:** Claude Code CLI 2.1.280 or newer (for `claude-opus-5-5`), logged in with the Claude subscription. `jarvis health` checks this.
- **Half-done work:** None.
- **Last update:** 2026-10-10, office laptop (Windows 11, Python 3.12).
- **GitHub:** Pushed to `main` on 2026-10-10 with Sachin's OK.

## Next step

1. **Claude:** Build Phase 1 per the plan Sachin approved on 2026-10-10 (memory store as markdown + SQLite FTS5 unicode61/trigram index with RRF, `/remember`, memory commands, context builder, privacy gate v1 with P3 filters, Jarvis-owned agent loop with `memory_search` and `load_skill`, session search, skill loader, SOUL.md template, extractor pipeline, eval scaffold). Vectors deferred.
2. With the subscription provider available, the extractor, query rewrite and the Phase 1 memory test (10 facts, at least 9 used) can now run for real.

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
| 2026-10-10 | Phase 0 started without an API key, using the fake provider; live Claude check after the key arrives |
| 2026-10-10 | Do not use the Claude API for now. The Claude API adapter stays in the code but is not approved |
| 2026-10-10 | Use Sachin's Claude Max subscription instead, through the Claude Code CLI as a provider adapter (`claude_code`). Claude Code CLI updated to 2.1.296 on the office laptop |
| 2026-10-10 | Start Phase 1 now, built and tested against the fake provider plus the subscription provider. Vector search deferred (keyword + trigram first) |

## Open decisions

See "Open decisions" in PLAN.md. Most important:
- 5 things Jarvis should do every day (before Phase 1)
- Whether email sender and subject count as P1 or P2 (before Phase 5)
- Claude API key and monthly budget (for Phase 0)
- Where to keep the private backup of Jarvis's personal data

## Session log

| Date | Machine | What happened |
|---|---|---|
| 2026-10-09 | MacBook M4 | Online research, YouTube video, 2 blueprints, Mac check, 5 research agents, PLAN v1 to v3 |
| 2026-10-10 | MacBook M4 | Vetted 8 suggestions (PLAN v3.1). Connected the repo. Created CLAUDE.md, PROGRESS.md, .gitignore. Switched all files to English (PLAN v3.2). Pushed to GitHub |
| 2026-10-10 | MacBook M4 | PLAN v3.3: AI provider layer, privacy classes P0–P3, migration roadmap Stages A–D, migration evaluation suite. Brain-loop recommendation changed to a Jarvis-owned loop. No code |
| 2026-10-10 | MacBook M4 | Sachin decided: own loop, Tavily, no P2 to cloud at start (PLAN v3.4) |
| 2026-10-10 | MacBook M4 | PLAN v3.5: migration path for every AI-dependent component, rule for moving a component local. CLAUDE.md rule added |
| 2026-10-10 | Office laptop (Windows) | Cloned repo. Built Phase 0 cross-platform: provider interface, fake + Claude adapters, routing, SQLite, audit, keyring, CLI, setup scripts, 26 tests passing |
| 2026-10-10 | Office laptop (Windows) | Added the Claude Code CLI adapter (subscription login, isolated, JSON reply/action mode). Live greeting test passed. Phase 0 complete. Phase 1 plan approved |
