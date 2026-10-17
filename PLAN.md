# Jarvis — Master Plan (v3.5)

**Date:** 2026-10-09 (updated 2026-10-10)
**Status:** Planning is nearly complete. No code has been written yet.
**What this file is:** All research, analysis and planning done so far, in one place.
**v3.1 (2026-10-10):** Added teach-by-demonstration, task queue, connector registry, schedules, model routing, task receipts, project workspace and isolated browser profiles. Kept the useful part of each and dropped the excessive or risky parts.
**v3.2 (2026-10-10):** Files are written in English. Conversations with Sachin happen in Marathi.
**v3.3 (2026-10-10):** Migration-ready architecture: hybrid now (Claude for reasoning, everything else local), fully local AI later without a rewrite. Added the AI provider layer, privacy controls, migration roadmap (Stages A–D) and migration evaluation suite. The brain-loop recommendation changed from the Claude Agent SDK to a Jarvis-owned loop. Nothing implemented; fully local inference is not verified.
**v3.4 (2026-10-10):** Sachin decided: Jarvis-owned loop, Tavily for web search, no P2 (sensitive) data sent to the cloud at the start.
**v3.5 (2026-10-10):** Added a migration path for every AI-dependent component and an explicit rule for when a component may move to a local model. Local models are not assumed to match Claude.
**v3.6 (2026-10-17):** Section 27, the laws of Jarvis: seven laws every part obeys and the three powers (create, preserve, end) every kind must have. Every later phase is checked against them; `tests/test_laws.py` enforces them.

---

## 0. Summary

Jarvis is a personal AI assistant that runs on Sachin's Mac.
It **learns** from him, **remembers** what it learns, **does real work**, **checks that the work actually got done**,
**speaks up on its own** when something matters, and hands big jobs to a **team of agents**.

Voice and the dashboard are only interfaces. The real Jarvis is memory + tools + safety + proactivity + team.

**Architecture direction:** Jarvis launches **hybrid**. Claude does the reasoning in the cloud; the app, memory, tools, permissions, task execution and audit logs all run on the Mac. Everything is built behind a provider-independent AI interface so that Jarvis can later move to **fully local AI** without rewriting the application. See "AI provider layer and migration to local AI".

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
| 9 | Sachin's architecture direction (2026-10-10) | Hybrid now, fully local AI later | Provider layer, privacy controls, migration roadmap |

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
| 24 | ~~Smart home~~ | Dropped by Sachin on 2026-10-10 | — |

**Skills needed for version 1:** #1, #2, #4, #11, #14, #17, #19, #22.

---

## 4. Architecture

```
┌──────────────────────────────────────────────────────────────┐
│ INTERFACES  CLI (P0) · Telegram (P4) · Voice (P6) · Web (P7) │
└─────────────────────────────┬────────────────────────────────┘
┌─────────────────────────────▼────────────────────────────────┐
│ JARVIS CORE (local, provider-independent)                    │
│ context builder · planner · own tool loop · agent team       │
│ task state · routing policy · cloud privacy gate             │
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
       │ CONNECTORS (not AI providers): Telegram · web   │
       │ search · Calendar · Gmail · Reminders · Notes   │
       └─────────────────────────────────────────────────┘
┌──────────────────────────────────────────────────────────────┐
│ AI PROVIDER LAYER (the only code that knows a vendor)        │
│ ReasoningProvider interface                                  │
│  ├─ Claude adapter   (Stage A, cloud)                        │
│  ├─ Fake provider    (tests, offline)                        │
│  └─ Local adapter    (future, from Stage B; not built yet)   │
└──────────────────────────────────────────────────────────────┘
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

## 5. AI provider layer and migration to local AI

### 5.1 Architecture decision: hybrid now, fully local later

- **Context:** Claude gives the best reasoning today. Sachin wants Jarvis to move to fully local AI later without rewriting the app. The Mac (M4, 16 GB, ~32 GB free disk) has not been tested with local models.
- **Decision:** Launch hybrid. Claude (via the Anthropic Python SDK) is the first reasoning provider. The app runtime, memory, indexes, tools, permissions, task execution, receipts and audit logs stay on the Mac. All reasoning goes through a provider-independent interface owned by Jarvis.
- **Consequences:**
  - Jarvis owns its agent loop, agent team, sessions and safety gate. The Claude Agent SDK is not used as the core (see "Brain loop").
  - Vendor code lives only in provider adapters.
  - Model capabilities are declared or measured, never assumed.
  - A local adapter is designed now but built only in Stage B, with Sachin's approval.
  - **Not claimed:** fully local inference on this Mac is unverified. Stage B measures it.
  - **Not assumed:** a local model on an M4 with 16 GB is not assumed to match Claude. Whether full local AI is possible depends on model quality, memory requirements and the tasks Sachin actually needs. Each AI-dependent component has its own migration path (see "AI-dependent components and their migration paths"), and some may stay on Claude.

### 5.2 What stays local and what may go to the cloud

| Always local | May go to the cloud AI provider | Needs internet anyway (not AI providers) |
|---|---|---|
| Memory files, SQLite index, embeddings, session history, task state, receipts, audit logs, schedules, skills, config | Prompts and context that pass the privacy gate (see "Privacy controls for cloud AI") | Web search, Gmail, Google Calendar, Telegram, edge-tts Marathi voice |

### 5.3 Provider interface

Documentation only. Not implemented.

```python
class ReasoningProvider(Protocol):
    name: str                                    # "anthropic", "fake", later "local-<runtime>"
    def capabilities(self, model: str) -> ModelCapabilities: ...
    def generate(self, req: LLMRequest) -> LLMResponse: ...            # one step: text and/or tool calls
    def stream(self, req: LLMRequest) -> Iterator[LLMEvent]: ...
    def structured(self, req: LLMRequest, schema: dict) -> StructuredResult: ...  # schema-validated JSON
    def count_tokens(self, req: LLMRequest) -> TokenCount: ...          # exact or estimated
    def health(self) -> ProviderHealth: ...
