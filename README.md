# Jarvis

A personal AI assistant that remembers what it is taught, uses tools safely, and runs an agent team for bigger jobs. Built phase by phase; the plan is in [PLAN.md](PLAN.md) and the current status in [PROGRESS.md](PROGRESS.md).

Jarvis owns its agent loop, memory, tools and safety rules. AI models are reached only through the provider interface in `jarvis/providers/`, so the model can change (Claude today, local models later) without rewriting the app.

## Setup

Requirements: Python 3.12+, and the Claude Code CLI 2.1.280 or newer logged in with a Claude subscription (Jarvis uses it as its model provider; no API key needed).

Windows:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\setup.ps1
```

macOS:

```bash
bash scripts/setup.sh
```

Then start Jarvis in one click:

```bash
jarvis app --install-shortcut       # once: puts "Jarvis" on the Desktop (Windows; macOS: Jarvis.command)
jarvis app                          # or double-click the shortcut: dashboard + schedules (+ Telegram if set up)
```

Everything below can also be done from the app (Setup tab for keys and settings). In a terminal:

```bash
jarvis health                       # checks the Claude login and providers
jarvis secret set tavily_api_key    # web search (stored in Keychain / Credential Manager)
jarvis chat
```

Optional extras: `pip install -e ".[voice]"` (speech), `".[google]"` (Calendar, Gmail), `".[browser]"` (isolated browser), `".[voice-cloud]"`, `".[wakeword]"`. Dashboard frontend: `cd dashboard && npm install && npm run build`.

## Main commands

Every command below also has a place in the app (`jarvis app`): Chat, Memory, Tasks & Approvals, Projects & Docs,
Teach, Schedules & Reminders (with event triggers), India, Agents, Connectors, Setup, Settings & Usage.

| Command | What it does |
|---|---|
| `jarvis app` | One click: dashboard + scheduler + Telegram (if set up), opens the browser. `--install-shortcut`, `--autostart on\|off` (off by default), `--no-browser`, `--port` |
| `jarvis chat` | Chat. `/remember`, `/memory`, `/task`, `/repeat`, `/why`, `/project`, `/record`, `/help` |
| `jarvis task run "<goal>"` | Plan, run (team, operator or coder), verify, receipt |
| `jarvis tasks`, `jarvis receipt <id>` | Task board and receipts |
| `jarvis memory list|search|show|archive|export|conflicts` | Long-term memory; `conflicts` lists memories about the same subject that disagree |
| `jarvis task repeat <id> "<when>"`, `jarvis task draft <id>` | Turn a finished task into a skill + schedule (saved only after your yes); read a pending draft in full |
| `jarvis record start|stop|draft|approve` | Teach a task once; Jarvis turns it into a skill |
| `jarvis docs index|search` | Project document library with citations |
| `jarvis schedule …`, `jarvis brief`, `jarvis daemon` | Schedules, morning brief, Telegram bot |
| `jarvis voice`, `jarvis say` | Push-to-talk voice |
| `jarvis dashboard` | Dashboard only, without the scheduler (127.0.0.1, token) |
| `jarvis connectors status` | Tools, risk tiers, health checks |
| `jarvis nav`, `jarvis bills`, `jarvis wallet` | India: AMFI NAVs, bills and subscriptions (never pays), document wallet with masked numbers |
| `jarvis backup create|list|restore-check` | Dated local backups of personal data (default `~/JarvisBackups`, never inside the repo, not encrypted yet) |
| `jarvis stop` / `jarvis resume` | Emergency stop for every model and tool call |
| `jarvis eval` | Evaluation suite (for comparing models) |

## Safety in short

- Every tool has a risk tier: T0 read-only runs, T1 local writes run and are verified, T2/T3 always ask with the exact arguments, T4 (secrets, security bypass) never runs.
- Web and email text is data, never instructions: reading it taints the session, and pages are read by a separate model call without tools.
- Secrets live only in the OS secret store. Passwords, keys, OTPs and ID numbers are never stored in memory or sent to a model.
- Sensitive (P2) data is not sent to cloud models.
- Personal data (`memory/`, `profile/`, `projects/`, `skills/`, `data/`, `workspace/`) is git-ignored; this repo is public.

## Tests

```bash
python -m pytest -q                      # offline, uses a fake model
JARVIS_LIVE=1 python -m pytest -m live -s   # real model (uses your subscription)
```

`JARVIS_TEST_MODEL=claude-fable-5-1` runs every route on one model for final testing.
