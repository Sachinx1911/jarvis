# Jarvis wins on reliability, not breadth

Jarvis already covers more ground than most commercial assistants offer one user in India. It has long-term memory, schedules and a morning brief, a Telegram channel, Gmail and Calendar, a research team, browser and computer agents, and code-enforced approval tiers. The gaps that matter are not missing headline features. They are the qualities users reward: **jobs that run every day without failing, memory the user can see and correct, approvals that show their effect instead of prompting all the time, and agents that check their own work before saying "done"**. Usage studies show daily assistant use is dominated by asking for guidance, looking things up and editing text. **Only about a quarter of AI users use agents regularly, and only 9% accept fully autonomous purchases.** For India, the hard limits are clear. **WhatsApp has been closed to general-purpose AI assistants since 15 January 2026.** Agentic UPI exists only as pilots run by licensed players. DigiLocker and UMANG APIs onboard organisations only. So Jarvis's India value lies in safe "prepare and remind" features: bill and AutoPay tracking, a document wallet with Aadhaar masking, AMFI and IMD data, and Marathi speech through AI4Bharat models. Most evidence below is vendor-published or secondary, as of 10 October 2026, and is labelled where it is weak.

## Every vendor now ships memory, schedules and browser agents behind confirm gates

By October 2026 the major assistants have converged on the same core. ChatGPT's June 2026 memory upgrade updates memories automatically and lets users review their "sources" and a summary ([OpenAI release notes](https://help.openai.com/en/articles/6825453-chatgpt-release-notes)). Claude's chat and Cowork have shared one memory since 25 August 2026. Memories can be viewed and edited by topic, and **health and politics are excluded unless the user opts in** ([The Next Web](https://thenextweb.com/news/anthropic-claude-cowork-shared-memory-default); [9to5Mac](https://9to5mac.com/2026/08/25/anthropic-update-unifies-memory-feature-across-claude-cowork-and-chat/)). Proactive feeds are giving way to user-configured scheduled tasks. ChatGPT Pulse was reportedly retired in June 2026 and folded into Scheduled Tasks and web-monitoring tasks. That claim comes from secondary sources and is not confirmed in OpenAI's notes ([TechJack Solutions](https://techjacksolutions.com/ai-brief/agentic-ai-news-openai-launches-scheduled-tasks-in-chatgpt-a/)). Gemini offers scheduled actions on paid plans ([How-To Geek](https://www.howtogeek.com/gemini-scheduled-actions-are-finally-live/)).

Browser and computer agents are the current frontier. They include ChatGPT agent, Gemini auto browse in Chrome (live in India, but English-device only, with reported daily caps), Copilot Mode in Edge, and Claude for Chrome as a Cowork client ([OpenAI Help](https://help.openai.com/en/articles/11752874-chatgpt-agent); [Google India blog](https://blog.google/intl/en-in/products/bringing-gemini-in-chrome-with-auto-browse-to-india/); [The New Stack](https://thenewstack.io/claude-chrome-cowork-sessions/)). Microsoft runs Copilot Actions in a **separate, auditable "Agent Workspace" desktop** and asks before touching local files ([Windows Insider blog](https://blogs.windows.com/windows-insider/2025/11/17/copilot-on-windows-copilot-actions-begins-rolling-out-to-windows-insiders/)). Copilot Vision lets the user share a window for one session and stores nothing ([Copilot Labs](https://copilotlabs.microsoft.com/experiment/copilot-vision)). Voice in Indian languages is mature. Alexa+ India handles English, Hindi and Hinglish with mid-sentence switching ([Amazon](https://www.aboutamazon.com/news/devices/alexa-plus-international-launch)), and Google Search Live added Marathi in March 2026 ([Google India blog](https://blog.google/intl/en-in/products/explore-communicate/search-live-comes-to-more-indian-languages/)).

The safety pattern is the same everywhere: confirm before consequential actions, and never complete a payment autonomously. One test shows prompt-level rules are not enough. In Zenity's test of Atlas, a "confirm before sending" rule was defeated by injected text that pre-answered the confirmation. The only barrier that held was a code-level block on Amazon's buy button. That account comes from a secondary review ([AgentGuard](https://www.agentguard.one/review/chatgpt-atlas-agent-mode/)).

Open-source personal agents have converged on a recognisable shape. OpenClaw and Nous Research's Hermes Agent (Python) combine a chat gateway (Telegram first), cron, file-based skills, bounded profile memory with **FTS5 session search**, MCP and command approval ([Hermes GitHub](https://github.com/nousresearch/hermes-agent)). OpenClaw's heartbeat is the most copied design. Its rules:

- The model replies `NO_REPLY` when nothing needs attention.
- Runs happen only within set active hours.
- Results go only to the owner's DM.
- Runs are skipped when the checklist is empty.
- An isolated context cuts a run from **about 100K to 2–5K tokens**.
- Exact-time jobs live in cron, with their own run history, because the heartbeat "is prompt context, not a scheduler".

Source: [OpenClaw docs](https://docs.openclaw.ai/gateway/heartbeat).

OpenClaw is also the cautionary case:

- **341 malicious skills** were found among 2,857 on ClawHub ([The Hacker News](https://thehackernews.com/2026/02/researchers-find-341-malicious-clawhub.html)).
- **30,000+ gateways were exposed** to the internet because it bound to 0.0.0.0 by default.
- An indirect injection rewrote its HEARTBEAT.md so that it took commands from an attacker's server ([The Hacker News](https://thehackernews.com/2026/02/openclaw-integrates-virustotal-scanning.html)).

Jarvis already avoids most of these by design. The lesson to keep is that any file the agent can edit (heartbeat, skills, memory) is a place where an injection can persist.

## Users reward quiet, reliable help and refuse to hand over payment

The largest usage study shows what assistants are mostly for. In OpenAI/NBER's analysis of ChatGPT, practical guidance, seeking information and writing make up **nearly 80% of conversations**. Within writing, editing the user's own text beats writing from scratch, and non-work use rose to 73% ([NBER w34255](https://www.nber.org/papers/w34255); figures via [TechSpot](https://techspot.com/news/109483-openai-reveals-how-people-really-use-chatgpt-personal.html)). Microsoft's report on 37.5M conversations found **health is the top mobile topic at every hour** ([Microsoft AI](https://microsoft.ai/news/its-about-time-the-copilot-usage-report-2025/)). In nearly one in five health chats, people describe their own symptoms or test results, often on behalf of family ([Microsoft AI health](https://microsoft.ai/health/)). Indian users lean technical. OpenAI reports India's technical-task share at **nearly 4x the global average**, with about 2x more education questions ([OpenAI](https://cdn.openai.com/signals/how-india-uses-chatgpt.pdf)). An older Indian survey found 90% of users typed and only 10% used voice ([Outlook Business](https://www.outlookbusiness.com/start-up/chatgpt-most-used-ai-platform-to-find-info-in-india-31-willing-to-switch-to-deepseek-survey)). For Jarvis, that makes the core loop fast, sourced answers, coding and learning help, and text editing. Voice is a useful add-on.

Agents are a power-user feature. Menlo's 2026 survey found **41% of AI users have tried an agent and 24% use one regularly**, and 92% of agent users pay ([Menlo 2026](https://menlovc.com/wp-content/uploads/2026/09/menlo_ventures_consumer_ai_report-2026.pdf)). Real-site reliability is still poor. Booking agents succeed on **17–33% of tasks** ([arXiv 2602.12544](https://arxiv.org/pdf/2602.12544)), and shopping agents on under 35% ([arXiv 2506.02839](https://arxiv.org/html/2506.02839v1)). An older study found that most booking failures went unnoticed by the agent itself ([arXiv 2407.13032](https://arxiv.org/pdf/2407.13032)). Trust in agent purchases is falling. In Q1 2026, **55% of US and UK consumers were uncomfortable with agents buying for them**, down from about 7 in 10 being comfortable a quarter earlier ([Riskified](https://ir.riskified.com/node/8896/pdf)). Accenture found 32% would let an agent choose a product if they still confirm payment, but **only 9% accept fully autonomous purchases** ([Accenture](https://www.accenture.com/ma-en/insights/consulting/talk-my-ai-agent)).

Memory and approvals each have a failure mode users notice. In a CHI 2026 interview study, most ChatGPT users had negative surprises when they saw what was remembered. They asked for visibility and control ([UGA Grady](https://grady.uga.edu/research/ai-never-forgets-exploring-users-perceptions-of-ai-memory-and-chatgpts-memory-feature/)). On approvals, a 2026 paper reports that users switch to "allow everything" rather than answer hundreds of prompts. It also notes that prompts show commands, not their effects ([arXiv 2604.13536](https://arxiv.org/pdf/2604.13536)). Anthropic reports users approving about 93% of Claude Code permission prompts ([Anthropic](https://www.anthropic.com/engineering/how-we-contain-claude)).

The clearest signal from individual builders is about reliability. In HN threads, morning briefings are the most-cited use. One user said theirs is "easily worth an hour of my day", while another dropped a Raspberry Pi briefing that worked only once or twice a week ([Ask HN](https://news.ycombinator.com/item?id=47783940)). Complaints focus on upgrades breaking setups and idle loops costing "a few dollars a day while doing nothing" ([Ask HN](https://news.ycombinator.com/item?id=49871556)). This evidence is anecdotal. There is no public per-feature retention data from any vendor.

## India closes WhatsApp, payments and government APIs to personal apps

**WhatsApp.** Meta's Business Solution terms have barred general-purpose AI assistants since 15 January 2026. ChatGPT, Perplexity and others left, and Meta AI is the only general assistant remaining ([respond.io](https://respond.io/blog/whatsapp-general-purpose-chatbots-ban); [Business Standard](https://www.business-standard.com/technology/tech-news/meta-bans-ai-chatbots-from-whatsapp-business-api-chatgpt-to-shut-down-jan-2026-125102200335_1.html)). The EU got a paid 12-month exception, which is not stated to apply to India ([Thurrott](https://www.thurrott.com/?p=333392)). Unofficial personal-account libraries breach WhatsApp's terms, and their own docs warn of bans ([OpenWA README](https://gitblind.noratr.app/rmyndharis/OpenWA)). The exact clause was not read first-hand. The practical answer is the same either way: keep Telegram as the remote channel, and treat WhatsApp as read-only input at most, for example chat exports that Sachin provides by hand.

**Payments.** Agentic UPI exists only as licensed pilots. The October 2025 pilot by NPCI, Razorpay and OpenAI used UPI Reserve Pay with bank partners ([TechCrunch](https://techcrunch.com/2025/10/09/india-pilots-ai-chatbot-led-e-commerce-with-chatgpt-gemini-claude-in-the-mix)). A reported NPCI "Unified Agent Protocol" with about ₹10,000 Reserve Pay caps is **unconfirmed by NPCI** ([Inc42](https://inc42.com/buzz/npci-to-launch-agentic-payments-on-upi-report/)). A self-built app cannot register as a UPI agent. Jarvis's safe scope is to:

- read payment alerts and receipts;
- track subscriptions and AutoPay mandates (the no-PIN limit is ₹1,00,000 only for mutual funds, insurance and credit-card bills, and ₹15,000 for everything else) ([PersonalFN](https://www.personalfn.com/dwl/Mutual-Funds/no-more-otp-hassle-rbi-greenlights-hike-in-transaction-limit-for-upi-auto-payments));
- remind before due dates;
- hand the user a payment link to complete in his own UPI app.

**Government services.** API Setu, DigiLocker Requester and UMANG require organisational PAN, GST and an official email domain ([API Setu SOP](https://cdn.apisetu.gov.in/portal/assets/sop-apisetu-v0.pdf); [DigiLocker Requester Terms](https://cf-media.api-setu.in/resources/DigiLocker-Terms-of-User-Requester-june-2025.pdf)). IRCTC historically penalised booking automation, though its current terms were not fetched ([Medianama](https://www.medianama.com/2011/06/223-itz-cash-asks-franchisees-to-abide-by-irctc-rules-or-face-action/)). Aadhaar regulations bar keeping Aadhaar numbers beyond the consented purpose, and UIDAI recommends masked Aadhaar ([UIDAI regulations](https://www.uidai.gov.in/images/The_Aadhaar_Sharing_of_information_regulation_2016.pdf)). What works is a local document wallet: files Sachin downloads himself, with Aadhaar masked on ingest, expiry reminders, and links to the official portals.

**Open data sources.** Three good sources are open and free:

- AMFI's daily NAV file at amfiindia.com/spages/NAVAll.txt ([SEBI circular](https://www.sebi.gov.in/legal/circulars/feb-2001/disclosure-of-navs-on-amfi-website_18073.html)).
- IMD's API gateway, free for non-commercial use with a key ([IMD RTI reply](https://internal.imd.gov.in/section/rti/rticases/20260112_rti_211.pdf)).
- NDMA Sachet's CAP alert feeds for Maharashtra ([thejeshgn.com](https://thejeshgn.com/2025/05/28/common-alerting-protocol-cap-in-the-indian-context/)).

Railways has no documented public PNR API, and third-party ones are unstable ([code2care](https://code2care.org/2015/irctc-indian-railways-official-erail-api-11-for-developers-train-info)).

**Language.** AI4Bharat's IndicConformer Marathi ASR, IndicF5 TTS and IndicTrans2 are listed as MIT and run locally ([AIKosh IndicConformer MR](https://aikosh.indiaai.gov.in/home/models/details/ai4bharat_indicconformer_stt_mr_hybrid_ctc_rnnt_large_marathi_automatic_speech_recognition_model.html); [AIKosh IndicF5](https://aikosh.indiaai.gov.in/home/models/details/aibharat_indicf5.html)). Stock Whisper large-v2 scores **38.3% WER on Marathi**, against **18.2% for IndicWhisper** ([MMS paper](https://arxiv.org/pdf/2305.13516); [Vistaar](https://github.com/AI4Bharat/vistaar)). Jarvis's "Whisper pending" plan should therefore start from the AI4Bharat models, not stock Whisper. Bhashini's official sign-up terms could not be retrieved.

**Privacy law.** The DPDP Act's Section 3 excludes data processed by an individual for a personal or domestic purpose, which covers Sachin's own household assistant ([dpdpa.com](https://dpdpa.com/dpdpa2023/chapter-1/section3.html)). Aadhaar rules apply regardless of that exemption.

## Jarvis's gaps sit in trust plumbing and India-specific daily data

Compared with the field, Jarvis lacks few capabilities outright. Its gaps cluster in three areas.

**Trust and reliability.** These close the gap between "has the feature" and "users keep using it":

- **Memory inspector.** Jarvis stores memory in markdown and SQLite, but there is no view of what it remembers, with the source chat for each item and one-click edit or delete. ChatGPT and Claude now ship this, and the CHI study shows its absence causes distrust.
- **Sensitive-topic default.** There is no default exclusion of health and political topics from memory, unlike Claude's.
- **Job reliability.** Schedules, heartbeat and the morning brief exist, but users drop a brief that fails. Every job needs a run history, an alert when a run fails or is missed, and a quiet heartbeat: `NO_REPLY`, active hours and a cheap isolated context.
- **Effect previews in approvals.** Approval prompts should show what will change, where, and how much money is involved, and should group low-risk steps. That counters approval fatigue before standing approvals widen what Jarvis can do on its own.
- **Verify after acting.** Operator and browser agents should read back or screenshot the result before reporting success, because real-site agents fail silently.

**Missing capabilities with clear evidence of value.** These are:

- Web-monitoring and event-trigger tasks: page change, price drop, a mail from a named sender. ChatGPT folded Pulse into exactly this, and Jarvis's triggers are in progress.
- On-request, session-only screen understanding, as in Copilot Vision. It is feasible with a screenshot tool behind T1 approval, and nothing should be stored.
- Photo and receipt input over Telegram, feeding the existing receipt and document pipeline.
- Health questions answered with sources and a strict privacy default, given that health is the top mobile topic.

**India-specific.** Jarvis has none of these yet:

- a bill, subscription and AutoPay tracker built from Gmail receipts, with UPI hand-off links, that never initiates a payment;
- a local document wallet with Aadhaar and PAN redaction applied before any cloud call;
- statutory deadline reminders (ITR, advance tax), noting that the exact statute sections were not verified;
- AMFI NAV, IMD forecast and Sachet disaster-alert feeds;
- Marathi speech on AI4Bharat models.

**Things to skip deliberately:**

- WhatsApp automation (terms breach and ban risk on his main number);
- any UPI or payment execution (prohibited in Jarvis's rules, and not available to individuals);
- IRCTC or Tatkal booking scripts;
- government-portal scraping behind login;
- an open skill marketplace (the ClawHub precedent);
- smart-home control, since Alexa+ already covers that and the value for Sachin is unproven.

MCP client support is the main ecosystem standard, but tool poisoning makes it risky. If added, each server should be approved manually, with every MCP tool output treated as tainted.

| Gap | Evidence of user value | Feasibility (Python, Win/Mac) | Safety risk |
|---|---|---|---|
| Job run history and quiet heartbeat | High (HN abandonment, cost complaints) | High | Low |
| Memory inspector and sensitive-topic exclusion | High (CHI 2026, vendor convergence) | High | Lowers risk |
| Effect-preview approvals | High (approval-fatigue studies) | Medium | Lowers risk |
| Web-monitor and event triggers | Medium-high (ChatGPT Tasks pivot) | High | Medium (tainted inputs) |
| Marathi STT/TTS via AI4Bharat | Medium (voice minority, but Marathi niche) | Medium (RAM, latency unmeasured) | Low |
| Bills, AutoPay and UPI hand-off tracker | Medium-high (money reminders, safe scope) | High (Gmail exists) | Medium (financial data) |
| Document wallet with redaction | Medium | High | Lowers risk if redaction is solid |
| AMFI, IMD and Sachet feeds | Medium | High (open feeds) | Low |
| Session-only screen understanding | Medium (Copilot Vision, Siri on-screen) | High | Medium (screen may hold secrets) |
| Verify-after-act for agents | High (silent failures on benchmarks) | Medium | Lowers risk |

## Conclusion

The research changes where Jarvis's effort should go. Commercial vendors compete on agent breadth, yet the evidence shows breadth is not what users keep. They keep a small set of jobs that work every day, memory they can audit, and agents that prepare work while the user confirms. Jarvis's edge comes from what no commercial product combines: Marathi, local control of the computer, private memory, and India-aware safety rules. That edge grows more from making existing features dependable and visible than from adding new surfaces. India's closed WhatsApp, UPI and government APIs are a design constraint that pushes Jarvis toward "track, remind, prepare, hand off", which happens to be the posture users trust most.

Prioritized build list, top 10:

1. **Job run history, missed-run alerts and a quiet heartbeat** (NO_REPLY, active hours, isolated cheap context): users abandon unreliable briefs, and idle loops cost real money.
2. **Memory inspector with sources, edit and delete, plus a default exclusion of health and politics**: visible, controllable memory is the top trust request, and both leading vendors ship it.
3. **Effect-preview approvals with low-risk batching, before standing approvals go live**: approval fatigue turns prompts into rubber stamps, so prompts must show what will change.
4. **Finish event triggers as web and mail monitors (page change, price drop, sender match), with tainted inputs**: this is where ChatGPT moved after Pulse, and it reuses Jarvis's schedules and price tiers.
5. **Verify-after-act for Operator, Coder and browser tasks** (read-back or screenshot before "done"): real-site agents fail silently in most booking and shopping attempts.
6. **Marathi STT on IndicWhisper or IndicConformer, replacing the pending stock Whisper**: about 18% WER against 38% for Whisper large-v2, and local, so it fits the provider interface.
7. **Bills, subscriptions and AutoPay tracker from Gmail receipts, with due reminders and UPI hand-off links only**: high daily value inside the only payment scope a personal app may legally use.
8. **Local document wallet with Aadhaar and PAN masking on ingest and before any cloud call, plus expiry and tax-deadline reminders**: covers the DigiLocker and UMANG API gap safely and meets UIDAI masking guidance.
9. **AMFI NAV, IMD forecast and Sachet Maharashtra alert feeds in the morning brief**: free, official, low-risk Indian data that no global assistant provides in Marathi.
10. **On-request, session-only screen understanding and Telegram photo/receipt input**: matches Copilot Vision and Siri's direction at low cost, with nothing stored and a T1 approval for each capture.