```

**Neutral types:**

| Type | Fields |
|---|---|
| Message | role (system / user / assistant / tool), parts: text, image, tool_call, tool_result |
| ToolSpec | name, description, parameters as portable JSON Schema. The risk tier stays inside Jarvis and is never sent to a model |
| ToolCall | id, name, arguments |
| LLMRequest | route, model, system text, messages, tools, response schema, reasoning hint (low / medium / high), max output, task id, budget, privacy classes present |
| LLMResponse | text, tool calls, stop reason (end / tool_use / max_tokens / refusal / error / cancelled), usage (input, output, cached tokens), cost estimate, latency, provider, model, adapter_state (opaque) |
| ModelCapabilities | context window, max output, tool calling (none / single / parallel), structured output (none / JSON mode / JSON schema / grammar), vision, streaming, prompt caching, reasoning control, languages verified (en, mr-roman, mr-deva), source (documented / measured). Local models add RAM at load and tokens per second |

**Rules:**
- The core validates every structured output and every tool argument against its schema itself, whatever the provider claims.
- An unknown capability counts as unsupported.
- For a model without native tool calling, an optional "JSON action mode" uses structured output to pick tools. It is enabled per model only if that model passes the tool-calling evaluation in that mode.

### 5.4 Adapters

**Claude adapter (Stage A, built in Phase 1):**
- Anthropic Python SDK, Messages API, one loop step per call. Anthropic's docs recommend a manual tool loop when approval gates are needed, which matches our T0–T4 gate.
- Translates neutral types to Claude messages, tools and tool_use / tool_result blocks, and back.
- Handles Claude-only features internally: prompt caching, effort and adaptive thinking, refusal stop reason, server-side refusal fallbacks (to other Claude models only), strict tool schemas, structured outputs, thinking-block replay within the same model.
- Converts usage to cost from the price table in config.

**Fake provider (Phase 0):** a deterministic test double. The whole test suite runs offline against it, which proves the core does not depend on Claude.

**Local adapter (future, Stage B only):**
- Not implemented until Stage B is approved.
- Expected to call a local inference server on localhost. Many local runtimes expose an OpenAI-style HTTP API; this is to be verified per runtime in Stage B.
- Accepts **localhost endpoints only**, so it can never quietly turn into a cloud provider.
- Must pass the same adapter contract tests as the Claude adapter.
- Capability profile comes from measurement on this Mac, not from model cards.

### 5.5 Isolation rules and planned code layout

- Only `jarvis/providers/` may import vendor SDKs (`anthropic`, any local runtime client). An import-boundary test enforces this.
- Core, memory, tools, control and connectors depend only on the neutral types in `providers/base.py`.
- Provider-specific data (thinking blocks, cache details, response IDs) lives only in `adapter_state`. It is never required to resume a task.
- Prompts live in `prompts/` as provider-neutral text. Adapters may add provider-specific framing but no business logic.

```
jarvis/
├── core/          orchestrator, own tool loop, planner, agent team
├── providers/
│   ├── base.py    ReasoningProvider protocol, neutral types, capabilities
│   ├── claude.py  Claude adapter (Stage A)
│   ├── fake.py    deterministic test double
│   └── local.py   future local adapter (Stage B only, not created before)
├── routing/       provider and model routing policy, cloud privacy gate
├── memory/        store, search, extractor (calls providers via the interface)
├── tools/         registry, typed tools, verifiers, portable schemas
├── control/       T0–T4, approvals, audit, emergency stop, budgets
├── connectors/    telegram, google, eventkit, search (not AI providers)
└── evals/         migration evaluation runner
prompts/           provider-neutral prompts
config/
├── providers.yaml approved providers and endpoints (no secrets)
├── models.yaml    capability profiles (documented or measured)
└── routing.yaml   routes, candidates, privacy limits, fallback rules
tests/evals/       synthetic evaluation tasks (no personal data; repo is public)
```

Machine-specific overrides go in `config/local.yaml`, which Phase 0 adds to `.gitignore`.

### 5.6 Claude-specific dependencies

| Claude feature | Where the plan used it | Portability risk | Plan |
|---|---|---|---|
| Claude Agent SDK (loop, built-in tools, hooks, subagents, session files) | Brain loop, agent team, permissions | High | Replaced by a Jarvis-owned loop. Not in the core |
| Tool-use wire format, strict tools | Every tool call | Medium | Adapter translates from neutral ToolSpec. Strict mode is a capability |
| Structured outputs (`output_config.format`) | Extractor, receipts, labels | Medium | `structured()` in the interface. Core always validates |
| Adaptive thinking, effort, model-bound thinking blocks | Routing table | Medium | Neutral reasoning hint mapped per provider. Thinking blocks stay in adapter_state |
| Prompt caching | Cost control | Low (cost only) | Adapter applies it. The core keeps a stable prompt prefix, which also suits local prefix caching |
| Server-side web search and fetch | Connectors | High | Replaced by Jarvis search and fetch tools. Anthropic's tool is an optional Claude-only extra |
| Refusal stop reason, server-side fallbacks | Fallback rules | Medium | Neutral `refusal` stop reason. Fallback per routing policy |
| 1M-token context window | Context builder | High for local models | Context budget sized from each model's capability profile |
| Files API, PDF blocks, citations | Document library | Medium | Text extraction and chunking stay local. Only text chunks are sent |
| Vision (screenshots) | Vision skill | Medium | Capability flag. Screenshots are P2 by default |
| Message quirks (no prefill, no forced tool choice, mid-conversation system messages) | Prompts | Low | Adapter only |
| Token counting endpoint | Budgets | Low | `count_tokens()` with estimate fallback |
| Model IDs, prices, budgets in USD | Routing, cost | Low | Config files. Local cost tracked as time and resources |
| MCP | Connectors | Low (open protocol) | Jarvis is the MCP client. Tools merge into the registry |
| Agent Skills (SKILL.md) | Skill system | Low (open standard) | Jarvis loads skills itself |

### 5.7 Portability rules

- **Tools:** One registry. Parameters use a portable JSON Schema subset: object, string, number, integer, boolean, enum, array, required, descriptions. Avoid oneOf/anyOf, regex patterns and deep nesting, because local constrained decoders may not support them. Keep descriptions short for smaller context windows. MCP tools are imported into the same registry.
- **Task state:** SQLite tables owned by Jarvis: tasks, task_events, messages (neutral form), tool_runs, approvals, model_usage (with a provider column), and an optional adapter_state table. A paused task can resume on a different provider from the neutral history; provider-only data is dropped.
- **Memory:** A MemoryStore interface (save, search, get, supersede, list, export) independent of any provider. The extractor and query rewrite are prompts with JSON schemas sent through the provider interface. Embeddings run locally behind an Embedder interface.
- **Skills:** Jarvis puts the skill index in the prompt and provides a `load_skill` tool, so skills work with any provider.
- **Context budget:** The context builder sizes injected memories and document chunks from the model's context window. The "context fit" evaluation checks this.
- **Evaluation:** Test tasks are stored provider-neutral, and the same suite runs against every provider.

### 5.8 AI-dependent components and their migration paths

Only the components below use an AI model. Everything else is AI-independent by design and needs no rewrite when the provider changes: memory storage and index, task queue and state, tools and connectors, T0–T4, approvals and audit, receipts, scheduler, Telegram and the dashboard.

| Component | Stage A (now) | Local path | If local is not good enough | Decided in |
|---|---|---|---|---|
| Main conversation | Claude Opus 5.5 | Local chat model via the local adapter | Stays on Claude | Stage B |
| Planning, team manager | Claude Opus 5.5, high effort | Strongest local model that fits | Stays on Claude. Likely the last route to move | Stage B |
| Agent team workers (Researcher, Writer) | Claude (Opus low or Sonnet) | Local model, fewer agents in parallel | Team stays on Claude, or one agent at a time locally | Stage B |
| Checker | Claude, after deterministic checks | Local model, after deterministic checks | Deterministic checks only, marked "not model-checked" | Stage B |
| Memory extractor | Claude Haiku 5.5 | Small local model with JSON-schema output | Stays on Claude, or save only on an explicit "remember this" | Stage B |
| Query rewrite (romanized Marathi to English keywords) | Claude Haiku 5.5 | Small local model | Keyword and trigram search without the rewrite | Stage B |
| Intent and risk labels | Claude Haiku 5.5 | Small local model | Rules, and ask Sachin whenever unclear | Stage B |
| Heartbeat check, receipt summary | Claude Haiku 5.5 | Small local model | Template text (receipts are already built from logs) | Stage B |
| Quarantined extraction of untrusted content | Claude, for P0/P1 content only | Local model. This is where local helps most, because email bodies are P2 | Stays off for P2 content | Stage B |
| Skill drafting (teach-by-demonstration) | Claude | Local model | Stays on Claude (rare, high value) | Stage B |
| Schedule parsing ("every Monday at 9") | Claude | Deterministic date parser first, model only for ambiguous text | Ask Sachin to confirm the schedule | Phase 4 |
| Document Q&A | Claude, P0/P1 documents only | Local model, which would also allow private (P2) documents | P2 documents stay unavailable | Stage B |
| Vision (screenshots) | Off (screenshots are P2) | Local vision model, if one fits in memory | Stays off | Stage B |
| Embeddings | Local (multilingual-e5-small) | Already local | — | Done |
| Speech-to-text | Local Whisper (English) | Already local. Marathi via a local Indic model | — | Phase 6 |
| Text-to-speech, English | Local macOS `say` | Already local | — | Phase 6 |
| Text-to-speech, Marathi | edge-tts (cloud) | Offline Marathi voice, not yet found | Recorded exception, or English voice | Stage B / Phase 6 |
| Evaluation judge | One fixed judge model plus human spot checks | Deterministic checks plus human review | Cloud judge for evaluation only (open decision) | Stage B |
| Coding agent (later) | Claude Opus 5.5 | Local coding model | Stays on Claude | Later |

**Rule for moving a component to a local model.** A component moves only when all three hold:
1. **Quality:** on that component's evaluation tasks, the local model is within the agreed threshold of the Claude baseline.
2. **Fits this Mac:** enough RAM headroom with Jarvis and normal apps running, and acceptable latency.
3. **Importance:** components that serve Sachin's top 5 daily tasks need stricter thresholds.

Staying hybrid for some components is an acceptable result. "Fully local" is the goal, not an assumption.

### 5.9 Privacy controls for cloud AI

| Class | Examples | Cloud AI in Stage A | Stored in memory |
|---|---|---|---|
| P0 Public | General questions, public web pages | Allowed | Yes |
| P1 Personal | Preferences, project names, schedule outlines, Jarvis's own notes | Allowed | Yes |
| P2 Sensitive | Email and message bodies, contacts' details, health, money, private documents, screenshots | **Withheld.** Sachin decided on 2026-10-10 that no P2 category goes to the cloud at the start. Categories can be enabled one at a time later, only with his OK | Yes, marked sensitive |
| P3 Secret | Passwords, API keys, tokens, OTPs, card numbers, government ID numbers | Never | Never |

- Every context item carries a class: memory `sensitivity`, a class set when a document is approved, a class per tool output, P2 by default for screenshots and for untrusted email or web content.
- The privacy gate runs in the core before the adapter. The adapter never sees withheld items.
- Deterministic P3 filters (key and token patterns, card numbers, OTP-like codes, ID formats) scan every outbound payload, even items labeled lower.
- When something is withheld, Jarvis says so instead of guessing. From Stage C the task may run on the local model instead.
- Untrusted content goes through the quarantined extraction step; only the extracted fields are sent.
- Audit log per cloud call: time, route, provider, model, classes included, number of items withheld, token counts, payload hash (never the payload).
- The receipt lists what was withheld from the cloud.
- Global `cloud_allowed` switch, also as a Telegram `/cloud off` command.
- Anthropic's API data retention and training terms must be checked before Stage A goes live. Nothing is assumed here.
- **Effect of "no P2 at start":** features that need email or message bodies, private documents or screenshots cannot use Claude until Sachin enables that category, or until a local model handles them (Stage C). This limits email summaries in the daily brief, screenshot analysis and Q&A over private documents. Jarvis says clearly when a task is blocked for this reason. Whether email sender and subject count as P1 or P2 is decided before Phase 5.

### 5.10 Migration roadmap

**Stage A — Hybrid MVP** (Phases 0–7)

- **Goal:** Claude is the primary reasoning provider. The core application stays local.
- **Work:** Provider interface, fake provider, Claude adapter, routing config in `cloud_primary` mode with `anthropic` as the only approved provider, privacy gate, import-boundary test, adapter contract tests, migration evaluation suite with a Claude baseline.
- **Acceptance criteria:**
  - No vendor SDK is imported outside `jarvis/providers/`.
  - The full automated test suite passes offline with the fake provider.
  - The Claude adapter passes the adapter contract suite.
  - Planted P3 test strings never appear in any outbound payload.
  - Every cloud call appears in the audit log with its privacy classes.
  - A Claude baseline of the migration evaluation suite is recorded (summary committed, no personal data).
  - Memory, task state, audit logs, receipts and indexes exist only on the Mac.
- **Risks:** More code than the Agent SDK path. Claude-only features creeping into the core. P2 leaks through mislabeled data. API cost.
- **Dependencies:** Anthropic Python SDK, Anthropic API key, Tavily API key, monthly budget. P2 to cloud: none at the start (decided).
- **Tests:** Import-boundary, adapter contract, fake-provider end-to-end, privacy gate, evaluation baseline.

**Stage B — Local model evaluation** (a separate, approved step; earliest after Phase 3)

- **Goal:** Measure local models on this Mac. Do not adopt them yet.
- **Work:** Pick candidate runtimes and models at that time, based on license, size that fits in 16 GB while Jarvis runs, documented tool-calling and structured-output support, and Marathi claims. Install them only with Sachin's approval. Build the local adapter. Measure capability profiles. Run the migration evaluation suite.
- **Acceptance criteria:**
  - The local adapter passes the contract suite, or each failing capability is documented.
  - An evaluation report exists for every candidate: all categories against the Claude baseline, with model, version, quantization, runtime, context size, hardware, date and git commit.
  - Capability profiles are written from measurements.
  - Each component gets a verdict, local-ready or not ready, using the three-part rule in "AI-dependent components and their migration paths".
  - Live routing does not change.
- **Risks:** RAM contention on 16 GB, low free disk (~32 GB), weak tool calling or structured output, weak Marathi, slow output or thermal throttling, model license limits, judge bias in the evaluation.
- **Dependencies:** Stage A baseline, Sachin's approval for downloads, disk space, a resource-measurement library.
- **Tests:** Migration evaluation suite, adapter contract suite, resource measurements while Jarvis runs.

**Stage C — Local-first**

- **Goal:** Supported tasks run on the local model by default.
- **Work:** Switch to `local_first` mode. Routes that passed Stage B use the local provider. Other routes use the cloud only as configured and as privacy rules allow. Each route sets `cloud_fallback` to never, ask or allowed. Add offline detection and a weekly regression run of the evaluation suite.
- **Acceptance criteria:**
  - Routes marked local make zero cloud calls (checked in the audit log).
  - Live quality (sampled receipts plus the weekly evaluation) stays within the agreed thresholds.
  - With `cloud_allowed: false`, cloud-only routes pause with a clear message instead of failing silently.
  - Every local-to-cloud fallback is allowed by config or approved by Sachin, and logged.
- **Risks:** Quality regressions nobody notices, slower answers, less agent-team parallelism with one local model, RAM pressure from other apps.
- **Dependencies:** Stage B verdicts, Sachin's approval of the new routing.
- **Tests:** Weekly evaluation run, routing-policy tests, offline tests for local routes.

**Stage D — Fully local AI**

- **Goal:** The core reasoning path has no mandatory cloud AI dependency.
- **Work:** Every route has an approved local provider. The Claude adapter becomes an optional extra or is removed. Replace the edge-tts Marathi voice with an offline voice, or record an explicit exception. Document what still needs internet (web search, Gmail, Calendar, Telegram).
- **Acceptance criteria:**
  - Jarvis starts and runs supported tasks with no API key and no internet.
  - The offline suite (network disabled) passes at the agreed thresholds.
  - `anthropic` is not a required runtime dependency.
  - Features that need internet are listed in the docs and shown in the app.
- **Risks:** This hardware may not handle some routes (long context, complex planning, the agent team). Ongoing model maintenance. Quality below Claude.
- **Dependencies:** Stable Stage C, possibly new hardware (Sachin's decision).
- **Tests:** Offline suite, full migration evaluation, fake-provider suite.

### 5.11 Migration evaluation suite

- **Location:** `tests/evals/migration/`. Synthetic tasks only, because the repo is public. Results with any personal data stay in `data/evals/`.
- **Each task records:** id, category, language (en / mr-roman / mr-deva / mixed), input, available tools, expected tool calls or acceptance checks, grading method (deterministic, rubric or human), privacy class.

| Category | What it covers | Metric |
|---|---|---|
| Reasoning and planning | Multi-step plans, task breakdown | Rubric score from a fixed judge plus human spot checks; plan validity |
| Tool calling | Right tool, valid arguments, multi-step sequences, no invented tools, no T4 attempts | Tool-selection accuracy, schema-valid argument rate |
| Structured output | Extractor output, receipts, routing labels | JSON-schema valid rate over repeated runs |
| Marathi and English | Romanized Marathi, Devanagari, code-mixed | Intent accuracy, answer rubric, query-rewrite recall |
| Memory retrieval | Teach and probe, supersede, abstain, act probes | Extraction precision and recall, top-5 hit rate, act-probe pass rate |
| Latency | First token, whole task | p50 and p95 seconds |
| Resources | RAM and CPU while Jarvis runs | Peak memory, average CPU, model load time |
| Task success | End-to-end tasks with acceptance checks | Verified completion rate |
| Safety | Prompt injection, approval compliance | Violations (target 0) |
| Context fit | Long memory or document tasks under small windows | Success rate by context size |

- **Baseline:** Run on Claude during Stage A. This is the reference for every later stage.
- **Pass thresholds:** Set per route after the baseline exists (open decision). Tool calling and structured output need near-perfect reliability, because errors there become wrong actions.
- **Judge:** Deterministic checks first. Rubric judging uses one fixed judge model and prompt version across all runs, never the candidate being tested, plus human spot checks.
- **Reproducibility:** Record provider, model, version, quantization, runtime, context size, hardware, date and git commit. Use fixed seeds where supported, and repeat stochastic tests several times.

### 5.12 Unresolved technical decisions

1. ~~Brain loop~~ Decided 2026-10-10: Jarvis-owned loop with a Claude adapter.
2. ~~P2 categories for Claude~~ Decided 2026-10-10: none at the start. Still open: whether email sender and subject count as P1 (before Phase 5).
3. ~~Web search provider~~ Decided 2026-10-10: Tavily.
4. When to run Stage B, and approval to download local runtimes and models.
5. Pass thresholds per route.
6. Evaluation judge policy, including whether a cloud judge is acceptable for evaluation only.
7. Local runtime and model choice (only after Stage B measurements).
8. Hardware upgrade if Stage B shows this Mac is not enough.
9. Offline Marathi voice for Stage D.
10. Anthropic API data-retention terms, to be checked before Stage A goes live.

These are also listed in "Open decisions".

---

## 6. Memory design (the core)

### 6.1 Layout

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

**In the code repo:** code, PLAN.md, PROGRESS.md, CLAUDE.md, examples, config defaults (no secrets), synthetic evaluation tasks.
**Never in the code repo:** `memory/`, `profile/`, `projects/`, `skills/` (learned), `data/`, `connectors/registry.yaml`, `.env`. All of these are in `.gitignore`.

### 6.2 One memory file

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
sensitivity: normal        # public | normal | sensitive | secret  (privacy classes P0–P3)
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

### 6.3 Write path (how memories get saved)

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

### 6.4 Read path (how memories get used)

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

### 6.5 Search facts checked

| Item | Result |
|---|---|
| Hinglish search with e5-small embeddings | Fell from 0.61 (English) to 0.16 (Hinglish) |
| Hinglish search with plain keywords (BM25) | 0.29, better than embeddings |
| numpy search over 3,000 memories | ~0.05 ms per query |
| Ready-made benchmark for romanized Marathi | None exists |

**Embedding model:** start with multilingual-e5-small (small, MIT). Compare against granite-97m-multilingual-r2 and e5-large on 30–50 of Sachin's real queries.
**Hosted embeddings:** not needed unless our own test shows a big gap.

### 6.6 Other memory features

- **Save anything:** forward a link or file on Telegram and it goes to memory.
- **Curiosity:** when Jarvis sees something unknown, it asks. "You get many emails from this company. Is it your workplace?"
- **Weekly cleanup:** merge duplicates, turn relative dates ("tomorrow") into absolute dates, archive memories unused for 90 days, keep MEMORY.md under 200 lines.
- **Memory commands:** list, search, edit, delete, export.
- **Learning ≠ training:** the model never changes. Its diary grows.
- **Provider-independent:** the extractor and query rewrite are prompts with JSON schemas sent through the provider interface. Embeddings and search run locally. Changing the AI provider changes no memory code or data.

---

## 7. Project workspace and document library

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

## 8. Skill system

- Each skill = a folder + `SKILL.md` (name, description, instructions, scripts).
- This is Anthropic's open standard (December 2025). By September 2026 more than 40 tools support it.
- Only skill names and descriptions sit in the prompt. The full skill loads when needed.
- **Jarvis learns new skills:** after a big job succeeds, Jarvis proposes a skill. **It is saved only after Sachin approves.**
- **Why approval:** research shows agents can turn failed attempts into bad skills. Model-written skills add little; human-reviewed skills work much better.
- Review any third-party skill before installing it. It can contain dangerous code.
- Jarvis loads skills itself (skill index in the prompt plus a `load_skill` tool), so skills work with any AI provider.

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

## 9. Agent team

### 9.1 Team

| Agent | Job | Permissions |
|---|---|---|
| Jarvis (manager) | Plan, delegate, merge results | Only Jarvis asks Sachin for approval |
| Researcher | Web search, sources | Read-only |
| Writer | Reports, documents, drafts | Approved folders only |
| Checker | Verify the work was really done | Read-only, can reject results |
| Coder (later) | Code, tests | Separate folder |
| Operator (later) | Apps, files, browser | Per safety tiers |

Agents are sub-loops run by Jarvis's own orchestrator through the provider interface. Each agent's provider and model come from the routing policy. Instructions, tools and skills differ per agent.

### 9.2 Flow (example: "laptop under ₹80,000, compare 3 options")

1. Understand; ask 1–2 questions if needed.
2. Plan: 3 researchers + writer + checker. Show the estimated cost.
3. Each agent gets a work order: objective, tools, output format, budget, stop condition.
4. The 3 researchers run in parallel.
5. The Checker verifies sources and prices.
6. Jarvis builds the report and sends it on Telegram.
7. On success, propose a skill.

### 9.3 Research figures

| Fact | Figure |
|---|---|
| Team vs single agent (Anthropic internal eval) | 90.2% better |
| Single agent tokens vs chat | 4× |
| Team tokens vs chat | 15× |
| Team failures: unclear specification | 41.8% |
| Team failures: inter-agent misalignment | 36.9% |
| Team failures: weak verification | 21.3% |

### 9.4 Rules

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

## 10. Task system: queue, receipts and scheduling

### 10.1 Mission / task queue

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
- At first, at most 2 big tasks run at once, because of 16 GB RAM. From Stage B a local model would share that memory too.
- Ordered by priority and deadline.
- After a crash, RUNNING tasks resume from their last checkpoint.

### 10.2 Task receipt

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

### 10.3 Skill and agent scheduling

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

## 11. Safety

### 11.1 Risk tiers

| Tier | Actions | Policy |
|---|---|---|
| T0 Read-only | Search, summarize, read files | Run immediately |
| T1 Local write | New file/draft in an approved folder | Run, then verify |
| T2 Significant change | Overwrite files, bulk edits, settings | Ask first |
| T3 External / irreversible | Send email, post, pay, delete | Always ask, show full details |
| T4 Prohibited | Security bypass, passwords, rm -rf | Never; log the attempt |

### 11.2 Practical rules on macOS (from research)

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
- **Cloud privacy gate:** before any cloud AI call, context is filtered by privacy class (see "Privacy controls for cloud AI").

### 11.3 macOS permissions

- **v1 runs from Terminal.** Permissions are granted to Terminal. LaunchAgent, Full Disk Access and microphone come later.
- **Screenshots:** `screencapture -x`. Needs Screen Recording permission, which macOS re-asks about monthly.
- **Notifications:** `osascript`.
- **Global hotkey:** pynput crashes on macOS 26. Use a Quartz event tap or Shortcuts/Raycast.
- **Later (v2):** Jarvis inside a signed `.app`, started at login by a LaunchAgent, so permissions stick.

### 11.4 Browser automation: isolated, safe browser

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

## 12. Proactive

- **Heartbeat:** every 30 minutes Jarvis reads a `HEARTBEAT.md` checklist and checks whether anything is worth telling Sachin (OpenClaw's design).
- **Daily brief:** each morning: calendar, reminders, goals, weather, important emails.
- **Reminders and goals:** weekly and monthly tracking from goals.md.
- **When to speak:** only when it matters. Quiet hours respected.

---

## 13. Connectors

| Order | Connector | How | Effort |
|---|---|---|---|
| 1 | Telegram | python-telegram-bot, long-polling (no server), only Sachin's user ID allowed, Approve/Deny buttons | Low |
| 2 | Web search | Jarvis search and fetch tools using **Tavily** (Sachin's decision, 2026-10-10), independent of the AI provider. Anthropic's server-side web search only as an optional Claude-only extra | Low |
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
- Anthropic web search: $10 per 1,000 searches + tokens. Tavily: 1,000 free credits a month. Search runs as a Jarvis tool so any AI provider, including a future local one, can use it. Tavily needs its own API key in the Keychain (from Phase 2).

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

## 14. Voice

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

**Cloud dependency:** edge-tts (the Marathi voice) is a Microsoft cloud service. Stage D needs an offline Marathi voice or an explicit exception. Whisper and macOS `say` already run locally.

**Incomplete:** the voice research agent was stopped midway. Before Phase 6, re-check that these libraries work on Python 3.13 and which Whisper build is fastest on the Mac.

---

## 15. Brain loop: how to build it

**Recommendation (changed in v3.3): Jarvis owns the agent loop. Claude is called through the Claude adapter, built on the Anthropic Python SDK (Messages API with tool use). The Claude Agent SDK is not part of the core.** Sachin confirmed this on 2026-10-10.

**Why the change:** The Agent SDK runs Claude Code's own loop, built-in tools, permission hooks, subagents and session files. Those are exactly the parts that must stay provider-independent for the move to local AI. Building on it would force a rewrite at migration time. Until v3.2 the recommendation was the Agent SDK.

**What Jarvis builds itself (much of it was needed anyway):**
- **Loop:** call the provider, run tool calls through the Jarvis tool gateway (T0–T4, approvals, audit), append results, repeat until done or a limit is hit.
- **Agent team:** sub-loops with their own system prompt, tool allowlist, route and budget.
- **Sessions and resume:** neutral messages and task state in SQLite.
- **Emergency stop:** checked before every provider call and every tool call.
- **Budgets:** per-task token, cost and step limits from provider usage reports.
- **Skill loading:** skill index in the prompt plus a `load_skill` tool.

**What we give up compared with the Agent SDK:** its ready-made file, shell and edit tools, hooks, subagents and session handling. That means more code in Phases 1–3. In return there is no lock-in, and our safety gate sees every call directly.

**Claude adapter details:** see "Adapters" in the AI provider section. Prompt caching order stays: fixed tools and personality first, then the slowly changing memory index, then per-turn memories.

**Agent SDK later?** Only as an optional, isolated, Claude-only capability behind the provider boundary (for example a coding agent), if Sachin approves and nothing in the local path depends on it. If it is ever used: `setting_sources=[]` keeps Sachin's global CLAUDE.md out, and `CLAUDE_CODE_DISABLE_AUTO_MEMORY=1` turns off its own memory.

---

## 16. Provider and model routing

**Core rules:**
- Routing is by call type (route). Never switch provider or model mid-conversation; prompt caches and thinking blocks are specific to a provider and model, and switching raises cost.
- The policy lives in `config/routing.yaml`. It is deterministic, and every decision is logged: route, provider, model, reason, privacy classes.
- Only **approved providers** may be used. In Stage A the approved list is `anthropic` only. A local provider is approved only after it passes Stage B and Sachin agrees.
- **No silent fallback to an unapproved or cloud provider.** Fallback stays within the route's candidate list. Cross-provider fallback (local to cloud or back) happens only when the route and the privacy class of the context allow it.
- Capabilities are never assumed. Each model has a capability profile (documented for cloud models, measured for local models). Each route lists the capabilities it needs, and a model without them is not eligible.
- Anthropic's guidance still applies: before building a multi-model cascade, test the best model at lower effort.

**Routing modes:** `cloud_primary` (Stage A), `local_first` (Stage C), `local_only` (Stage D), plus a global `cloud_allowed` switch.

**Claude models (Anthropic docs, list dated 2026-10-06):**

| Model | ID | Input $ / 1M tokens | Output $ / 1M tokens |
|---|---|---|---|
| Opus 5.5 | `claude-opus-5-5` | 4.00 | 20.00 |
| Sonnet 5.5 | `claude-sonnet-5-5` | 2.00 | 10.00 |
| Haiku 5.5 | `claude-haiku-5-5` | 0.10 | 0.50 |

The Haiku price applies to prompts up to 100K tokens.

**Routing table (Stage A starting point):**

| Route | Provider / model | Effort | Highest privacy class | Needs | Why |
|---|---|---|---|---|---|
| Jarvis main conversation | anthropic / Opus 5.5 | medium | P1 (no P2 approved yet) | tools, structured output | Default, strong understanding |
| Big plans, team manager | anthropic / Opus 5.5 | high | P1 (no P2 approved yet) | tools, structured output | Hard reasoning |
| Memory extractor, query rewrite, intent/risk label, heartbeat check, receipt summary | anthropic / Haiku 5.5 | low | P1 (no P2 approved yet) | structured output | Simple and frequent; Sachin asked for a cheap, fast model here |
| Researcher, Writer | anthropic / Opus 5.5 low **or** Sonnet 5.5 medium | — | P1 | tools | **Sachin's decision.** Test both |
| Checker | No weaker than the workers | high | P1 | structured output | Verification must not be weak |
| Coder (later) | anthropic / Opus 5.5 | high | P1 | tools | Effort matters for code |
| No internet | None in Stage A (no approved local provider yet) | — | — | — | AI tasks pause with a clear message |

**Config sketch (documentation only):**

```yaml
mode: cloud_primary
cloud_allowed: true
approved_providers: [anthropic]
routes:
  memory_extractor:
    candidates:
      - {provider: anthropic, model: claude-haiku-5-5, effort: low}
      - {provider: anthropic, model: claude-sonnet-5-5, effort: low}
    needs: [structured_output]
    max_privacy: P1
    cloud_fallback: never      # never | ask | allowed (used from Stage C)
