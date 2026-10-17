# Jarvis — Progress

Starting a session: `git pull`, then read this file, then PLAN.md.
Ending a session: update this file and commit.

## Current status

- **Step 2 built, UI on hold (2026-10-17, office laptop, Windows):** on `main`, after step 1:
  - **Narada between lokas (27.5 item 6):** `jarvis/workspaces/narada.py` — `jarvis workspace ask <from> <to>
    "<goal>"`, `/ask <slug> <goal>` in chat, `POST /api/workspaces/{slug}/requests`; personal may ask any
    office, a company only its `allies`; the asked office gets a task (`owner narada:<from>`); when it
    finishes, only the deliverable crosses back into `data/workspaces/<from>/inbox/` (audited
    `loka_request_delivered`); requests archive, `delete_forever` only when archived.
  - **File truth and the pralaya test (law 2, 27.8 item 10):** tasks, schedules and triggers are files
    (`data/tasks/<id>/task.json` + `events.jsonl`, `data/schedules/<id>.json`, `data/triggers/<id>.json`),
    SQLite is the index. `jarvis verify` and `jarvis rebuild [--dry-run] [--prune]`; the nightly review adds a
    "truth check" line. The pralaya test deletes the database and rebuilds the same world (tests and a CLI
    smoke run). **On an existing machine run `jarvis rebuild --prune` once** so old rows get their files.
  - **Task archive:** `jarvis task archive|unarchive <id>` (final tasks only), `jarvis tasks --archived`,
    `POST /api/tasks/{id}/archive|unarchive`.
  - **Office page API:** `GET /api/office` and `/api/office/{slug}/teams/{team}` (live counts per office and
    team, brain, waiting items). The Office tab TSX exists but is **unbuilt and will be redone** to Sachin's
    chosen design (see "Waiting for Sachin").
  - Tests: `test_narada.py`, `test_web_api_narada.py`, `test_truth.py`, `test_web_api_office.py`,
    `test_loka_wiring.py` (end-to-end request through the orchestrator). Whole suite: 1664 passed, 25 skipped (Windows, 2026-10-17).
  - Gaps: requests (`loka_requests`), standing grants, sessions and model usage have no file truth yet (lost in
    a pralaya; next); routing choices are not stored (`needs_choice` always 0 on the Office page); scheduled
    approvals are not mapped to teams; no `decline` command for requests yet.
  - Next: Sachin's design → the whole frontend to that design (nav, Command Center, Office, Chat, Tasks,
    Memory) → Phase 9 (X-ray) → final Fable testing.

