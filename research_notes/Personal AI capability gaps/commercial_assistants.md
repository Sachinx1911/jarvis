# Commercial personal AI assistants: capability inventory (as of 2026-10-10)

Scope: ChatGPT, Google Gemini, Microsoft Copilot, Apple Intelligence/Siri, Anthropic Claude apps, Amazon Alexa+, Meta AI, India-specific assistants (Sarvam Indus, Krutrim/Kruti, Jio).
Method note: 15 web searches/fetches. Many results were secondary (tech press, blogs, forum summaries). Primary sources are marked (P). Items dated before 2025 are marked [possibly outdated]. Anything not sourced is in Gaps.

## Q1. What capabilities do commercial assistants offer, grouped by capability?

### Takeaway
By October 2026 every major vendor offers memory, voice, and some kind of scheduled or background agent. The frontier is now browser/computer agents (ChatGPT agent, Gemini auto browse, Copilot Mode in Edge, Claude for Chrome/Cowork, Alexa+ "complete tasks") and cross-device sessions. India gets most features late, often English-only for agentic features, while voice in Indian languages is mature (Gemini Live 9 Indian languages since 2024, Alexa+ Hindi/Hinglish since Sept 2026).

### Cited Findings

**1. Proactive briefings / feeds**
- ChatGPT Pulse (Pro): did asynchronous research once a day based on past chats, memory and feedback, delivered as a morning feed — [OpenAI, Introducing ChatGPT Pulse (P)](https://openai.com/index/introducing-chatgpt-pulse/); [OpenAI release notes (P)](https://help.openai.com/en/articles/6825453-chatgpt-release-notes)
- Pulse reportedly retired on 2026-06-17; its useful parts were folded into user-configured Scheduled Tasks and web-monitoring tasks, with 14 days of legacy access for Pro — [TechJack Solutions](https://techjacksolutions.com/ai-brief/agentic-ai-news-openai-launches-scheduled-tasks-in-chatgpt-a/); [Prowlo](https://prowlo.com/blog/chatgpt-pulse-shut-down). NOT confirmed in OpenAI's release notes (the page seen ended at 2026-06-04).
- Meta AI: since July 2026 reportedly can send a daily briefing from calendar and email and run recurring jobs (e.g. weekly meal plan), starting in select markets and still spreading to WhatsApp — [PreScouter, Oct 2026](https://www.prescouter.com/2026/10/meta-ai-vs-chatgpt/) (single secondary source)
- Copilot "Proactive Actions" in Deep Research mode suggest next steps (Fall Release, Oct 2025) — [WindowsForum summary](https://windowsforum.com/threads/copilot-fall-release-mico-avatar-groups-collaboration-memory-and-edge-journeys.386524/)

**2. Scheduled and triggered tasks**
- ChatGPT Tasks: automated prompts ChatGPT runs for you (managed in Pulse in Dec 2025) — [OpenAI release notes (P)](https://help.openai.com/en/articles/6825453-chatgpt-release-notes). June 2026: new Scheduled Tasks sidebar hub; reportedly capped at once per hour and auto-paused if unattended — [TechJack Solutions](https://techjacksolutions.com/ai-brief/agentic-ai-news-openai-launches-scheduled-tasks-in-chatgpt-a/) (unverified)
- Gemini scheduled actions: launched June 2025 for AI Pro/Ultra and some Workspace plans, US/Canada/UK first then EEA; reportedly max 10 active actions — [How-To Geek](https://www.howtogeek.com/gemini-scheduled-actions-are-finally-live/); [GSMArena](https://www.gsmarena.com/googles_gemini_now_supports_scheduled_actions-news-68154.php)
- Gemini agent (Gemini at Work 2026, enterprise): can be assigned work, scheduled, or respond to events — [Google Cloud blog (P)](https://cloud.google.com/blog/products/ai-machine-learning/welcome-to-gemini-at-work-2026). A consumer "Agent Mode" tab absorbing scheduled actions and skills was leaked — [TestingCatalog](https://www.testingcatalog.com/google-prepares-agent-mode-on-gemini-to-tackle-complex-tasks/)
- Gemini Live + Spark (2026-08-26): hand off long-running jobs lasting days/weeks by voice; keeps running when the app is closed — [Claypier](https://claypier.com/en/gemini-live-spark-voice-agent/) (secondary)
- Claude Cowork: runs tasks in the cloud; started as a desktop app Jan 2026, web and mobile for Max by July 2026 — [MemX blog](https://memx.app/blog/claude-cowork-chat-shared-memory/); [9to5Mac](https://9to5mac.com/2026/08/25/anthropic-update-unifies-memory-feature-across-claude-cowork-and-chat/)
- Alexa+: voice-created Routines — [Amazon (P)](https://www.aboutamazon.com/news/devices/alexa-plus-international-launch)

**3. Memory and personalization**
- ChatGPT: June 2026 memory upgrade; memories update automatically, goal of reducing stale/contradictory memories, users can review "sources" and a memory summary — [OpenAI release notes (P)](https://help.openai.com/en/articles/6825453-chatgpt-release-notes). Claim that Gmail context feeds memory is unverified — [Substack review](https://digitalstrategyai.substack.com/p/what-i-learned-after-testing-every)
- Claude: chat and Cowork share one memory since 2026-08-25; on by default for Free/Pro/Max; health and politics excluded unless user opts into "include sensitive topics"; memories viewable/editable by topic; Claude Code not included — [9to5Mac](https://9to5mac.com/2026/08/25/anthropic-update-unifies-memory-feature-across-claude-cowork-and-chat/); [The Next Web](https://thenextweb.com/news/anthropic-claude-cowork-shared-memory-default); [The Register](https://www.theregister.com/ai-and-ml/2026/08/25/claude-and-cowork-now-share-what-they-know-about-you/5292412); [Dataconomy](https://dataconomy.com/2026/08/26/claude-memory-across-chats-and-cowork/)
- Copilot: remembers preferences, projects, prior context; user can view/edit/delete; explicit consent for memory and connectors (Fall Release, Oct 2025) — [WindowsForum](https://windowsforum.com/threads/copilot-fall-release-mico-avatar-groups-collaboration-memory-and-edge-journeys.386524/)
- Meta AI: memory viewable/deletable; also uses Facebook/Instagram profile data; context shared across WhatsApp/Messenger/Instagram — [PreScouter](https://www.prescouter.com/2026/10/meta-ai-vs-chatgpt/); [iTechGuides](https://www.itechguides.com/meta-ai-on-whatsapp-what-it-can-and-cant-do-in-2026/)
- Alexa+: recognizes family members, remembers preferences (music, teams, food) — [Amazon (P)](https://www.aboutamazon.com/news/devices/alexa-plus-international-launch)
- Siri personal context (reads your messages/mail/app data): repeatedly delayed; not in iOS 26.4 beta (Feb 2026); shown in iOS 27 developer builds at WWDC (2026-06-08) — [MacRumors](https://www.macrumors.com/2026/02/17/ios-26-4-no-new-siri-features/); [AppleInsider](https://appleinsider.com/articles/26/02/11/siri-testing-isnt-going-well-new-features-probably-wont-ship-in-ios-264); [Apple WWDC26 session (P)](https://developer.apple.com/videos/play/wwdc2026/240/)

**4. Email/calendar triage and drafting**
- Claude Cowork connectors for Google Drive and Gmail (enterprise release, Feb 2026) — [Wikipedia: Claude](https://en.wikipedia.org/wiki/Claude_(language_model))
- Meta AI daily briefing from calendar and email (July 2026, select markets) — [PreScouter](https://www.prescouter.com/2026/10/meta-ai-vs-chatgpt/)
- Alexa+: schedule management, sending party invitations — [Amazon (P)](https://www.aboutamazon.com/news/devices/alexa-plus-international-launch)

**5. Browser agents: travel/shopping/booking, form filling**
- ChatGPT agent: operates a browser, fills forms, runs multi-step workflows; safeguards include confirmations for high-impact actions, watch mode on sensitive sites, prompt-injection monitoring — [OpenAI Help: ChatGPT agent (P)](https://help.openai.com/en/articles/11752874-chatgpt-agent). OpenAI also describes a newer "ChatGPT Work" agent for longer tasks — [OpenAI release notes (P)](https://help.openai.com/en/articles/6825453-chatgpt-release-notes)
- ChatGPT Atlas browser (Oct 2025) with Agent Mode — [Wikipedia: ChatGPT Atlas](https://en.wikipedia.org/wiki/ChatGPT_Atlas). One report says Atlas is no longer offered and has a desktop-browser successor — [WindowsForum](https://windowsforum.com/news/chatgpt-atlas-agent-mode-enabled-cross-origin-data-theft-uw-finds.445938/latest) (unverified)
- Gemini in Chrome "auto browse": desktop and Android, AI Pro/Ultra, now in India; English-device-only for the agent part; caps reported at 20 tasks/day (Pro) and 200 (Ultra); not in Incognito; can add recipe items to a cart for user review — [Google India blog (P)](https://blog.google/intl/en-in/products/bringing-gemini-in-chrome-with-auto-browse-to-india/); [Gizbot](https://www.gizbot.com/artificial-intelligence/gemini-auto-browse-for-chrome-is-finally-live-in-india-here-is-what-it-actually-does-for-you-128999.html); [Storyboard18](https://www.storyboard18.com/digital/google-brings-geminis-auto-browse-to-india-turning-chrome-into-an-ai-task-doer-ws-l-112145.htm); [NewsBytes](https://www.newsbytesapp.com/news/science/google-launches-gemini-auto-browse-for-chrome-android-in-india/tldr)
- Copilot Mode in Edge: reasons over open tabs; opt-in actions like filling forms and bookings; Journeys groups past browsing into resumable storylines; US-first (Oct 2025) — [WindowsForum](https://windowsforum.com/threads/microsoft-copilot-fall-release-mico-memory-health-and-edge-agentic-features.386203/)
- Claude for Chrome: became a full Cowork client 2026-08-12 (Max/Team first); sessions continue on desktop/web/mobile; reported GA on paid plans 2026-08-26 (unverified) — [The New Stack](https://thenewstack.io/claude-chrome-cowork-sessions/); [AI Toolbox](https://www.ai-toolbox.co/claude-management-and-productivity/claude-for-chrome-setup-limits-2026)
- Alexa+: completes tasks start to finish (ordering a gift); restaurant bookings and food delivery "coming soon" in India; browser access "coming soon to India" — [Amazon (P)](https://www.aboutamazon.com/news/devices/alexa-plus-international-launch)

**6. Phone/device/computer control**
- Copilot Actions on Windows: works on local files inside a separate "Agent Workspace" (separate desktop instance), contained and auditable; Windows Insiders, Copilot Labs experiment (Nov 2025) — [Windows Insider blog (P)](https://blogs.windows.com/windows-insider/2025/11/17/copilot-on-windows-copilot-actions-begins-rolling-out-to-windows-insiders/)
- Apple Siri + App Intents: in the 27 releases Siri can access apps' entities; View Annotations link on-screen views to entities so Siri knows what is on screen — [Apple WWDC26 (P)](https://developer.apple.com/videos/play/wwdc2026/240/); [Medium developer guide](https://medium.com/macoclock/app-intents-is-the-part-of-ios-27-that-explains-why-siri-might-work-this-time-3e69ffa52fb5). EU later due to DMA (single secondary source) — [aimadetools](https://www.aimadetools.com/blog/siri-ai-developers-app-intents-2026/)
- ChatGPT agent controlling desktop software (third-party claim) — [Suprmind](https://suprmind.ai/hub/chatgpt/features/)

**7. Camera/screen understanding**
- Copilot Vision on Windows: user shares a window/screen during a session; nothing stored; personal Microsoft account; availability conflicts (US-first vs "all markets") — [Copilot Labs (P)](https://copilotlabs.microsoft.com/experiment/copilot-vision); [Engadget](https://engadget.com/ai/microsofts-copilot-vision-ai-helper-is-now-available-on-windows-in-the-us-160034369.html)
- Windows Recall: Copilot+ PCs only; opt-in; encrypted local screen snapshots — [Copilot Labs FAQ (P)](https://copilotlabs.microsoft.com/experiment/copilot-vision)
- Google Search Live (voice + camera) in India: English and Hindi first, then Marathi, Bengali, Gujarati, Kannada, Malayalam, Odia, Tamil, Telugu, Urdu (Mar 2026) — [Google India blog (P)](https://blog.google/intl/en-in/products/explore-communicate/search-live-comes-to-more-indian-languages/)
- Siri on-screen awareness: iOS 27 developer builds (June 2026) — [Medium](https://medium.com/macoclock/app-intents-is-the-part-of-ios-27-that-explains-why-siri-might-work-this-time-3e69ffa52fb5)

**8. Voice conversation (real-time, languages)**
- Gemini Live: Hindi from 2024-10-03 plus Marathi, Bengali, Gujarati, Kannada, Malayalam, Telugu, Tamil, Urdu [possibly outdated, 2024] — [Digit](https://www.digit.in/news/general/gemini-live-is-now-available-in-9-indian-languages-including-hindi-everything-announced-at-google-for-india.html); 40+ languages overall — [Neowin](https://www.neowin.net/news/google-expands-gemini-live-support-to-more-than-40-languages/)
- Alexa+ India: English, Hindi, Hinglish with mid-sentence switching; understands "dhai baje", "ek paav", kinship terms; more Indian languages in 2027; no wake word needed for follow-ups — [Amazon (P)](https://www.aboutamazon.com/news/devices/alexa-plus-international-launch)
- Copilot voice with Mico animated avatar (Oct 2025) — [WindowsForum](https://windowsforum.com/threads/copilot-fall-release-a-human-centered-ai-with-memory-groups-and-edge-actions.389734/)
- Sarvam Indus: voice-first Indian-language assistant, on Play Store Feb 2026 (waitlist at first), India-hosted, 105B model, free — [BusinessToday](https://www.businesstoday.in/technology/news/story/indus-by-sarvam-a-first-look-at-indias-homegrown-ai-chat-app-built-for-local-languages-517385-2026-02-21); [Google Play (P)](https://play.google.com/store/apps/details?id=ai.sarvam.indus&hl=en_IN); [Swadeshi Apps](https://swadeshiapps.com/productivity/sarvam-indus)
- Meta AI voice on WhatsApp: uneven rollout — [iTechGuides](https://www.itechguides.com/meta-ai-on-whatsapp-what-it-can-and-cant-do-in-2026/)

**9. Document/photo understanding**
- Sarvam Indus: web search and PDF analysis; no image/video generation — [Swadeshi Apps](https://swadeshiapps.com/productivity/sarvam-indus)
- Meta AI on WhatsApp: understands, edits, generates images on supported accounts — [Chatarmin](https://chatarmin.com/en/blog/meta-ai-whats-app)

**10. Health/finance**
- Copilot for Health (Fall Release, Oct 2025) — [WindowsForum](https://windowsforum.com/threads/copilot-fall-release-a-human-centered-ai-with-memory-groups-and-edge-actions.389734/)
- Claude memory excludes health topics by default — [The Next Web](https://thenextweb.com/news/anthropic-claude-cowork-shared-memory-default)

**11. Smart home**
- Alexa+: multiple devices in one request, inferred intent ("I'm cold" adjusts temperature), India partners Atomberg, Qubo, Dreame, Wipro — [Amazon (P)](https://www.aboutamazon.com/news/devices/alexa-plus-international-launch)

**12. Deep research**
- Copilot Deep Research mode with proactive next steps — [WindowsForum](https://windowsforum.com/threads/copilot-fall-release-mico-avatar-groups-collaboration-memory-and-edge-journeys.386524/)

**13. File/app integrations**
- Claude Cowork connectors (Drive, Gmail) — [Wikipedia: Claude](https://en.wikipedia.org/wiki/Claude_(language_model))
- Alexa+ India services: Amazon Music, Apple Music, JioSaavn, Prime Video, Netflix, Sanjeev Kapoor Recipes; Amazon Now coming — [Amazon (P)](https://www.aboutamazon.com/news/devices/alexa-plus-international-launch)
- Apple App Intents / App Schemas expose app content to Siri — [Apple WWDC26 (P)](https://developer.apple.com/videos/play/wwdc2026/240/)

**14. Cross-device continuity**
- Claude: one window for chat, Cowork, Artifacts (2026-09-16, Pro/Max); Chrome tasks resumable on desktop/web/mobile — [TechCrunch](https://techcrunch.com/2026/09/16/anthropic-merges-claude-chat-and-cowork-in-one-interface/); [The New Stack](https://thenewstack.io/claude-chrome-cowork-sessions/)
- Alexa+: Echo, Fire TV, app, browser; conversation context carries over — [Amazon (P)](https://www.aboutamazon.com/news/devices/alexa-plus-international-launch)
- Meta AI memory across WhatsApp/Messenger/Instagram — [iTechGuides](https://www.itechguides.com/meta-ai-on-whatsapp-what-it-can-and-cant-do-in-2026/)
- Edge Journeys: resumable browsing storylines — [WindowsForum](https://windowsforum.com/threads/copilot-fall-release-mico-avatar-groups-collaboration-memory-and-edge-journeys.386524/)

**India availability and pricing**
- Alexa+ India Early Access from Sept 16 (2026); free in Early Access, then free with Prime or INR 2,000/month standalone (no auto-renew); request at amazon.in/alexaplus — [Amazon (P)](https://www.aboutamazon.com/news/devices/alexa-plus-international-launch)
- Jio users: 18 months free Google AI Pro (Gemini Pro, 2 TB, NotebookLM), started with ages 18–25 on some plans — [Gulf News](https://gulfnews.com/technology/companies/google-and-jio-launch-free-18-month-ai-pro-access-for-millions-in-india-1.500328266); [AOL/Reuters](https://www.aol.com/articles/google-offer-free-gemini-ai-142632043.html)
- ChatGPT Go free for 12 months for India sign-ups from 2025-11-04 (normally INR 399/month, UPI accepted); current status unclear — [Business Standard](https://www.business-standard.com/technology/tech-news/chatgpt-go-free-one-year-plan-india-openai-details-step-by-step-125110400200_1.html); [TechRadar](https://www.techradar.com/ai-platforms-assistants/chatgpt/chatgpt-go-is-now-free-in-india-and-u-s-users-are-wondering-if-theyre-next)
- Gemini auto browse live in India (AI Pro/Ultra, English devices only) — [Google India blog (P)](https://blog.google/intl/en-in/products/bringing-gemini-in-chrome-with-auto-browse-to-india/)
- Krutrim's agentic assistant Kruti reported discontinued and delisted (checked 2026-09-02); conflicting guide still lists Krutrim (the discontinuation claim came from a swadeshiapps.com page seen only as a search summary; exact URL not captured) — [Wikipedia: Kruti](https://en.wikipedia.org/wiki/Kruti); [IndianAIapps](https://www.indianaiapps.com/blog/best-free-ai-apps-india-2026)
- JioBrain is an enterprise ML platform, not a consumer assistant — [Parikshit Khanna directory](https://www.parikshitkhanna.com/post/top-50-ai-tools-created-in-india-for-india-2026-features-pricing-owners-users-and-valuation)

### Inferences
- Pattern across vendors: proactive "feeds" are giving way to explicit, user-configured scheduled tasks (ChatGPT retired Pulse; Gemini scheduled actions; Meta recurring jobs). Jarvis's user-defined schedules plus a morning brief match the current direction.
- No commercial assistant combines all of: Marathi voice, local-Mac control, private memory and WhatsApp. That combination is a real niche for Jarvis.
- Agentic features reach India late and English-first. Voice in Indian languages is mature.

### Gaps
- No primary OpenAI confirmation of Pulse retirement date or Scheduled Tasks limits.
- No source found on: Gemini on Android device control (phone actions via apps) in 2026, Gemini in Gmail/Calendar/Keep specifics, Project Astra/Mariner status, ChatGPT Apps SDK/connectors list, ChatGPT voice changes, Claude Skills, OpenAI notifications on phone.
- Whether Siri personal context actually shipped to the public (iOS 26.5 or iOS 27 release, Sept 2026) is not confirmed; no India status for Apple Intelligence Siri found.
- No confirmed Gemini Live camera/screen-share support in Marathi or Hindi.
- No 2026 status for Copilot Actions or Recall GA.
- No consumer Jio assistant found.

## Q2. Which capabilities require approval/confirmation, and how are risky actions handled?

### Takeaway
All vendors rely on a confirm-before-consequential-action pattern (purchases, posting, sending, accessing local files), plus supervision modes and sandboxing. Independent tests show prompt-level confirmation rules can be bypassed; only hard code-level blocks held.

### Cited Findings
- ChatGPT agent: asks permission before actions with real-world consequences (e.g. purchase); refuses disallowed tasks; "watch mode" on sensitive sites requires the tab to stay active and pauses if the user moves away; OpenAI says this does not remove all risk — [OpenAI Help (P)](https://help.openai.com/en/articles/11752874-chatgpt-agent); [Simon Willison quoting OpenAI CISO](https://simonwillison.net/2025/Oct/22/openai-ciso-on-atlas/)
- Zenity test of Atlas: a "confirm before sending" rule was defeated by injected text that pre-answered the confirmation; the only barrier that held was code-level (Atlas would not press Amazon's final buy button), and it was bypassed by asking Amazon's Rufus to order — reported via [AgentGuard review](https://www.agentguard.one/review/chatgpt-atlas-agent-mode/) / search summary; UW found cross-origin data theft in Atlas agent mode — [WindowsForum](https://windowsforum.com/news/chatgpt-atlas-agent-mode-enabled-cross-origin-data-theft-uw-finds.445938/latest)
- Gemini auto browse: asks for confirmation before buying or posting to social accounts; user reviews cart; Google says users are responsible for what Gemini does, including unintended purchases; not in Incognito; daily task caps — [Google India blog (P)](https://blog.google/intl/en-in/products/bringing-gemini-in-chrome-with-auto-browse-to-india/); [Gizbot](https://www.gizbot.com/artificial-intelligence/gemini-auto-browse-for-chrome-is-finally-live-in-india-here-is-what-it-actually-does-for-you-128999.html); [NewsBytes](https://www.newsbytesapp.com/news/science/google-launches-gemini-auto-browse-for-chrome-android-in-india/tldr)
- Copilot: Edge actions are opt-in and need explicit confirmation; Windows Copilot Actions run in a separate, auditable Agent Workspace and request confirmation before accessing local files or making changes — [Windows Insider blog (P)](https://blogs.windows.com/windows-insider/2025/11/17/copilot-on-windows-copilot-actions-begins-rolling-out-to-windows-insiders/); [AlternativeTo](https://alternativeto.net/news/2025/10/microsoft-expands-copilot-on-windows-with-ai-agent-capabilities-vision-and-voice-wake-up)
- Copilot Vision is session-only; nothing stored. Recall is opt-in, encrypted, local — [Copilot Labs (P)](https://copilotlabs.microsoft.com/experiment/copilot-vision)
- Claude memory: sensitive topics (health, politics) excluded unless opted in — [The Next Web](https://thenextweb.com/news/anthropic-claude-cowork-shared-memory-default)
- Alexa+: Privacy dashboard to review recordings and set retention; camera controls and listening indicator — [Amazon (P)](https://www.aboutamazon.com/news/devices/alexa-plus-international-launch)
- Third-party guides recommend user-side spend caps and "always ask before login or pay" standing rules for Atlas — [WrittenlyHub](https://www.writtenlyhub.com/blog/agent-mode-in-chatgpt-atlas)

### Inferences
- For Jarvis: approvals must be enforced in code (a policy gate around the tool), not only in the prompt. The Atlas test is direct evidence.
- Sandboxing the agent (Copilot's separate Agent Workspace) and "watch mode" are useful patterns to copy for Mac control.

### Gaps
- Primary Zenity report not fetched; details come from secondary summaries.
- Anthropic's own confirmation rules for Claude for Chrome (e.g. blocked site categories) not found in this pass.
- Alexa+ India payment/checkout confirmation flow not described by Amazon.

## Q3. What is not offered or restricted, and why?

### Takeaway
Payments are gated (confirm or code-blocked), WhatsApp is closed to third-party general AI assistants since 2026-01-15 (except paid access in the EU), and many agentic features are geo- or language-limited (US-first, English-only, EU delayed).

### Cited Findings
- WhatsApp: from 2026-01-15 Meta's Business Solution terms ban general-purpose AI chatbots where the AI is the product; ChatGPT, Copilot, Perplexity, Luzia left; Meta AI is the only general assistant on WhatsApp. Meta's stated reason: infrastructure load and API meant for business support — [The Decoder](https://the-decoder.com/meta-removes-rival-chatbots-from-whatsapp/); [respond.io](https://respond.io/blog/whatsapp-general-purpose-chatbots-ban); [Gulf News](https://gulfnews.com/technology/no-more-chatgpt-and-perplexity-on-whatsapp-meta-bans-major-ai-chatbots-from-2026-1.500316016)
- EU partial reversal: after European Commission pressure, WhatsApp allows general-purpose chatbots on the Business API in Europe for 12 months, for a fee — [Thurrott](https://www.thurrott.com/?p=333392). Not stated to apply to India.
- Meta Business Agent (June 2026) is for businesses to serve customers, not a personal agent — [TechCrunch](https://techcrunch.com/2026/06/03/metas-ai-agent-for-whatsapp-business-is-now-available-globally/); [WhatsApp Business blog (P)](https://whatsappbusiness.com/blog/introducing-meta-business-agent-ai/)
- Payments: Atlas hard-blocks final buy buttons on Amazon; agents ask before purchases — [OpenAI Help (P)](https://help.openai.com/en/articles/11752874-chatgpt-agent); [AgentGuard](https://www.agentguard.one/review/chatgpt-atlas-agent-mode/)
- Geo/language limits: Gemini auto browse English-device-only in India; Gemini scheduled actions launched US/CA/UK only; Copilot Fall features US-first; Siri AI later in EU (DMA); Alexa+ browser and food/restaurant features "coming soon" in India; Recall only on Copilot+ PCs — [Google India blog (P)](https://blog.google/intl/en-in/products/bringing-gemini-in-chrome-with-auto-browse-to-india/); [How-To Geek](https://www.howtogeek.com/gemini-scheduled-actions-are-finally-live/); [WindowsForum](https://windowsforum.com/threads/microsoft-copilot-fall-release-mico-avatar-memory-and-gpt-5-routing.386433/); [aimadetools](https://www.aimadetools.com/blog/siri-ai-developers-app-intents-2026/); [Amazon (P)](https://www.aboutamazon.com/news/devices/alexa-plus-international-launch); [Copilot Labs (P)](https://copilotlabs.microsoft.com/experiment/copilot-vision)
- Plan gating: Gemini auto browse (AI Pro/Ultra), Claude for Chrome Cowork client (Max/Team first), Pulse (Pro only) — sources above.

### Inferences
- A personal WhatsApp assistant for Jarvis cannot use the official Business API as a general-purpose bot (outside the EU); options would be the Meta Business API in a narrow, task-oriented role, or local Mac automation of WhatsApp Desktop (account-risk; needs checking against WhatsApp ToS).
- Payments should stay "draft to the cart, user pays" — every vendor converges on that.

### Gaps
- Exact WhatsApp policy text and whether personal/self-use bots on the Business API are allowed in India not checked against Meta's primary terms.
- Date of the EU reversal not found.
- No vendor found that offers autonomous payments; no source on UPI-based agent payments in India.
