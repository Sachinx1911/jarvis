# Jarvis — Master Plan (v3.2)

**Date:** 2026-10-09 (updated 2026-10-10)
**Status:** Planning is nearly complete. No code has been written yet.
**What this file is:** All research, analysis and planning done so far, in one place.
**v3.1 (2026-10-10):** Added teach-by-demonstration, task queue, connector registry, schedules, model routing, task receipts, project workspace and isolated browser profiles. Kept the useful part of each and dropped the excessive or risky parts.
**v3.2 (2026-10-10):** Files are written in English. Conversations with Sachin happen in Marathi.

---

## 0. Summary

Jarvis is a personal AI assistant that runs on Sachin's Mac.
It **learns** from him, **remembers** what it learns, **does real work**, **checks that the work actually got done**,
**speaks up on its own** when something matters, and hands big jobs to a **team of agents**.

Voice and the dashboard are only interfaces. The real Jarvis is memory + tools + safety + proactivity + team.

---

## 1. Sources of information

| # | Source | What it gave us | Decision |
|---|---|---|---|
| 1 | Online research (GitHub Jarvis projects, 2026 trends) | Wake word, Whisper, tool calling, memory and local LLMs are common | Took the basic features |
| 2 | YouTube video: Jack Roberts, "Agentic OS" | Memory core, profile interview, save anything, daily brief | Took ideas only, not his kit |
| 3 | Blueprint 1 (JARVIS_Advanced_AI_Assistant_Blueprint.docx) | Verifier, approvals, audit, emergency stop | Took the good parts, dropped the over-engineering |
| 4 | Master Blueprint (Advanced_JARVIS_AI_Assistant_Master_Blueprint.docx) | T0–T4 risk tiers, task state machine, Claude Code rules, "top 5 workflows" | Took the good parts |
| 5 | Check of Sachin's Mac | M4, 16 GB, macOS 26, Python 3.13 | Cloud-first, lightweight stack |
| 6 | 5 research agents | Memory, brain loop, connectors, Marathi search, Mac safety | All rules folded in below |
| 7 | OpenClaw and Hermes Agent | Skill system, heartbeat, session search | Added new skills |
| 8 | Multi-agent research (Anthropic, MAST paper) | When a team helps and when it hurts | Agent team design |

---

## 2. Analysis

### 2.1 YouTube video (Jack Roberts, "Agentic OS")

- **What it is:** A local web dashboard + LLM + memory + integrations. Looks good, but it is not an "OS".
- **Ideas taken:** Memory core, profile interview, save anything, goals + daily brief, model picker, calendar events by voice, magic search, memory graph view.
- **Skipped:** Higgsfield image/video, website design system, Skool/finance dashboard, Zapier.
- **Note:** The starter kit link returned 404 and the community is paid. We build our own.

### 2.2 Blueprint 1

**Good (taken):** Task lifecycle, verifier, approvals, audit log, emergency stop, memory metadata, hybrid search, prompt-injection defense, backup.

**Problems:**
- Voice is in Phase 2 and memory in Phase 3, yet its own final recommendation says memory first. That is a contradiction.
- Security is in Phase 7 while tools arrive in Phase 4, so three phases run without safety.
- It never says how memories get **saved** (the write path), only how they are retrieved.
- PostgreSQL, Redis, n8n, 15 agents, 12 tabs. Too much for one user.

### 2.3 Master Blueprint

**Improvements over Blueprint 1 (taken):**
- Memory before voice. Push-to-talk first, wake word later.
- Permissions treated as a core feature, not polish.
- Task state machine: RECEIVED, PLANNING, WAITING_APPROVAL, RUNNING, VERIFYING, COMPLETED, FAILED, CANCELLED.
- Five risk tiers, T0–T4.
- Hallucination controls: arithmetic in code, check that files exist, confirm emails were actually sent.
- Rules for Claude Code: one phase, test, report, stop, get permission.
- Decide the "top 5 real workflows" first. **The single most important point.**

**Remaining problems:**
- Still no memory write path. Phase 3 focuses on document search.
- No mention of macOS. It assumes Windows/Linux and Ryzen/NVIDIA hardware.
- Phase 1 is pure infrastructure (API, PostgreSQL, dashboard), so nothing useful appears for a long time.
- PostgreSQL, Redis, users/roles/login, 15 agents, 14 tabs.
- Does not mention that Marathi voice is hard.
- No personality, profile, daily brief, Telegram or MCP.

### 2.4 Facts checked on Sachin's Mac

| Item | Result | Consequence |
|---|---|---|
| Chip / RAM | Apple M4, 16 GB | Cloud-first. Only small local LLMs |
| Free disk | ~32 GB | No large local models |
| macOS | 26.5 (Tahoe) | Newer permission rules apply |
| Python | python.org 3.13.14 | Works, but its SQLite cannot load extensions, so no vector extension; use numpy |
| Already installed | numpy, torch, onnxruntime, mlx, ffmpeg, git, brew, Node 24, Docker, sandbox-exec | Easy setup |
| Ollama | Not installed | Add later if needed |
| Marathi system voice | **None** (only Hindi "Lekha" and en_IN "Rishi/Aman/Tara") | Marathi speech needs edge-tts |

---

## 3. Jarvis's 24 skills

### 15 from the Master Blueprint

| # | Skill | What it does | Phase |
|---|---|---|---|
| 1 | Brain & Reasoning | Understand, reason, plan | 1 |
| 2 | Memory & Learning | Learn, remember, reuse | 1 |
| 3 | Voice & Conversation | Listen, speak, handle interruptions | 6 |
| 4 | Computer Control | Apps, files, post-action checks | 2 |
| 5 | Browser & Research | Web search, sources, forms | 2 |
| 6 | Office & Business | Word, Excel, PDF, reports | 2–3 |
| 7 | Multi-Agent | Split work across a team | 3 |
| 8 | Planning & Automation | Steps, deadlines, recurring work | 3–4 |
| 9 | Coding | Code, tests, debugging | 8 |
| 10 | Vision & Documents | Screenshots, PDFs, tables | 2 |
| 11 | Security & Permissions | Ask, block, log | 2 |
| 12 | System & Cost Monitoring | RAM, CPU, API spend | 0, 4 |
| 13 | Data Analysis | Calculations, charts | 8 |
| 14 | Knowledge & Personalization | Preferences, projects, people | 1 |
| 15 | Evaluation & Quality | Verification, tests | Every phase |

