# Jarvis — Progress

Starting a session: `git pull`, then read this file, then PLAN.md.
Ending a session: update this file and commit.

## Current status

- **Phase:** Phase 3 built (offline tests pass; live laptop-compare run with opus and sonnet workers in progress). Phases 4, 5, 6, 7 being built in parallel by agents in separate worktrees (`.claude/worktrees/`, git-ignored); the lead merges them.
- **Phase 3 code:** `jarvis/tasks/` (store with states, budget, receipt), `jarvis/agents/` (team sub-loops, orchestrator), `jarvis/projects.py`, `jarvis/skills/recorder.py` (teach-by-demonstration), `jarvis/cli_tasks.py` (`task`, `tasks`, `receipt`, `project`, `record`, `skill`; chat `/task`, `/record`, `/note`), `config/tasks.yaml`, team routes in `config/routing.yaml`.
- **Phase 2:** done-when met on Claude via subscription: 10/10 tool tasks verified, prompt-injection page blocked, no T4 action ran.
- **AI provider now:** Claude through Sachin's Claude Max subscription, via the local Claude Code CLI (`claude -p`), adapter `jarvis/providers/claude_code.py`. No API key, no per-call billing; calls count against the plan's usage limits. Main chat: Opus 5.5 (medium). Memory enrichment/extraction: Haiku 5.5 (low). The Anthropic API adapter (`claude.py`) stays but is not approved in `config/routing.yaml`.
- **Code:** Phase 0 (provider interface, fake + Claude Code + Claude API adapters, routing, SQLite, audit, keyring, CLI) plus Phase 1:
  - `jarvis/memory/`: markdown memory files + SQLite index (FTS5 unicode61 + trigram, RRF, gate, recency boost), `/remember`, two-step extractor (quote required, ADD/UPDATE/SUPERSEDE/NOOP/REJECT), MEMORY.md index.
  - `jarvis/core/`: context builder (SOUL, rules, memory index, hard rules, skill index, relevant memories, local time), Jarvis-owned agent loop with step limit, chat session (memories extracted at /exit).
  - `jarvis/privacy.py`: P0–P3 classes, P3 filters (keys, passwords, OTP, cards with Luhn, Aadhaar, PAN); P3 redacted from every outbound payload; P2 memories withheld from cloud routes.
  - `jarvis/tools/registry.py` (T0 only in Phase 1): `memory_search`, `session_search`, `load_skill`. `jarvis/skills/loader.py` (SKILL.md). `jarvis/control/stop.py` (emergency stop file).
  - `jarvis/evals/runner.py` + `tests/evals/migration/tasks.yaml` (8 synthetic tasks).
  - CLI: `chat` (/remember, /remember-private, /memory, /forget), `memory list|search|show|archive|export|reindex|add`, `sessions search`, `interview`, `eval`, `stop`, `resume`.
- **Phase 2 code:**
  - `jarvis/control/approvals.py`: T0 runs; T1 runs then verified (asks once the session is tainted); T2/T3 ask with exact arguments; T4 never runs and is logged. Decisions go to the `approvals` table and the audit log (with output hash).
  - `jarvis/tools/registry.py`: schema check -> path pre-check (secret paths are T4) -> gate -> run -> verify -> log. Taint flag set by web tools.
  - `jarvis/tools/files.py`: read/list (T0), write new (T1), overwrite/move (T2), delete to `.trash` (T3); only inside `workspace/` (config `config/tools.yaml`).
  - `jarvis/tools/web.py` + `quarantine.py`: Tavily search, page fetch (public http(s) only, redirects checked), weather (Open-Meteo, no key). Pages are read by a quarantined Haiku call with no tools.
  - `jarvis/tools/system.py`: open_app (allowlist, T1), notify (T1), media keys (T1), open_url (T2), brightness (T2, Windows). Windows and macOS.
  - `jarvis/tools/catalog.py`: all built-in tools and the private registry `connectors/registry.yaml` (disable or raise a tier; lowering is ignored). `jarvis connectors status`.
  - Chat asks for approval in the terminal; one-shot `chat -m` denies anything that needs approval.
- **Tests:** 125 pass offline, 4 live tests opt-in (`JARVIS_LIVE=1 pytest -m live -s`). Live on 2026-10-10: memory 10/10, tools 10/10 + injection blocked, eval baseline 8/8.
- **Not live-tested on purpose:** media keys, notifications, open_app, brightness (they change the computer). Covered by unit tests only; Sachin can try them in chat.
- **Tavily:** key stored in Windows Credential Manager on the office laptop (2026-10-10); live search and a chat news question work. The Mac needs its own `jarvis secret set tavily_api_key`.
- **Not built (deferred):** news via RSS (Tavily `topic: news` covers news and cricket), traffic (needs a maps API), Do Not Disturb (no simple Windows API), vector search (decided), automatic extraction 10–30 min after a quiet session (needs the Phase 4 scheduler; now runs at /exit), weekly memory cleanup, query rewrite as a separate model call (summary_en + keywords saved with each memory cover romanized Marathi for now).
- **Needs on each machine:** Claude Code CLI 2.1.280 or newer, logged in with the Claude subscription. `jarvis health` checks this.
- **Half-done work:** None.
- **Last update:** 2026-10-10, office laptop (Windows 11, Python 3.12).
- **GitHub:** Pushed to `main` on 2026-10-10 (up to Phase 2) with Sachin's OK.

## Waiting for Sachin

Parked items. Work that does not depend on them continues.

- Pick the worker model (Researcher/Writer) after the opus vs sonnet laptop-compare comparison.
- Push to GitHub: Phase 3 and later commits are local only until Sachin OKs a push.

## Next step

1. **Sachin:** Try Phase 2 in chat (weather, files in `workspace/`, volume, open notepad), then review.
2. **Sachin:** Say "Start Phase 3" (Tasks + Agent team).

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
| 2026-10-10 | (Confirmed by Sachin) P2 "sensitive" in memory prompts = health, money, ID document contents/numbers, other people's phone/email/address. Family names, where things are kept, schedules and preferences are P1. The first live run marked a daughter's name and a document location as P2, which withheld them from Claude |
| 2026-10-10 | Start Phase 2. Web search stays Tavily (compared with Brave, Claude search via Max, Google CSE, DuckDuckGo, SearXNG; Tavily: no card, AI-ready content, provider-independent) |
| 2026-10-10 | Tavily MCP server not used for now: Jarvis already calls the Tavily REST API directly; MCP client comes with connectors (Phases 4–5) |
| 2026-10-10 | File tools start with the Jarvis `workspace/` folder only; more folders can be added one at a time in `config/local.yaml` |

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
| 2026-10-10 | Office laptop (Windows) | Built Phase 2: tiers and approvals, taint flag, quarantine, file/web/weather/system/media tools, verifier, connector registry. Live: 10/10 tasks, injection blocked, 0 T4 runs |
| 2026-10-10 | Office laptop (Windows) | Built Phase 1: memory store/search, write path, context builder, agent loop, privacy gate v1, tools, skills, session search, emergency stop, interview, eval scaffold. Live memory test 10/10, eval baseline 8/8 |
