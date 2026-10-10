# Jarvis — Master Plan (v3.1)

**Tarikh:** 2026-10-09 (update: 2026-10-10)
**Status:** Planning purna hot ahe. Ajun ekhi line code lihili nahi.
**Ha file kay ahe:** Aatparyant kelela sagla research, analysis ani planning ekach thikani.
**v3.1 (2026-10-10):** Teach-by-demonstration, task queue, connector registry, schedules, model routing, task receipts, project workspace ani surakshit browser profiles jodle. Pratyekacha upyogi bhag ghetla, ani jast kiva dhokadayak bhag kadhla.

---

## 0. Thodkyat

Jarvis ha tuzya Mac var chalnara personal AI assistant asel.
To tuzyakadun **shikel**, **lakshat thevel**, **kaam karel**, kaam **khare jhale ka te tapasel**,
garaj aslyavar **swata pudhakar gheun sangel**, ani motha kaam aale tar **agents chi team** kadun karun gheil.

Voice ani dashboard he fakt interface ahet. Khara Jarvis mhanje memory + tools + safety + proactive + team.

---

## 1. Mahiti kuthun ghetli

| # | Source | Kay milale | Nirnay |
|---|---|---|---|
| 1 | Online research (GitHub Jarvis projects, 2026 trends) | Wake word, Whisper, tool calling, memory, local LLM he common ahe | Basic features ghetle |
| 2 | YouTube video: Jack Roberts "Agentic OS" | Memory core, profile interview, save anything, daily brief | Fakt ideas ghetlya, tyacha kit nahi |
| 3 | Blueprint 1 (JARVIS_Advanced_AI_Assistant_Blueprint.docx) | Verifier, approvals, audit, emergency stop | Changle bhag ghetle, over-engineering kadhle |
| 4 | Master Blueprint (Advanced_JARVIS_AI_Assistant_Master_Blueprint.docx) | T0–T4 risk, task state machine, Claude Code niyam, "top 5 workflows" | Changle bhag ghetle |
| 5 | Tuzya Mac chi tapasni | M4, 16 GB, macOS 26, Python 3.13 | Cloud-first, halka stack |
| 6 | 5 research agents | Memory, brain loop, connectors, Marathi search, Mac safety | Sagle niyam khali ghatle |
| 7 | OpenClaw ani Hermes Agent | Skill system, heartbeat, session search | Navin skills jodlya |
| 8 | Multi-agent research (Anthropic, MAST paper) | Team kadhi changli, kadhi nahi | Agent team cha design |

---

## 2. Analysis

### 2.1 YouTube video (Jack Roberts, "Agentic OS")

- **He kay ahe:** Local web dashboard + LLM + memory + integrations. Chaan dista, pan "OS" nahi.
- **Ghetlelya ideas:** Memory core, profile interview, save anything, goals + daily brief, model picker, voice ne calendar event, magic search, memory graph view.
- **Skip kele:** Higgsfield image/video, website design system, Skool/finance dashboard, Zapier.
- **Note:** Starter kit chi link 404 hoti ani community paid ahe. Aapan swata banavto.

### 2.2 Blueprint 1

**Changle (ghetle):** Task lifecycle, verifier, approvals, audit log, emergency stop, memory metadata, hybrid search, prompt injection pasun bachav, backup.

**Problem:**
- Voice Phase 2 la ani Memory Phase 3 la. Pan tyachich final recommendation mhante memory adhi. Contradiction.
- Security Phase 7 la, pan tools Phase 4 la. Mhanje 3 phases safety vina.
- Memory **save** kashi hoil (write path) he nahi. Fakt shodhne ahe.
- PostgreSQL, Redis, n8n, 15 agents, 12 tabs. Ek user sathi jast.

### 2.3 Master Blueprint

**Pahilya peksha sudharle (ghetle):**
- Memory voice chya adhi. Push-to-talk adhi, wake word nantar.
- Permissions core feature, polish nahi.
- Task state machine: RECEIVED, PLANNING, WAITING_APPROVAL, RUNNING, VERIFYING, COMPLETED, FAILED, CANCELLED.
- Risk che 5 levels T0–T4.
- Chukiche uttar talnyache niyam: hishob code ne, file check, email confirmation.
- Claude Code sathi niyam: ek phase, test, report, thamb, permission.
- "Top 5 real workflows" adhi tharva. **Sarvat mahatvachi gosht.**

**Ajun problem:**
- Memory write path ajun nahi. Phase 3 cha focus document search var.
- Mac cha ullekh nahi. Windows/Linux ani Ryzen/NVIDIA hardware.
- Phase 1 madhe fakt infrastructure (API, PostgreSQL, dashboard). Upyogi kahi yayla ushir.
- PostgreSQL, Redis, users/roles/login, 15 agents, 14 tabs.
- Marathi voice kathin ahe he sangitle nahi.
- Personality, profile, daily brief, Telegram, MCP nahi.

### 2.4 Tuzya Mac var tapaslele facts

| Gosht | Result | Parinam |
|---|---|---|
| Chip / RAM | Apple M4, 16 GB | Cloud-first. Local LLM fakt lahan models |
| Free disk | ~32 GB | Mothe local models nako |
| macOS | 26.5 (Tahoe) | Permissions che navin niyam lagu |
| Python | python.org 3.13.14 | Chalel. Pan tyacha SQLite extension load karu det nahi, mhanun vector extension nako, numpy vaparu |
| Already installed | numpy, torch, onnxruntime, mlx, ffmpeg, git, brew, Node 24, Docker, sandbox-exec | Setup sopa |
| Ollama | Nahi | Garaj lagli tar nantar |
| Mac madhe Marathi voice | **Nahi** (fakt Hindi "Lekha", en_IN "Rishi/Aman/Tara") | Marathi bolnyasathi edge-tts |

---

## 3. Jarvis chya 24 skills

### Document madhlya 15