- **Step 1 of the laws built (2026-10-17, office laptop, Windows):** Sachin took all eleven design
  decisions of PLAN.md 27.8 as recommended ("sarv final", 2026-10-17 on the Mac). Work follows 27.8 item 11:
  step 0 (lokas and teams as data, the owner tag) → step 1 (this) → step 2 (Office page, Narada between
  lokas) → Phase 9 (X-ray). Step 0 is merged (`9108130`). Step 1 is merged on `main`, built by the lead and
  two agents in worktrees:
  - **Archive everywhere (law 2):** schedules and triggers end by archive; "delete" in CLI, Telegram and
    the dashboard archives. Only `jarvis schedule|trigger delete --forever` on an archived item, after
    asking, removes the row (audited `*_delete_forever`, by Sachin). `delete_forever` is the one DELETE a
    truth table allows (laws test). Dashboard buttons say Archive (rebuild the frontend to see it).
  - **Owner tag:** `workspace` on triggers and reminders too; grants can be bound to one office
    (`jarvis approvals grant <tool> --workspace <slug>`).
  - **Receipts into memory (law 3):** a completed task's summary becomes an episode memory of its own
    office (`receipt_remembered`).
  - **Adhipati (27.4):** the planner is the lead of the office's best-matching team (`jarvis/workspaces/
    routing.pick_team`); members' briefs, tools (never wider than the role) and model profiles apply;
    receipt shows `Team: research (Acme)`. Karma-yoga: an independent checker, no completion without a
    `verify` event.
  - **Dharma routing (27.5):** `/task`, `jarvis task add|run` and `POST /api/tasks` route a goal to an
    office by its duties/name/projects (both scripts); unsure → asks (CLI/chat numbered prompt, API 409
    `needs_choice`); `POST /api/workspaces/route`. Audited `task_routed`.
  - **Shruti (27.10):** `profile/SOUL.md`, `config/**`, `prompts/**`, CLAUDE.md, PLAN.md cannot be read or
    written by any tool (T4 `t4_attempt`), checked by an AST scan of every write in `jarvis/`.
  - **Kubera (27.4, 27.6):** per-office daily budgets (`budget:` in workspace.yaml) stop tasks
    (`loka budget: ...`), schedules and triggers (recorded CAPPED, one notice a day, `loka_capped`);
    `jarvis workspace show` prints today's spend.
  - **Fences (27.3):** `tools: allow/deny/always_ask` in workspace.yaml fence chat, tasks and workers
    (`tool_fenced`; always_ask asks on any tier and blocks standing grants).
  - **Astra (27.4a):** every tool declares how its act is checked or undone (`samhara`); a T2 with none
    is T3 (open_url and bill_upi_link are T3 now); one irreversible action in flight at a time
    (`astra_inflight`, stale 30 min); a failed verify withdraws the tool's standing grants
    (`grant_withdrawn`, "needs regrant" in `jarvis workspace show`); the Brahmastra takes one target,
    released once per approval.
  - Tests: `test_laws.py`, `test_laws_shruti.py`, `test_routing_dharma*.py`, `test_team_lead.py`,
    `test_loka_budget.py`, `test_fence.py`, `test_astra.py`, `test_loka_wiring.py`. Whole suite:
    1628 passed, 25 skipped (Windows, 2026-10-17).
  - Not done in step 1 (declared in `jarvis/core/kinds.py` gaps or here): tasks end by cancel, not archive
    (step 2); task/schedule file truth (27.8 item 10, step 2); operator/coder member briefs are not applied;
    trigger fires are not counted in the office's runs; the dashboard task form does not yet show the
    409 `needs_choice` candidates (step 2, Office page); routing is word overlap only (by design).
  - Next: step 2 (Office page in the dashboard, Narada between lokas, task archive) → Phase 9 (X-ray) →
    final Fable testing.

- **Phase:** All phases 0–8 are built and merged into `main` (2026-10-10). 494 offline tests pass. Live checks on Claude (subscription) passed for Phases 0–2; Phase 3 live checks are being rerun after quality fixes (see "Phase 3"). Phases 4–8 are tested offline with fakes; their live checks wait for items in "Waiting for Sachin". Final testing on Claude Fable comes last (Sachin's rule).
- **How the work was done:** Phase 3 by the lead session; Phases 4, 5, 6, 7, 8 by parallel agents in git worktrees (`.claude/worktrees/`, git-ignored), each owning its own files, then merged and wired in by the lead.
- **AI provider now:** Claude through Sachin's Claude Max subscription, via the local Claude Code CLI (`claude -p`), adapter `jarvis/providers/claude_code.py`. No API key, no per-call billing; calls count against the plan's usage limits. Main chat Opus 5.5 (medium); memory, quarantine, summaries Haiku 5.5 (low); planner and checker Opus 5.5 (high); workers per profile (`config/tasks.yaml`). The Anthropic API adapter (`claude.py`) stays but is not approved in `config/routing.yaml`.
- **Needs on each machine:** Python 3.12+, `pip install -e ".[dev]"`, Claude Code CLI 2.1.280 or newer logged in with the subscription (`jarvis health`), Tavily key (`jarvis secret set tavily_api_key`). Optional extras: `[voice]`, `[voice-cloud]`, `[wakeword]`, `[google]`, `[browser]`. Dashboard frontend: `cd dashboard; npm install; npm run build`.
- **Half-done work (handoff 2026-10-10, office laptop -> home):**
  - On `main` and tested (902 pass): everything through Phases 0–8, research fixes (prompt-injection hardening, price tiers, memory retrieval), one-click app, event triggers, approval previews + grouped and standing approvals + memory sources/trash + "why" panel.
  - Stopped mid-work, saved on branches (pushed, NOT merged, not tested): `wip/india-features` (AMFI NAV, IMD/Sachet feeds, bills tracker, document wallet, UPI link; tests partly written) and `wip/verify-repeat` (verify-after-act, `/repeat`). Resume each: check out the branch, run the whole suite, finish the brief in this file's "Next step", then merge.
  - Done later on the Mac (2026-10-10): global daily cap, nightly review, backups, India features, verify/repeat, dashboard India tab and triggers.
- **Last update:** 2026-10-11, home MacBook (Apple M4, macOS 26.5, Python 3.13): voice merged (local Marathi speech-to-text, offline Marathi voice, wake word model; 1420 passed). Laptop compare rerun on Fable (see Final testing). Stage B (local models) merged: measurements only, no route uses a local model (1461 passed). Marathi voice: Sachin dislikes MMS-TTS; plan is IndicF5 with his own recorded voice, parked by Sachin for now. Later the same day: grader fixes, voice status in the dashboard and CLI, "Hey Jarvis" made to work on this Mac, the dashboard redesign (Command Center, voice stage, hands-free chat) from Sachin's mockups, core memory (USER.md + MEMORY.md), the Mac app (`Jarvis.app`), and **voice v2** (see "Voice v2" below). 1518 passed.
- **Models on the home MacBook** (all under `data/models/`, git-ignored): Whisper small 484 MB, IndicConformer Marathi 138 MB, MMS-TTS Marathi 114 MB, openWakeWord 9 MB, Qwen3.5-9B Q4_K_M 5.7 GB (unsloth/Qwen3.5-9B-GGUF), Gemma 4 E4B Q4_K_M 5.0 GB (unsloth/gemma-4-E4B-it-GGUF, downloaded by Sachin in the browser, SHA-256 checked). Ollama and `gemma3:4b` on this Mac belong to another of Sachin's projects, not to Jarvis: leave them alone.
- **GitHub:** `main` pushed on 2026-10-10 from the home MacBook (all Mac merges, fixes and Fable results) with Sachin's OK. The old branches `wip/india-features` and `wip/verify-repeat` on GitHub are merged and can be deleted.

### What each phase delivered

- **Phase 0 — setup:** provider interface (`jarvis/providers/base.py`), fake provider, adapters, routing policy, SQLite (migrations), audit log, keyring secrets, CLI, setup scripts.
- **Phase 1 — brain + memory:** markdown memories + SQLite FTS5 (words + trigrams, RRF), `/remember`, two-step extractor with quotes, context builder, Jarvis-owned agent loop, privacy gate v1 (P0–P3, P3 filters), skills loader, session search, emergency stop, interview, eval scaffold. Live: memory test 10/10, eval baseline 8/8.
- **Phase 2 — tools + safety:** T0–T4 gate with approvals, taint flag, quarantine for web pages, workspace-only file tools, Tavily search, page fetch, weather, apps/notify/media/brightness, verifiers, private tool registry. Live: 10/10 tasks, injection blocked, 0 T4 runs.
- **Phase 3 — tasks + agent team:** task queue and states, planner, parallel researchers, writer, deterministic link-grounding check + independent checker, follow-up research and one revision, receipts from logs, budgets (calls, tokens, notional USD), checkpoints and resume, projects, teach-by-demonstration (chat, tool runs, file changes, terminal transcript, browser steps, notes → SKILL.md draft → approval), worker profiles opus/sonnet.
- **Phase 4 — Telegram + proactive:** APScheduler schedules (missed runs, no overlap, unattended = T0/T1 only), heartbeat, morning brief (weather, calendar, reminders, goals, tasks, schedules), reminders, Telegram bot (only Sachin's user ID, Approve/Deny buttons, `/stop`, `/cloud off`), `jarvis daemon`.
- **Phase 5 — connectors:** document library (md/txt/pdf/docx, page citations, P2 by default), `doc_search`, active project context, Google Calendar + Gmail via OAuth desktop flow (create event T2 with read-back verify, send T3), time parser (English + Marathi), EventKit (Mac only), connector health.
- **Phase 6 — voice:** push-to-talk loop, Windows System.Speech and macOS `say`, faster-whisper speech-to-text, voice approvals default to deny. Added 2026-10-11: local Marathi speech-to-text (AI4Bharat IndicConformer, ONNX int8 via `onnx-asr`) with en/mr/auto routing, offline Marathi voice (Meta MMS-TTS Marathi, ONNX), wake word model downloaded (wake word still off), optional Marathi cloud voice (off).
- **Phase 7 — dashboard:** FastAPI on 127.0.0.1 with a token, strict origin checks, approvals queue with argument hash, emergency stop; Next.js static export with Chat, Memory, Tasks & Approvals, Agents, Connectors, Schedules, Settings & Usage. `jarvis dashboard`.
- **Phase 8 — extras:** isolated Playwright browser (domain allowlist, fresh context, T3 submit with exact fields, passwords never logged, download checks), browser step recording, Operator and Coder agents, `run_tests` allowlist. Not built: OCR, signed .app, meeting notes, magic search. (Smart home dropped by Sachin.)

### Phase 3 live results

- **First run (2026-10-10), before fixes:** both worker profiles FAILED verification twice. Opus workers: 4 min, 24 calls, $1.34 notional. Sonnet workers: 5 min, 30 calls, $1.10 notional. The pipeline and receipts worked; the causes were criteria nobody can prove online (live stock), researchers stopping at an aggregator, and revisions that could not add facts. Fixed in commit "Make team tasks pass on real research".
- **Second run (after fixes, still 1 fix round):** both FAILED, but closer: Opus workers 8 min, 44 calls, $2.90 notional, round 2 passed 4 of 5 criteria (one availability detail left). Sonnet workers 12 min, 45 calls, $2.03 notional; the checker caught a real error (one laptop at Rs 82,990, above the limit). Change made: 2 fix rounds, budget 90 calls / $5 notional.
- **Demo -> skill replay (done-when part 2):** PASS on Opus (skill `create-weekly-plan-note` drafted, approved, replayed for a new week in a new session).
- **Worker model comparison so far:** Opus workers cost more but got closer to passing; Sonnet workers were slower here. Recommendation: Opus (low) for now.

### Final testing on Claude Fable (2026-10-10)

**Second round, home MacBook (after all merges, commit 3a8d9fb and later):**
- Live suites (`JARVIS_LIVE=1 JARVIS_TEST_MODEL=claude-fable-5-1 pytest -m live`): greeting, memory test, demo -> skill and injection PASS. Tools first 7/10 (web fetch and weather failed: python.org Python on macOS had no CA certificates); after the TLS fix (`jarvis/netssl.py`) tools 10/10, injection blocked, 0 T4 runs.
- Eval suite: 12/12.
- Memory eval live (`jarvis eval --suite memory --live`): raw 22/29, but all 7 misses were correct answers the grader could not read (romanized/Devanagari forms, Marathi declines, old value named as history). Grader fixed; the same answers re-grade to 29/29, stale 0/4, abstention 4/4.
- Laptop compare (2026-10-10 night, Tavily key now on the Mac; task `t-001`, $12 notional budget, 580k tokens in, 43k out): FAILED rounds 1 and 2, much closer than before. Round 3 was cut off by Sachin's emergency-stop test. 7 of 9 checks passed: 3 laptops (2 Lenovo, 1 Dell), all under Rs 80,000, specs right, every price dated and labelled "estimate (aggregator)", recommendation consistent. Failed checks:
  - "Check yourself" link: researchers cannot get Amazon/Flipkart product URLs (Jarvis does not open those sites). In round 2 the writer made search URLs itself (`amazon.in/s?k=<model>`), and the link-grounding check rejected them as not from research.
  - The "dropped candidates" table showed prices without a label.
  - The checker said the report "ends mid-sentence". The file on disk is complete (9.8 KB). Cause not found yet.
  - Proposed fix: Jarvis's code (not the model) builds the Amazon/Flipkart search link from a model number that appears in the research. Sachin said to leave it for now (2026-10-11). Until then, shop-price comparisons can end as "verification failed" even when the report is useful; the report is still saved in the task folder.

**Hands-on checks by Sachin (2026-10-10 night):**
- Emergency stop from the dashboard: PASS. Pressed at 23:31:26 while `t-001` was running. The running researcher stopped within 16 s, the app stopped, and `data/STOP` stayed until `jarvis resume`.
- Dashboard microphone in Chrome: "Permission denied by system". macOS has not given Chrome microphone access (System Settings > Privacy & Security > Microphone). Sachin will turn it on.

**First round, office laptop:**

- Live suites with `JARVIS_TEST_MODEL=claude-fable-5-1`: greeting PASS, memory test 10/10, tools 10/10 with injection blocked and 0 T4 runs, demo -> skill PASS (API-key test skipped: no key, by decision).
- Eval suite: 12/12 (Marathi/English, memory, structured output, tool calling).
- Laptop compare team task on Fable: FAILED twice (first $5 budget hit; then 3 rounds, 62 calls, $11.65 notional): no price could be confirmed on an Indian retailer page. Research shows Amazon/Flipkart terms forbid automated price collection, so the verifier needs source tiers (see Next step).

### Voice v2 (2026-10-11): one voice engine, Alexa-style

Why: the Mac app's own recordings showed the real fault. Audio was clean, but Whisper's free language
guess called an Indian-accent "hello hello hello" Arabic (0.28) and the clip was dropped as unclear;
"Jarvis" was heard as "that was". Standards checked: Amazon's Alexa attention states (Idle / Listening /
Thinking / Speaking) and Follow-Up Mode (5 s), Google's earcon guidance (few, brief, consistent), and
current voice-agent endpointing practice (short confident-done delay, ~0.5-0.7 s silence; 8 s no-speech).

- Speech-to-text: auto mode narrows Whisper's guess to English or Marathi (Hindi counts as Marathi); an
  unsure guess is settled by one decode forced to Marathi (Devanagari = Marathi, Latin = English).
  Whisper gets hotwords "Jarvis" and no carry-over context. `min_confidence` 0.35. Measured: all 12 test
  clips route right; Sachin's own clip went from "ألو ألو ألو" (unclear) to "Hello, hello, hello" (0.72).
- The page sends raw WAV at the microphone's rate (no MediaRecorder); the server resamples and evens
  out the level. The microphone is opened without echo cancellation, so macOS stops ducking Jarvis's
  spoken replies (the "volume goes up and down" complaint).
- One state machine for push to talk, "Hey Jarvis" (judged from the sound by the wake-word model; the
  server cuts the wake phrase off) and conversation mode: 0.5 s pre-roll, 0.7 s end silence, 15 s cap,
  8 s no-speech timeout, 5 s follow-up listening, tap to interrupt (POST /api/voice/stop), the server
  says when speech ends (GET /api/voice/speaking). Two earcons. A red "mic on" indicator. Voice never
  approves and never sends "/" commands.
- One Voice settings panel (mode, speak replies, auto-send, follow-up, sounds) on the Command Center
  and in Chat; the scattered switches are gone. Sidebar regrouped: Home, Work, Jarvis learns, Life,
  Settings. Memory tab has the Core memory editor.
- Mac app `~/Applications/Jarvis.app` (mac/Jarvis, `scripts/build_mac_app.sh`): the dashboard in its
  own window with the microphone; starts and stops Jarvis itself; watchdog restarts Jarvis if it
  disappears. Rebuild after moving the repo (it stores the repo path and PATH).
- Tests no longer read the developer's `config/local.yaml` (`JARVIS_LOCAL_CONFIG`, tests/conftest.py).
- Not done yet: a real-microphone check of voice v2 by Sachin (the engine was verified on recorded
  clips and in unit tests); Marathi voice quality (parked); Whisper on the GPU (MLX/whisper.cpp).

## Not built yet (as of 2026-10-10)

Built on 2026-10-10 (Mac): office files (`create_docx`, `create_xlsx` with native charts, `analyze_table`), missed-run alerts, dashboard repeat drafts and trigger create/delete, Apple Notes connector.

Also built on 2026-10-10: `jarvis connectors status --live`, `/repeat` and `/why` in the dashboard chat.

Can be built after Sachin's OK:
- Adding a UPI payee in the app with an explicit "I checked this ID" step.

Built on 2026-10-11 (Mac): local Marathi speech-to-text, offline Marathi voice, wake word model (see Phase 6).

Built on 2026-10-11: Stage B (local adapter `jarvis/providers/local.py`, localhost only, listed in `providers.yaml` but NOT in `routing.yaml` approved_providers; `python -m jarvis.evals.local_run` runs the evals on a local model through an in-memory config copy; measured profiles in `config/models.yaml`; report `docs/stage-b/2026-10-10-local-models.md`). Runtime: Homebrew `llama.cpp` 0.6.0 (`llama-server`, Metal, about 29 MB, MIT).

### Stage B results (2026-10-10/11, home MacBook M4 16 GB)

| | Claude (Fable 5.1) | Qwen3.5-9B Q4_K_M | Gemma 4 E4B Q4_K_M |
|---|---|---|---|
| Migration suite | 12/12 | 10/12 | 12/12 (10/12 after review) |
| Memory eval | 29/29 | 24/29 | 26/29 |
| Memory: temporal | 6/6 | 3/6 | 3-4/6 |
| JSON valid | - | 36/36 | 36/36 |
| Extraction correct | - | 8/12 (misses Marathi facts) | 12/12 |
| Right tool: English / Marathi | - | 22/22 / 9/18 | 22/22 / 14/18 |
| Answers Marathi in Marathi | mostly | yes, poor romanized | 7/19 |
| Injection harm | 0 | 0/5 | 0/5 |
| Decode speed | - | 6-9 tok/s | 25-27 tok/s |
| First token, chat turn (cold / cached) | - | 73 s / 0.7 s | 38-55 s / 0.6 s |
| Peak RAM | - | 7.1 GB | 6.6 GB |

- Verdict: no component is local-ready yet (no agreed thresholds, small samples, RAM borderline: free memory fell to 18-36% and swap was used). Closest: memory extraction and quarantined extraction on Gemma 4 E4B. Planner, query rewrite, labels, receipts and document Q&A have no eval tasks yet.
- Qwen once invented weather data instead of calling the tool. Gemma's chat template puts tools after the changing system text, so every turn re-processes the whole prompt (memory eval 20 min vs 6 for Qwen).
- Ollama and `gemma3:4b` on this Mac belong to another project; none of the reported runs overlapped Ollama's loaded model.

Need Sachin's OK for a download or a decision first:
- Backup encryption (deferred by Sachin; location decided: local).
- Signed Mac `.app` started by a LaunchAgent (stable macOS permissions).
- Documents overview in Projects & Docs (idea vetted 2026-10-11 from a Google Drive skill Sachin shared): categories, flags (empty, old, very large, unreadable), search and sort over Jarvis's own local document library. Local only (documents are P2): categories from folders, file types and dates, or a local model later; no Google Drive connector. Sachin: add it to the list, build later.
- Dashboard "later" items from the mockups (need a backend endpoint first): global search across files/notes/tasks, CPU/RAM/storage rings, a P2-safe recent-activity feed, file attach/upload.

Blocked by the "no P2 to the cloud" rule until a category is enabled or a local model is ready:
- Screen understanding on request (screenshots are P2).
- Telegram photo/receipt input, OCR of scanned PDFs, magic search across photos/files.
- Meeting/lecture notes (recording, transcript, summary).

## Waiting for Sachin

Parked items. Work that does not depend on them continues.

- **Worker model:** Claude recommends Opus (low) after the comparison (see Phase 3 live results). Default stays opus until Sachin decides.
- **Telegram (Phase 4 live check):** create a bot with @BotFather, run `jarvis telegram set-token`, put your numeric Telegram user ID in `config/local.yaml` (`proactive_file: {telegram: {allowed_user_id: ...}}`) and a default weather place (`proactive_file: {brief: {place: "..."}}`). Then `jarvis telegram test` and `jarvis daemon`.
- **Google (Phase 5 live check):** create a Google Cloud project, enable Calendar and Gmail APIs, create an OAuth "Desktop app" client, set the app to "In production" (Testing tokens expire in 7 days), put the client JSON path in `config/local.yaml` (`connectors_file: {google: {client_secret_file: ...}}`), `pip install -e ".[google]"`, run `jarvis google auth`.
- **Confirm tiers:** `parse_time` set to T0 (pure local computation); EventKit tools kept at T2.
- **Voice (Phase 6 live check):** models and packages are installed. Restart `jarvis app`, allow Chrome microphone access in macOS settings, say one English and one Marathi sentence and check the text; run `jarvis say --lang mr "..."` and rate the Marathi voice.
- **Voice:** Marathi cloud voice (edge-tts) stays off unless Sachin turns it on. Wake word "hey jarvis" is downloaded but off: turn it on in `config/local.yaml` if wanted.
- **Marathi voice (2026-10-11):** Sachin dislikes the MMS-TTS voice. Samples made in `data/voice/samples/` (MMS, Microsoft Aarohi/Manohar, SYSPIN female/male, macOS Lekha). He chose the ElevenLabs library voice "Bunty" but does not want the ElevenLabs API; Claude will not copy that voice without the voice artist's permission. Plan: IndicF5 (AI4Bharat, MIT, 1.4 GB, local, copies a voice from a short clip) with Sachin's own voice. Waiting for: (1) OK to install IndicF5's code from GitHub into a separate test venv (the install was blocked pending his OK); (2) accept the terms at huggingface.co/ai4bharat/IndicF5 and run `hf auth login`; (3) his recordings of the given Marathi (and optional Hindi) passage. If the Bunty artist gives written permission and a clean recording, the same engine can use it.
- **Stage B decisions:** (1) pass thresholds per route; (2) keep a ~7 GB model loaded all the time or load on demand (~5 s); (3) a round 2 for Gemma 4 E4B with a bigger Marathi-heavy extraction/quarantine set after moving the stable prompt part first; (4) keep, delete or try Qwen once on MLX (5.7 GB on disk).
- **Browser (Phase 8):** `jarvis browser setup` downloads Playwright Chromium (~150–200 MB) per machine; this laptop already has a cached copy.
- **Phase 9 X-ray, live parts (2026-10-17):** the offline code (kit, clean browser, capture, teardown note, voice routes, `jarvis xray`, `jarvis preflight`) is being built with fakes. Before a real teardown runs: (1) OK to install REA pinned 6.5.0 under `~/.jarvis-tools/rea` with npm (`jarvis xray setup` asks); (2) use the installed Google Chrome with a fresh profile per job; (3) on the Mac, allow Jarvis → Chrome Automation for "this site"; (4) galaxy viewer skipped; (5) teardown notes live in `workspace/teardowns` as project `teardowns`.
- **Dashboard design (2026-10-17, Sachin's rule):** Sachin rejected the current look (old tab bar and the sidebar redesign alike). No new UI is built until he generates images from `reports/Dashboard design prompts.md`, picks one and says "final". Frontend work is on hold (the Office tab TSX from step 2 will be redone to the chosen design); backend APIs keep moving.
- **Dashboard rebuild on this laptop (2026-10-17):** `dashboard/out/` here is the old design and lacks the Archive labels; run `cd dashboard; npm ci; npm run build` (one-time download of node packages) when you are OK with it.
- **Dashboard (Phase 7):** on this laptop the built frontend is already in `dashboard/out/` (copied from the agent's build). On another machine: `cd dashboard; npm install; npm run build` (one-time download).
- **Mac checks:** Rishi voice (`say -v '?'`), Whisper speed on the M4, microphone permission, EventKit (`pyobjc-framework-EventKit`, Reminders permission), browser profiles permissions, everything once on the Mac.

## Next step

On a new machine first: `git clone`, run `scripts/setup.ps1` (Windows) or `scripts/setup.sh` (Mac), log in to Claude Code with the subscription (`claude`), `jarvis secret set tavily_api_key`, then `cd dashboard; npm install; npm run build`, then `jarvis health`. Personal data (memory, projects, data) does not travel with the repo.

1. **Done 2026-10-10 (Mac):** finished and merged `wip/india-features` (see session log). Was: India tools need registering in `jarvis/tools/catalog.py` (`india_tools`), brief sections via `register_india_sections()` from `jarvis/proactive/integration.py`, CLI `cli_india` in the module tuple of `jarvis/cli.py`; whole suite green; merge.
2. **Done 2026-10-10 (Mac):** finished and merged `wip/verify-repeat` (verify-after-act with claims vs evidence; `/repeat` in chat, Telegram and `jarvis task repeat`). Was: verify-after-act checks for Operator/Coder/browser and receipt "claims vs evidence"; `/repeat <when>` and `jarvis task repeat` (skill + schedule saved only after confirmation); merge.
3. **Done 2026-10-10 (Mac):** global daily cap + runaway guard, nightly review (episode file + memory conflicts in the brief) merged. Backups merged: `jarvis backup create|list|restore-check` (destination `~/JarvisBackups` by default; open decision #10).
4. **Done 2026-10-10 (Mac):** dashboard triggers adapter and Event triggers panel, India tab, why-panel recording for every chat (CLI, Telegram) with `GET /api/sessions/{id}/turns` and `/why`, sensitive-topic enforcement in code.
5. **Done 2026-10-10 (Mac):** laptop compare rerun on Fable: FAILED on "check yourself" links (see Final testing). Search links left out by Sachin for now. Small fixes that need no decision: keep prices out of the dropped-candidates table, find why the checker saw a cut-off report. Was: final testing on Claude Fable (`JARVIS_TEST_MODEL=claude-fable-5-1`): live suites, eval + memory eval (`jarvis eval --suite memory --live`), injection live set, laptop compare with price tiers; record results here.
6. **Sachin:** the "Waiting for Sachin" list; hands-on testing with TESTING.md (section 9: the app).
7. **Done 2026-10-11:** Stage B merged and recorded (see Stage B results). Grader fixes merged (real temperature check, Devanagari greeting check, बानेर spelling, tm-1 history, "kadhi" is not a past word); re-graded: migration Claude 12, Qwen 10, Gemma 10; memory Claude 29, Qwen 24, Gemma 26. Still open: Sachin's Stage B decisions.
8. **Done 2026-10-11:** dashboard redesign merged (sidebar, top bar with the true mode "Claude · local off", Command Center with voice stage, chat bubbles, auto-send voice, hands-free listening, kanban board, light/dark/system themes). The built frontend was copied to `dashboard/out` on this Mac; other machines run `npm ci && npm run build` in `dashboard/`. Next: Sachin tries hands-free in Chrome (the in-app browser pane blocks the microphone).
9. **Parked by Sachin:** laptop report small fixes (prices out of the dropped-candidates table; why the checker saw a cut-off report).
10. **Parked by Sachin (voice change):** IndicF5 voice engine with a reference clip folder (`data/voice/reference/`), speed measured on the M4, then Sachin's own voice as the Marathi voice.

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
| 2026-10-10 | Smart home control (skill #24) is not wanted: dropped from the plan |
| 2026-10-10 | #19 decided: email sender/subject and Apple Notes titles stay P2 (not sent to the cloud model) for now |
| 2026-10-10 | #10 decided: backups stay local (`~/JarvisBackups`, never inside the repo) and must be encrypted |
| 2026-10-10 | Backup encryption work deferred by Sachin ("backup apan nantar baguya"); backups stay as they are (local, not encrypted) until he picks it up |
| 2026-10-10 | No adding UPI payees from the app; payees stay terminal-only |
| 2026-10-10 | Downloads approved: English Whisper model, Marathi speech models (STT/TTS), wake word, and Stage B local AI (runtime + models). Stage B measures only; live routing changes need Sachin's OK |
| 2026-10-11 | Amazon/Flipkart search links as "check yourself" links in price reports: leave it for now |
| 2026-10-11 | Marathi voice: no ElevenLabs API. Wants a "Bunty"-like voice; will use his own recorded voice with a local voice-copy model |
| 2026-10-11 | Voice change parked ("bar avaj rahu de"); design first |
| 2026-10-11 | Dashboard design follows his mockups (navy HUD, sidebar, Command Center with a big mic, live waveform, stop button, current task steps) |
| 2026-10-11 | Documents overview goes on the later list; the Google Drive skill he shared is NOT installed in Claude |
| 2026-10-10 | Vetted the Hermes Agent Masterclass (Jack Roberts, hermes-masterclass.vercel.app). Taken: a global daily cap for unattended work (runaway-loop risk), a nightly review into `memory/episodes/` with memory conflicts in the brief, local dated backups (destination still open decision #10). Already in Jarvis: soul file, markdown memory + FTS, risk tiers/approvals/kill switch, Telegram allow-list, cron/heartbeat/brief, planner-worker-critic, budgets, dashboard. Dropped: VPS/Docker hosting (data leaves the laptop), OpenRouter (new key/cost), WhatsApp (banned for AI assistants), public webhooks (security), the selling/money module, the unproven "CLI uses 100x fewer tokens" claim |

## Decisions made by Claude (for Sachin to review)

| Date | Decision |
|---|---|
| 2026-10-17 | `open_url` and `bill_upi_link` are T3 (were T2): neither has an undo or verify path, so the astra rule (27.4a) treats them as irreversible; they ask every time and take no standing grant |
| 2026-10-17 | Telegram and the dashboard can only archive a schedule or trigger; `delete --forever` exists in the CLI alone, on an archived item, after a y/N question |
| 2026-10-17 | A failed verification withdraws the tool's standing grants in that office; grants made before step 1 have no office and are withdrawn everywhere |
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
| 2026-10-10 | Apple Notes: search/read T0, create T1 (new notes only, in folder "Jarvis"); note text P2; note titles P2 until Sachin decides (same question as email subjects, #19); live check only on request |
| 2026-10-10 | Office files: create_docx/create_xlsx are T1 and create-only; the Writer may use them inside the task folder (sandboxed like write_file); formulas only from a short allowlist (no HYPERLINK, WEBSERVICE, INDIRECT, external links); openpyxl added as a dependency. Files made by openpyxl have no cached formula results, so analyze_table reads formula cells as blank until the file is saved in Excel |
| 2026-10-10 | Missed-run alerts: one grouped notice; heartbeat and memory extraction stay quiet (`schedules.alert_missed`, `missed_alert_quiet_kinds`) |
| 2026-10-10 | Dashboard: an email trigger's sender is hidden even on the local draft screen (question for Sachin: show it there?) |
| 2026-10-11 | Marathi speech-to-text: AI4Bharat IndicConformer (MIT) from OpenVoiceOS's ungated ONNX int8 copy (the official repo needs a Hugging Face login), run with `onnx-asr` (4 MB, MIT, new in the `[voice]` extra). Auto mode: English stays with Whisper, anything else goes to Marathi (Whisper labelled 6 of 18 Marathi clips as Hindi/Sinhala/Bengali). Measured on 18 FLEURS clips: WER 23.1%, CER 7.6% |
| 2026-10-11 | Offline Marathi voice: Meta MMS-TTS Marathi (CC-BY-NC, personal use only) as a third-party ONNX export; checked against the official weights (99.6% of the tensors used for speaking match exactly; the rest are training-only parts). Marathi text uses it first, then the cloud voice if enabled, then the system voice. Indic Parler-TTS skipped (0.9B + torch) |
| 2026-10-11 | Wake word threshold 0.25 on this Mac (`config/local.yaml`): Sachin's "Hey Jarvis" scored 0.20-0.47, silence 0.00 |
| 2026-10-11 | Speech language routing: when Whisper names a language other than English or a sure Marathi, compare only Whisper's English and Marathi probabilities (transcript confidences cannot be compared: IndicConformer writes English in Devanagari with high confidence) |
| 2026-10-11 | Dashboard: the display name is kept in the browser only (never in the repo or on the server); the mode pill says the truth ("Claude · local off"); hands-free pauses while Jarvis thinks, speaks (estimated from reply length) or an approval waits; voice never approves and never sends "/" commands |
| 2026-10-11 | Voice model downloads are pinned to a commit and checked by SHA-256; Hugging Face xet transfer turned off for them (`HF_HUB_DISABLE_XET`) because it stalled on this Mac |

## Open decisions

See "Open decisions" in PLAN.md. Most important:
- 5 things Jarvis should do every day
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
| 2026-10-11 | Home MacBook M4 | Voice v2 (see above), core memory USER.md + MEMORY.md, the Mac app, menu regrouped, test isolation from local.yaml. 1518 passed. Hermes Agent memory vetted: core memory taken; vector index still deferred |
| 2026-10-11 | Home MacBook M4 | Merged grader fixes, voice status (dashboard Setup tab, API, CLI), accented-English routing fix, dashboard redesign. Wake word tuned for Sachin's voice. Vetted a Google Drive skill (not installed; documents overview added to the later list). 1494 passed |
| 2026-10-11 | Home MacBook M4 | Merged Stage B (local adapter not approved, eval runner, measured profiles, report). 1461 passed. Marathi voice samples made; ElevenLabs engine started then stopped at Sachin's request; IndicF5 with Sachin's own voice planned |
| 2026-10-11 | Home MacBook M4 | Merged voice (Marathi speech-to-text, offline Marathi voice, wake word model). 1420 passed. Tavily key added; laptop compare rerun on Fable failed on check links (fix waiting for Sachin). Sachin tested the dashboard emergency stop (PASS) and downloaded Gemma 4 E4B. Removed unused models and the pip cache to free disk. Stage B agent still running |
| 2026-10-10 | Home MacBook M4 | Small follow-ups: `connectors status --live`, `/repeat` and `/why` in the dashboard chat. 1379 passed |
| 2026-10-10 | Home MacBook M4 | Smart home dropped (Sachin). Built and merged: missed-run alerts; Apple Notes connector (titles P2 by default); dashboard repeat drafts + trigger create/delete (structured confirm result); office files with receipts, previews and Writer prompt. 1375 passed |
| 2026-10-10 | Home MacBook M4 | Merged dashboard India tab + event triggers (fixed a pending-approvals table race, added `GET /api/sessions/{id}/turns`, docs). Added `/why`. Fable final tests on the Mac (see Final testing). Fixed macOS TLS certificates and the memory-eval grader. 1230 passed |
| 2026-10-10 | Home MacBook M4 | Merged why-panel recording for every chat and sensitive enforcement; fixed two privacy gaps found by the agent (Devanagari-digit P3, sensitive memories in the extractor's decide step). 1186 passed |
| 2026-10-10 | Home MacBook M4 | Merged backups and verify-after-act + repeat-this (made the Telegram `/repeat` draft P2-safe, added `jarvis task draft`). 1100 passed |
| 2026-10-10 | Home MacBook M4 | Sachin updated Claude Code to 2.1.296. Live greeting through the subscription CLI: PASS on the Mac |
| 2026-10-10 | Home MacBook M4 | Merged `wip/india-features` (wired tools, brief sections, CLI; brief shows bills/wallet as counts unless `india.brief.details`; offline tests now block all non-loopback network). Merged daily cap + runaway guard (`proactive unattended`), nightly review (`review` schedule kind, `memory/episodes/`), memory conflicts (`jarvis memory conflicts`, brief count). 970 passed. Agents running on `wip/verify-repeat`, `feature/backup`, `feature/dashboard-india` (India tab, triggers in dashboard), `feature/small-hooks` (why-panel for CLI/Telegram, sensitive-topic enforcement) |
| 2026-10-10 | Home MacBook M4 | Pulled office work. `scripts/setup.sh` OK. Offline suite on macOS: 899/902, then 902 passed after fixes: Windows-style paths (`C:/...`, UNC) now refused on Mac/Linux in `PathPolicy` and grant rules (POSIX had treated them as names inside the workspace), shortcut path parsed as a Windows path. `jarvis health`: claude_code OK (Max); Claude Code CLI 2.1.260 too old for `--system-prompt-file` |
| 2026-10-17 | Office laptop (Windows) | Step 2 backend built by three agents (Narada requests, file truth + pralaya + task archive, Office page API) and merged; Narada wired into the orchestrator. Sachin rejected the dashboard look: design prompts written (`reports/Dashboard design prompts.md`), UI on hold until he picks one. 1664 passed, 25 skipped (Windows, 2026-10-17) |
| 2026-10-17 | Office laptop (Windows) | Step 0 merged. Step 1 built: lead (archive everywhere, owner tags, receipts into memory, wiring), agent A (adhipati, dharma routing, shruti, karma-yoga), agent B (Kubera budgets, fences, astra). Merged on `main`. 1628 passed, 25 skipped (Windows, 2026-10-17) |
| 2026-10-10 | Office laptop (Windows) | Built Phase 3 (tasks, team, receipts, projects, teach-by-demo). Five parallel agents built Phases 4–8; all merged and wired in. 494 offline tests pass. First live laptop compare failed verification; quality fixes made; rerun started |
