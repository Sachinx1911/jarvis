# Dashboard design prompts (2026-10-17, v2: no dashboard at all)

Sachin rejected the current dashboard look and also the first prompt set (same sidebar + cards format as
every other dashboard). Rule from him: no new UI is built until he has generated images from these prompts,
picked a direction, and said "final". Frontend work (including the Office tab from step 2) is on hold and
will be redone to the chosen design. Backend APIs keep moving.

These five are deliberately NOT dashboards: no sidebar, no tabs, no card grid, no tables. Each is one
world where the live data of Jarvis (offices, teams, tasks, memories, approvals, audit log) has a physical
place. The prompts are in English for image tools; the names follow PLAN.md 27 (lokas, Trimurti, Kubera,
Narada, Chitragupta).

## Common rule for every prompt

"Concept art of a software interface, 16:9, 1920x1080, Figma-quality mockup, real UI text, not a game
screenshot. Dark night indigo background, saffron and antique gold accents, a cool teal for anything alive
right now, thin golden lines, Devanagari and English together (the greeting 'नमस्कार, सचिन'). Calm,
premium, no cartoon characters, no 3D-game look, no neon clutter."

## 1. Yantra: the whole screen is one living yantra

"The entire screen is a single living yantra (sacred geometric diagram) drawn in thin gold on night indigo;
there is no menu, no sidebar, no tabs. The bindu at the centre is Jarvis: a soft breathing point of light
whose rhythm shows its state (idle slow, listening fast, thinking a ripple). Around it, concentric rings
are time: the inner ring is now, the next ring is today, the outer ring is this week; schedules and
reminders sit on the rings as small gold marks at their hour. The eight petals of the yantra are the
offices (lokas): 'Personal', 'Acme Ltd', 'Digital Marketing'... each petal glows according to its activity
and shows its name in Devanagari and English; a rotating petal brought to the top opens like a lotus to
reveal its teams and running agents as beads on threads. Approvals waiting for the user are knots on the
threads near the centre, lit saffron. The conversation with Jarvis flows as a thin river of text through
the centre, newest at the bindu. Memories are faint stars behind the geometry, brighter when used today."

## 2. Nakshatra: the sky at night

"A software interface that is a night sky seen from a rooftop, no menu, no panels. Every memory Jarvis
holds is a star; stars form constellations (nakshatras) that are the offices and topics: 'Personal',
'Acme Ltd', 'Health', 'Money', each outlined in thin gold with its name in Devanagari. Running tasks are
planets moving slowly along orbits with a short label ('researcher-2: searching'). The day's schedule is
the ecliptic: a gold arc across the sky with marks for each hour's work. The audit log is the Milky Way: a
faint band of tiny glyphs that can be read when zoomed. Approvals waiting for the user are comets with a
saffron tail, hanging still until touched. The horizon at the bottom holds a single line: the user's words
to Jarvis and Jarvis's reply, with a microphone glyph. One constellation is zoomed in, showing the stars as
readable memory lines with confidence shown as brightness."

## 3. Pothi: the manuscript Chitragupta writes

"A software interface that is a single continuous palm-leaf manuscript (pothi) unrolling vertically, as if
written live by Chitragupta, the keeper of deeds. No menu, no cards. The scroll is the day: earlier
entries above in a warm aged-paper tone, 'now' in the middle with ink still wet (teal shimmer), and what
is to come below as faint pencil. Each entry is one deed in English or Marathi: 'acme / research team
finished: Laptop compare (3 model calls)', 'Reminder at 18:00: call the bank'. Where Jarvis needs the
user's word, the scroll shows a wax seal waiting: pressing the seal approves, tearing the corner denies.
The margins hold small notes: the office (loka) the line belongs to, the budget spent (Kubera), who saw
the evidence. At the very top, a small brass lamp shows whether Jarvis is listening. The user's own
sentence is written in a different hand at the bottom edge."

## 4. Mandir: the temple plan

"A software interface that is a top-down architectural plan of a temple complex drawn in thin gold lines
on night indigo, like a vastu mandala. No menu. The garbhagriha at the centre is the core of Jarvis: its
memory and soul, shown as a soft light. Around it the mandapas are the offices (lokas): 'Personal', 'Acme
Ltd', 'Digital Marketing', each a hall with its teams as rooms; in every room a small oil lamp (diya) per
agent, lit teal while that agent works, dim when idle, with the agent's name beside it. The pradakshina
path around the complex is today's schedule: the user's day walks the path clockwise, with hour marks and
the current time as a walking light. The gate (dvara) at the bottom holds the approvals: guardians stand
by each request that waits for the user. The treasury room shows the daily budget as grain in a vessel.
Narada's messages between halls are shown as tiny birds on the paths. The user's conversation with Jarvis
is spoken into the centre and appears as light text over the garbhagriha."

## 5. Pran: one line of breath

"An extremely minimal software interface: a near-black indigo screen with a single luminous horizontal
line across the middle, Jarvis's breath. The line is flat when idle, ripples gently when listening, and
pulses in teal while thinking. Everything else appears only when needed and dissolves afterwards: a
spoken question becomes a few words above the line; the reply forms below it in Devanagari or English;
when a task runs, a small bead travels along the line with its step; when something waits for the user, a
saffron knot forms on the line; offices are shown as faint gold tick marks along the line, and touching one
briefly opens its teams as a constellation above. A thin arc at the top edge is the day's schedule. No
menus, no panels, no cards: the line is the whole interface."

## How to use

1. Generate each with any image tool (keep the common rule line in every prompt). Change what you like.
2. Pick one direction (or mix) and say "final"; put the chosen images in `reports/design/`.
3. Then the frontend is rebuilt as that world: the live data behind it (offices, teams, tasks, memories,
   approvals, audit, schedules) already exists as APIs; no backend change needed.