### 9 added by us

| # | Skill | Why | Phase |
|---|---|---|---|
| 16 | Proactive | Speak up unasked, heartbeat | 4 |
| 17 | Personality & Profile | Character, "Sir", profile interview | 1 |
| 18 | Connectors & Phone | Calendar, Gmail, Telegram | 4–5 |
| 19 | Skill system | Learn and add new skills | 1 |
| 20 | Daily info | Weather, news, cricket, traffic | 2 |
| 21 | Media & quick controls | Music, volume, brightness, Do Not Disturb | 2 |
| 22 | Language & translation | Romanized Marathi, Devanagari, translation | 1 |
| 23 | Meeting / lecture notes | Record, transcript, summary | 8 |
| 24 | Smart home | Lights, fan, AC (only if devices exist) | Optional |

**Skills needed for version 1:** #1, #2, #4, #11, #14, #17, #19, #22.

---

## 4. Architecture

```
┌──────────────────────────────────────────────────────────────┐
│ INTERFACES   CLI (P0) · Telegram (P4) · Voice (P6) · Web (P7) │
└─────────────────────────────┬────────────────────────────────┘
┌─────────────────────────────▼────────────────────────────────┐
│ JARVIS (manager)                                             │
│ context builder: personality + profile + memory index        │
│                  + relevant memories + task state + skills   │
│ planner · tool loop · delegate work to agent team            │
└──────┬─────────────┬─────────────┬─────────────┬─────────────┘
┌──────▼─────┐ ┌─────▼──────┐ ┌────▼───────┐ ┌───▼──────────┐
│ MEMORY     │ │ TOOLS +    │ │ CONTROL    │ │ PROACTIVE    │
│ md files   │ │ SKILLS     │ │ T0–T4      │ │ heartbeat    │
│ SQLite idx │ │ typed tools│ │ approvals  │ │ daily brief  │
│ extractor  │ │ SKILL.md   │ │ audit log  │ │ reminders    │
│ hybrid     │ │ verifier   │ │ kill switch│ │ goals        │
│ search     │ │            │ │ budget     │ │              │
└────────────┘ └─────┬──────┘ └────────────┘ └──────────────┘
       ┌─────────────▼───────────────────────────────────┐
       │ AGENT TEAM: Researcher · Writer · Checker        │
       │             (later) Coder · Operator             │
       └─────────────┬───────────────────────────────────┘
       ┌─────────────▼───────────────────────────────────┐
       │ CONNECTORS: Telegram · Web search · Calendar ·   │
       │             Gmail · Reminders · Notes            │
       └─────────────────────────────────────────────────┘
```

### Task lifecycle

1. Receive the message and work out the intent.
2. Pull relevant memories, skills and task state.
3. For big jobs, make a plan: steps + what "done" means (acceptance criteria).
4. Decide: do it alone, or use the team.
5. Check the risk tier of every tool call. Ask when required.
6. Execute and log every step.
7. **Verify**: exit code, file exists, event created. Limited retries on failure.
8. Report the result: Success, Partial or Failed.
9. Save what was learned to memory. After a successful big job, propose a skill.

### Task states

BACKLOG → PLANNED → RUNNING → WAITING_APPROVAL → VERIFYING → COMPLETED / FAILED / CANCELLED

Plus SCHEDULED and PAUSED. Details in the "Task system" section.

---

## 5. Memory design (the core)

### 5.1 Layout

**Source of truth = markdown files.** Sachin can read, edit and delete them. Keep the folder in git, but in a **separate private repo**. The code repo is public and never contains memory.
**SQLite = index.** Keyword search (FTS5), vectors (numpy BLOBs), tasks, audit. One file, no server.

```
memory/
├── MEMORY.md          index, always in the prompt (under 200 lines)
├── facts/             what is true
├── preferences/       how Sachin wants things
├── procedures/        how to do things (later become skills)
├── constraints.md     "never do X", health, hard rules. ALWAYS in the prompt
└── episodes/          what happened each day (YYYY-MM-DD.md)
profile/
├── SOUL.md            Jarvis's character
├── life.md · work.md · goals.md
skills/                learned skills (SKILL.md folders)
projects/<name>/       project workspace: PROJECT.md, docs/, notes/, outputs/
connectors/
└── registry.yaml      connectors, tools, permissions, health
data/
├── jarvis.db          SQLite: index, tasks, schedules, model_usage
├── tasks/<id>/        task workspace and receipt.md
├── sessions/          past conversations (searchable)
├── browser/<site>/    isolated browser profiles for approved sites (Phase 8)
└── audit.jsonl        log (chmod 600)
```

**In the code repo:** code, PLAN.md, PROGRESS.md, CLAUDE.md, examples.
**Never in the code repo:** `memory/`, `profile/`, `projects/`, `skills/` (learned), `data/`, `connectors/registry.yaml`, `.env`. All of these are in `.gitignore`.

### 5.2 One memory file

```markdown
---
id: m-0042
name: college-project-run
type: procedure            # fact | preference | procedure | constraint | episode
status: active             # active | superseded | archived
subject: college-project   # who or what this memory is about
description: How to run the college project
when_to_use: when Sachin says "college project chalav" / "run the college project"
summary_en: How to run the college project (make run in ~/Projects/college)
keywords: college project run start make chalav
evidence: "maza college project ~/Projects/college madhe ahe, make run ne chalto" (session s-17)
source: user-said          # user-said | inferred | imported
confidence: high           # inferred memories stay at or below 0.6
sensitivity: normal
valid_from: 2026-10-09
valid_until:
superseded_by:
last_used:
use_count: 0
expires:                   # for short-lived facts
---
Folder: ~/Projects/college
Command: make run
```

