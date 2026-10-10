# Open-source and indie personal AI assistants / agents (state as of 2026-10-10)

Research notes. Most project facts come from READMEs and docs. Several come from third-party blogs and listicles, which are marked as such. Star counts are snapshots and differ between sources.

## Feature inventory per project

### Takeaway
The 2026 "personal agent" category is dominated by OpenClaw and Nous Research's Hermes Agent. Both are always-on gateways that combine chat channels (Telegram, WhatsApp, Signal, Discord, Slack), a heartbeat or cron loop, file-based skills, persistent memory and MCP. The older projects split into narrower niches: memory servers (Letta), knowledge and second-brain tools (Khoj), chat front ends (Open WebUI, LobeChat, AnythingLLM, Jan), desktop dev agents (Goose, Open Interpreter), workflow engines (n8n, AutoGPT) and voice and smart home (Home Assistant, OVOS, Leon).

### Cited Findings

**OpenClaw** (formerly Clawdbot, then Moltbot; TypeScript)
- Self-hosted gateway with 50+ messaging integrations and full system access. About 160K stars, about 430K lines of code, 1GB+ RAM. — [rywalker.com landscape (third-party)](https://rywalker.com/openclaw-alternatives-2026)
- Heartbeat: a "system-owned automation" that runs periodic agent turns in the main session, and the model decides whether anything needs attention. The default interval is 30m, or 1h when Anthropic OAuth or token auth is configured. `activeHours` sets start and end times with a timezone. The default delivery target is `owner`, a DM to the first allow-listed owner and never a group. Without a route the run is skipped with `reason=no-route`. — [OpenClaw docs: Heartbeat](https://docs.openclaw.ai/gateway/heartbeat)
- How heartbeat stays quiet: the default prompt tells the agent to reply `NO_REPLY` when nothing needs attention, or to call `heartbeat_respond` with `notify:false`. The legacy `HEARTBEAT_OK` token is dropped when the rest of the reply is 300 characters or fewer. An empty checklist skips the run (`reason=empty-heartbeat-file`). — [OpenClaw docs: Heartbeat](https://docs.openclaw.ai/gateway/heartbeat)
- HEARTBEAT.md is no longer read at runtime. `openclaw doctor --fix` imports it into a "scratch" checklist stored in the database. The docs say "Monitor scratch is prompt context, not a scheduler", and recurring checks should be separate cron automation jobs, each with its own schedule and run history. — [OpenClaw docs: Heartbeat](https://docs.openclaw.ai/gateway/heartbeat)
- Heartbeat cost: each heartbeat is a full agent turn. Setting `isolatedSession:true` drops a run from about 100K tokens to about 2–5K. `lightContext`, a cheaper model and `target:none` are also recommended. — [OpenClaw docs: Heartbeat](https://docs.openclaw.ai/gateway/heartbeat)
- Skills marketplace: ClawHub, with 2,857 skills at the time of Koi's audit (early February 2026). One critical analysis says it later held over 31,000 skills, with no mandatory review, no static analysis at publish time and no verified publisher program. — [The Hacker News](https://thehackernews.com/2026/02/researchers-find-341-malicious-clawhub.html); [vibecoding.app (third-party)](https://vibecoding.app/blog/openclaw-clawhub-skills-security)
- Its core runs on "Pi", a minimal agent with four tools (read, write, edit, bash). — [rywalker.com](https://rywalker.com/openclaw-alternatives-2026)
- Docker tool sandboxing is optional. Full system access is the default. — [The Hacker News, 2026-02-08](https://thehackernews.com/2026/02/openclaw-integrates-virustotal-scanning.html)

**Hermes Agent** (Nous Research, Python)
- One gateway process serves Telegram, Discord, Slack, WhatsApp, Signal and the CLI. The docs table also lists Email and Home Assistant. — [GitHub README](https://github.com/nousresearch/hermes-agent)
- Memory: "agent-curated memory with periodic nudges", Honcho dialectic user modelling, and FTS5 session search with LLM summarization. — [GitHub README](https://github.com/nousresearch/hermes-agent)
- Memory files: bounded memory in `MEMORY.md` and `USER.md`, about 800 and 500 tokens respectively. — [tosea.ai guide (third-party)](https://tosea.ai/blog/hermes-agent-self-improving-ai-guide)
- Skills: created by the agent after complex tasks and improved during use. Compatible with the agentskills.io open standard. — [GitHub README](https://github.com/nousresearch/hermes-agent)
- Built-in cron scheduler that delivers to any platform. 40+ tools. MCP client. Isolated subagents for parallel work. Seven terminal backends: local, Docker, SSH, Singularity, Modal, Daytona, Vercel Sandbox. — [GitHub README](https://github.com/nousresearch/hermes-agent)
- Safety: command approval, DM pairing, container isolation. — [GitHub README](https://github.com/nousresearch/hermes-agent)
- Voice: voice-memo transcription. TTS and a cloud browser (Browser Use) through the Nous Portal Tool Gateway. — [GitHub README](https://github.com/nousresearch/hermes-agent)
- About 252K stars and 54.6K forks at fetch time. The fetched page listed no formal releases. — [GitHub README](https://github.com/nousresearch/hermes-agent). Launch date is disputed: one source says 2026-02-25, another says early 2025. — [WebSearch summary of third-party sites](https://hermes-agent.nousresearch.com/)

**Smaller "claw" variants** (stars from [rywalker.com](https://rywalker.com/openclaw-alternatives-2026), third-party)
- NanoBot (Python, about 4K lines, 8 channels, 22K stars).
- ZeroClaw (Rust, WASM sandbox, credential encryption, prompt-injection defence, 16K stars).
- NanoClaw (Docker or Apple Container isolation).
- Moltis (Rust single binary, MCP multiplexing, SQLite).
- ZeptoClaw ("seven security layers on by default").
- Lobu (gateway-proxied MCP that keeps secrets away from workers).
- LettaBot (memory-first, built on Letta).
- droidclaw (drives an Android phone over ADB).

**Letta (MemGPT)**
- Memory "blocks": labelled sections of the context window, each with a character limit, that can be shared between agents.
- Sleep-time agents: a background agent that rewrites the main agent's memory asynchronously. The docs mark this as experimental.

Source: [Letta docs: sleep-time agents](https://docs.letta.com/guides/agents/architectures/sleeptime)

- Letta Code: open-source, stateful terminal coding agent. Memory persists across `/clear` and `/new`. — [Letta Code docs](https://docs.letta.com/letta-code)
- Criticism: agent logic lives inside Letta's server model, which makes migrating away harder than leaving a library. — [mausbot.com (third-party)](https://mausbot.com/blog/best-self-hosted-ai-agents)

**Khoj**
- Reachable from a browser, Obsidian, Emacs, desktop, phone and WhatsApp.
- Scheduled automations deliver newsletters and notifications by email.
- Deep research mode, custom agents, and semantic search over PDF, Markdown, Notion, Word and org-mode files.
- Local or online LLMs. 37.6K stars.

Source: [GitHub](https://github.com/khoj-ai/khoj)

- Built around documents rather than acting on email, calendar or apps. AGPL-3.0. — [mausbot.com](https://mausbot.com/blog/best-self-hosted-ai-agents)

**Goose** (Block, now under the Linux Foundation Agentic AI Foundation)
- Apache-2.0 licence. Desktop app and CLI.
- Extensions are MCP-based, with 70+ documented. Local models through Ollama or LM Studio.
- No persistent memory of the user and no multi-channel surfaces.

Source: [mausbot.com / openalternative.co listicles (third-party)](https://openalternative.co/blog/best-open-source-ai-agents)

**Agent Zero**
- Gives the model its own Docker Linux computer. — [mausbot.com (third-party)](https://mausbot.com/blog/best-self-hosted-ai-agents)
- The licence (reported as MIT) was not confirmed against a primary source.

**Open Interpreter / 01**
- 01 Light hardware was discontinued and orders were refunded. The project moved to a 01 phone app, and the 01 repo was last updated 2024-11-02. — [Open Interpreter blog](https://changes.openinterpreter.com/log/01-app); [GitHub org](https://github.com/openinterpreter)
- The current Open Interpreter is a Rust rewrite built on Codex and focused on coding agents. Latest release v0.0.56 on 2026-10-07. The original Python version lives on as a community fork. — [freedom.tech (third-party)](https://freedom.tech/posts/2026-10-07-open-interpreter-0-0-56/)

**Leon**
- Rebuilding as 2.0 around tools, context, memory and agentic execution. The repo notice (2026-03-29) says the focus is the 2.0 Developer Preview on the develop branch. No 2.0 release found. — [Leon GitHub](https://github.com/leon-ai/leon); [Leon progress update](https://leonai.substack.com/p/leon-ai-progress-update-toward-20)

**OpenVoiceOS** (Mycroft successor)
- Active. ovos-core was released 2026-08-11. The 2026-09-26 blog post covers a wake-word verifier plugin that recognises who is speaking. raspOVOS Raspberry Pi images exist. — [PyPI](https://pypi.org/user/OpenVoiceOS/); [OVOS blog](https://blog.openvoiceos.org/archive); [raspOVOS releases](https://github.com/OpenVoiceOS/raspOVOS/releases)

**Home Assistant Assist**
- Typical local pipeline: openWakeWord → Wyoming STT (Whisper or Speech-to-Phrase) → Assist intents → LLM conversation agent (for example Ollama) → Piper TTS. — [kunalganglani.com (third-party)](https://www.kunalganglani.com/blog/local-ai-voice-assistant-whisper-piper-ollama)
- 2026.8 reportedly shipped first-party llama.cpp and LiteLLM conversation integrations. I could not reach the official release notes to confirm this. — [privacysmarthome.com (third-party)](https://www.privacysmarthome.com/guides/home-assistant-2026-8-local-ai-voice-ready-replace-cloud-2026/)
- Users report wake-word problems on Android (2026.3: "only works once"). — [HA community](https://community.home-assistant.io/tag/assist)

**Open WebUI, LobeChat, AnythingLLM, Jan** (chat front ends)
- Open WebUI: native HTTP MCP plus OpenAPI tools, RAG and user management.
- LobeChat: positioned as a multi-agent "Agent Groups" workspace.
- AnythingLLM: document-RAG workspaces. Its MCP support differs between the Docker and Desktop versions.
- Jan: offline and privacy-first. No reliable MCP details found.

Source: [aicybr.com](https://aicybr.com/blog/open-webui-vs-librechat-vs-anythingllm); [pinggy.io](https://pinggy.io/blog/best_open_source_alternatives_to_chatgpt/) (third-party)

**n8n and AutoGPT** (workflow engines)
- n8n: the AI Agent node uses MCP servers as tools, and n8n can also act as an MCP server. Reportedly, since April 2026 the server can generate, validate and test new workflows. — [uibakery.io](https://uibakery.io/blog/n8n-mcp-guide); [fast.io](https://fast.io/resources/mcp-server-for-n8n/) (third-party)
- AutoGPT platform: visual block builder plus "AutoPilot". Agents run on schedules or triggers. The platform code is reportedly under Polyform Shield (source-available, not OSI open source). Sources conflict on this. — [pyshine.com](https://pyshine.com/2026/04/20/autogpt-platform-continuous-ai-agents/); [openalternative.co](https://openalternative.co/autogpt)

### Inferences
- The feature set users now expect of a "personal agent" is:
  - chat-app access (Telegram first);
  - a quiet proactive loop (heartbeat) kept separate from exact-time cron jobs;
  - file-based skills (SKILL.md / agentskills.io);
  - small bounded profile memory plus searchable session history;
  - MCP for integrations;
  - an approval or sandbox layer.
- Hermes is closest in shape to a Python Jarvis.
- Pure voice projects (Leon, OVOS, 01) have stalled or are being rebuilt, while chat-first agents grew. Voice is a niche add-on in 2026, not the main interface.

### Gaps
- Official Home Assistant 2026.x release notes were not fetched. The LLM integration details are second-hand.
- No primary-source detail gathered on Jan's MCP support, Agent Zero's current version, or LobeChat's current star count.
- Hermes's exact launch date is unconfirmed.

## Which features users praise or ask for most

### Takeaway
The anecdotal evidence (HN threads, 2026) points to one main use: scheduled, low-noise briefings and alerts delivered to a chat app the user already checks. Overnight research and chat-based lookup come next. The main complaints are reliability (cron or upgrades breaking), cost of idle loops, and setup friction.

### Cited Findings
- **Morning briefings are the most-cited use.**
  - One user's Raspberry Pi briefing (Calendar, Trello, Gmail) "worked maybe once or twice a week", so they cut the cron job.
  - Another user calls their briefing "easily worth an hour of my day".
  - Other briefings described: an AI-filtered Hacker News digest, and a briefing that becomes a podcast MP3.

  Source: [Ask HN: Who is using OpenClaw?](https://news.ycombinator.com/item?id=47783940) and related threads (via search summary)
- **One user built their own small agent instead of using OpenClaw.** It is a stdlib-only Python agent that sends weather and air quality, dependency and security digests, reminders via cron and visa-change alerts over Telegram. It deliberately has no calendar or email access. — [Ask HN: What are people doing with their OpenClaw set ups now?](https://news.ycombinator.com/item?id=49871556) (about late September 2026)
- **Reported uses for app marketing:** Google Search Console, GA4 and Paddle reports, blog drafts and a weekly strategy review. — [same thread](https://news.ycombinator.com/item?id=49871556)
- **Complaints:**
  - "some of the buggiest, clunkiest software"; upgrades repeatedly broke setups;
  - idle cost of "a few dollars a day while doing nothing";
  - a stream of poorly reviewed AI-generated features being merged.

  Source: [same thread](https://news.ycombinator.com/item?id=49871556)
- **Skeptics' view:** home automation and calendar alerts are already covered by existing triggers, and condensed email feeds risk missing things. — [same thread](https://news.ycombinator.com/item?id=49871556)
- **Trust patterns users describe:**
  - an agent that explains its reasoning for each email action and earns autonomy gradually;
  - SMS alerts for high-priority items;
  - human confirmation for bookings.

  Source: [HN: "OpenClaw is a security nightmare dressed up as a daydream"](https://news.ycombinator.com/item?id=47479962)
- **Group-chat logistics:** one user's agent posted a daily WhatsApp itinerary for a group trip. — [HN Ask threads via search summary](https://news.ycombinator.com/item?id=47147183)

### Inferences
- Reliability of scheduled jobs matters more to users than breadth of features. A briefing that fails 5 days in 7 gets abandoned.
- Silent-unless-needed behaviour and low idle cost are what users value, which matches OpenClaw's NO_REPLY and isolatedSession design.

### Gaps
- No quantitative data on feature demand, such as GitHub issue vote counts or Reddit polls. The evidence is anecdotal HN comments. Reddit r/LocalLLaMA and r/selfhosted were not fetched.

## Security incidents and criticisms, and the mitigations adopted

### Takeaway
OpenClaw is the cautionary case. Its problems were:
- a malicious-skill supply chain (ClawHavoc, about 341+ skills);
- 30K+ internet-exposed gateways, because it bound to 0.0.0.0 by default;
- auth-bypass and one-click RCE bugs;
- prompt injection that rewrote its own HEARTBEAT.md.

Its fixes were mostly reactive: VirusTotal scanning, patches, and a promised threat model. Sandboxing is still optional.

### Cited Findings
- **ClawHavoc malicious skills.** Koi Security audited 2,857 ClawHub skills and found 341 malicious, 335 of them from one campaign. They posed as crypto and trading tools and installed infostealers on macOS and Windows. — [The Hacker News](https://thehackernews.com/2026/02/researchers-find-341-malicious-clawhub.html)
  - Other counts: 386 (McCarty, Feb 1–3), and 1,184 by one blog. The figures conflict. — [eSecurity Planet](https://www.esecurityplanet.com/threats/hundreds-of-malicious-skills-found-in-openclaws-clawhub/)
- **Credential leaks through skills.** Snyk found 283 of 3,984 skills (7.1%) with critical flaws that expose credentials in plaintext through the LLM context and logs. — [The Hacker News, 2026-02-08](https://thehackernews.com/2026/02/openclaw-integrates-virustotal-scanning.html)
- **Exposed gateways.** The gateway bound to 0.0.0.0:18789 by default. Censys counted 30,000+ internet-accessible instances (2026-02-08), most of them token-protected. — [same](https://thehackernews.com/2026/02/openclaw-integrates-virustotal-scanning.html)
- **Patched bugs:**
  - proxied traffic was misclassified as local, which bypassed auth;
  - a one-click RCE leaked the auth token over WebSocket.

  OX Security also reported cleartext credential storage and `eval` on user input. — [same](https://thehackernews.com/2026/02/openclaw-integrates-virustotal-scanning.html)
- **Prompt injection.** An indirect injection in a web page made OpenClaw edit its HEARTBEAT.md so that it awaited commands from an external server. A zero-click document backdoor gave an attacker control via a Telegram bot. — [same](https://thehackernews.com/2026/02/openclaw-integrates-virustotal-scanning.html)
- **Moltbook.** The agent social network built on OpenClaw had a misconfigured Supabase database that exposed 1.5M API tokens and 35K emails (per Wiz). — [same](https://thehackernews.com/2026/02/openclaw-integrates-virustotal-scanning.html)
- **CVE-2026-25253.** Reported as a crafted skill escaping the Docker sandbox. The source is a vendor blog; not verified against the CVE record. — [designcopy.net](https://designcopy.net/en/openclaw-security-clawhavoc-hardening/)
- **OpenClaw's mitigations:**
  - every skill hashed and checked or uploaded to VirusTotal Code Insight: benign skills auto-approved, suspicious ones warned, malicious ones blocked;
  - daily re-scans;
  - user reporting;
  - malicious accounts banned.

  OpenClaw itself says scanning is "not a silver bullet". A threat model, security roadmap and full code audit are announced but not delivered. — [The Hacker News](https://thehackernews.com/2026/02/openclaw-integrates-virustotal-scanning.html); [Unit 42](https://unit42.paloaltonetworks.com/openclaw-ai-supply-chain-risk/)
- **Hermes safety design:** command approval, DM pairing (only paired users can message the agent) and container backends. — [GitHub](https://github.com/nousresearch/hermes-agent)
- **ZeroClaw and ZeptoClaw** market security as their difference: WASM sandbox, encrypted credentials, injection defence, secure defaults. Lobu keeps secrets in a gateway MCP proxy. — [rywalker.com](https://rywalker.com/openclaw-alternatives-2026)

### Inferences
These are the attack surfaces relevant to a one-user Jarvis:
- third-party skills;
- a network-listening gateway;
- secrets visible in the LLM context;
- self-editable instruction files (HEARTBEAT.md, skills, memory) that an injection can rewrite;
- inbound messages from chat apps.

### Gaps
- No primary CVE record for CVE-2026-25253 was fetched.
- No data found on whether Hermes has had security incidents.

## What a careful one-user assistant should copy, or avoid

### Takeaway
Copy: the quiet heartbeat (NO_REPLY, active hours, owner-only DM, cheap isolated context), cron kept separate from heartbeat, bounded profile memory plus full-text session search, SKILL.md-style skills, MCP, command approval, and allow-listed sender pairing.

Avoid: open skill marketplaces, binding to 0.0.0.0, secrets in the prompt or .env read by the agent, letting web or email content edit instruction files, full system access by default, and feature sprawl that breaks reliability.

### Cited Findings
- Heartbeat design worth copying: model decides to stay silent; active hours; owner-DM only, never groups; skip when the checklist is empty; isolated cheap context (about 2–5K tokens instead of about 100K). — [OpenClaw docs](https://docs.openclaw.ai/gateway/heartbeat)
- Keep exact-time jobs out of the heartbeat: the docs say heartbeat "is prompt context, not a scheduler". — [OpenClaw docs](https://docs.openclaw.ai/gateway/heartbeat)
- Bounded memory files (about 800 and 500 tokens) plus FTS5 session search with summarization. — [tosea.ai](https://tosea.ai/blog/hermes-agent-self-improving-ai-guide); [Hermes GitHub](https://github.com/nousresearch/hermes-agent)
- Background memory consolidation (Letta sleep-time agents) is a known pattern, but the docs mark it experimental. — [Letta docs](https://docs.letta.com/guides/agents/architectures/sleeptime)
- Injection rewriting HEARTBEAT.md shows that self-editable instruction files are a persistence vector. — [The Hacker News](https://thehackernews.com/2026/02/openclaw-integrates-virustotal-scanning.html)
- Users abandon unreliable cron briefings, and idle loops cost real money. — [HN thread](https://news.ycombinator.com/item?id=49871556)
- Gradual-autonomy and confirm-before-consequential-action patterns are used successfully by individuals. — [HN thread](https://news.ycombinator.com/item?id=47479962)

### Inferences
- **Jarvis (Python, one user, Mac) is architecturally closest to Hermes and NanoBot.** The best features to borrow:
  1. Telegram as the first remote channel, with sender allow-list and pairing.
  2. A heartbeat with a NO_REPLY convention, active hours and a cheap-model or isolated-context option, kept separate from exact-time cron jobs that keep their own run history.
  3. Bounded `USER`/`MEMORY` profile plus SQLite FTS5 search over past sessions.
  4. Skills in the agentskills.io SKILL.md format, but only locally authored or reviewed. No auto-install from a marketplace.
  5. Approval gates for shell, network and outbound messages, plus an optional container backend for risky code.
- **Things to avoid explicitly:**
  - listening on non-loopback interfaces;
  - secrets ever entering the model context;
  - web, email or chat content being able to write to heartbeat, skills or memory without approval or logging;
  - auto-generated skills going live without review (Hermes auto-creates them, which is convenient but is a self-modification risk).
- **Reliability over breadth.** A small set of jobs that run every day, with run logs and failure alerts, matches what users actually keep.

### Gaps
- No direct comparison found of memory-design quality (Letta versus Hermes versus OpenClaw) on real tasks. No benchmarks were gathered.