| # | Skill | Kay karte | Phase |
|---|---|---|---|
| 1 | Brain & Reasoning | Samajne, vichar, plan | 1 |
| 2 | Memory & Learning | Shikne, lakshat thevne, vaparne | 1 |
| 3 | Voice & Conversation | Aikne, bolne, madhech thambavne | 6 |
| 4 | Computer Control | Apps, files, kaam nantar tapasni | 2 |
| 5 | Browser & Research | Web search, sources, forms | 2 |
| 6 | Office & Business | Word, Excel, PDF, reports | 2–3 |
| 7 | Multi-Agent | Kaam team la vatne | 3 |
| 8 | Planning & Automation | Steps, deadlines, roj chi kaame | 3–4 |
| 9 | Coding | Code, tests, debug | 8 |
| 10 | Vision & Documents | Screenshot, PDF, tables | 2 |
| 11 | Security & Permissions | Vicharne, band karne, log | 2 |
| 12 | System & Cost Monitoring | RAM, CPU, API kharcha | 0, 4 |
| 13 | Data Analysis | Hishob, charts | 8 |
| 14 | Knowledge & Personalization | Preferences, projects, lok | 1 |
| 15 | Evaluation & Quality | Tapasni, tests | Pratyek phase |

### Mi jodlelya 9

| # | Skill | Ka | Phase |
|---|---|---|---|
| 16 | Proactive | Na vicharta sangne, heartbeat | 4 |
| 17 | Personality & Profile | Swabhav, "Sir", profile interview | 1 |
| 18 | Connectors & Phone | Calendar, Gmail, Telegram | 4–5 |
| 19 | Skill system | Navin skills shikne ani jodne | 1 |
| 20 | Daily info | Weather, news, cricket, traffic | 2 |
| 21 | Media & quick controls | Music, volume, brightness, DND | 2 |
| 22 | Language & translation | Roman Marathi, Devanagari, bhashantar | 1 |
| 23 | Meeting / lecture notes | Record, transcript, saransh | 8 |
| 24 | Smart home | Lights, fan, AC (devices astil tar) | Optional |

**Version 1 sathi lagnarya skills:** #1, #2, #4, #11, #14, #17, #19, #22.

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
│ planner · tool loop · agent team la kaam vatne               │
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
       │             (nantar) Coder · Operator            │
       └─────────────┬───────────────────────────────────┘
       ┌─────────────▼───────────────────────────────────┐
       │ CONNECTORS: Telegram · Web search · Calendar ·   │
       │             Gmail · Reminders · Notes            │
       └─────────────────────────────────────────────────┘