### 5.3 Write path (how memories get saved)

**Risks found in research:**

| Problem | Figure |
|---|---|
| Junk memories in a 32-day audit of one memory system | 97.8% of 10,134 |
| Junk even with a strong extractor model | 89.6% |
| A recalled memory re-saved as new (feedback loop) | Same fact saved 808 times |
| Remembered preferences that were still not applied | ~35% |

**So our rules are:**
1. **Default to "save nothing".** The extractor prompt includes negative examples.
2. **The extractor sees only Sachin's messages.** Strip the system prompt and injected memories. Use Jarvis's own text only if Sachin confirmed it.
3. **Every memory needs a quote of Sachin's own words.** No quote means REJECT.
4. **Two steps:** First extract candidates. Then fetch the 10 most similar memories and let the LLM choose ADD, UPDATE, SUPERSEDE, NOOP or REJECT.
5. **Conflicts only on the same subject.** Old memories are marked "superseded", never deleted.
6. **Similarity thresholds** (starting guesses, tune with tests): above 0.97 = duplicate. 0.85–0.97 = LLM merges.
7. **Inferred memories** become firm only after two sightings or Sachin's OK.
8. **When:** 10–30 minutes after the session goes quiet. "Remember this" saves immediately.
9. **On save** the LLM adds an English summary and keywords. This is the biggest win for romanized Marathi search.
10. **Never saved:** passwords, API keys, card numbers (regex filter). Content from emails or web pages is never saved automatically.

### 5.4 Read path (how memories get used)

1. MEMORY.md and constraints.md are always in the prompt.
2. Rewrite Sachin's message into English keywords (query rewrite).
3. Search three ways:
   - FTS5 unicode61: whole words, including Devanagari
   - FTS5 trigram: misspellings (karaycha / karaicha)
   - Vector similarity
4. Merge the three lists with reciprocal rank fusion: score = sum of 1/(60 + rank).
5. Only "active" memories. A minimum score gate returns 0 to 5 memories, not always 5.
6. Small recency boost for newer memories.
7. If nothing is found, **search past conversations** (session search, as in Hermes).

### 5.5 Search facts checked

| Item | Result |
|---|---|
| Hinglish search with e5-small embeddings | Fell from 0.61 (English) to 0.16 (Hinglish) |
| Hinglish search with plain keywords (BM25) | 0.29, better than embeddings |
| numpy search over 3,000 memories | ~0.05 ms per query |
| Ready-made benchmark for romanized Marathi | None exists |

**Embedding model:** start with multilingual-e5-small (small, MIT). Compare against granite-97m-multilingual-r2 and e5-large on 30–50 of Sachin's real queries.
**Hosted embeddings:** not needed unless our own test shows a big gap.

### 5.6 Other memory features

- **Save anything:** forward a link or file on Telegram and it goes to memory.
- **Curiosity:** when Jarvis sees something unknown, it asks. "You get many emails from this company. Is it your workplace?"
- **Weekly cleanup:** merge duplicates, turn relative dates ("tomorrow") into absolute dates, archive memories unused for 90 days, keep MEMORY.md under 200 lines.
- **Memory commands:** list, search, edit, delete, export.
- **Learning ≠ training:** the model never changes. Its diary grows.

---

## 6. Project workspace and document library

All information about one project lives in one place, so every agent gets the same approved context.

```
projects/<project-name>/
├── PROJECT.md      goal, status, people, links, project rules
├── docs/           documents Sachin approved (PDF, DOCX, MD)
├── notes/          project notes
└── outputs/        finished reports and files
```

- **Memory link:** memories carry `scope: project:<name>`. While a project is active, memories in that scope are searched first.
- **Document library:** documents in `docs/` are split into chunks and indexed in SQLite. Each chunk keeps its file name, page and date. Jarvis cites the source in answers.
- **Approved documents only:** only what Sachin puts in `docs/` or explicitly adds. Email attachments are never added automatically.
- **Context pack for agents:** when a task starts, Jarvis gives agents PROJECT.md, relevant chunks and scoped memories, read-only.
- **Write rule:** agents write only to their task folder. After checking, Jarvis moves final output to `outputs/`.
- **Not included:** graph database and multi-user access control. Not needed for one user.
- **Phase:** PROJECT.md and scoping in Phase 3. Document indexing in Phase 5. OCR for scanned PDFs in Phase 8.

---

## 7. Skill system

- Each skill = a folder + `SKILL.md` (name, description, instructions, scripts).
- This is Anthropic's open standard (December 2025). By September 2026 more than 40 tools support it.
- Only skill names and descriptions sit in the prompt. The full skill loads when needed.
- **Jarvis learns new skills:** after a big job succeeds, Jarvis proposes a skill. **It is saved only after Sachin approves.**
- **Why approval:** research shows agents can turn failed attempts into bad skills. Model-written skills add little; human-reviewed skills work much better.
- Review any third-party skill before installing it. It can contain dangerous code.

### Teach-by-demonstration

Sachin does a task once. Jarvis captures the steps and turns them into an editable skill.

**What gets recorded** (between "start recording" and "stop recording"):

| Source | How | Phase |
|---|---|---|
| Work done together with Jarvis | The conversation and every tool call are already logged. Most reliable | 3 |
| Terminal commands | Terminal session log in record mode (`script` command) | 3 |
| File changes | Before/after snapshot of allowed folders | 3 |
| Sachin's explanation | Chat or Telegram voice note: "why this step" | 3 |
| Key screenshots | Only when Sachin asks, never continuous | 3 |
| Browser steps | Playwright codegen in an isolated browser profile | 8 |

