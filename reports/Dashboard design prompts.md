# Dashboard design prompts (2026-10-17)

Sachin rejected the current dashboard look (both the old tab bar and the sidebar redesign). Rule from him:
no new UI is built until he has generated images from these prompts, picked one, and said "final".
Until then the backend keeps moving; frontend work (including the Office tab written in step 2) is on hold
and will be redone to match the chosen design. Prompts are in English for image tools.

## Style anchors (use with every prompt)

"Jarvis" personal AI command center; the Hindu cosmos as the design language (PLAN.md 27): lokas =
offices as realms, the Trimurti kernel at the centre, Chitragupta's register as the audit log. Dark
background like deep night sky (near-black indigo), accents of saffron/gold and a cool teal for "live"
states, thin golden lines, mandala-like geometry used sparingly, Devanagari and English together.
Calm, premium, not gamified; no cartoon characters; no neon clutter. Desktop 16:9, 1920x1080, UI mockup,
Figma-quality, flat with soft depth, readable at a glance.

## Prompt 1: Command Center (home)

"UI mockup of a personal AI assistant command center called Jarvis. Dark indigo night-sky background with
faint golden mandala lines. Centre: a glowing circular 'core' showing the assistant's state (listening /
thinking / idle) with a short Marathi greeting in Devanagari ('नमस्कार, सचिन') and the time. Around it in
a ring: today's brief (weather, 3 calendar items, 2 reminders), a task board strip (planned / running /
done), and a 'waiting for you' badge with 2 approvals. Left: a slim vertical navigation with icons and
labels: Office, Chat, Tasks, Schedules, Memory, Teach, India, Setup. Top-right: a status pill 'Claude ·
local off' and an emergency stop button in deep red. Typography: a clean humanist sans for English and a
matching Devanagari face. Accents saffron and gold, live states teal. Flat UI with soft shadows, no 3D."

## Prompt 2: Office page (lokas and teams)

"UI mockup of an 'Office' page in a dark AI dashboard. The page shows several offices (called lokas) as
elegant rooms on a subtle isometric grid drawn in thin golden lines: 'Personal', 'Acme Ltd', 'Digital
Marketing'. Each room contains small team cards (Research, Writing, Dev, Admin) with member dots that glow
teal when working; a count 'done / running / waiting' per team; a budget bar labelled 'Kubera' at the
room's base. In the centre of the page a luminous 'Brain' sphere with counts: memories, documents, skills.
Top line: '12 agents · 3 running · 2 waiting for you'. A side panel on the right is open for one team,
showing the lead (Adhipati), members (Gana) with their status, tools, skills and recent tasks. Dark indigo
background, saffron and gold accents, calm, premium, readable."

## Prompt 3: Chat

"UI mockup of a chat screen with a personal AI assistant named Jarvis, dark indigo theme with gold
accents. Messages in English and Marathi (Devanagari) in rounded bubbles; the assistant's bubbles carry a
thin gold edge. Above the input: a small approval card 'Jarvis wants to send an email to Rahul – Allow /
Deny' with a tier badge 'T3'. Right rail: 'Why this answer' panel listing the memories and documents used,
each with a confidence mark. Bottom: a wide input with a microphone button (voice), a 'Project: none'
selector and an 'Office: Personal' selector. Clean, calm, premium."

## Prompt 4: Tasks and receipts

"UI mockup of a task board for an AI assistant, dark indigo and gold. Columns: Backlog, Planned, Running,
Verifying, Done. Cards show title, office tag, team tag, budget used as a thin bar, and a step line like
'researcher-2: searching'. One card is expanded into a receipt panel: a timeline of events, 'claims vs
evidence' checklist with ticks, model calls and cost, and a 'Team: research (Acme)' line. Running cards
pulse softly in teal. Premium, readable, no clutter."

## Prompt 5: Memory

"UI mockup of a memory page for a personal AI assistant, dark indigo and gold. Left: core memory as two
scrolls 'USER' and 'MEMORY' with Devanagari headings. Centre: a searchable list of memories with type
chips (fact, preference, procedure, constraint, episode), confidence dots, office tag and 'last used'. A
toggle 'show archived'. Right: a timeline of where each memory came from (chat, receipt, interview).
Calm, premium, readable."

## What happens next

1. Sachin generates images from the prompts (any tool), changes the prompts as he likes.
2. He picks one direction and says "final"; the chosen images go into `reports/design/` (private is fine).
3. Then the frontend is rebuilt to that design: nav, Command Center, Office, Chat, Tasks, Memory, the
   rest; the backend APIs do not change for this.
