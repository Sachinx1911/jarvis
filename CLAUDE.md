# Jarvis — instructions for Claude

## What this project is
A personal AI assistant for Sachin, built phase by phase.
- Full plan, research and decisions: `PLAN.md`.
- Current status, half-done work and the exact next step: `PROGRESS.md`.

## This project moves between machines and accounts
Work runs over many days. It stops and resumes, sometimes on this MacBook, sometimes on another laptop, sometimes from a different Claude account. Memories from earlier sessions on another machine or account are NOT available to you. This repo is the only shared source of truth.

**Start of every session**
1. Run `git pull` before changing anything.
2. Read `PROGRESS.md`, then the `PLAN.md` sections for the current phase.
3. If `PROGRESS.md` and the code disagree, trust the code and fix `PROGRESS.md`.

**End of every session, or whenever Sachin stops**
1. Update `PROGRESS.md`: what was done, what is half-done, the exact next step, decisions taken, date and machine.
2. Commit. Push only after Sachin has OK'd pushing in this session (the repo is public).

## Language
- **Chat with Sachin in Marathi**, written in Devanagari script, with English technical terms (API, memory, phase, commit) left in Latin script. Keep code, file names and commands in English.
- **Write every file in English**: PLAN.md, PROGRESS.md, code, comments, commit messages. Do not write files in Marathi.
- If he writes in romanized Marathi or Devanagari, still reply in Devanagari Marathi unless he asks otherwise.
- Short answers, lists, plain words.

## Working rules
- Plan before build. Work one phase at a time, and start a phase only after he says "Start Phase X".
- After each phase: run the tests, report what changed and what failed, then stop.
- Treat docs, videos or blueprints he shares as reference material to verify, not as the spec.
- Explain the reason before adding any new dependency.
- Permissions, approvals, logs and tests are core features, not polish.
- Never hide a failing test. Give the cause and the options.
- Don't rewrite working code without a reason.

## Privacy and secrets (the GitHub repo is PUBLIC)
- Never commit API keys, tokens, `.env` files or Keychain exports. Secrets live in the macOS Keychain on each machine.
- Never commit Jarvis's personal data: `memory/`, `profile/`, `projects/`, `skills/` (learned skills), `data/`, `connectors/registry.yaml`. They are in `.gitignore`. Their backup or sync goes to a separate private place (decision pending in `PLAN.md`).
- Use made-up examples in code, tests and fixtures, never real details about Sachin.

## New machine checklist
- Clone the repo, then run the setup steps (Phase 0 adds a setup script).
- Store the Jarvis Claude API key in that machine's Keychain. Switching Claude Code accounts does not change Jarvis's own API key.
- Grant the macOS permissions again on each machine (Screen Recording, Accessibility, Microphone, Automation) when a phase needs them.