**After recording:**
1. Jarvis drafts a `SKILL.md`: steps, inputs (e.g. date, file name), preconditions, the risk tier of each step, and how to verify the result.
2. Shows Sachin the draft for edits.
3. **Dry run** on test input. Steps at T2 or above ask every time.
4. After approval, saved as version 1.
5. Reused next time. If Sachin corrects something, Jarvis proposes an update and keeps the old version.

**Not included:** continuous mouse and keyboard recording. It needs Input Monitoring and Accessibility permissions, which is keylogger-level access. pynput crashes on macOS 26. Coordinate-based replay breaks whenever the UI changes. We use steps based on commands, APIs and the browser DOM instead.

---

## 8. Agent team

### 8.1 Team

| Agent | Job | Permissions |
|---|---|---|
| Jarvis (manager) | Plan, delegate, merge results | Only Jarvis asks Sachin for approval |
| Researcher | Web search, sources | Read-only |
| Writer | Reports, documents, drafts | Approved folders only |
| Checker | Verify the work was really done | Read-only, can reject results |
| Coder (later) | Code, tests | Separate folder |
| Operator (later) | Apps, files, browser | Per safety tiers |

All agents use Claude models; each agent's model is set by "Model routing". Instructions, tools and skills differ per agent.

### 8.2 Flow (example: "laptop under ₹80,000, compare 3 options")

1. Understand; ask 1–2 questions if needed.
2. Plan: 3 researchers + writer + checker. Show the estimated cost.
3. Each agent gets a work order: objective, tools, output format, budget, stop condition.
4. The 3 researchers run in parallel.
5. The Checker verifies sources and prices.
6. Jarvis builds the report and sends it on Telegram.
7. On success, propose a skill.

### 8.3 Research figures

| Fact | Figure |
|---|---|
| Team vs single agent (Anthropic internal eval) | 90.2% better |
| Single agent tokens vs chat | 4× |
| Team tokens vs chat | 15× |
| Team failures: unclear specification | 41.8% |
| Team failures: inter-agent misalignment | 36.9% |
| Team failures: weak verification | 21.3% |

### 8.4 Rules

