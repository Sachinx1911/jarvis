# India-specific capabilities for a personal AI assistant (Maharashtra, Marathi + English), October 2026

Scope: what a self-built Python assistant on one user's own laptop can legally and technically do with India-specific services. Research date: 2026-10-10. About 15 searches; most findings come from press and secondary sources. Items that only secondary sources confirm are marked **[unconfirmed - not official]**.

## Messaging: the WhatsApp Business API ban, personal-account automation, and Telegram/RCS/SMS alternatives

### Takeaway
Since 15 Jan 2026, Meta's WhatsApp Business Solution terms bar general-purpose AI assistants. ChatGPT left WhatsApp because of this. Automating a personal WhatsApp account with unofficial libraries breaks WhatsApp's terms and risks a ban. Telegram's official Bot API is the low-risk, sanctioned channel for a personal assistant.

### Cited Findings
- Meta announced the policy in October 2025. It applied to new users from 15 Oct 2025 and to all existing users from 15 Jan 2026. — [respond.io](https://respond.io/blog/whatsapp-general-purpose-chatbots-ban); [Business Standard](https://www.business-standard.com/technology/tech-news/meta-bans-ai-chatbots-from-whatsapp-business-api-chatgpt-to-shut-down-jan-2026-125102200335_1.html)
- Scope: providers of AI/ML technology, including LLMs and generative AI assistants, may not use the WhatsApp Business Solution when the AI is the primary or standalone functionality. AI that is incidental to a business service (customer support, bookings) remains allowed. — [respond.io policy 2026](https://respond.io/blog/whatsapp-chatbot-policy-2026); [dataslayer](https://www.dataslayer.ai/blog/meta-bans-general-purpose-ai-chatbots-on-whatsapp-business)
- Affected services reported: ChatGPT, Perplexity, Luzia, Poke. OpenAI confirmed that ChatGPT would stop working on WhatsApp. Meta AI is the only general-purpose assistant left on the platform. — [Gulf News](https://gulfnews.com/technology/no-more-chatgpt-and-perplexity-on-whatsapp-meta-bans-major-ai-chatbots-from-2026-1.500316016); [APH Networks](https://www.aphnetworks.com/news/30920-meta-says-no-more-general-purpose-chatbots-whatsapp-except-its-own)
- **[Not read first-hand]** The exact clause in whatsapp.com/legal (Business Solution Terms) was not fetched. The wording above comes from vendor and press paraphrase.
- Unofficial personal-account libraries (whatsapp-web.js, Baileys-based gateways) break WhatsApp's terms. whatsapp-web.js itself warns that blocking is possible. One gateway README says never to connect a primary personal number. WhatsApp's ban signals reportedly weigh who you message (strangers) and block/report rates more than raw volume. — [whatsapp ban guide](https://whatsapp.checkleaked.cc/uk/blog/avoid-whatsapp-ban); [OpenWA README](https://gitblind.noratr.app/rmyndharis/OpenWA); [bot.space](https://www.bot.space/blog/whatsapp-api-vs-unofficial-tools-a-complete-risk-reward-analysis-for-2025) (vendor sources)
- The only sanctioned WhatsApp automation is the WhatsApp Business Platform (Cloud API), directly or through a Meta BSP. — [YCloud](https://www.ycloud.com/blog/official-vs-unofficial-whatsapp-business-api) (vendor)
- Telegram bots are an official, supported API. Indian civic precedent: CoWIN slot-alert bots in 2021 called public CoWIN APIs. Security caveat: bots can collect chat history, and one bot reportedly held Aadhaar/PAN documents. — [Swarajya](https://swarajyamag.com/amp/story/insta/trouble-finding-cowin-slots-these-telegram-bots-can-help-you); [Vajiram explainer](https://vajiramandravi.com/current-affairs/how-do-telegram-bots-function/)
- The Maharashtra government partnered with Meta on a WhatsApp citizen-services chatbot ("Aaple Sarkar") in Marathi, English and Hindi. This is a citizen channel the user can use manually, not a developer API. — [IBTimes](https://www.ibtimes.co.in/maharashtra-govt-partners-meta-whatsapp-based-citizen-services-880162)

### Inferences
- For a single-user Jarvis, the Business API ban matters less than it seems: Jarvis talks to its own owner, not to a business's customers. Using the Business API to give Sachin a general assistant would still be the banned use case, though. The personal-account route is a ToS breach with real ban risk on his main number. Recommendation: Telegram bot (official) or the local desktop UI as the chat channel. WhatsApp should be read-only at most, for example by parsing exported chats the user provides manually.
- SMS sending in India needs TRAI DLT registration (sender ID and template), which is meant for businesses. Receiving or parsing SMS on the user's own phone is the useful direction.

### Gaps
- RCS Business Messaging in India (Google/Jio): eligibility for individuals was not researched.
- TRAI DLT rules for individuals sending automated SMS were not verified from trai.gov.in.
- No post-January 2026 reporting found on enforcement or later amendments of the WhatsApp policy.

## Payments: UPI, NPCI agentic payments, UPI Lite/AutoPay, and what an assistant may safely do

### Takeaway
Agentic UPI exists only as tightly controlled pilots run by licensed players (NPCI + Razorpay + OpenAI in ChatGPT, October 2025; Pine Labs P3P, June 2026). A reported NPCI "Unified Agent Protocol" built on UPI Circle and Reserve Pay is not officially confirmed. No route exists for a self-built personal app to initiate UPI payments, and Jarvis must not try. Reminders, bill tracking and parsing of SMS/email receipts are safe.

### Cited Findings
- October 2025: NPCI, Razorpay and OpenAI piloted UPI payments inside ChatGPT. Axis Bank and Airtel Payments Bank were banking partners; BigBasket was an early merchant. The agent browses and proposes, then places the order after user consent. — [TechCrunch](https://techcrunch.com/2025/10/09/india-pilots-ai-chatbot-led-e-commerce-with-chatgpt-gemini-claude-in-the-mix); [Inc42](https://inc42.com/buzz/npci-piloting-agentic-ai-based-payments-with-upi)
- The pilot uses UPI **Reserve Pay**, where funds are blocked for specific merchants. Gemini and Claude integrations were described as "in development". At Global Fintech Fest 2025, NPCI showed a Gemini demo that ordered from BigBasket and paid with an HDFC credit card through Google Pay. — [TechCrunch](https://techcrunch.com/2025/10/09/india-pilots-ai-chatbot-led-e-commerce-with-chatgpt-gemini-claude-in-the-mix); [Entrepreneur India](https://india.entrepreneur.com/news-and-trends/breaking-down-agentic-payments-upis-ai-moment-and-more/498203)
- **[Unconfirmed - not official]** Reuters, in early September 2026, citing three unnamed sources, reported an NPCI "Unified Agent Protocol" (UAP). AI agents would pay without per-transaction approval, using UPI Circle (delegation) plus Reserve Pay (about ₹10,000 cap for up to 90 days) and a registry of trusted agents. Banks reportedly cap full UPI Circle delegation at ₹15,000/month. Liability rules are not public, and RBI approval is reportedly required. NPCI has not formally confirmed the protocol. — [Inc42](https://inc42.com/buzz/npci-to-launch-agentic-payments-on-upi-report/); [Yahoo Finance](https://finance.yahoo.com/technology/ai/articles/india-eyes-ai-driven-upi-084800065.html); [CIO.inc](https://www.cio.inc/india-readies-upi-to-support-payments-initiated-by-ai-agents-a-32777)
- Pine Labs launched "P3P", described as an agentic payment protocol on UPI, live since June 2026 (reported). — [The Paypers](https://thepaypers.com/payments/news/india-prepares-agentic-payments-rollout-on-upi-network)
- UPI AutoPay: in December 2023 RBI raised the no-AFA (no-PIN) limit from ₹15,000 to ₹1,00,000 per transaction, for mutual fund subscriptions, insurance premiums and credit card bills only. The general limit stays at ₹15,000. — [PersonalFN](https://www.personalfn.com/dwl/Mutual-Funds/no-more-otp-hassle-rbi-greenlights-hike-in-transaction-limit-for-upi-auto-payments); [IBS Intelligence](https://ibsintelligence.com/ibsi-news/rbi-boosts-upi-popularity-by-raising-automatic-payment-limit)
- UPI Lite: ₹1,000 per transaction and a ₹5,000 wallet balance (RBI, December 2024). An NPCI circular of 27 Feb 2025 says top-up is online and needs AFA. — [Outlook Money](https://www.outlookmoney.com/amp/story/banking/rbi-enhances-upi-lite-transaction-limits-rs-1000-per-transaction-and-rs-5000-per-day); [ClearTax](https://cleartax.in/s/what-is-upi-lite)

### Inferences
- Every agentic UPI path runs through a PSP/bank/NPCI-registered entity. An individual's Python app cannot register as a UPI agent. Jarvis's safe scope: parse bank and UPI SMS or email alerts that the user exports or forwards; track subscriptions and AutoPay mandates; send due-date reminders for bills, EMIs, SIPs and insurance; hand off a deep link or QR to the user's own UPI app. Never store UPI PINs, never automate UPI apps through screen control, never approve mandates.
- This matches CLAUDE.md's rule that Jarvis never executes financial transfers.

### Gaps
- No official NPCI circular on agentic payments or UAP was found at npci.org.in. Also unverified: what NPCI actually announced at GFF 2026 (9–11 Sept 2026).
- No source found on NPCI rules about third-party apps reading UPI transaction data. The Account Aggregator framework (RBI NBFC-AA) was not researched; it is regulated-entity only.

## Government and citizen services: DigiLocker, IRCTC, UMANG, Aadhaar, income tax, passport, Parivahan, Aaple Sarkar

### Takeaway
Nearly every official government API (DigiLocker, UMANG/API Setu) onboards organisations only, with PAN, GST and an official email domain. A personal app cannot get access. IRCTC automation is effectively prohibited. Jarvis should handle reminders and deep links, and read documents the user downloads manually. It must never store Aadhaar numbers.

### Cited Findings
- DigiLocker "Requester" API: an organisation asks a user for consent, then reads that user's documents. Listed requester types are government departments, educational institutions, financial service providers, employers and embassies. Registration must use the organisation's official email domain and is verified by NeGD. — [API Setu](https://api.apisetu.gov.in); [DigiLocker Requester Terms (June 2025)](https://cf-media.api-setu.in/resources/DigiLocker-Terms-of-User-Requester-june-2025.pdf); [Requester workflow](https://cdn.apisetu.gov.in/portal/assets/workflow_requester.pdf)
- API Setu (MeitY) connects UMANG, DigiLocker, PAN, CBSE results and more. It has 2,000+ partners and 6,400+ APIs. Sign-up at partners.apisetu.gov.in needs proof of identity, an authority letter, organisation PAN, GST certificate and certificate of incorporation. — [API Setu docs](https://docs.apisetu.gov.in/document-central/explore-apisetu/Introduction.html); [API Setu SOP](https://cdn.apisetu.gov.in/portal/assets/sop-apisetu-v0.pdf); [NeGD onboarding guidelines](https://negd.gov.in/wp-content/uploads/2025/05/Guidelines-for-Onboarding-for-API-as-a-service-provider-v15-Rev.pdf)
- IRCTC: its own current public ToS text on automation was **not found**. IRCTC penalised agents for "illegal software" that automated bookings (2011). A partner contract requires all third-party use to be by a human user. Community automation scripts say they are "educational only". — [Medianama 2011](https://www.medianama.com/2011/06/223-itz-cash-asks-franchisees-to-abide-by-irctc-rules-or-face-action/); [irctc-api npm](https://npmjs.com/package/irctc-api)
- Aadhaar: the Aadhaar (Sharing of Information) Regulations 2016 say no entity may keep Aadhaar numbers, or documents and databases containing them, longer than the purpose consented to. Breaching this counts as a violation of Section 29(2). Section 29(4) bars public display. UIDAI recommends masked Aadhaar, which shows only the last 4 digits. — [UIDAI Sharing Regulations 2016](https://www.uidai.gov.in/images/The_Aadhaar_Sharing_of_information_regulation_2016.pdf); [UIDAI masked Aadhaar FAQ](https://www.uidai.gov.in/283-faqs/aadhaar-online-services/e-aadhaar/1887-what-is-masked-aadhaar.html); [The Week](https://www.theweek.in/news/biz-tech/2022/05/29/dont-share-aadhaar-photocopy-use-masked-version-uidai.amp.html)
- Aaple Sarkar (Maharashtra): a service portal run by Mahaonline. No public developer API was found. Its chatbot vendor (Haptik) received internal government APIs. A WhatsApp citizen chatbot exists in Marathi, English and Hindi. — [IBTimes](https://www.ibtimes.co.in/maharashtra-govt-partners-meta-whatsapp-based-citizen-services-880162); [CAG audit summary](https://cag.gov.in/uploads/download_audit_report/2023/5-Executive-summary-064215057e11292.44286813.pdf)
- Parivahan/VAHAN: no official public developer API was confirmed. Vehicle RC lookup is sold by licensed third-party KYC vendors (e.g. Surepass) for business use. — [Surepass](https://surepass.io/rc-verification-api-for-andaman-and-nicobar-island/); [GitHub discussion](https://github.com/orgs/community/discussions/196411) (unverified)

### Inferences
- Feasible for Jarvis: a "document wallet" of files the user downloads himself from DigiLocker or other portals, stored locally and encrypted, with Aadhaar numbers masked or redacted on ingest. Expiry and renewal reminders for passport, driving licence, PUC, vehicle insurance and RC. Income-tax deadline reminders (the 31 July ITR due date; advance tax on 15 Jun/Sep/Dec/Mar), which are fixed statutory dates, though the Act sections were not verified here. Deep links into UMANG, IRCTC, Passport Seva and Aaple Sarkar for the user to act himself.
- Not feasible or not allowed: automated IRCTC booking or Tatkal scripts, scraping DigiLocker or UMANG behind login, VAHAN lookups of other people's vehicles (also a privacy problem).

### Gaps
- IRCTC's current Terms of Use and any official IRCTC developer API were not fetched.
- Passport Seva, the Income Tax e-filing portal and UMANG ToS on automation were not checked.
- Not confirmed whether DigiLocker offers any individual or sandbox developer access. The suggested contact is partners@digitalindia.gov.in (from secondary summary).

## Daily-life India data sources with APIs: trains, weather, cricket, Marathi news, NAV, bills, fuel, festivals

### Takeaway
The best official, free sources are the AMFI daily NAV file (public text file), IMD's API gateway (free for non-commercial use, key-based) and NDMA Sachet CAP alerts (RSS). Indian Railways has no documented public PNR or running-status API. Cricket score rights are commercially contested, but personal, non-redistributed use of a licensed API is low risk.

### Cited Findings
- AMFI publishes all scheme NAVs at https://www.amfiindia.com/spages/NAVAll.txt as a semicolon-delimited file (scheme code; ISINs; name; NAV; date). SEBI and AMFI require NAV upload by 8 pm daily. No ToS found, so keep request volume low. — [SEBI circular](https://www.sebi.gov.in/legal/circulars/feb-2001/disclosure-of-navs-on-amfi-website_18073.html); [india-mutual-fund-info README](https://unpkg.com/india-mutual-fund-info@1.0.1/README.md); [KDE forum](https://forum.kde.org/viewtopic.php%3Ff=69&t=167885.html)
- IMD: api.imd.gov.in is the "unified gateway" with JWT, user onboarding and key-based access. An RTI reply (September 2025) says IMD provides APIs "without any charges for non-commercial use only". Endpoints in the API doc include a city 7-day forecast, current weather and district nowcast. Raw AWS/ARG station data was locked from the public in May 2025. — [IMD API portal](https://api.imd.gov.in/); [IMD API doc](https://mausam.imd.gov.in/Forecast/marquee_data/API_doc.pdf); [IMD RTI reply](https://internal.imd.gov.in/section/rti/rticases/20260112_rti_211.pdf); [Down To Earth](https://www.downtoearth.org.in/amp/story/climate-change/imd-locking-up-its-awsarg-data-portal-hampers-public-weather-alerts-experts)
- NDMA Sachet (built by C-DOT) uses the Common Alerting Protocol and runs in all 36 states/UTs. It offers RSS feeds of CAP 1.2 XML at country and state level (e.g. Maharashtra), plus browser push and an app. — [thejeshgn.com](https://thejeshgn.com/2025/05/28/common-alerting-protocol-cap-in-the-indian-context/); [Vikaspedia](https://en.vikaspedia.in/social-welfare/disaster-management-1/national-disaster-alert-portal)
- Railways: no official documented public PNR API was found. Official channels are the web, SMS to 139 and phone, plus NTES for running status. Third-party APIs are unstable; eRail.in's API is "suspended until further notice", and RailwayAPI.com's status is unknown. — [GeeksforGeeks](https://geeksforgeeks.org/python-find-live-running-status-pnr-of-any-train-using-railway-api); [code2care on eRail](https://code2care.org/2015/irctc-indian-railways-official-erail-api-11-for-developers-train-info); [ctpnr PyPI](https://pypi.org/project/ctpnr/)
- Cricket: BCCI sells exclusive dissemination rights. Star India sued live-score apps; one Delhi HC judgment (2013) held that scores are facts and not property, and a Supreme Court interim order required deposits. Final outcome not confirmed. CricketData.org (formerly CricAPI) has a free plan with 100 hits/day. — [Delhi HC judgment](https://delhihighcourt.nic.in/app/case_number_pdf/2013:DHC:4289-DB/SRB30082013FAOOS1532013.pdf); [Medianama](https://www.medianama.com/2013/03/223-star-sends-notices-to-app-developers-after-delhi-hc-judgment-grants-cricket-score-rights/); [freeapihub](https://freeapihub.com/apis/cricketdata-api)

### Inferences
- Good for Jarvis now: the NAV tracker (AMFI file, once a day after 9 pm IST), weather (IMD key, or keep Open-Meteo as a fallback), disaster alerts (Sachet Maharashtra RSS), cricket (CricketData free tier, personal use, no redistribution).
- PNR and running status: let the user paste a PNR and open the official NTES or IRCTC page, or parse the IRCTC confirmation email or SMS. Avoid scraping.
- Electricity and gas bills: MSEDCL/Mahavitaran and gas-provider APIs were not researched. The practical path is parsing bill emails or SMS that the user forwards.

### Gaps
- Not researched due to the tool-call budget: Marathi news RSS (Loksatta, Lokmat, Maharashtra Times, BBC Marathi), fuel price sources (IOCL/HPCL daily RSP pages; no official API known), panchang/festival calendars (an open-source option is the Python library for Drik-style computations, not verified), MSEDCL bill APIs.
- No exact Sachet RSS URL was confirmed. Check sachet.ndma.gov.in.
- IMD terms may have changed after the September 2025 RTI reply.

## Indian languages: Marathi in assistants, Bhashini, AI4Bharat models

### Takeaway
Open AI4Bharat models with Marathi support (IndicTrans2 translation, IndicConformer ASR, IndicF5 TTS) are listed under MIT licence and can run locally, which fits Jarvis's provider-interface design. Bhashini offers free government APIs through ULCA/Dhruva with a user ID and API key, but official sign-up, quota and terms text could not be retrieved.

### Cited Findings
- IndicF5 TTS: 11 Indian languages including Marathi, about 1,417 hours of training data, MIT licence (AIKosh listing). — [AIKosh IndicF5](https://aikosh.indiaai.gov.in/home/models/details/aibharat_indicf5.html)
- IndicConformer Marathi ASR (STT-MR hybrid CTC/RNNT large, about 120M parameters): MIT, open (AIKosh listing). — [AIKosh IndicConformer MR](https://aikosh.indiaai.gov.in/home/models/details/ai4bharat_indicconformer_stt_mr_hybrid_ctc_rnnt_large_marathi_automatic_speech_recognition_model.html); [GitHub IndicConformerASR](https://github.com/AI4Bharat/IndicConformerASR)
- IndicTrans2: NMT for all 22 scheduled languages including Marathi, MIT (AIKosh listing). — [AIKosh IndicTrans2](https://aikosh.indiaai.gov.in/home/models/details/indic_trans2.html)
- Bhashini: 300+ pre-trained models exposed to "ecosystem partners" through Open Bhashini APIs. A UPSC explainer says any individual developer can call it for STT, TTS and translation. — [Wikipedia: Bhashini](https://en.wikipedia.org/wiki/Bhashini); [Anantam IAS](https://anantamias.com/bhashini-bhasha-interface-for-india/) (secondary)
- The auth flow seen in community code: user ID plus ULCA API key, then fetch a pipeline config, then call inference on dhruva-api.bhashini.gov.in. **[Unconfirmed - community code]** — [bhashini-translator PyPI](https://www.pypi.org/project/bhashini-translator); [HF space speech_api.py](https://huggingface.co/spaces/pvanand/web-server/blob/73677f4c4cbb41e0633c2fc2a2862e5215d11894/speech_api.py)
- ULCA itself is an open dataset/benchmark platform for MT, ASR, TTS and OCR. — [ULCA GitHub](https://github.com/bhashini-dibd/ulca)
- Marathi ASR benchmark datasets (Kathbath, IndicTTS, CommonVoice, FLEURS Marathi) are on AIKosh under CC BY-SA 4.0. They are useful for measuring a local versus cloud STT choice. — [AIKosh Kathbath MR](https://aikosh.indiaai.gov.in/home/datasets/details/marathi_asr_benchmark_dataset_kathbath_marathi_noisy_test_known.html)

### Inferences
- These models fit Jarvis's rule that local versus cloud is decided per component from measurements. Candidates: IndicConformer-MR (local STT) against cloud STT; IndicF5 (local Marathi TTS; F5 is heavy, so check RAM and latency on the Mac); IndicTrans2 when translation is needed. The Kathbath and FLEURS Marathi test sets can drive the WER comparison.
- Bhashini can be a free cloud fallback provider once sign-up terms are confirmed.

### Gaps
- The bhashini.gov.in page did not render; official developer sign-up, free-tier quota and ToS were not retrieved.
- Marathi support in ChatGPT, Gemini and Claude was not benchmarked here. The Sarvam AI (Indian LLM/STT/TTS) offering was not researched.
- Licences were not confirmed from upstream LICENSE files; AIKosh metadata may lag behind.

## Privacy law: DPDP Act 2023 and DPDP Rules 2025 for a personal assistant handling family and contact data

### Takeaway
The DPDP Rules were notified on 13–14 November 2025 (G.S.R. 843(E)/846(E)) and phase in over 18 months, to about 13 May 2027. Section 3 excludes personal data processed by an individual for a "personal or domestic purpose", which covers a single user's own assistant holding family and contact data. Third-party cloud AI providers processing that data are a separate question.

### Cited Findings
- The Rules were notified as G.S.R. 846(E), dated 13 Nov 2025 (some sources say 14 Nov). Data Protection Board provisions took effect immediately. Consent Manager provisions apply after 12 months (about 13 Nov 2026). Full obligations apply after 18 months (about 13 May 2027). — [S.S. Rana](https://ssrana.in/articles/meity-notifies-final-digital-personal-data-protection-rules-2025/); [Conventus Law](https://conventuslaw.com/featured-content/building-indias-digital-privacy-framework-an-overview-of-the-dpdp-rules-2025/); [TCSA roadmap](https://www.tcsa.in/resources/dpdp-rules-2025-implementation-roadmap)
- Section 3: the Act does not apply to personal data processed by an individual for any personal or domestic purpose. An example given: a contact list kept on one's own phone. The test is purpose, not size. — [dpdpa.com Section 3](https://dpdpa.com/dpdpa2023/chapter-1/section3.html); [Tsaaro](https://tsaaro.com/blogs/regulatory-carve-outs-examining-exemptions-under-the-dpdp-act-2023-and-dpdp-rules-2025)
- Section 3 and Section 17 commence 18 months after 13 Nov 2025, under clause (c) of G.S.R. 843(E) (per secondary commentary). — [DPDP wiki](https://dpdp.myndsolution.com/wiki/act/section-3/); [IIT BHU summary](https://iitbhu.ac.in/contents/institute/cf/cis/doc/dpdp_act_rules_summary.pdf)

### Inferences
- Jarvis used by Sachin for himself and his household falls under the personal/domestic exclusion. Data fiduciary duties (notice, consent, DPO) would apply only if Jarvis were offered to others or used for a business purpose.
- Good practice anyway, matching CLAUDE.md: keep family and contact data local and gitignored. Send the minimum to cloud LLMs. Redact Aadhaar, PAN and bank numbers before any cloud call. Cloud AI providers act as processors under their own terms.
- Aadhaar handling is governed separately by the Aadhaar Act and Regulations, regardless of the DPDP exemption. Mask on ingest.

### Gaps
- The Gazette text of G.S.R. 843(E)/846(E) was not read; dates come from law-firm and secondary summaries.
- No authoritative guidance found on whether household use of a cloud LLM changes the "personal purpose" analysis.