```

### Task lifecycle

1. Message ghe, intent samaj.
2. Relevant memory, skills ani task state kadh.
3. Motha kaam asel tar plan bana: steps + "jhale mhanje kay" (acceptance criteria).
4. Ekta karu ki team? Tharav.
5. Pratyek tool cha risk level tapas. Garaj asel tar vichar.
6. Execute kar, pratyek step log kar.
7. **Verify** kar: exit code, file ahe ka, event banla ka. Fail tar limited retry.
8. Result sang: Success, Partial kiva Failed.
9. Navin shiklele memory madhe. Yashasvi motha kaam asel tar skill suchav.

### Task states

BACKLOG → PLANNED → RUNNING → WAITING_APPROVAL → VERIFYING → COMPLETED / FAILED / CANCELLED

Tyasobat SCHEDULED ani PAUSED. Purna mahiti "Task system" section madhe.

---

## 5. Memory design (sarvat mahatvacha bhag)

### 5.1 Rachana

**Source of truth = markdown files.** Tu vachu, badalu, delete karu shaktos. Folder git madhe thevaycha, pan **vegalya private repo madhe**. Code repo public ahe, tyat memory kadhich nahi.
**SQLite = index.** Keyword search (FTS5), vectors (numpy BLOB), tasks, audit. Ek file, server nahi.

```
memory/
├── MEMORY.md          index, nehmi prompt madhe (200 lines peksha kami)
├── facts/             kay ahe
├── preferences/       tula kasa pahije
├── procedures/        kase karaycha (nantar skills madhe jatat)
├── constraints.md     "kadhich X karu nako", health, hard rules. NEHMI prompt madhe
└── episodes/          roj kay jhale (YYYY-MM-DD.md)
profile/
├── SOUL.md            Jarvis cha swabhav
├── life.md · work.md · goals.md
skills/                SKILL.md folders
projects/<naav>/       project workspace: PROJECT.md, docs/, notes/, outputs/
connectors/
└── registry.yaml      connectors, tools, permissions, health
data/
├── jarvis.db          SQLite: index, tasks, schedules, model_usage
├── tasks/<id>/        task cha workspace ani receipt.md
├── sessions/          junya conversations (shodhnyasathi)
├── browser/<site>/    approved sites che vegle browser profiles (Phase 8)
└── audit.jsonl        log (chmod 600)
```

**Code repo madhe kay:** code, PLAN.md, PROGRESS.md, CLAUDE.md, examples.
**Code repo madhe kadhich nahi:** `memory/`, `profile/`, `projects/`, `skills/` (learned), `data/`, `connectors/registry.yaml`, `.env`. He sagle `.gitignore` madhe ahet.

### 5.2 Ek memory file

```markdown
---
id: m-0042
name: college-project-run
type: procedure            # fact | preference | procedure | constraint | episode
status: active             # active | superseded | archived
subject: college-project   # hi memory konabaddal ahe
description: College project kasa chalvaycha
when_to_use: "college project chalav/run kar" mhatlyavar
summary_en: How to run the college project (make run in ~/Projects/college)
keywords: college project run start make chalav
evidence: "maza college project ~/Projects/college madhe ahe, make run ne chalto" (session s-17)
source: user-said          # user-said | inferred | imported
confidence: high           # inferred aslyas 0.6 peksha jast nahi
sensitivity: normal
valid_from: 2026-10-09
valid_until:
superseded_by:
last_used:
use_count: 0
expires:                   # thodya divsanchya goshtinsathi
---
Folder: ~/Projects/college
Command: make run
```

### 5.3 Write path (save kase hote)

**Research madhe sapdlele dhoke:**

| Problem | Akda |
|---|---|
| Ek memory system chya 32 divas audit madhe kachra memories | 10,134 paiki 97.8% |
| Changla model vaparun pan kachra | 89.6% |
| Athavleli memory parat navin mhanun save jhali (feedback loop) | Ekach gosht 808 vela |
| Lakshat aslelya preferences pan vaparlya nahit | ~35% |

**Mhanun aaple niyam:**
1. **Default "kahi save karu nako".** Prompt madhe chukichya udaharananchi yadi.
2. **Extractor la fakt tuze messages.** System prompt ani injected memories kadhun takaychya. Jarvis che uttar fakt tu confirm kele tarach.
3. **Pratyek memory la tuzya shabdanche quote lagel.** Quote nasel tar REJECT.
4. **Don step:** Adhi candidates kadh. Mag 10 sarkhya memories kadhun LLM tharavto: ADD, UPDATE, SUPERSEDE, NOOP kiva REJECT.
5. **Conflict fakt same subject var.** Juni memory delete nahi, "superseded" mark.
6. **Similarity thresholds** (suruvaticha andaj, test karun badalu): 0.97 peksha jast = duplicate. 0.85–0.97 = LLM merge karel.
7. **Andaj (inferred)** memory don vela disli kiva tu ho mhanalas tarach pakki.
8. **Kevha:** Session shant jhalyavar 10–30 minitanni. "Lakshat thev" mhatle tar lagech.
9. **Save kartana** LLM English summary ani keywords jodel. Roman Marathi shodhnyasathi he sarvat motha fayda.
10. **Kadhich save nahi:** passwords, API keys, card numbers (regex filter). Email kiva web page madhla text apoap save nahi.

### 5.4 Read path (vapar kasa hoto)

1. MEMORY.md ani constraints.md nehmi prompt madhe.
2. Tuzya message che English keywords madhe rupantar (query rewrite).
3. Teen prakare shodh:
   - FTS5 unicode61: purna shabd, Devanagari pan
   - FTS5 trigram: chuklele spelling (karaycha / karaicha)
   - Vector similarity
4. Teen yadya ekatra: reciprocal rank fusion, score = sum of 1/(60 + rank).
5. Fakt "active" memories. Minimum score gate: 0 te 5 memories, nehmi 5 nahi.
6. Navin memories la thoda boost.
7. Kahi sapdle nahi tar **junya conversations madhe shodh** (session search, Hermes cha design).

### 5.5 Search che tapaslele facts

| Gosht | Result |
|---|---|
| Hinglish search: e5-small embeddings | English 0.61 varun Hinglish 0.16 la padle |
| Hinglish search: sadha keyword (BM25) | 0.29, embeddings peksha changle |
| numpy search, 3,000 memories | ~0.05 ms prati query |
| Roman Marathi sathi tayar benchmark | Ekhi nahi |

**Embedding model:** suruvat multilingual-e5-small (lahan, MIT). Tuzya 30–50 khare prashna gheun granite-97m-multilingual-r2 ani e5-large shi tulana karu.
**Hosted embeddings** gharaj nahi, fakt test madhe motha farak disla tar.

### 5.6 Itar memory features

- **Save anything:** Telegram var link/file forward kar, memory madhe jail.
- **Curiosity:** Mahit nasleli gosht disli tar Jarvis vicharel. "Ya company che emails khup yetat, hi tuzi office ahe ka?"
- **Weekly cleanup:** duplicates merge, "udya" sarkhya tarkha pakkya tarkhet, 90 divas na vaparlelya archive, MEMORY.md 200 lines khali.
- **Memory commands:** list, search, edit, delete, export.
- **Learning ≠ training:** Model badlat nahi. Tyachi diary vadhte.

---

## 6. Project workspace ani document library

Ek project chi sagli mahiti ekach thikani. Tyamule pratyek agent la toch approved context milto.

```
projects/<project-naav>/
├── PROJECT.md      goal, status, lok, links, ya project che niyam
├── docs/           tu approve kelele documents (PDF, DOCX, MD)
├── notes/          project notes
└── outputs/        tayar jhalele reports ani files
```

- **Memory jodni:** Memory madhe `scope: project:<naav>` asel. Project che kaam chalu asel tevha tyach scope chya memories adhi shodhlya jatat.
- **Document library:** `docs/` madhlya documents che tukde (chunks) SQLite madhe index hotat. Pratyek tukdya sobat file che naav, page ani tarikh asate. Uttar detana Jarvis source sangto.
- **Fakt approved documents:** Tu `docs/` madhe takle kiva "ha document project madhe ghe" mhanalas tarach. Email attachment apoap jat nahi.
- **Agents sathi context pack:** Task suru jhala ki Jarvis agents na PROJECT.md, relevant tukde ani scoped memories deto. Agents te fakt vachu shaktat.
- **Lihinyacha niyam:** Agents fakt task folder madhe lihitat. Final output tapasun jhalyavar Jarvis `outputs/` madhe thevto.
- **Kay nahi:** Graph database ani multi-user access control. Ek user sathi garaj nahi.
- **Phase:** PROJECT.md ani scope Phase 3 madhe. Document indexing Phase 5 madhe. Scan kelelya PDF sathi OCR Phase 8 madhe.

---

## 7. Skill system

- Pratyek skill = ek folder + `SKILL.md` (name, description, instructions, scripts).
- Anthropic cha open standard (December 2025). Sept 2026 paryant 40+ tools vapartat.
- Suruvatila fakt skill chi naav ani description prompt madhe. Purna skill garaj aslyavarach load.
- **Jarvis navin skill shikto:** Motha kaam yashasvi jhale ki Jarvis skill suchavto. **Tu approve kelyavarach save.**
- **Ka approval:** Research nusar agent fail jhalelya prayatnatun pan chukichi skill banavu shakto. Model ne lihilelya skills cha fayda kami, manasane tapaslelya jast changlya.
- Baherun aanleli skill install karnyapurvi vachun tapasaychi. Tyat dhokadayak code asu shakto.

---

### Kaam dakhavun shikavne (Teach-by-Demonstration)

Tu ekda kaam karun dakhavtos. Jarvis tyache steps pakadto ani tyatun editable skill banavto.

**Kay record hote** ("record suru" ani "record band" chya madhe):

| Source | Kase | Phase |
|---|---|---|
| Jarvis sobat kelele kaam | Conversation ani pratyek tool call adhich log madhe asto. Sarvat bharvasyacha | 3 |
| Terminal commands | Record mode madhe terminal session cha log (`script` command) | 3 |
| File badal | Allowed folders cha adhi ani nantar snapshot | 3 |
| Tuze explanation | Chat kiva Telegram voice note: "ha step ka" | 3 |
| Mahatvache screenshots | Tu sangshil tevhach, satat nahi | 3 |
| Browser steps | Playwright codegen, vegalya browser profile madhe | 8 |

**Recording nantar:**
1. Jarvis `SKILL.md` cha draft banavto: steps, lagnare inputs (udaharan: tarikh, file che naav), adhi kay lagte, pratyek step cha risk level, ani kaam jhale he kase tapasaycha.
2. Tula draft dakhavto. Tu badal karu shaktos.
3. **Dry run:** Test input var chalavto. T2 kiva tyapeksha jast risk che steps pratyek veli vicharun.
4. Tu approve kelyavar skill version 1 mhanun save hote.
5. Pudhchya veli vaparto. Tu kahi durust kelas tar Jarvis skill update suchavto ani juni version japutun thevto.

**Kay nahi:** Mouse ani keyboard che satat recording. Tyala Input Monitoring ani Accessibility permissions lagtat, mhanje keylogger itke adhikar. pynput macOS 26 var crash hoto. Ani screen coordinates var aadharit replay UI badalla ki tutto. Mhanun commands, API ani browser DOM var aadharit steps ch vaparu.

---

## 8. Agent team

### 8.1 Team

| Agent | Kaam | Permission |
|---|---|---|
| Jarvis (manager) | Plan, kaam vatne, result jodne | Fakt toch tula permission magto |
| Researcher | Web shodh, sources | Fakt vachne |
| Writer | Report, document, draft | Fakt approved folder |
| Checker | Kaam khare jhale ka tapasne | Fakt vachne, result nakaru shakto |
| Coder (nantar) | Code, tests | Vegla folder |
| Operator (nantar) | Apps, files, browser | Safety levels nusar |

Sagle ekach Claude model. Instructions, tools ani skills vegvegalya. Sope kaam swasta model la.

### 8.2 Flow (udaharan: "₹80,000 paryant laptop, 3 options compare kar")

1. Samaj, garaj asel tar 1–2 prashna.
2. Plan: 3 researchers + writer + checker. Andaje kharcha dakhav.
3. Pratyek agent la work order: objective, tools, output format, budget, kevha thambaycha.
4. 3 researchers ekach veli.
5. Checker sources ani kimati tapasto.
6. Jarvis report banavto, Telegram var pathavto.
7. Yashasvi tar skill suchavto.

### 8.3 Research che akde

| Tathya | Akda |
|---|---|
| Team ne ek agent peksha changla result (Anthropic test) | 90.2% jast |
| Ek agent: chat peksha tokens | 4 pat |
| Team: chat peksha tokens | 15 pat |
| Team fail: kaam spashta nahi | 41.8% |
| Team fail: agents madhe gondhal | 36.9% |
| Team fail: tapasni kamjor | 21.3% |

### 8.4 Niyam

- Adhi Jarvis ekta. Team fakt motha ani vatun deta yenara kaam.
- Sopya prashnala 1 agent, comparison la 2–4, mothya research la jast.
- Ekmekanvar avalambun kaam (ekach feature cha code) team la nahi.
- Work order cha format thartla.
- Ek file, ek malak.
- Checker swatantra, shakya titke nakki tests.
- Ekach veli 3–5 agents. Worker navin agent banavu shakat nahi. Turn ani kharcha limit. Varvar fail = thamb.
- Agent chhota saransh parat deto, purna itihas nahi.
- Lamb kaam background la, progress Telegram var, crash nantar resume.
- Email/payment sarkhe kaam worker karu shakat nahi.

---

## 9. Task system: queue, receipts ani scheduling

### 9.1 Mission / Task queue

**States:**

BACKLOG → PLANNED → RUNNING → WAITING_APPROVAL → VERIFYING → COMPLETED / FAILED / CANCELLED

Tyasobat SCHEDULED (vel tharleli) ani PAUSED (tu thambavle, kiva model/internet nahi).
VERIFYING mudam thevla ahe. Tapasni jhalyashivay kontahi task COMPLETED hot nahi.

**Pratyek task var disnari mahiti:**

| Field | Udaharan |
|---|---|
| Owner | Jarvis / Researcher / Writer |
| Project | laptop-kharedi |
| Priority, deadline | High, udya 6 paryant |
| Progress | 3 paiki 2 steps |
| Current / next step | "Checker sources tapasat ahe" / "Report lihine" |
| Pending approval | "Report email karu ka?" |
| Last error | "Website timeout" |
| Retry | 1 / 3 |
| Kharcha | $0.14 / $0.60 budget |
| Receipt | data/tasks/t-031/receipt.md |

**Kuthe disel:**
- Phase 3: Terminal madhe `jarvis tasks`.
- Phase 4: Telegram var `/tasks`, `/task <id>`, `/pause`, `/cancel`.
- Phase 7: Dashboard var board.

**Queue che niyam:**
- "He nantar kar" mhatlas tar task BACKLOG madhe jato.
- Suruvatila ekach veli jast-ast 2 mothe tasks. Karan 16 GB RAM ani pratyek Agent SDK session la sumare 1 GiB lagte.
- Priority ani deadline pramane kram.
- Crash nantar RUNNING tasks shevtchya checkpoint pasun parat suru hotat.

### 9.2 Task receipt

Pratyek task samplyavar vachta yenari pavti.

- **Facts logs madhun yetat, LLM kadun nahi.** Task events ani audit log varun receipt banate, mhanun tyat khote lihile jaat nahi. LLM fakt don olincha saransh lihito.
- **Receipt madhe:** goal, plan, kontya agent ne kontya tool ne kay kele, kontya files badalalya (path ani diff), kay tapasle ani pass/fail, kontya approvals ghetlya ani tuze uttar, kontya models vaparle (fallback jhala asel tar to pan), kharcha, vel, final status, ani kay baki ahe.
- **Kuthe:** `data/tasks/<id>/receipt.md`. Chhoti version Telegram var. Terminal madhe `jarvis receipt <id>`.
- **Audit log machine sathi ahe. Receipt tuzyasathi ahe.**

```
COMPLETED · t-031 · Laptop compare · 14 min · $0.14
Plan: 3 researchers, writer, checker
- Researcher x3: 14 sources vachle (web_search, web_fetch)
- Writer: projects/laptop/outputs/compare.md banavla
- Checker: kimati 3/3 match, links 14/14 chaltat  [PASS]
Approvals: kahi nahi (sagle T0/T1)
Models: opus-5-5 (Jarvis), workers (routing nusar)
Baki: kahi nahi
```

### 9.3 Skill ani agent scheduling

Fakt heartbeat ani daily brief nahi. Kontyahi skill kiva agent la vel deta yeil.

Udaharan:
- Roj ratri 9 la "aajcha work report" skill.
- Dar somvari sakali 9 la project summary (Writer agent).
- Roj sandhyakali 6 la follow-up list tapasne.

**Pratyek schedule madhe:**

| Field | Arth |
|---|---|
| Kay chalvaycha | Skill, agent kiva prompt + input |
| Kevha | Cron, timezone Asia/Kolkata |
| Result kuthe | Telegram, file kiva donhi |
| Budget | Pratyek run chi limit |
| Permission | Tu nastana fakt T0/T1. T2 kiva jast asel tar approval queue madhe thambte |
| Missed run | Mac zoplela asel tar jaga jhalyavar ekda chalav, kiva grace vel sampli tar sod |
| Overlap | Magcha run chalu asel tar navin suru hot nahi |
| Status | Enabled/paused, shevtcha run, receipt |

- **Chat madhun banavne:** "Dar somvari 9 la project summary de" mhatlas ki Jarvis schedule samjun dakhavto. Tu ho mhanalas tarach save hote.
- **Commands:** list, pause, resume, run-now, delete.
- **Tech:** APScheduler (`misfire_grace_time`, `coalesce`, `max_instances=1`). Schedules SQLite madhe.
- **Maryada:** Mac band kiva zoplela asel tar schedule chalat nahi. Mac zoplela astana pan chalavi ashi kaame asli tar nantar cloud paryay (Claude Managed Agents scheduled deployments) vichar karu.

---

## 10. Safety

### 10.1 Risk levels

| Level | Kaam | Policy |
|---|---|---|
| T0 Read-only | Shodh, saransh, file vachne | Lagech |
| T1 Local lihine | Approved folder madhe navin file/draft | Lagech, nantar tapasni |
| T2 Motha badal | File overwrite, bulk edit, settings | Vichar |
| T3 Baherche / parat na yenare | Email send, post, payment, delete | Nehmi vichar, purna details dakhav |
| T4 Bandi | Security bypass, passwords, rm -rf | Kadhich nahi, log |

### 10.2 Mac var practical niyam (research madhun)

- Raw shell nako, **typed tools** (open_app, read_file). Shell tool asel tar `shlex.split`, `shell=False`, allowlist, baki sagle confirm.
- **Path check:** `Path.resolve()` + allowed folders. `~/.ssh`, `~/.aws`, Keychain, `.env`, `security` command band.
- **Timeouts:** pratyek command la timeout, process group kill, output limit, kami environment.
- **Secrets:** Keychain madhe (`keyring`). Logs madhun tokens kadhayche.
- **Prompt injection:**
  - Email/web text = data, aadnya nahi.
  - **Taint flag:** session ne email kiva web vachla ki fakt read-only tools vicharyashivay.
  - **Quarantined LLM:** tools nasleli vegli call content madhun JSON fields kadhte, main model la fakt te fields.
  - Content madhlya links/images apoap ughadaychya nahit.
  - Approval madhe exact arguments dakhavayche.
- **Emergency stop:** pratyek tool call adhi check. Flag file, Telegram `/stop` (LLM chya baher handle), menu bar button.
- **Audit log:** append-only JSONL: time, source, tool, arguments, decision, exit code, output hash.
- **Pratyek task la** step limit ani kharcha limit.

### 10.3 macOS permissions

- **v1 Terminal madhun chalavaycha.** Permissions Terminal la miltat. LaunchAgent, Full Disk Access, microphone nantar.
- **Screenshot:** `screencapture -x`. Screen Recording permission lagel, ani macOS mahinyatun ekda parat vicharte.
- **Notifications:** `osascript`.
- **Global hotkey:** pynput macOS 26 var crash hoto. Quartz event tap kiva Shortcuts/Raycast vaparaycha.
- **Nantar (v2):** Jarvis ek signed `.app` madhe, LaunchAgent ne login la suru. Mag permissions tikun rahtat.

### 10.4 Browser automation: vegla ani surakshit browser

Browser automation Phase 8 madhe yeil. Tevha he niyam lagu:

- **Tuzya Chrome pasun vegla.** Playwright cha swatacha Chromium. Tuza Chrome profile, passwords ani cookies kadhich vaparnar nahi.
- **Default:** Pratyek task la navin, kora browser context. Task samplyavar to band ani saaf hoto.
- **Login lagnari site:** Fakt tu approve kelelya site sathi vegla profile `data/browser/<site>/`, fakt tuzya user la access. Login tu swata karshil.
- **Domain allowlist:** Pratyek task la konte websites ughadu shakto he adhich nakki.
- **Downloads:** Task folder madhe, file type ani size tapasun.
- **Login, payment, form submit, post:** Nehmi T3. Approval madhe exact form ani values dakhavayche.
- **Page varcha text = data, aadnya nahi.** Browser vaparla ki taint flag lagto.
- **Screenshots** receipt madhe purava mhanun.
- **Adhi API.** API kiva sadha web fetch chalat asel tar browser vaparaycha nahi.

---

## 11. Proactive

- **Heartbeat:** Dar 30 minitanni Jarvis `HEARTBEAT.md` checklist vachto ani kahi sangnyasarkhe ahe ka tapasto (OpenClaw cha design).
- **Daily brief:** Sakali calendar, reminders, goals, weather, mahatvache emails.
- **Reminders ani goals:** goals.md varun athavda/mahina track.
- **Kadhi bolaycha:** fakt mahatvache asel tevha. Quiet hours.

---

## 12. Connectors

| Kram | Connector | Kase | Mehnat |
|---|---|---|---|
| 1 | Telegram | python-telegram-bot, long-polling (server nako), fakt tuzya user ID la parvangi, Approve/Deny buttons | Kami |
| 2 | Web search | Anthropic web search tool. Free backup: Tavily | Kami |
| 3 | Reminders + Calendar vachne | EventKit (pyobjc), Terminal madhun ekda permission | Kami–Madhyam |
| 4 | Google Calendar + Gmail | Direct Google API, OAuth "Desktop app" | Madhyam |
| 5 | Gmail send | `gmail.send`, nehmi approval nantar | Kami |
| 6 | Voice notes | Telegram OGG in/out | Madhyam |
| 7 | Apple Notes | AppleScript kiva MCP | Madhyam |
| 8 | WhatsApp | **Skip** | — |

**Mahatvache facts:**
- Google OAuth app "Testing" madhe asel tar token 7 divsat expire hoto. "In production" karaycha (personal use la verification nako, fakt warning).
- Google che official Gmail/Calendar MCP servers ajun Developer Preview madhe ahet. Gmail MCP draft-only ahe.
- Mail.app AppleScript ne email pathavne macOS 26 var bharvasyacha nahi.
- **WhatsApp:** 15 Jan 2026 pasun Meta ne Business API var general-purpose AI assistants band kele. Unofficial libraries ne number ban hou shakto. Mhanun Telegram.
- Anthropic web search: $10 prati 1,000 searches + tokens. Tavily: mahinyala 1,000 free credits.

### Connector ani MCP registry

Pratyek connector ani tool chi ek yadi: `connectors/registry.yaml`.

| Field | Udaharan |
|---|---|
| Naav, prakar | google-calendar, direct-api (kiva mcp-stdio, native) |
| Source ani version | Pinned version, kuthun aala |
| Auth | Keychain item che naav (secret nahi), scopes |
| Tools | Pratyek tool, tyacha risk level T0–T4, read ki write |
| Kon vaparu shakto | Jarvis, Researcher, ... |
| Health check | Chhota test call, shevtcha status, token kevha expire hoto |
| Enabled | Ho / nahi |

**Niyam:**
- Navin connector kiva navin tool aala ki default **T2 ani koni agent nahi**, jo paryant tu tyacha level tharvat nahis.
- MCP server cha version pin karaycha ani source vachaycha. MCP tool chi description pan untrusted manaychi, karan tyat lapleli aadnya asu shakte (tool poisoning).
- `jarvis connectors status` sagle health checks chalavto. Heartbeat roj ekda chalavto. Google token expire hot asel tar Telegram var sangto.
- **Phase:** Built-in tools sathi registry Phase 2 madhe. Connectors Phase 4–5 madhe jodle jatil. Dashboard tab Phase 7 madhe.

---

## 13. Voice

| Bhag | Choice | Note |
|---|---|---|
| Suruvat | Push-to-talk | Kami dhoka |
| Wake word | openWakeWord "hey_jarvis" | Tayar model, personal use la license OK |
| Fakt tuzach awaj | openWakeWord custom verifier | Gongat accuracy kami |
| STT English | Whisper | Kontya version cha (faster-whisper / mlx-whisper / whisper.cpp) to test karaycha |
| STT Marathi | IndicConformer / IndicWhisper | Sadha Whisper Marathi var kharab. Indic models read speech var ~10–15% WER |
| TTS English | macOS `say` "Rishi" | Offline |
| TTS Marathi | edge-tts "mr-IN-ManoharNeural" | Online lagte |
| Barge-in | silero-vad | Jarvis boltana madhech bolne |

**Apurna:** Voice research agent madhech thambavla. Phase 6 chya adhi Python 3.13 var he libraries chaltat ka, ani Mac var sarvat vegvan Whisper konta, he parat tapasayche.

---

## 14. Brain loop: kasa banavaycha

**Research chi recommendation: Claude Agent SDK (Python).**

**Ka:** File, shell, edit, streaming, sessions ani subagents che code swata lihave lagat nahi. Agent team sathi subagents adhich tayar ahet.

**Kase set karaycha:**
- `setting_sources=[]`, mhanje tuzi global CLAUDE.md (graphify) Jarvis madhe yenar nahi.
- `CLAUDE_CODE_DISABLE_AUTO_MEMORY=1`, mhanje SDK chi swata chi memory band, aapli vaparu.
- Custom system prompt: personality + memory index.
- Pratyek turn chya memories `UserPromptSubmit` hook ne.
- Ek `PreToolUse` hook = aapla T0–T4 gate. `deny` nehmi tikto.
- Confirm sathi `canUseTool`. Telegram var vicharaycha asel tar `defer`.
- Bash call `PreToolUse` madhech classify karaycha, karan auto-approved calls `canUseTool` la yet nahit.
- Agent team: `AgentDefinition` (prompt, tools, model, turn limit).
- `max_turns`, `max_budget_usd`, `interrupt()` emergency stop sathi.
- `fallback_model` (comma-separated list) ani pratyek `AgentDefinition` la vegla `model` deta yeto. He official Python SDK docs madhe tapasle.

**Tote (trade-off):**
- Pratyek session sathi ek subprocess, docs nusar ~1 GiB RAM. 16 GB Mac var ekach veli khup sessions nako.
- Kharcha fakt andaj, aapla vegla hishob lagel.

**Dusra paryay:** Anthropic SDK var swata loop. Purna control, pan jast code. **Nirnay tuzach.**

**Prompt caching:** Fixed tools ani personality adhi, mag halu badalnara memory index, shevti pratyek turn chya memories. Kharcha kami hoto.

---

## 15. Model routing ani fallback

**Mul niyam:**
- Routing **call cha prakar** pahun hote. Conversation chya madhech model badalat nahi, karan prompt cache ani thinking blocks model nusar vegle astat. Madhech badalla tar kharcha vadhto.
- Routing table nakki (deterministic) ahe, ani pratyek nirnay log madhe jato. LLM router nahi.
- Anthropic chi suchana: anek models chi cascade banavnyapurvi sarvat changla model kami effort var test kara. Anekda te purte, ani ek model mhanje ek cache.

**Models (Anthropic docs, 2026-10-06 chi yadi):**

| Model | ID | Input $ / 1M tokens | Output $ / 1M tokens |
|---|---|---|---|
| Opus 5.5 | `claude-opus-5-5` | 4.00 | 20.00 |
| Sonnet 5.5 | `claude-sonnet-5-5` | 2.00 | 10.00 |
| Haiku 5.5 | `claude-haiku-5-5` | 0.10 | 0.50 |

Haiku chi hi kimat 100K tokens paryant chya prompt sathi ahe.

**Routing table (suruvat):**

| Route | Model | Effort | Ka |
|---|---|---|---|
| Jarvis main conversation | Opus 5.5 | medium | Default, changla samaj |
| Mothe plan, team manager | Opus 5.5 | high | Kathin vichar |
| Memory extractor, query rewrite, intent/risk label, heartbeat check, receipt saransh | Haiku 5.5 | low | Sope ani khup vela hote. Tu swasta ani jalad model sangitlas |
| Researcher, Writer | Opus 5.5 low **kiva** Sonnet 5.5 medium | — | **Tuza nirnay.** Donhi test karun tharvu |
| Checker | Worker peksha kami nahi | high | Tapasni kamjor nako |
| Coder (nantar) | Opus 5.5 | high | Code sathi effort mahatvacha |
| Internet nahi | Ollama lahan model | — | Fakt chat, tools nahi |

**Fallback:**
1. 429 kiva 5xx error: automatic retry, `retry-after` pramane thambun.
2. Tari fail: Agent SDK cha `fallback_model` (Opus 5.5 nantar Sonnet 5.5).
3. Model ne nakar dila (refusal): code `stop_reason` tapasto. Opus ani Sonnet chya direct API calls var server-side `fallbacks: "default"`. Haiku la ha paryay nahi, mhanun aapla code Sonnet var parat prayatna karto.
4. Sagle fail: task PAUSED, nantar retry, ani Telegram var sangne.
5. **Kadhich gupchup nahi.** Fallback jhala tar receipt madhe lihaycha ani tula sangaycha.
6. **Safety model var avalambun nahi.** Kontahi model asla tari T0–T4 niyam tech.

**Budget:**
- Pratyek task la `max_budget_usd`. He client-side andaj ahe, mhanun limit thodi kami thevaychi.
- Pratyek route ani mahinyacha cap, 80% la warning.
- `model_usage` table: route, model, tokens, andaje kharcha, fallback jhala ka.

**Implementation note:** Opus 5.5 var thinking band karta yet nahi ani `budget_tokens` chalat nahi. Kharcha `effort` ne control karaycha. Forced `tool_choice` pan chalat nahi.

---

## 16. Tech stack

| Bhag | Choice | Ka |
|---|---|---|
| Language | Python 3.13, project venv | Installed |
| Brain | Claude API, cloud-first | 16 GB var local models kami smart |
| Agent loop | Claude Agent SDK (recommended) | Subagents, hooks, sessions tayar |
| Models | Opus 5.5 main, Haiku 5.5 sope kaam, workers test karun | Model routing section paha |
| Fallback | Ollama + lahan model (optional) | Internet nasel tevha |
| Memory | Markdown + SQLite (FTS5 + numpy vectors) | Server nahi, editable, extension nako |
| Embeddings | multilingual-e5-small | Lahan, MIT, test karun badalu |
| Skills | SKILL.md standard | Open standard |
| Scheduler | APScheduler | Heartbeat, brief |
| Phone | python-telegram-bot | Long-polling |
| Mac control | pyobjc, osascript, screencapture | Native |
| Secrets | Keychain (keyring) | .env peksha surakshit |
| Voice | openWakeWord, Whisper, say, edge-tts | Varti pahile |
| Dashboard | FastAPI + Next.js | Node installed |
| Browser automation | Playwright Chromium, vegla profile | Phase 8 |

**Kadhle:** PostgreSQL, pgvector, Redis, n8n, users/roles/login, Zapier, Higgsfield, WhatsApp, 15 vegle agents, 14 tabs.
**Ka:** Ek user, ek Mac, 16 GB RAM. Garaj vadhli tar SQLite varun PostgreSQL la jaata yete.

---

## 17. Phases

| Phase | Kaam | Purna kevha |
|---|---|---|
| **0. Setup** | venv, config, Keychain, folders, SQLite, audit log, CLI chat | "Good evening, sir." |
| **1. Brain + Memory** | Agent loop, SOUL.md, profile interview, Marathi samaj, memory write/read, session search, memory commands, skill system cha paya, model routing cha paya (Opus main, Haiku extractor) | Memory test: 10 goshti shikav, navin session madhe kamit kami 9 barobar. "Act" test pan pass |
| **2. Tools + Safety** | Typed tools, T0–T4, approvals, taint flag, kill switch, verifier, audit, daily info, media controls, connector registry (built-in tools) | 10 kaame verify. Ek pan T4 action chalat nahi. Prompt injection samples kaam karat nahit |
| **3. Tasks + Agent team** | Task queue ani states, planner, task folder, receipts, project workspace, teach-by-demonstration (chat, terminal, files), model routing, Researcher/Writer/Checker, budgets, resume | Laptop-compare sarkhe kaam report ani yogya receipt sobat, budget madhe. Ek dakhavlele kaam skill banun parat chalte |
| **4. Telegram + Proactive** | Bot (fakt tu), approve buttons, /stop, /tasks, heartbeat, daily brief, reminders, skill ani agent schedules | Sakali brief phone var. Phone varun approve chalte. Ek weekly schedule chalto ani missed run nit hatalto |
| **5. Connectors** | EventKit, Google Calendar, Gmail (read/draft, approval nantar send), registry entries ani health checks, document library | "Udya 11 la call lav" → event banto ani verify hoto. Project docs madhun source sobat uttar |
| **6. Voice** | Push-to-talk, Whisper, Rishi/Manohar, mag hey_jarvis, barge-in, awaj olakh, Marathi STT test | 5 voice commands chaltat |
| **7. Dashboard** | FastAPI + Next.js: Chat, Memory, Task board & Approvals, Agents, Connectors, Schedules, Settings & Usage | Browser madhun sagla control |
| **8. Extras** | Coder/Operator agents, magic search, meeting notes, Playwright vegalya profiles sobat, browser steps che recording, OCR, smart home, signed .app | Garaj nusar |

---

## 18. Anek laptops ani Claude accounts var kaam

Ha project anek divas chalel. Kaam kadhi thambel ani kadhi parat suru hoil. Kadhi ya laptop varun, kadhi dusrya laptop varun, ani kadhi dusrya Claude account varun kaam hoil.

- **Repo hach ekmev source of truth:** https://github.com/Sachinx1911/jarvis. Claude chi local memory laptop ani account nusar vegli aste, ti dusrikade yet nahi.
- **Context chya 3 files:** PLAN.md (plan), PROGRESS.md (sthiti, half-done kaam, pudhcha step), CLAUDE.md (Claude sathi niyam, Claude Code apoap vachto).
- **Session suru:** `git pull`, mag PROGRESS.md vachne.
- **Session sampavtana:** PROGRESS.md update, commit, push. Kaam madhech thambla tari "half-done" ani "exact next step" lihaycha.
- **Secrets:** Pratyek laptop chya Keychain madhe vegle. Repo madhe kadhich nahi.
- **Claude account badalla tari:** Jarvis chi API key Anthropic Console chi ahe, ti vegli ahe. Claude Code cha account badalnyane Jarvis var farak padat nahi.
- **Navin laptop:** clone, setup script (Phase 0 madhe banel), Keychain madhe key, ani macOS permissions parat dene.
- **Repo public ahe:** Code ani plan sarvanna distat. Jarvis chi memory, profile, projects, logs ani learned skills `.gitignore` madhe ahet. Tyancha backup vegalya private jagi.
- **Jarvis app kuthe chalel:** Ekaveli ekach Mac var chalavne changle. Don laptops var chalavaycha asel tar memory sync lagel, tyasathi private git repo kiva encrypted backup.

---

## 19. Development che niyam (Claude Code sathi)

1. Adhi existing files tapas, lagech code badlu nako.
2. Ek veli ek phase. Tuzya "Start Phase X" nantarach.
3. Pratyek phase nantar tests, kay badalle tyacha report, ani thamb.
4. Navin package add karnyapurvi karan sang.
5. Secrets, tokens, personal data code madhe nahi.
6. Permissions, approvals, logs ani tests he core features, polish nahi.
7. Test fail jhala tar lapvu nako. Karan ani paryay sang.
8. Kam chalnara code vinakaran parat lihu nako.

Build suru jhalyavar he niyam repo madhe `CLAUDE.md` mhanun thevu.

---

## 20. Version 1 "purna" kevha

- Text ne kaam gheto ani task state/history dakhavto.
- Shikavlele navin session madhe vaparto (memory test pass).
- Memory dakhavto, ani tu edit/delete karu shaktos.
- Plan, permission decision ani verification log karto.
- Approved folder madhe report banavto ani file tapasto.
- Agent team ne ek motha kaam purna karto.
- Pratyek task chi vachta yenari receipt milte.
- Ek dakhavlele kaam skill mhanun parat chalte.
- T3 kaam permission shivay kadhich hot nahi.
- Timeout, failure, cancel ani duplicate request hatalto.
- Phone var Telegram ne bolta yete ani sakali brief yeto.
- Automated tests pass.

---

## 21. Testing

**Memory eval (sarvat mahatvacha):**
- 50–100 scenarios: shikav, madhe dusre sessions, mag prashna.
- Mojaycha: kay save jhale (precision/recall), juni gosht nit superseded jhali ka, yogya memory top-5 madhe ali ka.
- "Act" test: prashnat memory cha ullekh na karta Jarvis tyanusar vagto ka.
- Na shikavleli gosht vicharli tar "mahit nahi" mhanto ka.
- Dar athavdyala 20 random memories haatane tapasun kachra mojaycha.
- Prompt badalla ki sagle parat chalavayche.

**Itar:** safety tests (band actions, prompt injection, secret leak), failure tests (timeout, internet nahi, crash), Marathi-English mixed commands, duplicate actions, model fallback, ani Mac zoplyavar missed schedule.

**Metrics:** memory recall, task success, verified completion, safety events, API kharcha prati task, latency.

---

## 22. Kharcha

- Navin hardware **nako**. M4 Mac purto.
- Mukhya kharcha = Claude API vapar. Agent team vaparli tar jast (15 pat tokens).
- Web search: Anthropic tool $10 prati 1,000 searches. Tavily free backup.
- Pratyek task la ani mahinyala kharcha limit, ani warning.
- Mahinyacha budget tu tharvaycha.

---

## 23. Tharvaychya goshti

| # | Prashna | Mazi suchana |
|---|---|---|
| 1 | **Jarvis ne roj karavit ashi tuzi 5 kaame** | Sarvat mahatvache. Tuzyakadun pahije |
| 2 | Claude API key ahe ka? | Cloud-first |
| 3 | Brain loop | Claude Agent SDK |
| 4 | Voice bhasha | Adhi English voice + Marathi text, Marathi voice nantar |
| 5 | Connectors kram | Telegram, web search, Calendar, Gmail |
| 6 | Mahinyacha API budget | Tu sang |
| 7 | Naav | "Jarvis" |
| 8 | WhatsApp skip chalel ka? | Ho, Telegram vapar |
| 9 | Worker agents cha model | Opus 5.5 kami effort ki Sonnet 5.5. Donhi test karun tharvu |
| 10 | Jarvis chya personal data cha backup ani sync | Vegla **private** GitHub repo (udaharan `jarvis-memory`) |
| 11 | Code repo public thevaycha ka? | Tuzi nivad. Public asla tari personal data tyat jaat nahi |

---

## 24. Ajun tapasayche

- Voice libraries Python 3.13 ani macOS 26 var (research apurna).
- Google official MCP personal Gmail account la chalto ka.
- Memory thresholds (0.97 / 0.85) tuzya data var.
- Embedding model tuzya khare prashna var.
- Shortcuts CLI macOS 26 var kiti bharvasyacha.
- Agent SDK cha `fallback_model` nakki kontya errors var chalto. Docs madhe spashta nahi.
- Agent SDK madhun Opus/Sonnet sathi server-side refusal `fallbacks` deta yeto ka.

---

## 25. Sources

**Jarvis projects ani trends**
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

**Marathi search ani embeddings**
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

**Mac ani safety**
- https://9to5mac.com/2024/08/14/macos-sequoia-screen-recording-prompt-monthly/
- https://github.com/apple/container
- https://ai.meta.com/blog/practical-ai-agent-security/
- https://simonwillison.net/2025/Apr/11/camel/
- https://www.anthropic.com/research/prompt-injection-defenses

**Browser ani scheduling**
- https://playwright.dev/python/docs/codegen
- https://apscheduler.readthedocs.io/en/3.x/userguide.html

**Voice**
- https://github.com/dscripka/openWakeWord/blob/main/docs/models/hey_jarvis.md
- https://github.com/dscripka/openWakeWord/blob/main/docs/custom_verifier_models.md
- https://github.com/AI4Bharat/IndicConformerASR
- https://arxiv.org/pdf/2305.15386
- https://json2video.com/ai-voices/azure/languages/marathi/