- Jarvis works alone first. The team is only for big, splittable jobs.
- Simple question: 1 agent. Comparison: 2–4. Big research: more.
- Tightly coupled work (one feature's code) does not go to a team.
- Fixed work-order format.
- One owner per file.
- Independent Checker, with deterministic tests wherever possible.
- 3–5 agents at once. Workers cannot spawn agents. Turn and cost limits. Repeated failures stop the task.
- Agents return short summaries, not full transcripts.
- Long jobs run in the background, progress on Telegram, resume after a crash.
- Workers can never send email or make payments.

---

## 9. Task system: queue, receipts and scheduling

### 9.1 Mission / task queue

**States:**

BACKLOG → PLANNED → RUNNING → WAITING_APPROVAL → VERIFYING → COMPLETED / FAILED / CANCELLED

Plus SCHEDULED (time set) and PAUSED (stopped by Sachin, or no model/internet).
VERIFYING is deliberate. No task becomes COMPLETED without verification.

**Shown for every task:**

| Field | Example |
|---|---|
| Owner | Jarvis / Researcher / Writer |
| Project | laptop-purchase |
| Priority, deadline | High, by 6 pm tomorrow |
| Progress | 2 of 3 steps |
| Current / next step | "Checker verifying sources" / "Write report" |
| Pending approval | "Email the report?" |
| Last error | "Website timeout" |
| Retry | 1 / 3 |
| Cost | $0.14 of $0.60 budget |
| Receipt | data/tasks/t-031/receipt.md |

**Where it shows:**
- Phase 3: `jarvis tasks` in the terminal.
- Phase 4: Telegram `/tasks`, `/task <id>`, `/pause`, `/cancel`.
- Phase 7: dashboard board.

**Queue rules:**
- "Do this later" puts a task in BACKLOG.
- At first, at most 2 big tasks run at once, because of 16 GB RAM and ~1 GiB per Agent SDK session.
- Ordered by priority and deadline.
- After a crash, RUNNING tasks resume from their last checkpoint.

### 9.2 Task receipt

A readable receipt for every finished task.

- **Facts come from logs, not from the LLM.** The receipt is built from task events and the audit log, so it cannot invent anything. The LLM writes only a two-line summary.
- **Contents:** goal, plan, which agent did what with which tool, files changed (path and diff), what was verified and pass/fail, approvals and Sachin's answers, models used (including any fallback), cost, duration, final status, what is left.
- **Where:** `data/tasks/<id>/receipt.md`. Short version on Telegram. `jarvis receipt <id>` in the terminal.
- **The audit log is for machines. The receipt is for Sachin.**

```
COMPLETED · t-031 · Laptop compare · 14 min · $0.14
Plan: 3 researchers, writer, checker
- Researcher x3: read 14 sources (web_search, web_fetch)
- Writer: created projects/laptop/outputs/compare.md
- Checker: prices 3/3 match, links 14/14 work  [PASS]
Approvals: none (all T0/T1)
Models: opus-5-5 (Jarvis), workers (per routing)
Remaining: nothing
```

### 9.3 Skill and agent scheduling

Not just the heartbeat and daily brief. Any skill or agent can be scheduled.

Examples:
- Every night at 9: "today's work report" skill.
- Every Monday at 9 am: project summary (Writer agent).
- Every evening at 6: check the follow-up list.

**Each schedule has:**

| Field | Meaning |
|---|---|
| What to run | Skill, agent, or prompt + input |
| When | Cron, timezone Asia/Kolkata |
| Output | Telegram, file, or both |
| Budget | Limit per run |
| Permission | Unattended runs may only do T0/T1. Anything T2+ waits in the approval queue |
| Missed run | If the Mac was asleep, run once on wake, or skip if past the grace window |
| Overlap | Do not start if the previous run is still going |
| Status | Enabled/paused, last run, receipt |

- **Created from chat:** "Give me a project summary every Monday at 9" → Jarvis shows the parsed schedule and saves it only after Sachin confirms.
- **Commands:** list, pause, resume, run-now, delete.
- **Tech:** APScheduler (`misfire_grace_time`, `coalesce`, `max_instances=1`). Schedules stored in SQLite.
- **Limit:** schedules do not run while the Mac is off or asleep. For jobs that must run anyway, consider a cloud option later (Claude Managed Agents scheduled deployments).

---

## 10. Safety

### 10.1 Risk tiers

| Tier | Actions | Policy |
|---|---|---|
| T0 Read-only | Search, summarize, read files | Run immediately |
| T1 Local write | New file/draft in an approved folder | Run, then verify |
| T2 Significant change | Overwrite files, bulk edits, settings | Ask first |
| T3 External / irreversible | Send email, post, pay, delete | Always ask, show full details |
| T4 Prohibited | Security bypass, passwords, rm -rf | Never; log the attempt |

### 10.2 Practical rules on macOS (from research)

- No raw shell; use **typed tools** (open_app, read_file). If a shell tool exists: `shlex.split`, `shell=False`, allowlist, confirm everything else.
- **Path checks:** `Path.resolve()` against allowed folders. Block `~/.ssh`, `~/.aws`, Keychains, `.env` files and the `security` command.
- **Timeouts:** per-command timeout, kill the process group, cap output, minimal environment.
- **Secrets:** in the Keychain (`keyring`). Strip tokens from logs.
- **Prompt injection:**
  - Email and web text is data, not instructions.
  - **Taint flag:** once a session has read email or web content, only read-only tools run without asking.
  - **Quarantined LLM:** a separate call with no tools extracts JSON fields from untrusted content; the main model sees only those fields.
  - Never auto-open links or images found in content.
  - Approval prompts show the exact arguments.
- **Emergency stop:** checked before every tool call. Triggers: a flag file, Telegram `/stop` (handled outside the LLM loop), a menu bar button.
- **Audit log:** append-only JSONL with time, source, tool, arguments, decision, exit code, output hash.
- **Every task** has a step limit and a cost limit.

### 10.3 macOS permissions

- **v1 runs from Terminal.** Permissions are granted to Terminal. LaunchAgent, Full Disk Access and microphone come later.
- **Screenshots:** `screencapture -x`. Needs Screen Recording permission, which macOS re-asks about monthly.
- **Notifications:** `osascript`.
- **Global hotkey:** pynput crashes on macOS 26. Use a Quartz event tap or Shortcuts/Raycast.
- **Later (v2):** Jarvis inside a signed `.app`, started at login by a LaunchAgent, so permissions stick.

### 10.4 Browser automation: isolated, safe browser

Browser automation arrives in Phase 8, with these rules:

- **Separate from Sachin's Chrome.** Playwright's own Chromium. Never use his Chrome profile, passwords or cookies.
- **Default:** a fresh, empty browser context per task, closed and wiped when the task ends.
- **Sites that need login:** a separate profile per approved site in `data/browser/<site>/`, accessible only to his user. Sachin logs in himself.
- **Domain allowlist:** each task's allowed websites are fixed up front.
- **Downloads:** into the task folder, with file type and size checks.
- **Login, payment, form submit, posting:** always T3. The approval shows the exact form and values.
- **Page text is data, not instructions.** Using the browser sets the taint flag.
- **Screenshots** go into the receipt as evidence.
- **APIs first.** If an API or plain web fetch works, don't use the browser.

---

## 11. Proactive

- **Heartbeat:** every 30 minutes Jarvis reads a `HEARTBEAT.md` checklist and checks whether anything is worth telling Sachin (OpenClaw's design).
- **Daily brief:** each morning: calendar, reminders, goals, weather, important emails.
- **Reminders and goals:** weekly and monthly tracking from goals.md.
- **When to speak:** only when it matters. Quiet hours respected.

---

## 12. Connectors

| Order | Connector | How | Effort |
|---|---|---|---|
| 1 | Telegram | python-telegram-bot, long-polling (no server), only Sachin's user ID allowed, Approve/Deny buttons | Low |
| 2 | Web search | Anthropic web search tool. Free backup: Tavily | Low |
| 3 | Reminders + reading Calendar | EventKit (pyobjc), one-time permission from Terminal | Low–Medium |
| 4 | Google Calendar + Gmail | Direct Google API, OAuth "Desktop app" | Medium |
| 5 | Gmail send | `gmail.send`, always after approval | Low |
| 6 | Voice notes | Telegram OGG in/out | Medium |
| 7 | Apple Notes | AppleScript or MCP | Medium |
| 8 | WhatsApp | **Skip** | — |

**Key facts:**
- If the Google OAuth app stays in "Testing", refresh tokens expire after 7 days. Set it to "In production" (personal use needs no verification, only a warning screen).
- Google's official Gmail/Calendar MCP servers are still in Developer Preview. The Gmail MCP can only draft.
- Sending email via Mail.app AppleScript is unreliable on macOS 26.
- **WhatsApp:** since 15 Jan 2026 Meta bans general-purpose AI assistants on the Business API. Unofficial libraries risk a number ban. Hence Telegram.
- Anthropic web search: $10 per 1,000 searches + tokens. Tavily: 1,000 free credits a month.

### Connector and MCP registry

One list of every connector and tool: `connectors/registry.yaml`.

| Field | Example |
|---|---|
| Name, type | google-calendar, direct-api (or mcp-stdio, native) |
| Source and version | Pinned version and origin |
| Auth | Keychain item name (not the secret), scopes |
| Tools | Each tool, its risk tier T0–T4, read or write |
| Who may use it | Jarvis, Researcher, ... |
| Health check | Small test call, last status, token expiry |
| Enabled | Yes / no |

**Rules:**
- A new connector or tool defaults to **T2 and no agent access** until Sachin classifies it.
- Pin MCP server versions and read their source. Treat MCP tool descriptions as untrusted too, since they can hide instructions (tool poisoning).
- `jarvis connectors status` runs all health checks. The heartbeat runs them daily and warns on Telegram before a Google token expires.
- **Phase:** registry for built-in tools in Phase 2. Connectors added in Phases 4–5. Dashboard tab in Phase 7.

---

## 13. Voice

| Part | Choice | Note |
|---|---|---|
| First step | Push-to-talk | Low risk |
| Wake word | openWakeWord "hey_jarvis" | Pre-trained model; license OK for personal use |
| Only Sachin's voice | openWakeWord custom verifier | Less accurate in noise |
| STT English | Whisper | Test which build (faster-whisper / mlx-whisper / whisper.cpp) |
| STT Marathi | IndicConformer / IndicWhisper | Plain Whisper is poor at Marathi. Indic models reach ~10–15% WER on read speech |
| TTS English | macOS `say` "Rishi" | Offline |
| TTS Marathi | edge-tts "mr-IN-ManoharNeural" | Needs internet |
| Barge-in | silero-vad | Interrupt Jarvis while it speaks |

**Incomplete:** the voice research agent was stopped midway. Before Phase 6, re-check that these libraries work on Python 3.13 and which Whisper build is fastest on the Mac.

---

## 14. Brain loop: how to build it

**Research recommendation: Claude Agent SDK (Python).**

**Why:** no need to write our own file, shell, edit, streaming, session and subagent code. Subagents for the agent team are built in.

**How to configure it:**
- `setting_sources=[]` so Sachin's global CLAUDE.md (graphify) does not leak into Jarvis.
- `CLAUDE_CODE_DISABLE_AUTO_MEMORY=1` to turn off the SDK's own memory; we use ours.
- Custom system prompt: personality + memory index.
- Per-turn memories via a `UserPromptSubmit` hook.
- One `PreToolUse` hook = our T0–T4 gate. A `deny` always holds.
- `canUseTool` for confirmations; `defer` when asking over Telegram.
- Classify Bash calls inside `PreToolUse`, because auto-approved calls never reach `canUseTool`.
- Agent team via `AgentDefinition` (prompt, tools, model, turn limit).
- `max_turns`, `max_budget_usd`, and `interrupt()` for the emergency stop.
- `fallback_model` (comma-separated list) and a per-`AgentDefinition` `model` are supported. Verified in the official Python SDK docs.

**Trade-offs:**
- One subprocess per session, ~1 GiB RAM each per the docs. Avoid many concurrent sessions on a 16 GB Mac.
- Cost figures are estimates; keep our own accounting.

**Alternative:** our own loop on the Anthropic SDK. Full control, more code. **Sachin's decision.**

**Prompt caching:** fixed tools and personality first, then the slowly changing memory index, then per-turn memories last. This keeps costs down.

---

## 15. Model routing and fallback

**Core rules:**
- Route by **call type**. Never switch models mid-conversation: prompt caches and thinking blocks are model-specific, and switching raises cost.
- The routing table is deterministic and every decision is logged. No LLM router.
- Anthropic's guidance: before building a multi-model cascade, test the best model at lower effort. It is often enough, and one model means one cache.

**Models (Anthropic docs, list dated 2026-10-06):**

| Model | ID | Input $ / 1M tokens | Output $ / 1M tokens |
|---|---|---|---|
| Opus 5.5 | `claude-opus-5-5` | 4.00 | 20.00 |
| Sonnet 5.5 | `claude-sonnet-5-5` | 2.00 | 10.00 |
| Haiku 5.5 | `claude-haiku-5-5` | 0.10 | 0.50 |

The Haiku price applies to prompts up to 100K tokens.

**Routing table (starting point):**

| Route | Model | Effort | Why |
|---|---|---|---|
| Jarvis main conversation | Opus 5.5 | medium | Default, strong understanding |
| Big plans, team manager | Opus 5.5 | high | Hard reasoning |
| Memory extractor, query rewrite, intent/risk label, heartbeat check, receipt summary | Haiku 5.5 | low | Simple and frequent; Sachin asked for a cheap, fast model here |
| Researcher, Writer | Opus 5.5 low **or** Sonnet 5.5 medium | — | **Sachin's decision.** Test both |
| Checker | No weaker than the workers | high | Verification must not be weak |
| Coder (later) | Opus 5.5 | high | Effort matters for code |
| No internet | Small Ollama model | — | Chat only, no tools |

**Fallback:**
1. 429 or 5xx: automatic retry, honoring `retry-after`.
2. Still failing: the Agent SDK's `fallback_model` (Opus 5.5 → Sonnet 5.5).
3. Refusal: code checks `stop_reason`. Direct API calls to Opus and Sonnet use server-side `fallbacks: "default"`. Haiku has no such option, so our code retries on Sonnet.
4. Everything fails: task goes to PAUSED, retried later, Sachin told on Telegram.
5. **Never silent.** Any fallback is written in the receipt and reported.
6. **Safety does not depend on the model.** T0–T4 rules are identical for every model.

**Budget:**
- `max_budget_usd` per task. It is a client-side estimate, so set the limit with headroom.
- Per-route and monthly caps, warning at 80%.
- `model_usage` table: route, model, tokens, estimated cost, whether a fallback happened.

**Implementation note:** Opus 5.5 cannot disable thinking and rejects `budget_tokens`; control cost with `effort`. Forced `tool_choice` is not supported either.

---

## 16. Tech stack

| Part | Choice | Why |
|---|---|---|
| Language | Python 3.13, project venv | Already installed |
| Brain | Claude API, cloud-first | Local models are weaker on 16 GB |
| Agent loop | Claude Agent SDK (recommended) | Subagents, hooks, sessions built in |
| Models | Opus 5.5 main, Haiku 5.5 for simple calls, workers after testing | See Model routing |
| Fallback | Ollama + small model (optional) | When offline |
| Memory | Markdown + SQLite (FTS5 + numpy vectors) | No server, editable, no extensions |
| Embeddings | multilingual-e5-small | Small, MIT, swap after testing |
| Skills | SKILL.md standard | Open standard |
| Scheduler | APScheduler | Heartbeat, brief, schedules |
| Phone | python-telegram-bot | Long-polling |
| Mac control | pyobjc, osascript, screencapture | Native |
| Secrets | Keychain (keyring) | Safer than .env |
| Voice | openWakeWord, Whisper, say, edge-tts | See Voice |
| Dashboard | FastAPI + Next.js | Node installed |
| Browser automation | Playwright Chromium, isolated profiles | Phase 8 |

**Dropped:** PostgreSQL, pgvector, Redis, n8n, users/roles/login, Zapier, Higgsfield, WhatsApp, 15 separate agents, 14 tabs.
**Why:** one user, one Mac, 16 GB RAM. If needs grow, SQLite can migrate to PostgreSQL.

---

## 17. Phases

| Phase | Work | Done when |
|---|---|---|
| **0. Setup** | venv, config, Keychain, folders, SQLite, audit log, CLI chat | Jarvis replies "Good evening, sir." |
| **1. Brain + Memory** | Agent loop, SOUL.md, profile interview, Marathi understanding, memory write/read, session search, memory commands, skill-system foundation, model-routing foundation (Opus main, Haiku extractor) | Memory test: teach 10 facts; in a new session at least 9 are used correctly. "Act" test passes too |
| **2. Tools + Safety** | Typed tools, T0–T4, approvals, taint flag, kill switch, verifier, audit, daily info, media controls, connector registry (built-in tools) | 10 tasks verified. No T4 action ever runs. Prompt-injection samples fail |
| **3. Tasks + Agent team** | Task queue and states, planner, task folders, receipts, project workspace, teach-by-demonstration (chat, terminal, files), model routing, Researcher/Writer/Checker, budgets, resume | A laptop-compare style job finishes with a report and a correct receipt, within budget. A demonstrated task replays as a skill |
| **4. Telegram + Proactive** | Bot (Sachin only), approve buttons, /stop, /tasks, heartbeat, daily brief, reminders, skill and agent schedules | Morning brief arrives on the phone. Approvals work from the phone. A weekly schedule runs and handles a missed run |
| **5. Connectors** | EventKit, Google Calendar, Gmail (read/draft, send after approval), registry entries and health checks, document library | "Put a call tomorrow at 11" creates a verified event. Answers from project docs cite sources |
| **6. Voice** | Push-to-talk, Whisper, Rishi/Manohar, then hey_jarvis, barge-in, voice verification, Marathi STT test | 5 voice commands work |
| **7. Dashboard** | FastAPI + Next.js: Chat, Memory, Task board & Approvals, Agents, Connectors, Schedules, Settings & Usage | Everything controllable from the browser |
| **8. Extras** | Coder/Operator agents, magic search, meeting notes, Playwright with isolated profiles, browser step recording, OCR, smart home, signed .app | As needed |

---

## 18. Working across laptops and Claude accounts

This project runs for many days. Work stops and resumes, sometimes on this laptop, sometimes on another, sometimes from a different Claude account.

- **The repo is the single source of truth:** https://github.com/Sachinx1911/jarvis. Claude's local memory is tied to one laptop and account and does not travel.
- **Three context files:** PLAN.md (plan), PROGRESS.md (status, half-done work, next step), CLAUDE.md (rules for Claude; Claude Code loads it automatically).
- **Starting a session:** `git pull`, then read PROGRESS.md.
- **Ending a session:** update PROGRESS.md, commit, push. Even if work stops midway, record the half-done work and the exact next step.
- **Secrets:** stored separately in each laptop's Keychain. Never in the repo.
- **Switching Claude accounts:** Jarvis's API key comes from the Anthropic Console and is separate. Changing the Claude Code account does not affect Jarvis.
- **New laptop:** clone, run the setup script (added in Phase 0), put the key in the Keychain, grant macOS permissions again.
- **The repo is public:** code and plan are visible to everyone. Jarvis's memory, profile, projects, logs and learned skills are in `.gitignore`. Back them up to a separate private place.
- **Where the Jarvis app runs:** best on one Mac at a time. Running it on two laptops needs memory sync, via a private git repo or encrypted backup.

---

## 19. Development rules (for Claude Code)

1. Inspect existing files first; don't change code right away.
2. One phase at a time, only after Sachin says "Start Phase X".
3. After each phase: tests, a report of what changed, then stop.
4. Explain the reason before adding a new package.
5. No secrets, tokens or personal data in code.
6. Permissions, approvals, logs and tests are core features, not polish.
7. Never hide a failing test; give the cause and the options.
8. Don't rewrite working code without a reason.

These rules are already in the repo's `CLAUDE.md`.

---

## 20. When version 1 is "done"

- Takes tasks by text and shows task state and history.
- Uses what it was taught in a new session (memory test passes).
- Shows memories and lets Sachin edit or delete them.
- Logs plans, permission decisions and verification results.
- Writes a report into an approved folder and verifies the file.
- Completes one big job through the agent team.
- Produces a readable receipt for every task.
- Replays a demonstrated task as a skill.
- Never performs a T3 action without permission.
- Handles timeouts, failures, cancellation and duplicate requests.
- Reachable on the phone via Telegram, with a morning brief.
- Automated tests pass.

---

## 21. Testing

**Memory eval (most important):**
- 50–100 scenarios: teach, unrelated sessions in between, then probe.
- Measure: what got saved (precision/recall), whether old facts were correctly superseded, whether the right memory lands in the top 5.
- "Act" probes: does Jarvis behave according to a memory without the prompt mentioning it?
- Asked about something never taught, does it say it doesn't know?
- Each week, hand-check 20 random memories and count junk.
- Re-run everything whenever a prompt changes.

**Other:** safety tests (blocked actions, prompt injection, secret leaks), failure tests (timeout, no internet, crash), mixed Marathi-English commands, duplicate actions, model fallback, and missed schedules after the Mac sleeps.

**Metrics:** memory recall, task success, verified completion, safety events, API cost per task, latency.

---

## 22. Cost

- **No** new hardware. The M4 Mac is enough.
- Main cost = Claude API usage. More when the agent team runs (15× tokens).
- Web search: Anthropic tool at $10 per 1,000 searches. Tavily as a free backup.
- Cost limits per task and per month, with warnings.
- Sachin sets the monthly budget.

---

## 23. Open decisions

| # | Question | Recommendation |
|---|---|---|
| 1 | **5 things Jarvis should do for Sachin every day** | Most important. Needed from Sachin |
| 2 | Is there a Claude API key? | Cloud-first |
| 3 | Brain loop | Claude Agent SDK |
| 4 | Voice language | English voice + Marathi text first; Marathi voice later |
| 5 | Connector order | Telegram, web search, Calendar, Gmail |
| 6 | Monthly API budget | Sachin decides |
| 7 | Name | "Jarvis" |
| 8 | OK to skip WhatsApp? | Yes, use Telegram |
| 9 | Worker agent model | Opus 5.5 at low effort vs Sonnet 5.5; test both |
| 10 | Backup and sync of Jarvis's personal data | Separate **private** GitHub repo (e.g. `jarvis-memory`) |
| 11 | Keep the code repo public? | Sachin's choice. Personal data never goes in it either way |

---

## 24. Still to verify

- Voice libraries on Python 3.13 and macOS 26 (research incomplete).
- Whether Google's official MCP works with a personal Gmail account.
- Memory thresholds (0.97 / 0.85) on real data.
- Embedding model on Sachin's real queries.
- How reliable the Shortcuts CLI is on macOS 26.
- Exactly which errors trigger the Agent SDK's `fallback_model`. The docs don't say.
- Whether the Agent SDK can pass server-side refusal `fallbacks` for Opus/Sonnet.

---

## 25. Sources

**Jarvis projects and trends**
- https://github.com/topics/jarvis-ai
- https://github.com/ndunl075/Jarvis
- https://github.com/PanPenek/JarvisAi
- https://github.com/vaibhav07772/jarvis
- https://github.com/llm-guy/jarvis
- https://medium.com/@danieljsmit/iron-man-jarvis-capabilities-3fc263395d9e
- https://www.youtube.com/watch?v=bjDDsdSfun8

**OpenClaw, Hermes, Skills**
- https://en.wikipedia.org/wiki/OpenClaw
- https://www.turingcollege.com/blog/openclaw
- https://github.com/nousresearch/hermes-agent
- https://hermes-agent.nousresearch.com/docs/
- https://arxiv.org/pdf/2608.12851
- https://atlan.com/know/ai-agent/ai-agent-skills/what-are-agent-skills/
- https://www.firecrawl.dev/blog/agent-skills

**Memory**
- https://arxiv.org/html/2504.19413v1
- https://docs.mem0.ai/migration/oss-v2-to-v3
- https://github.com/mem0ai/mem0/issues/4573
- https://github.com/getzep/graphiti/issues/1728
- https://docs.letta.com/v1-sdk/memory/memory-blocks
- https://langchain-ai.github.io/langmem/concepts/conceptual_guide/
- https://platform.claude.com/docs/en/agents-and-tools/tool-use/memory-tool
- https://code.claude.com/docs/en/memory
- https://arxiv.org/abs/2410.10813
- https://christian-schneider.net/blog/persistent-memory-poisoning-in-ai-agents/

**Marathi search and embeddings**
- https://arxiv.org/abs/2505.08411
- https://github.com/tanmay0401/code-mixed-search-benchmark/blob/main/reports/technical_report.md
- https://github.com/PrasadDhend/hinglish-semantic-cache-eval
- https://huggingface.co/intfloat/multilingual-e5-small
- https://huggingface.co/ibm-granite/granite-embedding-97m-multilingual-r2

**Brain loop (Claude Agent SDK)**
- https://code.claude.com/docs/en/agent-sdk/overview
- https://code.claude.com/docs/en/agent-sdk/permissions
- https://code.claude.com/docs/en/agent-sdk/hooks
- https://code.claude.com/docs/en/agent-sdk/subagents
- https://code.claude.com/docs/en/agent-sdk/hosting
- https://platform.claude.com/docs/en/build-with-claude/prompt-caching
- https://code.claude.com/docs/en/agent-sdk/python

**Multi-agent**
- https://claude.com/blog/building-multi-agent-systems-when-and-how-to-use-them
- https://simonwillison.net/2025/Jun/14/multi-agent-research-system/
- https://huggingface.co/papers/2503.13657
- https://addyosmani.com/blog/code-agent-orchestra/

**Connectors**
- https://github.com/taylorwilsdon/google_workspace_mcp
- https://developers.google.com/workspace/guides/configure-mcp-servers
- https://dev.to/ko-hi/googles-oauth-testing-mode-expires-refresh-tokens-in-7-days-publish-the-consent-screen-before-24hm
- https://docs.python-telegram-bot.org/en/stable/telegram.ext.filters.html
- https://respond.io/blog/whatsapp-general-purpose-chatbots-ban
- https://platform.claude.com/docs/en/agents-and-tools/tool-use/web-search-tool
- https://docs.tavily.com/documentation/api-credits

**macOS and safety**
- https://9to5mac.com/2024/08/14/macos-sequoia-screen-recording-prompt-monthly/
- https://github.com/apple/container
- https://ai.meta.com/blog/practical-ai-agent-security/
- https://simonwillison.net/2025/Apr/11/camel/
- https://www.anthropic.com/research/prompt-injection-defenses

**Browser and scheduling**
- https://playwright.dev/python/docs/codegen
- https://apscheduler.readthedocs.io/en/3.x/userguide.html

**Voice**
- https://github.com/dscripka/openWakeWord/blob/main/docs/models/hey_jarvis.md
- https://github.com/dscripka/openWakeWord/blob/main/docs/custom_verifier_models.md
- https://github.com/AI4Bharat/IndicConformerASR
- https://arxiv.org/pdf/2305.15386
- https://json2video.com/ai-voices/azure/languages/marathi/