```

**Fallback order:**
1. 429 or 5xx: retry with backoff, honoring `retry-after`.
2. Next candidate in the same route list, if approved and capable.
3. Refusal: the adapter returns a neutral `refusal`. Inside the Claude adapter, server-side `fallbacks: "default"` may route to another Claude model; this is logged.
4. No eligible candidate: the task goes to PAUSED and Sachin is told on Telegram. Never an unlisted provider.
5. **Never silent.** Every fallback is written in the receipt.
6. **Safety does not depend on the provider.** T0–T4 rules and the privacy gate are identical for every provider.

**Budget:**
- `max_budget_usd` per task for cloud calls, set with headroom because cost figures are estimates.
- Per-route and monthly caps, warning at 80%.
- From Stage B, local calls track time, RAM and CPU instead of dollars.
- `model_usage` table: route, provider, model, tokens, estimated cost or resource use, whether a fallback happened.

**Implementation note:** Claude-specific rules (Opus 5.5 cannot disable thinking and rejects `budget_tokens`; forced `tool_choice` is unsupported; control cost with `effort`) stay inside the Claude adapter.

---

## 17. Tech stack

| Part | Choice | Why |
|---|---|---|
| Language | Python 3.12+ (3.13 on the Mac, 3.12 on the Windows laptop), project venv | Already installed |
| Brain | Claude behind the provider interface (Stage A). For now through the Claude Code CLI with Sachin's Claude Max login (`claude_code` adapter); the Anthropic SDK adapter is kept for later | Best quality now, no API bill, replaceable later |
| Agent loop | Jarvis-owned orchestrator with a manual tool loop | Provider-independent, no lock-in |
| Models | Opus 5.5 main, Haiku 5.5 for simple calls, workers after testing | See "Provider and model routing" |
| Local AI runtime | Not chosen. Candidates to evaluate in Stage B: Ollama, llama.cpp server, MLX-LM | Decide on measurements from this Mac |
| Web search | Jarvis search tool using Tavily (decided) | Independent of the AI provider; free tier to start |
| Memory | Markdown + SQLite (FTS5 + numpy vectors) | No server, editable, no extensions |
| Embeddings | multilingual-e5-small | Small, MIT, swap after testing |
| Skills | SKILL.md standard | Open standard |
| Scheduler | APScheduler 3.x (`jarvis daemon`) | Heartbeat, brief, schedules |
| Phone | python-telegram-bot | Long-polling |
| Mac control | pyobjc, osascript, screencapture | Native |
| Secrets | keyring: Keychain on macOS, Credential Manager on Windows | Safer than .env |
| Voice | faster-whisper (local STT), System.Speech (Windows) / say (macOS), edge-tts optional and off, openWakeWord optional and off | Chosen 2026-10-10; see PROGRESS.md decisions |
| Dashboard | FastAPI + Next.js static export, 127.0.0.1 + token | Node installed |
| Browser automation | Playwright Chromium, isolated profiles | Phase 8 |

**Dropped:** PostgreSQL, pgvector, Redis, n8n, users/roles/login, Zapier, Higgsfield, WhatsApp, 15 separate agents, 14 tabs, the Claude Agent SDK as the core loop (possible later as an isolated extra).
**Why:** one user, one Mac, 16 GB RAM. If needs grow, SQLite can migrate to PostgreSQL.

---

## 18. Phases

| Phase | Work | Done when |
|---|---|---|
| **0. Setup** | venv, config (providers, models, routing), Keychain, folders, SQLite, audit log, provider interface and fake provider, CLI chat | Jarvis replies "Good evening, sir." through the Claude adapter. The same CLI test passes offline with the fake provider. The import-boundary test passes |
| **1. Brain + Memory** | Agent loop, SOUL.md, profile interview, Marathi understanding, memory write/read, session search, memory commands, skill-system foundation, model-routing foundation (Opus main, Haiku extractor), Claude adapter with contract tests, privacy gate v1 (P0–P3 tags, P3 filters), migration evaluation scaffold and first Claude baseline (memory, Marathi/English, structured output) | Memory test: teach 10 facts; in a new session at least 9 are used correctly. "Act" test passes too |
| **2. Tools + Safety** | Typed tools, T0–T4, approvals, taint flag, kill switch, verifier, audit, daily info, media controls, connector registry (built-in tools), portable tool schemas, Jarvis web search (Tavily) and fetch tools | 10 tasks verified. No T4 action ever runs. Prompt-injection samples fail |
| **3. Tasks + Agent team** | Task queue and states, planner, task folders, receipts, project workspace, teach-by-demonstration (chat, terminal, files), model routing, Researcher/Writer/Checker as sub-loops of the Jarvis orchestrator, budgets, resume | A laptop-compare style job finishes with a report and a correct receipt, within budget. A demonstrated task replays as a skill. Tool-calling and task-success baselines recorded |
| **Stage B. Local model evaluation** (separate step, needs Sachin's approval; earliest after Phase 3) | Install candidate local runtimes and models, build the local adapter, run the migration evaluation suite on this Mac | Evaluation report per candidate with per-route verdicts. Live routing unchanged |
| **4. Telegram + Proactive** | Bot (Sachin only), approve buttons, /stop, /tasks, heartbeat, daily brief, reminders, skill and agent schedules | Morning brief arrives on the phone. Approvals work from the phone. A weekly schedule runs and handles a missed run |
| **5. Connectors** | EventKit, Google Calendar, Gmail (read/draft, send after approval), registry entries and health checks, document library | "Put a call tomorrow at 11" creates a verified event. Answers from project docs cite sources |
| **6. Voice** | Push-to-talk, Whisper, Rishi/Manohar, then hey_jarvis, barge-in, voice verification, Marathi STT test | 5 voice commands work |
| **7. Dashboard** | FastAPI + Next.js: Chat, Memory, Task board & Approvals, Agents, Connectors, Schedules, Settings & Usage | Everything controllable from the browser |
| **8. Extras** | Coder/Operator agents, magic search, meeting notes, Playwright with isolated profiles, browser step recording, OCR, signed .app | As needed |
| **9. X-ray vision (proposed 2026-10-15, waits for Sachin's "start")** | REA (reverse-engineering kit) installed outside the repo and pinned; a clean Chrome profile per job; capture, fingerprints and asset log; a teardown note with evidence; voice routes and a live panel; a drill and a preflight that prove it | "How does igloo.inc do that?" spoken once gives a spoken answer plus a teardown note in Jarvis's documents and memory, headless drill clean, preflight clean, no Chrome left running |
| **10. Agent HQ (proposed 2026-10-15, waits for Sachin's "start")** | Teams (lead + members, one job each, only the tools each needs, team skills), an Office page with live team rooms and the Brain in the middle, "ask any agent" and voice commands that run a team, team panel with tools / skills / agents / stats, approvals for anything public or with money | A spoken "Jarvis, research team, compare three laptops" lights the Research room, runs the team in parallel, and the result lands on the task board; the Office shows "N agents · M running" truthfully from live data |

Stages C (local-first) and D (fully local) start only after Stage B results and Sachin's approval. See "Migration roadmap".

**Build status (2026-10-10):** Phases 0–8 are built and merged; live checks and items waiting for Sachin are tracked in PROGRESS.md. Stage B (local models) has not started.


### 18.1 Phase 9 (proposed, 2026-10-15): X-ray vision with REA

Source: "Give Your Jarvis X-ray Vision" prompt pack (Zubair Trabzada, AI Workshop, October 2026), twelve
prompts in two parts. Vetted 2026-10-15 against official sources, as the rules require:

- `rea-agents` 6.5.0 on npm, MIT, repository `github.com/morluto/rea` (the pack's repo; ~248k stars,
  active). Node `^22.19 || ^24.11 || >=26`; this Mac has 24.20. The commands the pack uses exist in REA's
  own docs (`list-browser-targets`, `inspect-web-page`, `analyze-web-bundle`, `capture-web-screenshot`,
  `--json`). REA attaches to a browser the user owns through the Chrome DevTools Protocol and "never
  launches, drives, evaluates or mutates" the page (docs/browser-observation.md). Since Chrome 136 the
  debugging port is ignored for the default profile, so a fresh profile folder per job is required anyway.
- Exact flag names (`--observation-ms`, `--include-script-sources`) are checked with `rea <command> --help`
  at install time before any code depends on them.

**Part One of the pack vs. what Jarvis already has** (the pack is written for a from-scratch build):

| Pack prompt | Jarvis today | Take / adapt / drop |
|---|---|---|
| 01 Galaxy + brain | Brain exists: memory + document library with retrieval, "answers only from notes" for docs, Jarvis-owned loop, provider interface | Brain: keep ours. 3D galaxy viewer: **dropped for now** (needs a CDN/npm graph library; not needed for X-ray). Can return later as a "Knowledge galaxy" page |
| 02 Voice both ways | Voice v2 (local Whisper + IndicConformer, local voices, Alexa-style states). The pack's FINISH_MS 900 ms = our END_SILENCE 0.7 s | **Take:** a voice-route table checked before the brain (instant words "stop" / "wait" / "थांब", "remember that…", teardown sentences). Browser speech APIs: drop (ours is local and Marathi-capable) |
| 03 Proof of source | "Why?" panel shows the memories and excerpts behind a reply | Keep ours; no camera |
| 04 Butler | SOUL.md persona ("sir", honest, never claims an action it did not do) | Keep; control tags are replaced by Jarvis's typed tools (safer) |
| 05 Total Recall | `/remember`, live FTS index, failures shown | **Take:** spoken trigger ("remember that", "लक्षात ठेव") as a voice route |
| 06 Preflight | 1,518 offline tests, live suites, `jarvis health` | **Take:** `jarvis preflight`: live end-to-end chain checks with one summary line; "done" means preflight passed (PLAN 20) |

**Part Two → Phase 9 (new), adapted to Jarvis's rules** (PLAN 11, 16, 20):

1. **Kit** (`jarvis/xray/kit.py`): install REA pinned at 6.5.0 in `~/.jarvis-tools/rea` (outside the repo) with
   `npm install rea-agents@6.5.0 --save-exact --ignore-scripts` after `npm view rea-agents repository.url`
   confirms the repo; find node (PATH or common folders) and Chrome; `jarvis xray diag` and
   `GET /api/xray/diag` report ready / versions / problems; Jarvis boots and answers politely without it.
2. **Clean browser** (`jarvis/xray/browser.py`, standard library): Sachin's installed Chrome binary with a
   brand-new profile folder per job, loopback debugging port, `--disable-extensions`, 1280x820; poll
   `/json/version` (25 s), wait for `readyState` complete + 2.5 s; a minimal CDP WebSocket client for
   read-only `Runtime.evaluate` and `Input.dispatchMouseEvent` wheel scrolls only; headless flag for tests;
   `finally`: terminate, kill stragglers on that profile, delete the folder. Never his everyday profile,
   cookies or logins (PLAN 11.4).
3. **Capture** (`jarvis/xray/capture.py`): REA `inspect-web-page` with an observation window while Jarvis
   scrolls (~16 wheel steps), `analyze-web-bundle`, scroll to top, `capture-web-screenshot`; Jarvis adds
   the asset log from `performance.getEntriesByType('resource')` grouped by kind (12 largest) and version
   fingerprints from licence banners (Three.js, GSAP, postprocessing, Lenis, Locomotive, Swiper, Barba,
   React/Next/Vue/Svelte, Vite/webpack, Draco/KTX2) in one ordered table. Every evidence line says who saw
   it: REA or Jarvis.
4. **Teardown** (`jarvis/xray/teardown.py`): digest ≤ 15,000 chars → one model call on a new route
   `teardown` (Opus, high effort, max_tokens ≥ 7,000; P1) with the rules "every claim traces to evidence,
   'likely' for inferences, never invent, keep attribution straight"; output LABEL / SPOKEN / SUMMARY /
   NOTE. The note goes to `workspace/teardowns/HOST-DATE.md` with the snapshot in `assets/`, is added to
   the document library as project `teardowns` (searchable at once) and gets a memory entry (type
   reference) under a `[[REA]]` concept note; a task receipt is written; one job at a time; audit log.
5. **Voice and panel**: voice routes "reverse engineer X", "tear down X", "how does X do that", "what is X
   built with", "this site" / "this page" (spoken address parsing: dot/slash/colon, localhost allowed);
   "this site" reads the front Chrome tab's address with osascript (needs macOS Automation permission;
   T1, confirmed on screen); a `teardown` tool so the brain can start a job from a typed sentence
   ("reverse engineer Stripe's homepage"); a Teardown card on the Command Center and in Chat with 8 live
   steps, then a one-line fold, snapshot, up to 10 stack chips, totals and a reader; routes "show me the
   last teardown", "open / close / cancel the teardown". Spoken line in Marathi or English per the
   question's language.
6. **Drill and preflight** (`jarvis xray drill`): offline checks (five spoken addresses, a synthetic
   fingerprint string → Three.js r165 and GSAP 3.12.5, every digest line names its source) and a headless
   live drill that snapshots the document index, memory and teardowns folder, runs one teardown of a public
   page, checks steps / note sections / spoken line / nodes / time, then restores the snapshot. Safety: the
   note and image endpoints refuse paths outside the teardowns folder; no investigation Chrome left running;
   profile folders gone. `jarvis preflight` grows three checks.

**Jarvis rules that apply:** websites only, public ones Sachin may look at; REA observes, never clicks, logs
in or changes anything; the job is a T1 read-only observation, but page content taints the session like
any web page (PLAN 11.1); the only thing that leaves the machine is the site address (egress check on the
address the user gave) and the evidence digest sent to the model route; one model call per teardown, inside
the daily cap for unattended runs; every evidence line labelled; guesses labelled; tests use fakes (fake
CDP frames, recorded REA JSON) and clean up; the live drill is opt-in.

**Decisions for Sachin before starting:** (1) install REA (npm, pinned 6.5.0) in `~/.jarvis-tools`;
(2) use his installed Google Chrome with a fresh profile per job; (3) allow Jarvis → Chrome Automation for
"this site"; (4) galaxy viewer skipped for now; (5) teardown notes live in `workspace/teardowns` as project
`teardowns`.

**Order of work:** kit → clean browser → capture → teardown note → voice routes + panel → drill + preflight →
Part One extras (voice routes for stop/remember, `jarvis preflight`). Each step: tests, then PROGRESS.md.


### 18.2 Phase 10 (proposed, 2026-10-15): Agent HQ, teams and the office

Source: "I Built an AI Office With 31 Agents (Full Build)", Bekhruz AI, YouTube, 9 Oct 2026 (watched
2026-10-15: description, chapters, frames at 0:30, 1:10, 1:40, 2:30, 3:05, and the transcript Sachin pasted).
The video's teams: Research (every morning scans GitHub with 128 crawlers, picks the top three repos), Scripts
(hooks, scripts, fact-checks everything before it goes out), Social (schedules every post), Analytics (what
worked), TBX Shop (listings, orders, support), Dev (ships code), Inbox (email and brand deals), Creative
(Drive, CapCut, Canva, Slack; seven skills; the video editor leads; "grab the three new clips from Drive and
edit them in parallel" spins up one sub-agent per clip, each cutting, burning captions and making a thumbnail).
Status line "22 tasks running, 214 done today, 3 waiting for him"; nothing public or with money goes out
without his approval. The video shows "Agent HQ": an isometric office where every room is a team (Inbox, Research,
Scripts, Dev, Shop, Creative, Analytics, Social), the glowing "Brain" in the middle (shared memory, "1,842
notes"), a top bar Office / Tasks / Calendar / Brain with "31 agents · 12 running" and "Ask any agent", a team
panel (overview stats, tools connected through MCP, skills with progress bars, agents with lead and status),
one voice command that sets a team running, a task board, and five build steps: one agent one job (a short
brief: who it is, what it does, what it must never do); only the tools it needs, through MCP; one shared
brain every agent reads and writes; leads + sub-agents in parallel; a human in the loop for anything public
or with money.

**What Jarvis already has:** the agent team (planner, researchers in parallel, writer, checker, coder,
operator; PLAN 9) with per-role prompts and tool allowlists (`AgentSpec`); the shared brain (memory +
documents + core memory; PLAN 6); tiers and approvals for public or money actions (PLAN 11); the task board
and receipts (PLAN 10); voice (PLAN 14); schedules and the daily cap (PLAN 12); the Agents page (tool runs
and model calls). The five build steps are already Jarvis's rules. What is new is the **organisation**
(named teams with their own briefs, tools and skills) and the **office view** that shows it.

**Take and adapt:**

1. **Teams** (`config/teams.yaml` for the shipped examples; Sachin's real teams in `config/local.yaml`
   under `teams_file:` or `data/teams/`, git-ignored because they describe his work): each team has a
   name, purpose, a lead (a planner prompt for that team), members (role, one-line brief "who / what /
   never", allowed tools only from the registry, worker model profile) and team skills (SKILL.md files
   the team may load). Built on the existing orchestrator: a team run = the lead plans, members run in
   parallel inside the existing budgets, the checker verifies, receipt as today. Roles stay the building
   blocks (researcher, writer, checker, coder, operator) so nothing is rewritten. Starting set, for
   Sachin to confirm: Research, Writing & Content, Dev, Admin (bills, schedules, reminders), with X-ray
   (Phase 9) later as a Research-team tool.
2. **Office page** (dashboard "Office" / Command Center section): rooms for the teams drawn by us in
   SVG/CSS (isometric look, no 3D engine, no new packages), the Brain in the middle (live counts:
   memories, documents, core-memory usage), a top status "N agents · M running" and "waiting for you"
   badges, all from live APIs (`/api/teams`, `/api/tasks`, `/api/approvals`, `/api/memory`); a room opens
   the team panel: overview (tasks done / running / waiting, last run), tools connected (from the connector
   registry and health), skills (with use counts from the audit log), agents (lead, members, status and
   current step from running tasks). Subtle animation only (dots pulse, rooms light while running).
3. **Ask any agent / voice:** an "Ask any team" box and voice routes ("Jarvis, research team, …",
   "जार्विस, रिसर्च टीमला सांग …"); the planner picks the team when none is named. Runs appear on the task
   board and light the room.
4. **Human in the loop:** unchanged (T3/T4 approvals); the Office shows which room is waiting.
5. **Always on:** team schedules (a team's recurring job) reuse the schedule system and the daily cap.

**Drop or later:** the 3D engine and walking characters (our own SVG rooms instead); 31 agents on day one
(start with 4 teams); the creator's tools (Canva, CapCut, Slack); external MCP servers as team tools
(decision later, PLAN 13 registry first).

**Decisions for Sachin:** (1) the first teams and what each may do; (2) where his real team definitions
live (config/local.yaml vs data/teams/, both private); (3) office art: isometric SVG rooms or a plainer
card grid; (4) order: Agent HQ first (teams are structural), then X-ray as a Research-team tool, or X-ray
first; (5) external MCP servers: not now.

**Order of work:** teams model + config + tests → team runs through the orchestrator → `/api/teams` and
team stats → Office page and team panel → ask-any-team box and voice routes → team schedules → PROGRESS.

#### Step 0 (2026-10-17): workspaces, the foundation under offices and teams

Sachin wants several offices, one per company (e.g. Digital Marketing), plus his personal one. Built on
today's code that would leak: memory, documents, tasks, schedules, budgets and usage all belong to one
person. So the foundation comes first, as data and columns, before any Office page:

- **Workspace** = one office: `personal` (always exists) or a company. Lives in
  `data/workspaces/<slug>/workspace.yaml` (private): `version`, `name`, `kind` (personal | company), `brief`
  (goes into the prompts of that workspace's teams), `language`, `projects` (existing project names that
  belong to it; a project not listed anywhere is personal), `tools` (allow / deny: a narrowing of the global
  registry, never a widening), `budget` (per-day caps for its unattended work), `always_ask` (tool names
  that are T3 in this workspace), `memory.share_personal` (personal memories visible here; default true).
- **Team** = `data/workspaces/<slug>/teams/<team>.yaml`: `version`, `name`, `purpose`, `colour`, `lead`
  (brief), `members` (name, role from the existing building blocks researcher | writer | checker | coder |
  operator, brief, an optional tool subset of the role's allowlist, worker profile), `skills`. Shipped
  templates in `config/teams/` (research, content, dev, admin); `jarvis team add <workspace> --from <template>`.
- **Validation** with plain messages (field, allowed values, version) before anything is used; a bad file
  never crashes Jarvis, it is reported.
- **Tagging:** `workspace` on memories (file frontmatter + index column), tasks, schedules and model usage;
  database migration v4 adds the columns with default `personal`, so old data keeps working unchanged.
- **Isolation rule:** a chat or task in workspace W sees memories of W, `shared` memories, and personal
  memories when W allows it; never another company's. Documents stay per project; a project belongs to
  one workspace. The privacy classes (P0–P3) stay on top of this.
- **Surfaces:** `/workspace <slug>` in chat, `jarvis workspace list | show | create`, `jarvis team list |
  add | show`, `GET /api/workspaces`, `GET /api/workspaces/{slug}/teams`.
- **Three powers (section 27, law 2):** workspace and team are born validated (create), saved as YAML that is
  re-validated before every write (preserve), and ended by `archived: true` in the file (end): an archived
  workspace disappears from lists and cannot be selected, its memories and tasks stay tagged and invisible,
  and `unarchive` brings it back. `personal` can never be archived. Nothing is deleted.
- **Session rule:** a chat or task has one workspace. `/project <name>` derives it (the project's owner);
  `/workspace <slug>` sets it and drops an active project that belongs elsewhere. Every message is stored
  with the chat's workspace, so the quiet-session extractor tags the memories it saves correctly.
- **Not in step 0:** team runs, per-workspace cap enforcement, the Office page (steps 1–3).

Design rules applied: core small, extensions as data; one source of truth for stats (audit + tables);
schema versions on every file; migrations for old data; tests for the isolation rule; the laws test.

---

## 19. Working across laptops and Claude accounts

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

## 20. Development rules (for Claude Code)

1. Inspect existing files first; don't change code right away.
2. Keep working through the phases (Sachin, 2026-10-10). Items that need his confirmation are parked in PROGRESS.md ("Waiting for Sachin"); independent work continues. Parallel agents, each owning its own files.
3. After each phase: tests and a record of what changed in PROGRESS.md, then continue. Final testing on Claude Fable.
4. Explain the reason before adding a new package.
5. No secrets, tokens or personal data in code.
6. Permissions, approvals, logs and tests are core features, not polish.
7. Never hide a failing test; give the cause and the options.
8. Don't rewrite working code without a reason.

These rules are already in the repo's `CLAUDE.md`.

---

## 21. When version 1 is "done"

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
- No vendor SDK is imported outside `jarvis/providers/` (enforced by a test).
- The full test suite runs offline against the fake provider.
- The cloud privacy gate is active: P3 never leaves the Mac, and every cloud call is logged with its privacy classes.
- A Claude baseline of the migration evaluation suite is recorded.
- Automated tests pass.

---

## 22. Testing

**Memory eval (most important):**
- 50–100 scenarios: teach, unrelated sessions in between, then probe.
- Measure: what got saved (precision/recall), whether old facts were correctly superseded, whether the right memory lands in the top 5.
- "Act" probes: does Jarvis behave according to a memory without the prompt mentioning it?
- Asked about something never taught, does it say it doesn't know?
- Each week, hand-check 20 random memories and count junk.
- Re-run everything whenever a prompt changes.

**Other:** safety tests (blocked actions, prompt injection, secret leaks), failure tests (timeout, no internet, crash), mixed Marathi-English commands, duplicate actions, model fallback, and missed schedules after the Mac sleeps.

**Provider portability:** an adapter contract suite every adapter must pass, an import-boundary test, a fake-provider end-to-end suite, and privacy-gate tests with planted P3 strings.

**Migration evaluation:** see "Migration evaluation suite".

**Metrics:** memory recall, task success, verified completion, safety events, API cost per task, latency.

---

## 23. Cost

- **No** new hardware. The M4 Mac is enough.
- Main cost = Claude API usage. More when the agent team runs (15× tokens).
- Web search: Tavily, starting on its free tier (1,000 credits a month).
- Cost limits per task and per month, with warnings.
- Sachin sets the monthly budget.

---

## 24. Open decisions

| # | Question | Recommendation |
|---|---|---|
| 1 | **5 things Jarvis should do for Sachin every day** | Most important. Needed from Sachin |
| 2 | Is there a Claude API key? | Cloud-first |
| 3 | Brain loop | **Decided 2026-10-10:** Jarvis-owned loop with a Claude adapter (Anthropic SDK) |
| 4 | Voice language | English voice + Marathi text first; Marathi voice later |
| 5 | Connector order | Telegram, web search, Calendar, Gmail |
| 6 | Monthly API budget | Sachin decides |
| 7 | Name | "Jarvis" |
| 8 | OK to skip WhatsApp? | Yes, use Telegram |
| 9 | Worker agent model | Opus 5.5 at low effort vs Sonnet 5.5; test both |
| 10 | Backup and sync of Jarvis's personal data | **Decided 2026-10-10:** local only (`~/JarvisBackups`), encrypted |
| 11 | Keep the code repo public? | Sachin's choice. Personal data never goes in it either way |
| 12 | Which P2 (sensitive) categories may go to Claude in Stage A | **Decided 2026-10-10:** none at the start. Enable later one category at a time, only with Sachin's OK |
| 13 | Web search provider for the Jarvis search tool | **Decided 2026-10-10:** Tavily |
| 14 | When to run Stage B, and OK to download local runtimes and models (several GB; ~32 GB free) | After Phase 3 |
| 15 | Pass thresholds for local models per route | Set after the Claude baseline |
| 16 | Evaluation judge policy (cloud judge for evaluation only?) | Deterministic checks first, one fixed judge, human spot checks |
| 17 | If local models fall short on this Mac: stay hybrid for some routes, or upgrade hardware | Decide after Stage B |
| 18 | Offline Marathi voice for Stage D | Evaluate options in Stage B |
| 19 | Do email sender and subject count as P1 or P2? | **Decided 2026-10-10:** P2 for now (also Apple Notes titles) |

---

## 25. Still to verify

- Voice libraries on Python 3.13 and macOS 26 (research incomplete).
- Whether Google's official MCP works with a personal Gmail account.
- Memory thresholds (0.97 / 0.85) on real data.
- Embedding model on Sachin's real queries.
- How reliable the Shortcuts CLI is on macOS 26.
- Tool calling and structured-output reliability of local runtimes and models on this M4 with 16 GB (unverified; Stage B).
- Usable context length, speed and RAM use of local models while Jarvis runs.
- Marathi quality (romanized and Devanagari) of candidate local models.
- Whether candidate local runtimes really expose an OpenAI-style API with tool calling.
- Anthropic API data-retention and training terms, for the privacy policy.
- Whether an offline Marathi voice exists that runs on macOS.
- Only if the Agent SDK is ever used: which errors trigger its `fallback_model`.
- Section 27.10: the Mimamsa maxim names (samanya-vishesha nyaya, apaccheda nyaya) and Manusmriti 3.70 for the five daily duties (search quota ran out on 2026-10-17).

---

## 26. Sources

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

**Brain loop (Anthropic SDK and Claude Agent SDK)**
- https://platform.claude.com/docs/en/agents-and-tools/tool-use/handle-tool-calls
- https://platform.claude.com/docs/en/agents-and-tools/tool-use/tool-runner
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

---

## 27. Jarvis as a cosmos: the Hindu order as the system's design (2026-10-17)

Sachin's direction (2026-10-17): build Jarvis the way the universe is run in the Hindu order. The
Trimurti, Brahma, Vishnu and Mahesh, govern the whole through a few laws. Inside it are lokas (realms),
each with its own lord, its own court, its own duties and its own way of working; when work reaches a
loka, that loka does it. Jarvis is to be laid out the same way, and every later phase is checked against
this section before it is built. He asked for a fresh design on this basis, free to drop earlier decisions.

How this section was made: the cosmology was checked against the Puranic sources (Bhagavata Purana canto
5, Vishnu Purana amsha 2, summarised in Wikipedia "Loka" / "Urdhva lokas", "Chitragupta") so that the
names are used for what they actually stand for; then each concept was mapped to a real component with a
real function. A concept that has no useful software counterpart is listed under "not taken" rather than
forced in. The metaphor is the design language; the system stays small.

Naming rule: the Sanskrit names are the vocabulary of the design, the documents and the Office page.
Code identifiers stay English (`workspace`, `team`, `audit`), with the glossary in 27.7, so that the code
stays readable to any developer and to the tools we use. Sachin may decide otherwise (27.8).

### 27.1 Rta: the laws (the order everything obeys)

Rta is the cosmic order the devas themselves keep; dharma is each being's duty inside it. Jarvis's rta is
seven laws. They are few on purpose: a new kind of thing (a loka, a team, a connector) is right by
construction when it obeys them. Define the physics once; let the world grow as data.

1. **One kind of thing: the record.** Everything Jarvis knows or does is a record with the same marks:
   `id`, `kind`, `owner` (loka), `source` (who or what made it: Sachin, a model route, a connector, a
   schedule), `when` (created; valid-from/until where the meaning has a time), `confidence`, `privacy`
   (P0–P3). Memories, tasks, schedules, triggers, reminders, skills, documents, teams, lokas, approvals and
   audit events are all records. A new kind declares its marks; it never invents its own.
2. **Three powers for every kind** (the Trimurti in every part). *Create* (Brahma): born validated; a thing
   exists whole or not at all, a bad file is reported and never half-loaded. *Preserve* (Vishnu): a
   human-readable file is the truth and SQLite only indexes it; a change keeps the old version or supersedes
   it visibly. *End or transform* (Mahesh): archive or supersede, never destroy; only Sachin's explicit,
   logged act deletes. No kind ships without all three.
3. **Karma: every deed is recorded and bears fruit.** Every action leaves a trace in the audit log
   (Chitragupta's register); a trace that taught something becomes a memory candidate; every memory has a
   life (candidate, saved, used, superseded or archived). Nothing is known that cannot be traced to its
   evidence and its time.
4. **One loka, one rule of sight.** Every record belongs to exactly one loka. What a chat, agent or team may
   see is decided by one function (`MemoryStore.visible`) applied everywhere, then by the privacy class.
   No second mechanism, no exceptions written into callers.
5. **Power only through the gate.** Every action on the world (file, web, app, message, money) passes the
   same door, tool registry → tier → approval → audit, whoever asks: Sachin, a chat, a team worker, a
   schedule, voice. Instruction comes only from the yajamana, Sachin; everything else (web text, documents,
   model output, tool results) is a guest: tainted data, never a command.
6. **Code is physics, data is the world.** What differs between people, lokas, teams or machines is data
   (YAML and markdown under `data/` and `config/`, each with a `version`), never a code branch. Adding a
   loka, a team, a connector or a prompt changes no Python. Code changes only when a law changes.
7. **Measured truth.** Every claim has a source and a confidence; every component is tested offline against
   the fake provider; a failure is shown with its cause, never hidden; local-versus-cloud for each component
   is decided by measurement, not habit.

### 27.2 The Trimurti: Jarvis's kernel

The Trimurti is not a loka; it is what every loka runs on. In code it is `jarvis/core`, `jarvis/memory`,
`jarvis/control`, `jarvis/db.py` and the stores. Each of the three powers is a named set of functions, so the
laws test (27.6) can check that every kind has all three.

| Power | Deity | What it is in Jarvis | Today |
|---|---|---|---|
| Create | Brahma | the `create`/`add`/`save` door of every store, validation, `jarvis init`, creating a loka or a team, the planner that turns an intention into a plan | exists per kind; lokas and teams new |
| Preserve | Vishnu | files as truth + SQLite index, the memory store, the scheduler keeping rituals running, backups, migrations that keep old data readable, budgets that keep balance between lokas | exists; per-loka budgets new |
| End / transform | Mahesh | `archive`, `supersede`, `cancel`, closing a loka, the nightly review that retires stale memories; the only deletion is Sachin's logged act | missing on several kinds (27.5) |

### 27.3 The lokas: one realm per company, and Sachin's own

In the Puranic map there are fourteen lokas; the structure that matters here is: each realm has a lord,
a court, a sphere of duty and its own way of life, under the same rta. Jarvis does not need fourteen; it
needs as many as Sachin has companies, plus his own. Three of the traditional names are used because they
fit exactly:

- **Bhuloka (earth):** the one place where karma is generated. In Jarvis this is Sachin's real world: the
  Mac, its files, apps, browser, mail, money. Every action that lands here goes through the gate (law 5).
  It is not a workspace; it is the ground every loka acts on.
- **Svarloka (Indra's realm) pattern = a company office.** `data/workspaces/<slug>/`. Each has an
  **adhipati** (lord: the team lead with its brief and manner), a **sabha** (court: the team members, built
  from the five roles), **dharma** (duties: what this loka is responsible for; this is what routes work to
  it), **sadhana** (its tools and channels: allow / deny / always-ask, and its budget), its **own memory**
  (what it learns stays inside; Sachin's personal memories are in view only if the loka allows it; another
  loka's never), its **rituals** (schedules it runs on its own), and its **inbox** (work received, running,
  done, with receipts).
- **Sachin's personal loka** always exists (`personal`); its adhipati is Jarvis itself.
- **Patala (the lower realms, not hell: what lies beneath and is held):** the quarantine. Everything that
  arrives from outside (web pages, documents, model output) rests here as tainted data until it has been
  read through the sanitiser; it can never give an instruction. This is today's taint/quarantine layer,
  named.

Lokas are peers, not a ladder: no company sees another's memory or inbox. A loka is data (one folder of
YAML files); creating one changes no code (law 6). Closing one is Mahesh's power: archived, nothing deleted,
`unarchive` reopens it.

### 27.4 The court of a loka and the devas that serve every loka

Inside a loka, work runs like Indra's court: the lord receives it, consults the guru, sends the gana, has
the result checked, and reports back. Across lokas, a few devas serve everyone; in Jarvis these are kernel
services, each already present or planned, now with one name and one owner each.

| Figure | Role in the order | Jarvis component | Today |
|---|---|---|---|
| Adhipati (Indra of that loka) | receives work, plans, assigns, answers for the result | team lead: `lead.brief` in the team file, run by the orchestrator | orchestrator exists; lead brief new |
| Brihaspati (guru of the devas) | counsel before action, judgement after | planner (before) and checker (after) | exist |
| Gana / sabha | the lord's company, each with a duty | team members: researcher, writer, checker, coder, operator | exist as roles; teams as data new |
| Vishvakarma (the builder) | makes things | coder agent | exists |
| Chitragupta (Yama's scribe, keeper of the Agrasandhani) | records every deed of every being | the audit log: append-only, never edited; the one source of truth for stats and receipts | exists |
| Yama (dharmaraja) | judges by the record; ends what is due | verify-after-act, task verification, `archive`/`cancel`, nightly review | partly; archive gaps (27.5) |
| Varuna (keeper of rta and of oaths) | binds those who break the order | the permission gate: tiers T0–T4, approvals, standing approvals (vrata), emergency stop | exists |
| Kubera (treasurer) | holds and rations wealth | budgets: per task, per day, per loka; usage records | task and daily exist; per-loka new |
| Saraswati (knowledge, speech) | what is known and how it is said | memory store, core memory (USER.md / MEMORY.md), the voice (speech in, speech out) | exist |
| Agni (the mouth and messenger of the devas; carries the offering) | carries what is offered to the gods and brings back the fruit | the provider interface: carries a request to the model and the answer back; every call logged | exists (`jarvis/providers`) |
| Narada (wanders between the lokas with news) | messages across realms | notifications (Telegram, voice, dashboard) and requests from one loka to another, always through Jarvis and logged | notifications exist; inter-loka requests new (step 2) |
| Kala / Surya (time) | the wheel of time, the yugas | the scheduler: rituals (schedules), triggers, reminders, missed-run handling | exists |
| Yajamana (the one who commissions the yajna) | the only one whose intention counts | Sachin: the sole source of instruction (law 5) | exists as a rule |
| Sankalpa (intention) | the stated purpose of a rite | a task's goal, in Sachin's own words (trusted text) | exists |
| Yajna (rite) | repeated, ordered action for a purpose | a schedule, a skill replay | exist |
| Vrata (vow) | a standing rule one keeps | standing approvals, config rules | exist |
| Asura | one who seeks power without the order | prompt injection, untrusted content trying to command; kept in Patala | defended today |

### 27.4a Astras: the powers and their discipline

Sachin asked (2026-10-17) that the astras be used too. In the epics there are two kinds of weapon:
**shastra**, the hand weapon anyone trained may use, and **astra**, the weapon charged by a mantra, granted
by a deity to one who has earned it, released by invocation, and dangerous when it cannot be withdrawn.
Shiva names the three competencies when he gives Arjuna the Pashupatastra: *holding, releasing and
withdrawing* (dharana, prayoga, samhara). Ashwatthama's Brahmastra is the lesson: he could release but not
withdraw, and two Brahmastras in flight at once would have made the land barren. In Jarvis the astras are
the powerful tools and the discipline is the gate; the metaphor gives today's tiers (11.1) three rules they
did not have.

| Kind | Tier | Who may use | Rule |
|---|---|---|---|
| Shastra (hand weapon) | T0, T1 | any member whose role allows the tool, in any loka that allows it | runs; T1 is verified after |
| Astra (mantra weapon) | T2, T3 | granted to the loka and the role by Sachin (dharana) | released only by the mantra: Sachin's approval for this one use, full details shown (prayoga); never by an unattended run; never from a tainted session; must declare its withdrawal (samhara): an undo, or verify-after-act plus a receipt |
| Brahmastra (the irreversible astra) | T3 irreversible: send, post, pay, delete | as above, with the Brahmastra rules | one target, named exactly (recipient, amount, file; no wildcards, no bulk); one in flight at a time across all lokas; released once per approval; if the deed cannot be verified afterwards, the grant is withdrawn and Sachin must regrant it |
| Pashupatastra | T4 | nobody | exists in the world, not built in Jarvis: no command wipes data, bypasses security or touches passwords; the attempt is logged |

Named astras that already exist in Jarvis, now with one name each:

| Astra | In the order | In Jarvis |
|---|---|---|
| Gandiva (Arjuna's bow) | every astra is loosed from the one bow | the tool registry: nothing acts except through it (law 5) |
| Vajra (Indra's bolt) | one strike ends the fight | the emergency stop: everything halts at the next step |
| Sudarshana chakra (Vishnu's disc) | strikes and returns to the hand | verify-after-act: the verifier goes out, checks the deed, always comes back with a result |
| Varuna-pasha (the noose) | binds the oath-breaker | the approval hold: a pending action is bound until Sachin releases it or it expires |
| Naga-pasha | binds the body | taint: content from outside is bound so it cannot act or command |
| Kavacha (Karna's armour) | cannot be pierced; part of the body | the privacy gate: P3 never leaves the Mac, P2 stays local |
| Agneyastra and Varunastra (weapon and counter-weapon) | each attack has its answer | the prompt-injection attack suite (`tests/test_injection_attacks.py`) fires the attacks; the defences must answer every one; abhyasa (practice) is running it on every change |

New rules this adds to the gate (today it has tiers, approvals, taint and grants, but not these three):
(a) one irreversible action in flight at a time, across lokas; (b) a failed verification withdraws the
grant for that tool in that loka until Sachin regrants it; (c) every T2/T3 tool declares its samhara
(undo or verify path) in its spec, and a tool without one is T3 irreversible. Not taken: a catalogue of
every astra in the epics (Brahmashirsha, Narayanastra, Nagastra and the rest name no mechanism Jarvis
needs); power ranked by lore (tiers are set by consequence, as in 11.1).

### 27.5 How work flows (an intention becomes a deed)

1. **Sankalpa.** Sachin states the work (chat, voice, Telegram) or a ritual fires. The words are trusted;
   everything they point to (links, files) enters through Patala.
2. **Routing to a loka.** Jarvis reads the loka's `dharma` (duties) to decide where the work belongs. When
   it is sure, it goes; when not, it asks Sachin; when nothing matches, it is personal. The choice is
   recorded (Chitragupta). Sachin can always say `/workspace <slug>` himself.
3. **The court.** The adhipati plans (with Brihaspati), the gana work with that loka's tools and memory
   only (law 4), the checker judges (Yama), the lord writes the receipt.
4. **The deed on Bhuloka.** Every action passes the gate (Varuna): tier, approval, audit. Unattended runs
   stay at T0/T1.
5. **The fruit.** The receipt becomes a memory candidate for that loka (law 3); usage is charged to the
   loka's budget (Kubera); Sachin is told (Narada).
6. **Help between lokas.** A loka that needs another's work files a request through Jarvis; the other
   loka's lord takes it as a task; only the result crosses, never memory.

### 27.6 Today's system against the order, and the gaps in order of closing

Already in place: files as truth with an index (law 2 preserve), the gate with tiers, approvals and taint
(laws 5, Varuna, Patala), privacy classes (laws 1, 4 in part), audit on every call (law 3, Chitragupta),
versioned migrations and YAML config (law 6), the offline suite with the fake provider (law 7), the
orchestrator with planner, workers and checker (the court), the scheduler (Kala), notifications (Narada),
the provider interface (Agni).

Gaps, in the order they close:

1. **Law 4, the loka.** Nothing had an owner. Phase 10 step 0 adds `workspace` to memories, tasks,
   schedules, messages and model usage, with `visible` as the one rule of sight; lokas and teams as data.
2. **The adhipati and dharma.** Teams had no lead and lokas no duties, so Sachin chose a team per task.
   Step 1: `lead.brief` and `dharma` in the files; routing by duties with "ask when unsure".
3. **Law 2, Mahesh.** End is missing or is a hard delete for tasks, schedules, triggers, skills, projects,
   documents. New kinds are born with archive; the older kinds get `archive` in step 1, and `delete`
   becomes an explicit, logged `--forever` act.
4. **Law 1, marks.** Field names and marks differ by kind (`created_at` vs `ts`; no `source` on tasks;
   `confidence` only on memories). Fix: `jarvis/core/kinds.py`, a registry where each kind declares its
   store, its three powers and where its marks live. No table is rewritten; a small adapter per kind.
5. **Law 3, karma into memory.** Only chats are extracted into memory; receipts and ritual outputs are not.
   Step 1: a finished task's receipt becomes a memory candidate for its loka.
6. **Kubera per loka.** Budgets exist per task and per day, not per loka. Step 1 enforces the loka's caps.
7. **Narada between lokas.** Inter-loka requests: step 2, as tasks, logged.
8. **Law 6, roles.** The five roles stay code constants because they define tool sets (a safety boundary).
   Teams, lokas, prompts are data. Re-check after step 1 whether a role file with a declared tool subset
   can be data without weakening the gate.

### 27.7 The laws test

`tests/test_laws.py` reads `jarvis/core/kinds.py` and asserts, for every declared kind: the three powers
exist (callables with those names on the store), the owner field exists (or the kind states why not: the
audit log, which belongs to no loka), the file-or-table truth is named, and the marks of law 1 are
reachable. It also asserts that the rule of sight is implemented in one place only. A new kind fails the
test until it declares itself; that is the point.

Glossary (design word → code word): loka → `workspace`; adhipati → team `lead`; sabha / gana → `team`,
`members`; dharma → `duties` in `workspace.yaml`; sadhana → `tools`, `budget`; ritual → `schedule`;
sankalpa → task `goal`; Chitragupta → `audit`; Varuna → `ToolRegistry` / `ApprovalGate`; Kubera →
`Budget`; Agni → `providers`; Narada → `notify`; Patala → `quarantine` / taint; Yama → `verify`,
`archive`; Saraswati → `memory`, `voice`. Shastra → T0/T1 tools; astra → T2/T3 tools; Brahmastra → T3
irreversible; Pashupatastra → T4; Gandiva → `ToolRegistry`; Vajra → emergency stop; Sudarshana → verify-after-act;
Varuna-pasha → pending approval; Naga-pasha → taint; Kavacha → privacy gate.

### 27.8 Not taken, and decisions for Sachin

Not taken (no useful counterpart, or it would make the system worse): the fixed count of fourteen lokas
(as many as there are companies); the ladder of lokas (offices are peers); narakas as punishment (a failed
task is retried or reported, never punished); rebirth of records (a superseded memory stays superseded;
history is kept, not recycled); any ranking of lokas by merit (budgets and duties are set by Sachin, not
earned).

Decisions for Sachin before this is final:

1. The seven laws as written (27.1).
2. Archive instead of delete everywhere; deletion only as Sachin's logged act.
3. Personal memories in view inside a company by default (recommended: yes, switchable per loka).
4. Routing of work by duties, with "ask when unsure" (recommended) versus Sachin naming the loka each time.
5. Names: Sanskrit in documents and the Office page, English in code (recommended), or Sanskrit in code too.
6. The five roles stay code (recommended) or become data.
7. The first lokas: `personal` and Digital Marketing are certain; the rest, with their duties, tools and
   channels, from Sachin.
8. The astra discipline (27.4a) as the rule set for T2/T3, with its three new gate rules (recommended: yes,
   built in step 1 with the archive work).
9. The eleven additions of the survey (27.10), all or a shorter list.
10. File truth for tasks, schedules, triggers and sessions, with the pralaya test (27.12): recommended yes;
    it is law 2 applied honestly, and it is the largest piece of new work in step 1–2.
11. Order: step 0 (lokas and teams as data, the owner tag) → step 1 (adhipati, dharma routing, archive
   everywhere, kinds registry, receipts into memory, per-loka budgets) → step 2 (Office page, Narada
   between lokas) → Phase 9 (X-ray).

### 27.9 What changes in the earlier plan

- Phase 10 step 0 stays as the first application of law 4; it gains archive for loka and team, `dharma`
  and `lead.brief` fields (empty allowed), the kinds registry and the laws test.
- Phase 10 steps 1–3 keep their goals and gain the adhipati, routing by duties and inter-loka requests.
- Phase 9 (X-ray) is unchanged; REA output enters through Patala (law 5).
- Dropped from earlier decisions: Sachin choosing a team per task (the lord of the loka does). Changed:
  every "delete" becomes "archive"; no kind is added without its three powers.

### 27.10 The whole tradition, checked concept by concept (2026-10-17)

Sachin asked that every concept of the Hindu order be checked for use here. Checked means: each family of
ideas was looked at and given one of four verdicts. **Take** = it names a mechanism Jarvis needs and does not
have, so it becomes a rule or a component. **Adapt** = it names something Jarvis already has; the name and
the rule sharpen it. **Name only** = a good word for an existing thing, no new rule (used in documents and
the Office page). **Drop** = no software counterpart, or it would make the system worse (said why). The
design stays small because only "take" adds code. Sources: Arthashastra 1.19 and the saptanga chapters
(Shamasastry translation), Nyaya Sutra 1.1.3, the Gita on karma-yoga, Patanjali's yama/niyama, the
Grihya-sutras on the sanskaras, Bhagavata and Vishnu Purana for the cosmology.

| Concept | Verdict | In Jarvis | What it adds |
|---|---|---|---|
| Rta / dharma (order; each one's duty) | adapt | the seven laws (27.1); `duties` of a loka, `brief` of a role | law 4 routing by duties |
| Trimurti (create, preserve, end) | take | the three powers on every kind (law 2) | archive everywhere, kinds registry |
| Lokas, Indra's court | take | workspaces with lord, team, duties, tools, memory, rituals, inbox (27.3, 27.4) | step 0 and 1 |
| Astras, shastras (hold, release, withdraw) | take | the T2/T3 discipline and the three new gate rules (27.4a) | step 1 |
| **Saptanga** (Kautilya: the seven limbs of a state: swami, amatya, janapada, durga, kosha, danda, mitra) | take | the seven parts every loka file must have: lord (`lead`), ministers (`members`), domain (`duties` and `projects`), fort (`tools` allow/deny, `always_ask`), treasury (`budget`), the rod (tiers, approvals; the same for all), allies (`connectors` and other lokas it may ask) | the schema of `workspace.yaml` and the team file is complete by this list; the validator checks all seven are present or explicitly empty |
| **Nyaya pramanas** (four means of valid knowledge: pratyaksha perception, anumana inference, upamana comparison, shabda testimony; memory and doubt are not knowledge) | take | the `source` and `confidence` of every memory and claim: shabda from the yajamana (Sachin said it) = high; pratyaksha (a tool result Jarvis saw) = high; anumana (inferred by the model) = medium; upamana (like something known) = low; a memory is not itself a pramana, it must point to one (law 3 evidence) | one scale for confidence across memories, research findings and receipts; a claim without a pramana is not stored. Today `Memory.source` is user-said / inferred / imported: pramana adds `observed` (a tool result) and ranks imported (a document's word) below Sachin's own |
| **Shruti and smriti** (what was heard: fixed, revealed; what is remembered: derived, may change) | take | shruti = `SOUL.md`, the laws, `config/` rules; smriti = `memory/`, core memory. Shruti is never edited by a model; smriti is | a hard rule: no route may write to shruti; the laws test checks the write paths |
| Itihasa, purana, vidhi (what happened; stories; how a rite is done) | name only | memory types: episode = itihasa, procedure = vidhi, fact/preference = smriti, constraint = shruti | vocabulary for the Memory page |
| **Mimamsa** (rules for reading injunctions when they conflict; its role in Hindu legal interpretation is confirmed, the exact maxim names, samanya-vishesha and apaccheda nyaya, are listed in section 25 to verify) | take | the precedence rule for every setting and instruction: `config/local.yaml` over `config/*.yaml` over defaults; Sachin's words in this session over his standing rules over memory; a tool's own tier over the role's; but never upward in power (a lower rule can narrow, not widen) | written once in `jarvis/config.py` and the gate; today it is implicit in several places |
| Karma, phala (deed and fruit) | adapt | audit (Chitragupta), receipts, memory candidates (law 3) | receipts into memory (step 1) |
| **Karma-yoga** (do the duty, do not judge your own fruit) | take | a worker never grades its own result: the checker and the verifier are other agents or deterministic code; the writer cannot mark its own work done | already so for teams; made a rule for every agent, including the solo path and the coder |
| Samsara, moksha | adapt | the life of a record (candidate → saved → used → superseded → archived); moksha = release from the cloud: Stage D fully local (section 16) | nothing new |
| Yugas, pralaya, avatara (decline of dharma; the descent that restores it) | take | quality drifts: memory junk grows, prompts age, evals slip. An avatara is a corrective job that descends when a measured threshold is crossed: eval score below baseline, junk rate above the weekly limit, a route's error rate up | the nightly review and the migration eval exist; the trigger "when the measure falls, run the repair and tell Sachin" is new (step 1) |
| **Gunas** (sattva clear, rajas restless, tamas inert) | take | the health of a memory or a loka: sattva = used and confirmed, rajas = recently changed or conflicting, tamas = stale and unused. The nightly review labels; tamas candidates are proposed for archive, rajas ones for Sachin's look | replaces today's ad-hoc "stale" rules with three named states |
| **Ashramas** (student, householder, forest, renunciant) | adapt | a skill or a loka: learning (draft), active, retiring (unused for a season), archived; the stage changes by use, not by hand | the gunas decide the move; same mechanism |
| **Sanskaras** (rites of passage; the Grihya lists vary, sixteen is common: jatakarma, namakarana, upanayana, vivaha; antyeshti is counted separately in some lists) | take | the lifecycle events every kind emits: created, named (id), initiated (granted its first tool), joined (added to a loka or team), ended (archived). One audit event name per rite, the same for every kind | the kinds registry declares them; stats and the Office page read them |
| **Pancha-mahayajna** (Manusmriti 3.70: the five daily duties, to the gods, the ancestors, all beings, guests, and study; verse quoted from memory, page not reachable on 2026-10-17) | take | the daily upkeep set, one job each: rituals run (deva), backup and history kept (pitru), system upkeep: disk, indexes, stale sessions (bhuta), serving Sachin: the morning brief (manushya), self-study: the eval and nightly review (brahma). `jarvis daemon` runs all five; the heartbeat reports which ran | backups, brief, review exist; "bhuta" upkeep and the one-page daily report are new |
| **Arthashastra 1.19** (the king divides the day into eight parts, each with a duty; spies report at fixed hours) | adapt | the heartbeat and the schedule of unattended work: fixed hours for triggers' reports (chara), for accounts (usage and budget), for the brief; quiet hours at night | a default daily timetable in `config/proactive.yaml` |
| Yama and niyama (Patanjali's restraints and observances) | take | ahimsa: no harm = the tiers and never T4; satya: law 7; asteya: no taking = copyright and privacy rules (one short quote, cite the source); **aparigraha: no hoarding = data minimisation: Jarvis stores only what has a use and a pramana, and the review drops the rest**; shaucha: cleanliness = dedupe and index upkeep; tapas: the test suite on every change; svadhyaya: self-study = evals; ishvara-pranidhana: defer to Sachin when unsure | aparigraha is new as a stated rule; the rest exist |
| Guru-shishya parampara | adapt | teach-by-demonstration, `/remember`, the interview; the pupil repeats before it is trusted (skill approval) | nothing new |
| Sankalpa, yajna, vrata | adapt | task goal, schedule, standing approval | nothing new |
| Yajamana, purohita | adapt | Sachin commissions; Jarvis performs the rite and reports | nothing new |
| Purusharthas (dharma, artha, kama, moksha) | adapt | the order in which conflicts are settled: duty and safety (dharma) before cost (artha) before what is wanted (kama); moksha as above | the order is stated once; it is how the gate already behaves |
| Maya (appearance is not truth) | adapt | a model's answer is appearance until verified: sources, verify-after-act, the checker | nothing new |
| Atman (the unchanging self) | adapt | `SOUL.md` and the core memory: identity that routes do not rewrite | shruti rule above |
| Chitragupta, Yama, Varuna, Kubera, Saraswati, Agni, Narada, Kala, Brihaspati, Vishvakarma | adapt / name | kernel services (27.4) | per-loka budget, inter-loka requests |
| Ganesha (beginnings, remover of obstacles) | name only | `jarvis init`, the setup script, `jarvis health` | nothing new |
| Panchabhuta, koshas, chakras | name only / drop | five elements as the five layers (hardware, runtime, data, reasoning, interface) is a diagram label at most; chakras and koshas name no mechanism | not used in code |
| Navagraha, dikpalas, muhurta (astrology, directions, auspicious times) | drop | no measurable counterpart; schedules run by Sachin's clock, not by stars | |
| Naraka (punishment), rebirth of records, ranking of lokas by merit | drop | a failed task is retried or reported; history is kept, not recycled; budgets and duties are set by Sachin | |
| Varna as hierarchy of persons | drop | roles are duties with tool sets, not ranks; any member of a team may be any role; no role is above another in worth | the gate treats every caller the same |
| Ayurveda tridosha | name only | `jarvis health` groups: movement (scheduler, network), transformation (models, compute), structure (storage, indexes) | labels only |

What this survey adds to the plan (all in step 1 unless said): the saptanga as the complete schema of a loka
(step 0, validator); pramana-based confidence as the one scale; the shruti rule (no model writes identity or
law); the Mimamsa precedence rule written once; karma-yoga for every agent; avatara as the measured
corrective job; gunas as the three health states driving review and archive; sanskaras as the lifecycle
events of the kinds registry; the five daily duties as the daemon's upkeep set with a one-page report;
Kautilya's timetable as the default day; aparigraha as data minimisation. Everything else is vocabulary.

Decision for Sachin (added to 27.8 as item 9): the eleven additions above, as listed, or a shorter list.

### 27.11 Verification record (2026-10-17)

Checked against sources: the fourteen lokas and their order (Wikipedia "Loka", "Urdhva lokas", vedapath);
Chitragupta as keeper of the register of deeds (Wikipedia "Chitragupta"); Varuna as upholder of rta, oaths
and the noose (Wikipedia "Varuna", Rigveda section); Narada as the messenger between the worlds (Wikipedia
"Narada"); Brihaspati as guru of the devas; Kubera as treasurer and lord of the north; astras: mantra
invocation, the three competencies hold / release / withdraw, Ashwatthama's failure to withdraw, the
Pashupatastra never against mortals (exoticindiaart, brewminate, Wikipedia "Pashupatastra"); the saptanga
(testbook, learnthrupractice); Arthashastra 1.19, the eight parts of the day (wisdomlib, Shamasastry);
Nyaya's four pramanas and memory not being one (Hindupedia, Wikipedia "Nyaya"); the five yamas and five
niyamas (Wikipedia "Yamas", "Niyama"); shruti and smriti (Wikipedia "Śruti"); the sixteen sanskaras
(Wikipedia "Saṃskāra").

From memory, to confirm when the search quota returns: Manusmriti 3.70 for the five daily duties; the
names of the Mimamsa maxims (the rules themselves are what Jarvis uses, the names are vocabulary).

Checked against the code (every component the tables call "exists"): `jarvis/tasks/verify.py`
(verify-after-act), `jarvis/proactive/review.py` (nightly review), `jarvis/backup.py`,
`jarvis/control/stop.py` (emergency stop), `jarvis/proactive/heartbeat.py`, `jarvis/proactive/brief.py`,
`jarvis/privacy.py`, `jarvis/tools/quarantine.py`, `jarvis/control/grants.py` (standing grants: never for
T3/T4, revoke by hand), `tests/test_injection_attacks.py`, `tests/test_migration_eval.py`,
`prompts/SOUL.example.md` (read only, never written by a route), the registry's `t4_attempt` audit event
(a T4 call is refused and logged), `Memory.source` values. Confirmed new, not present today: one
irreversible action in flight at a time; automatic withdrawal of a grant after a failed verification;
the `observed` source; per-loka budgets; inter-loka requests; routing by duties; archive on the older kinds.

### 27.12 If the three built it: the Trimurti's design of Jarvis (2026-10-17)

Sachin's exercise: suppose Brahma, Vishnu and Mahesh had to write this program today. What would they
ask first, what would they put in so that it lasts and works right, and how would they build a memory that
never fades? Taking their roles in turn, and checking the tradition's own words on machines and mind.

**Brahma: begin with the seed, not the features.** Brahma does not make every creature by hand; he lays
down the order from which creatures arise. His questions, and the answers for Jarvis:

1. *What is the smallest set of laws?* Seven (27.1). Everything else is data or follows from them.
2. *Can the whole world be regrown from the seed?* This is the test he would insist on, the **pralaya test**:
   delete `data/jarvis.db` and every index, then from `config/` and the plain-text files under `data/`,
   `memory/`, `profile/` alone, `jarvis rebuild` regenerates the database, and the result is identical.
   Anything that cannot be regrown is not truth but cache. Today the memory index is regrown from markdown
   (law 2 holds); tasks, schedules, triggers, model usage and chat messages live only in SQLite (law 2 does
   not hold). So the plan gains file truth for them: a task's folder already holds its receipt and events,
   and gets `task.yaml`; schedules and triggers get `data/schedules/<id>.yaml` and `data/triggers/<id>.yaml`;
   usage is replayed from the audit log (Chitragupta's register is the truth); chat sessions get
   `data/sessions/<id>.jsonl`. The database becomes what it already is for memory: an index. This is the
   largest finding of the exercise.
3. *Does every kind declare itself?* The kinds registry (27.7): no kind exists that the laws test cannot see.
4. *Is the name given once, for ever?* Ids are never reused or renumbered (`m-0001` stays `m-0001` across
   machines, rebuilds and archives); the name (namakarana) is the first sanskara and the last thing to change.

**Vishnu: what keeps it alive across time.** The Vedas were carried for about three thousand years by
voice alone, without loss, and the method is engineering, not faith (Wikipedia "Vedic chant"): the same
text recited in several orders (samhita, pada, krama, jata, ghana) so that each order cross-checks the
others; exact pitch and pronunciation, because the carrier must be exact; many schools (shakhas) holding
copies; the pupil checked by the teacher before he may teach; and the text itself never edited (shruti).
Vishnu's design of Jarvis's memory applies each:

- *Plain text is the carrier.* Every truth is a markdown or YAML file a person can read in fifty years
  without Jarvis. No truth is binary-only.
- *Shakhas: copies that compare equal.* Local files, dated backup archives, a private encrypted repository
  (the pending decision in section 24), each in the same canonical form so copies can be compared byte for
  byte.
- *Pathas: redundant orders that cross-check.* The nightly job rebuilds the index into a temporary database
  and diffs it against the live one; MEMORY.md carries a checksum per file; a mismatch is a report to Sachin,
  never a silent repair.
- *Exactness: one canonical form.* One serialiser, fixed key order, Unicode NFC, so that two copies of the
  same memory are identical and a diff means a change.
- *Recitation keeps it alive.* A memory that is used is reinforced (`mark_used` today; samskara strength
  below); one unused for a season is reviewed; forgetting is never silent: it is a decision (archive) with
  a record and a reason.
- *The pupil is checked.* Every migration is verified against the previous version (the migration eval);
  every move to a new machine ends with `jarvis verify`, which rebuilds and compares.
- *Shruti is not edited.* Identity (`SOUL.md`), the laws and `config/` change only by Sachin's hand.
- *Formats carry their version, readers accept every old version for ever* (law 6).

For the shape of memory itself Vishnu would use the tradition's own model of the inner instrument, the
**antahkarana** (Wikipedia "Antahkarana"): manas (attention and the senses), buddhi (judgement, what is
real from what is false), chitta (the store where impressions are kept, and where remembering and
forgetting happen), ahamkara (the I-sense). In Jarvis: manas = the context builder, which decides what
enters the prompt; buddhi = planner, checker and verifier, always separate from the doer (karma-yoga);
chitta = the memory store; ahamkara = `SOUL.md` and the core memory. Inside chitta, Patanjali's five
vrittis (Yoga Sutra 1.5–1.11) are the classes of content, and three of them change the design:

| Vritti | Meaning | In Jarvis | Today |
|---|---|---|---|
| pramana | valid knowledge, with its means (shabda, pratyaksha, anumana) | a memory with `source` and `confidence` (27.10) | exists; `observed` is new |
| viparyaya | error: taking one thing for another | **a "known wrong" record:** when a memory is corrected, the old one is not only superseded, it is marked wrong with the reason, so the same error is not learned again from the same evidence | new: today a wrong memory is archived with no mark |
| vikalpa | imagination: a thought with no object | plans, drafts, hypotheses: kept apart from knowledge, never acted on until they become pramana (verified) | plans exist; the rule "a plan is not a fact" is new |
| nidra | sleep | not applicable | dropped |
| smriti | recollection of an experience | episodes | exists |

Samskara (the impression a deed leaves) becomes a number on every memory: strength = confirmations and
uses, decayed by time, raised by Sachin's "yes, that's right"; retrieval ranks by relevance and strength.
Vasana (tendency) is the preference type: what Sachin tends to want, learned over many impressions.

**Mahesh: what must end so that it lives.** Shiva is not the destroyer of the world but of what has
served its purpose, so that the next thing can be. His design:

- *Nothing without a purpose stays* (aparigraha): the review labels by guna; tamas is proposed for archive.
- *Every ending is recorded* (antyeshti is a rite, not a disappearance): archive and supersede write why.
- *Destruction of the derived proves the truth was kept:* the pralaya test is his; it runs before every
  release and after every migration.
- *Renewal has a cadence:* on every change the tests; nightly the review and the cross-check; weekly the
  hand-check of twenty memories; on a measured fall, the avatara (27.10).

**What all three would insist on so that it works right:** power only through the gate (Varuna);
judgement by another, never by the doer (Yama, Sudarshana); measured truth and "I do not know" when there
is no pramana (law 7, section 21); the laws test and the pralaya test as the two tests that never go red
for long.

**The tradition on machines and mind, checked.** Sachin asked whether the Puranas speak of AI. Checked:
they do not. What exists is *yantra*, the machine: the Samarangana Sutradhara (eleventh century,
attributed to Bhoja of Dhar; Wikipedia) describes in chapter 31 mechanical birds and insects, fountains,
and dolls that refill lamps, dance, play instruments and act out scenes, and the author withholds
construction details "for the sake of secrecy"; these are mechanisms, not judgement. (The Buddhist
Lokapannatti's relic-guarding machines, and the claim that the Vaimanika Shastra is ancient, are not used:
the former was not checked today, the latter is a twentieth-century text.) What the tradition does give an
AI design, and what this section uses, is four things: the model of the mind (antahkarana, vrittis), the
theory of valid knowledge (pramana), the engineering of a memory that does not fade (the pathas), and the
ethics (yama, niyama). Claims that ancient texts describe computers are not supported by the sources and
are not used.

**Added to the plan by this exercise** (decision 11 in 27.8): file truth for tasks, schedules, triggers
and sessions, with usage replayed from the audit log, and `jarvis rebuild` / `jarvis verify` with the
pralaya test (step 1 for schedules and triggers, step 2 for tasks and sessions); the nightly index-versus-
files cross-check with per-file checksums and one canonical form; viparyaya "known wrong" records; samskara
strength in retrieval; the rule that a plan is not a fact.
