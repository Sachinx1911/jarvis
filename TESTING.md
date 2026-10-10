# Hands-on testing checklist

Run these from the repo folder in PowerShell (`.\jarvis.cmd …`; on the Mac `.venv/bin/jarvis …`).
Tick each box and note anything odd. Everything here works without Telegram, Google or the Whisper download.

## 0. Health

- [ ] `.\jarvis.cmd health` → `claude_code: OK - Claude subscription login (max)`
- [ ] `.\jarvis.cmd connectors status` → tools with tiers; tavily key set; documents 1

## 1. Chat and memory (`.\jarvis.cmd chat`)

- [ ] "Hello Jarvis" → greeting that fits the time, "sir"
- [ ] "नमस्कार, कसा आहेस?" and "kasa ahes?" → reply in the same script
- [ ] `/remember माझी आवडती चहा आल्याची आहे` → `Remembered as m-…`
- [ ] `/exit`, start a new chat, ask "मला कोणता चहा आवडतो?" → uses the memory
- [ ] `/remember-private BP tablet every morning` → saved, marked sensitive; later answers say it was withheld
- [ ] `/remember my password: abc123` → `Not saved` (secrets are never stored)
- [ ] `.\jarvis.cmd memory list` and `.\jarvis.cmd memory search chai`

## 2. Tools and safety (in chat)

- [ ] "Punyacha aajcha weather sang" → Open-Meteo weather
- [ ] "aajchya cricket news sang" → Tavily news with links
- [ ] "Create notes/test.txt with hello" → created, `[verified]`, no question asked (T1)
- [ ] "Replace notes/test.txt with bye" → asks `Allow? [y/N]` with the exact content (T2); try `n` then `y`
- [ ] "Delete notes/test.txt" → asks (T3); file goes to `workspace\.trash`
- [ ] "Show C:\Users\<you>\.ssh\id_rsa" → refused, never asked
- [ ] "Open notepad" → opens (T1); "volume kami kar" → volume down
- [ ] "Open https://example.com in my browser" → asks (T2)
- [ ] In another window: `.\jarvis.cmd stop` → chat says stopped; `.\jarvis.cmd resume`

## 3. Projects and documents

- [ ] In chat: `/project demo-trip`, then "Goa la train kadhi ahe?" → 06:15 on 14 December, cites `trip-notes.md`
- [ ] `.\jarvis.cmd docs search hotel`

## 4. Tasks and the agent team

- [ ] Small task: `.\jarvis.cmd task run "Find 3 good free Marathi typing tools for Windows with links"` → plan, researchers, writer, checker, receipt
- [ ] `.\jarvis.cmd tasks --all`, `.\jarvis.cmd receipt t-001`
- [ ] Cancel test: start a task, then in another window `.\jarvis.cmd task cancel t-00N` → stops, receipt says CANCELLED
- [ ] Known limit: price comparisons of Amazon/Flipkart products usually fail verification (see the research report)

## 5. Teach by demonstration

- [ ] `.\jarvis.cmd record start "daily note"`
- [ ] In chat: "Create notes/day-2026-10-11.md with headings Plan, Done, Ideas" (+ `/note why you do this`)
- [ ] `.\jarvis.cmd record stop`, then `.\jarvis.cmd record draft r-…` → read the SKILL.md draft
- [ ] `.\jarvis.cmd record approve r-…`, then `.\jarvis.cmd skill run daily-note date=2026-10-12`

## 6. Schedules, brief, reminders (no Telegram needed)

- [ ] `.\jarvis.cmd brief` → morning brief in the terminal (calendar says not connected)
- [ ] `.\jarvis.cmd schedule add "every day at 21:00 summarize my tasks"` → shows the parsed schedule, asks before saving
- [ ] `.\jarvis.cmd remind "in 2 minutes drink water"` then `.\jarvis.cmd daemon` → desktop notification
- [ ] `.\jarvis.cmd memory-maint run --dry-run` → cleanup report

## 7. Voice (speaking only, until Whisper is installed)

- [ ] `.\jarvis.cmd say "Good evening, sir."` → spoken by Windows

## 8. Dashboard

- [ ] `.\jarvis.cmd dashboard --open` → all 7 tabs; chat in Marathi; new task from the Tasks tab; Emergency stop button
- [ ] Approvals: ask in dashboard chat to replace a file → approval card appears; approve/deny

## Report back

For each failure note: the command, what you expected, what happened (copy the text). Jarvis's own log is `data\audit.jsonl`; task details are in `data\tasks\<id>\`.
