# Hands-on testing checklist

Run these from the repo folder in PowerShell (`.\jarvis.cmd …`; on the Mac `.venv/bin/jarvis …`).
Tick each box and note anything odd. Everything here works without Telegram, Google or the Whisper download.

## 0. Health

- [ ] `.\jarvis.cmd health` → `claude_code: OK - Claude subscription login (max)`
- [ ] `.\jarvis.cmd connectors status` → tools with tiers; tavily key set; documents 1
- [ ] Mac only: `.venv/bin/python -m jarvis.connectors.applenotes` → allow "Terminal wants to control Notes" → `apple notes last check: OK`; in chat "Make a note: demo list, milk and bread" → new note in the `Jarvis` folder, `[verified]`

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
- [ ] After a task the Operator or Coder did, the receipt has **Claims vs evidence**: each claim with `[x]` and the tool run (or file hash / test exit code) that proves it. A claim marked `[!]` means the task FAILED, never COMPLETED

## 5. Teach by demonstration

- [ ] `.\jarvis.cmd record start "daily note"`
- [ ] In chat: "Create notes/day-2026-10-11.md with headings Plan, Done, Ideas" (+ `/note why you do this`)
- [ ] `.\jarvis.cmd record stop`, then `.\jarvis.cmd record draft r-…` → read the SKILL.md draft
- [ ] `.\jarvis.cmd record approve r-…`, then `.\jarvis.cmd skill run daily-note date=2026-10-12`

## 5b. Repeat this (skill + schedule, saved only after your yes)

- [ ] `.\jarvis.cmd task repeat t-001 "every Monday at 9"` → SKILL.md draft + parsed schedule; answer `n` → `Not saved.`; run again and answer `y` → `Saved skill …` and `Saved schedule s-…`
- [ ] In chat: "Create notes/prices.md with Laptop A", then `/repeat every day at 21:00` → draft; `/repeat no` drops it; repeat and `/repeat yes` saves it
- [ ] `/repeat every 5 minutes` → refused (automations run at most every 30 minutes)
- [ ] `.\jarvis.cmd schedule run-now s-…` on the saved schedule → only T0/T1 steps run; anything else is listed as "refused unattended, waiting for approval"
- [ ] Telegram (when set up): `/repeat every day at 21:00` → draft with Save / Cancel buttons; nothing is saved before Save

## 6. Schedules, brief, reminders (no Telegram needed)

- [ ] `.\jarvis.cmd brief` → morning brief in the terminal (calendar says not connected)
- [ ] `.\jarvis.cmd schedule add "every day at 21:00 summarize my tasks"` → shows the parsed schedule, asks before saving
- [ ] `.\jarvis.cmd remind "in 2 minutes drink water"` then `.\jarvis.cmd daemon` → desktop notification
- [ ] `.\jarvis.cmd memory-maint run --dry-run` → cleanup report
- [ ] `.\jarvis.cmd memory conflicts` → "No possible memory conflicts", or pairs of memories about the same subject
- [ ] `.\jarvis.cmd schedule list` → includes **Nightly review** (22:30); `schedule run-now <id>` → `memory\episodes\<today>.md` written
- [ ] Daily cap: set `proactive_file: {unattended: {daily_cap: {max_model_calls: 1}}}` in `config\local.yaml`, wait for two scheduled runs → the second is "capped" and one notice arrives; remove the line afterwards
- [ ] `.\jarvis.cmd backup create` → archive in `~/JarvisBackups`; `backup list`; `backup restore-check latest` → all checks OK
- [ ] India: `.\jarvis.cmd bills add` (paste a made-up bill SMS) → tracked; `.\jarvis.cmd brief` shows only a count for bills

## 7. Voice (speaking only, until Whisper is installed)

- [ ] `.\jarvis.cmd say "Good evening, sir."` → spoken by Windows

## 8. Dashboard

- [ ] `.\jarvis.cmd dashboard --open` → all 7 tabs; chat in Marathi; new task from the Tasks tab; Emergency stop button
- [ ] Approvals: ask in dashboard chat to replace a file → approval card appears; approve/deny

## 9. In the app (no terminal)

Start: `.\jarvis.cmd app --install-shortcut` once, then double-click **Jarvis** on the Desktop (or `.\jarvis.cmd app`).
The browser opens the dashboard. Do not run `jarvis daemon` at the same time (the app already runs the scheduler).

- [ ] Double-click the shortcut again → no second copy; the browser just opens the running one
- [ ] **Setup**: paste the Tavily key → "set"; the key is never shown again. Run health checks → claude_code OK
- [ ] **Setup**: Telegram user id + weather place (e.g. Pune) → saved to `config\local.yaml`
- [ ] **Setup**: profile interview → answer two questions (one in Marathi) → memories saved (see Memory tab)
- [ ] **Chat**: "नमस्कार" → Marathi reply; tick "Speak replies" → spoken on the laptop speakers
- [ ] **Chat**: 🎤 Talk → says "speech-to-text not installed (run voice setup)" until Whisper is installed
- [ ] **Projects & Docs**: create `demo-trip2`, upload a .md/.pdf/.docx → indexed, P2; mark one P1 (asks first); search "train" → citation
- [ ] **Projects & Docs**: "Use in chat" → Chat shows the project; ask about the document
- [ ] **Teach**: Start recording → do the daily-note task in Chat → add a note → Stop → Draft a skill (asks first) → edit → Approve → Run in chat
- [ ] **Schedules & Reminders**: "every day at 21:00 summarize my tasks" → Read it → draft shown, nothing saved until **Save this schedule**
- [ ] Pause / Resume / Runs / Delete a schedule; Run now (asks first)
- [ ] Reminder "in 2 minutes drink water" → desktop notification while the app runs; cancel another one
- [ ] **Show morning brief**
- [ ] **Schedules & Reminders → Event triggers**: list, pause/resume, runs (email rules show no sender)
- [ ] **India**: refresh NAVs (after adding a scheme code), add a made-up bill from pasted text, mark it paid; add a wallet record with a made-up number → only the last 4 shown; UPI link preview shows payee and amount, link only after confirm
- [ ] **Chat** in the terminal: ask something, then `/why` → the memories and past chats used
- [ ] **Setup**: Run evaluation (asks first; calls the model) → results table
- [ ] **Setup**: Quit Jarvis → the page stops answering; start it again from the shortcut
- [ ] Optional: `.\jarvis.cmd app --autostart on`, log out and in → Jarvis starts; `--autostart off` to undo

## Report back

For each failure note: the command, what you expected, what happened (copy the text). Jarvis's own log is `data\audit.jsonl`; task details are in `data\tasks\<id>\`.
