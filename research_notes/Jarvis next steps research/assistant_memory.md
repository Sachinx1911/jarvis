# Long-term memory for personal AI assistants (2025 to October 2026): what measurably helps, and what to change in Jarvis

Research date: 2026-10-10. Labels used below: **[peer-reviewed]** means the paper was accepted at a conference. **[preprint]** means arXiv only. **[vendor]** means a company's own blog or README. **[independent]** means a third party reran the systems. "(older)" marks a result from before 2025.

## Systems: architectures and reported results

### Takeaway
Every major system is a variation on the same pattern: an LLM extracts facts at write time (ADD/UPDATE/DELETE), retrieval is hybrid or graph-based, and the store is either injected into the prompt or exposed as a tool. Most headline scores are vendor-reported and do not survive independent reruns well. The simple baselines (a filesystem with grep, or full context) are embarrassingly close to the products. Jarvis's design (extract-then-reconcile against similar memories, plus raw session search) already matches the best-performing pattern found in an independent 2026 rerun.

### Cited Findings
- **Mem0** [preprint, Apr 2025]
  - Pipeline: an LLM extracts candidate facts, then an update step reconciles them against similar existing memories with ADD/UPDATE/DELETE/NOOP. A graph variant ("Mem0g") also exists.
  - Results claimed: 26% relative gain over OpenAI memory on LoCoMo (LLM judge), graph variant about 2% better than base, 91% lower p95 latency and over 90% token saving versus full context — [arXiv 2504.19413](https://arxiv.org/abs/2504.19413).
  - Paper Table 2 gives J=66.88 for Mem0 and 65.99 for Zep — [dev.to critique citing the paper](https://dev.to/gde03/the-ai-memory-benchmark-everyone-quotes-forbids-saying-i-dont-know-o1n).
  - Mem0 now claims [vendor] 94.4% on LongMemEval, 92.5% on LoCoMo and 64.1% on BEAM-1M — [Mem0 blog](https://mem0.ai/blog/ai-memory-benchmarks).
  - Redis's table lists Mem0's reported LongMemEval score as 49.0% — [Redis report](https://redis.io/resources/agent-memory-benchmark-report/).
- **Zep / Graphiti** [preprint, Jan 2025]
  - A temporal knowledge graph whose edges carry validity intervals.
  - Results claimed: DMR 94.8% versus 93.4% for MemGPT, up to 18.5% accuracy gain on LongMemEval, 90% lower latency than baselines — [arXiv 2501.13956](https://arxiv.org/abs/2501.13956).
  - Its reported LongMemEval score with gpt-4o is 71.2% (not reproduced by Redis) — [Redis report](https://redis.io/resources/agent-memory-benchmark-report/). A 2026 vendor ranking cites 90.2% [vendor] — [Mem0 2026 page](https://mem0.ai/library/agent-memory/ai-memory-benchmarks-in-2026).
- **Letta / MemGPT**
  - MemGPT pages memory in and out under the agent's own control (older, 2023).
  - In MemoryAgentBench [preprint, likely ICLR 2026], MemGPT scored an accurate-retrieval average of 34.3 and an overall score of 28.3. Mem0 scored 32.6 and 21.1. Plain long-context agents scored up to 49.6 overall (Claude-3.7-Sonnet) — [arXiv 2507.05257v3](https://arxiv.org/html/2507.05257v3).
  - Letta's filesystem experiment [vendor, Aug 2025]: a gpt-4o-mini agent with grep, search_files, open and close over raw conversation files scored 74.0% on LoCoMo, against the 68.5% Mem0 reported for its best graph variant — [Letta blog](https://www.letta.com/blog/benchmarking-ai-agent-memory); [Aktagon summary](https://signals.aktagon.com/articles/2026/02/benchmarking-ai-agent-memory-is-a-filesystem-all-you-need/).
- **A-Mem** [peer-reviewed, NeurIPS 2025]
  - Zettelkasten-style "atomic notes" with LLM-written keywords, tags and links between notes; adding a new note can update older ones.
  - LoCoMo F1 (GPT block) versus the plain LoCoMo baseline: multi-hop 45.85 vs 18.41; temporal 12.14 vs 12.04; single-hop 27.02 vs 25.02; adversarial 50.03 vs 69.23 (worse).
  - Token use: about 2.5k versus 16.9k tokens per answer — [arXiv 2502.12110](https://arxiv.org/pdf/2502.12110); [NeurIPS proceedings](https://proceedings.neurips.cc/paper_files/paper/2025/hash/19909c36f51abc4856b4560aff3d36d6-Abstract-Conference.html).
- **MemOS** [preprint, Jul 2025]
  - The "MemCube" abstraction unifies plaintext, activation and parameter memory.
  - Self-reported LoCoMo LLM-judge average of 0.7331 versus 0.5275 for the OpenAI baseline, and "+159% temporal". Its README numbers come from differing setups — [arXiv 2507.03724](https://arxiv.org/pdf/2507.03724).
- **Redis "Remis + Instruct"** [independent, Sep 2026]
  - Remis is hybrid retrieval over raw sessions, with no LLM at ingest. It chunks sessions at topic shifts, scores 0.7·cosine + 0.3·BM25, and expands to neighbouring chunks.
  - Instruct is LLM fact extraction with create, update and delete.
  - Results on LongMemEval-S with a gpt-4o reader: the two combined scored 86.5% task-averaged, Remis alone 83.4%, plain RAG k=20 61.5% and Redis AMS 64.0%.
  - The union met or beat each component on every question type. Verbatim assistant recall rose from 72% to 100%. The biggest gains were on multi-session and temporal questions, because raw chunks keep exact numbers and dates that extraction drops — [Redis report](https://redis.io/resources/agent-memory-benchmark-report/).
- **ChatGPT memory** [vendor docs]
  - Two parts. "Saved memories" are always injected into context and the model can update, combine or remove them. "Reference chat history" is a separate, lossy, summarised recall of past chats.
  - Temporary chats neither read nor write memory — [OpenAI help](https://help.openai.com/en/articles/11146739-how-does-reference-saved-memories-work); [OpenAI FAQ](https://help.openai.com/en/articles/8590148-memory-faq).
  - LongMemEval (2024 data, older) measured ChatGPT (GPT-4o) at 0.577 against 0.918 for offline GPT-4o reading the same evidence — [arXiv 2410.10813v2](https://arxiv.org/html/2410.10813v2).
- **Claude memory** [vendor docs]
  - Memory is saved as individual topics during chat, and is project-scoped.
  - "Search past chats" is RAG exposed as tool calls (memory-as-tool).
  - The older design, a daily synthesis updated every 24 h, was replaced; legacy memory export was available until 9 Sep 2026 — [Claude help](https://support.claude.com/en/articles/11817273-using-claude-s-memory).

### Inferences
- The convergent best practice is extracted facts plus retrievable raw evidence, not either one alone. Jarvis has both: memory files, and session search over past chats. The gap is whether both reach the answer step together.
- Graph memory (Zep, Mem0g) gives at most small, contested gains (Mem0g about +2%). For a single-user assistant with hundreds to a few thousand memories, a graph is not justified. Jarvis's supersede chain already covers temporal validity.

### Gaps
- No independent numbers were found for Cognee or LangMem (the Redis appendix row for LangMem looks like a table error).
- OpenAI's and Anthropic's current internal memory architecture is undocumented.

## Benchmarks: what they measure, best scores, critiques

### Takeaway
LongMemEval (500 questions; 5 abilities including knowledge updates, temporal reasoning and abstention) is the most useful benchmark for a personal assistant. LoCoMo is weak: 10 conversations, a corrupted answer key, a lenient judge, and its abstention category is often dropped. Reported scores vary by +3 to −28 points when rerun, so only compare scores that use the same reader model and judge.

### Cited Findings
- **LongMemEval** [peer-reviewed, ICLR 2025]
  - 500 questions testing information extraction, multi-session reasoning, temporal reasoning, knowledge updates and abstention.
  - Long-context LLMs lose 30–60% accuracy. GPT-4o went from 0.870 with only the relevant sessions (oracle) to 0.606 with the full history — [arXiv 2410.10813](https://arxiv.org/abs/2410.10813); [HTML](https://arxiv.org/html/2410.10813v2).
- **Best LongMemEval-S scores:**
  - Vendor-reported: OMEGA 95.4%, Mem0 94.4%, Oracle 93.8%, PwC Chronos 92.6%, ContextStream 90.0% (gpt-5.5 reader, self-consistency k=3).
  - Independently reproduced: 86.5% is the best — [Redis report](https://redis.io/resources/agent-memory-benchmark-report/); [ContextStream](https://contextstream.io/benchmarks).
- **Reproduction gaps** [independent]:
  - Google Vertex Memory Bank: 42.4% reproduced versus about 70% in the paper it is based on.
  - Oracle: 86.0% (on gpt-5.5) versus 93.8% claimed, and 78.1% on gpt-4o.
  - AgentCore: 73.6% claimed, 77.0% reproduced.
  - Redis's own report has caveats too: single run, no confidence intervals, harness not linked — [Redis report](https://redis.io/resources/agent-memory-benchmark-report/).
- **LongMemEval-V2** (May 2026) tests memory over web-agent trajectories. The top score is 72.5% against an oracle ceiling of 86–90% — [benchmarklist](https://benchmarklist.com/benchmarks/longmemeval_v2/). Not verified against the primary paper.
- **LoCoMo critiques:**
  - Mem0's harness drops category 5 (adversarial / unanswerable, 446 questions, 22.5% of the set). Its prompt tells the model "NEVER say 'not specified'".
  - The judge accepts a match to any one item of a gold list and allows ±14 days on dates.
  - An audit (dial481/locomo-audit) found the judge accepted 62.8% of deliberately wrong answers, and that the corrupted answer key caps the honest score near 93.6 — [dev.to](https://dev.to/gde03/the-ai-memory-benchmark-everyone-quotes-forbids-saying-i-dont-know-o1n). These are secondary claims; the audit repo itself was not checked.
- **Mem0 vs Zep dispute:**
  - Zep says Mem0 misconfigured Zep: both speakers were set as the user, timestamps were put in the message text, and searches ran sequentially. Zep corrected its own LoCoMo figure to 75.14% ± 0.17 — [Zep blog](https://blog.getzep.com/lies-damn-lies-statistics-is-mem0-really-sota-in-agent-memory/).
  - Mem0's CTO argued that Zep's 84% excluded the adversarial category from the denominator, and that the corrected figure is 58.44% — reported via [search summary of the dispute](https://www.memoryplugin.com/wiki/evaluating.html). Unresolved.
  - A full-context baseline reportedly scored about 73% on LoCoMo, beating Mem0's best variant — [towardsai](https://towardsai.com/?p=52675) (secondhand).
- **MemoryAgentBench** [preprint, ICLR 2026 poster]
  - Tests four competencies: accurate retrieval, test-time learning, long-range understanding, and selective forgetting (conflict resolution).
  - On multi-hop fact consolidation, every method scored at most 7%. GPT-4o scored 60.0 on the single-hop version.
  - For accurate retrieval, BM25 (60.5) beat the best embedding retriever, Qwen3-Embedding-4B (54.7).
  - On long-range understanding, long-context agents (62.2) beat RAG (≤37.3) — [arXiv 2507.05257v3](https://arxiv.org/html/2507.05257v3); [ICLR page](https://iclr.cc/virtual/2026/poster/10010781).

### Inferences
- Jarvis's own eval set should mirror the LongMemEval categories, and must include unanswerable questions (abstention) and knowledge-update or supersede cases. These are exactly the categories that the vendor numbers hide.
- The finding that BM25 beats embeddings on accurate retrieval supports Jarvis's decision to defer embeddings, at least for factual recall.

### Gaps
- No per-type scores were found for LongMemEval-V2 or BEAM from primary sources.

## Techniques that measurably help (with effect sizes)

### Takeaway
The best-quantified wins are all cheap. Adding extracted facts to the index keys gives +9.4% recall and +5.4% accuracy. Time-aware query expansion gives +6.8–11.3% recall on temporal questions. Chain-of-Note plus structured reading gives up to +10 accuracy points. Fusing raw evidence with extracted facts gives about +3 points over raw evidence alone in an independent rerun, with large gains on temporal and verbatim questions. Graphs and embeddings add less than vendors claim.

### Cited Findings
All LongMemEval figures below are [peer-reviewed] and come from [arXiv 2410.10813v2](https://arxiv.org/html/2410.10813v2).
- **Fact-augmented key expansion** (index each chunk under its own text plus the facts extracted from it):
  - Averaged across models: +9.4% recall@k and +5.4% final accuracy.
  - Round granularity, Recall@5: 0.582 → 0.644. Session granularity: 0.706 → 0.732.
- **Time-aware query expansion** (an LLM pulls a time range out of the question and narrows the search to it): recall on temporal questions rises by 11.3% (round granularity) or 6.8% (session granularity) with GPT-4o. A small model (Llama 3.1 8B) gave weak or inconsistent gains.
- **Session decomposition into rounds:** helps GPT-4o reading significantly; neutral for Llama 3.1 8B (exact values only in a figure).
- **Reading strategy:** Chain-of-Note (extract the relevant notes first, then answer) plus JSON-formatted memories adds up to 10 absolute points across three LLMs. JSON helps only together with Chain-of-Note.
- **Hybrid raw plus extracted:** Remis + Instruct scored 86.5% versus 83.4% for Remis alone and 61.5% for naive RAG k=20. Verbatim recall rose from 72% to 100% [independent] — [Redis report](https://redis.io/resources/agent-memory-benchmark-report/).
- **BM25 versus dense:** BM25 led on accurate retrieval (60.5 vs 54.7); the two were roughly even on long-range understanding [preprint] — [arXiv 2507.05257v3](https://arxiv.org/html/2507.05257v3).
- **Hybrid with RRF for code-mixed text:** in CMIR 2025 shared-task papers (Bengali-English), RRF fusion of BM25 and dense retrieval "significantly improves" over either alone. BM25 plus SBERT re-ranking was reported as +83% over BM25 — [CEUR Vol-4173](https://ceur-ws.org/Vol-4173/T3-3.pdf). Workshop papers; the exact figures were not checked in the PDFs.
- **Memory as a tool (agentic search):** a grep and file-open agent scored 74.0% on LoCoMo [vendor] — [Letta](https://www.letta.com/blog/benchmarking-ai-agent-memory). Claude's chat search is exposed as a tool — [Claude help](https://support.claude.com/en/articles/11817273-using-claude-s-memory).
- **Always-injected core plus retrieved rest** is the ChatGPT saved-memories design — [OpenAI help](https://help.openai.com/en/articles/11146739-how-does-reference-saved-memories-work).
- **Conflict and update handling is the weakest area:** multi-hop fact consolidation scored ≤7% for every method — [arXiv 2507.05257v3](https://arxiv.org/html/2507.05257v3).
- **Abstention:** LoCoMo harnesses suppress it, and one system scored 0.000 on the adversarial set — [dev.to](https://dev.to/gde03/the-ai-memory-benchmark-everyone-quotes-forbids-saying-i-dont-know-o1n).

### Inferences
- Jarvis already does a form of fact-augmented keys (summary_en plus keywords on each memory). The missing piece is the reverse direction: indexing past-session chunks with the facts extracted from them, so that session search hits on the English summary terms.
- Jarvis has no time-aware query step. Questions like "what did I say last month about X" need one, and its frontmatter already has dates to filter on.
- Neither memory-as-tool nor auto-injection clearly wins. The evidence supports a small always-injected core (MEMORY.md and hard rules, as Jarvis does now) plus retrieval on demand.

### Gaps
- No clean 2025–26 ablation of cross-encoder reranking for conversational memory was found.
- No head-to-head comparison of memory-as-tool versus auto-injection under the same reader and judge was found.
- No effect size for LLM query rewriting outside the time-range case was found.

## Multilingual / code-mixed (Marathi, Hindi, romanized) retrieval

### Takeaway
On native-script Hindi and Marathi, BGE-M3 is generally the strongest open embedding model, with multilingual-e5-large close and sometimes ahead on Hindi. On romanized or transliterated text, multilingual embedders are reported to do poorly, and no published benchmark gives BGE-M3, Qwen3-Embedding or Jina numbers on romanized Marathi. Jarvis's poor e5-small result fits this pattern. Lexical search plus script normalization is the defensible choice until a local test shows otherwise.

### Cited Findings
- **Hindi-BEIR** (2024, older): average NDCG@10 of 47.29 for BGE-M3 versus 39.93 for mE5 — [arXiv 2408.09437](https://arxiv.org/pdf/2408.09437).
- **IndicRAGSuite** [preprint, 2025] (IndicMSMarco, 13 languages): BGE-M3 is best or near-best in 8 of 13 languages. mE5-large was top for Hindi (MRR 0.52). LLM2Vec scored 0.49 on Hindi and Marathi — [arXiv 2506.01615](https://arxiv.org/pdf/2506.01615).
- **Marathi IndicQA retrieval** [model card, self-reported]: 0.697 for BGE-M3, 0.712 after fine-tuning — [HF card](https://huggingface.co/karmx/Llama-Karmx-Indic-Embedding-bge-m3).
- **Romanized text:** state-of-the-art multilingual models "still face challenges in handling Romanized script" — [arXiv 2511.22769](https://arxiv.org/abs/2511.22769). This is a BigCyber workshop paper; its abstract gives no retrieval numbers.
- **Normalization:** code-mixed retrieval systems at CMIR 2025 used dictionary replacement plus fuzzy matching to absorb transliteration variants before BM25, dense retrieval and RRF — [CEUR Vol-4173](https://ceur-ws.org/Vol-4173/T3-9.pdf).

### Inferences
- The cheapest robust trick is to store a normalized form at write time. Jarvis already writes summary_en, an English gloss of every memory. Adding a romanized Marathi line or a Devanagari transliteration to the keywords would let FTS5 word search and trigram search match whichever script the user types.
- If embeddings are retried, BGE-M3 (568M parameters, runs on a Mac) is the candidate to measure. Embed summary_en and the normalized text rather than the raw code-mixed text.

### Gaps
- No MMTEB/Indic-MTEB per-language retrieval tables for Marathi were retrieved.
- No evaluation of Qwen3-Embedding, Jina v3 or v4, or IndicSBERT on romanized Marathi or Hinglish retrieval was found.
- No published measurement of transliteration-normalization gains for Hinglish retrieval was found.

## Recommendations for Jarvis: highest-value, low-cost changes and how to evaluate them

### Takeaway
Five cheap changes, each tied to measured evidence. Each can be tested in Jarvis's existing eval runner by adding LongMemEval-style question categories and comparing retrieval recall and answer accuracy before and after.

### Cited Findings (evidence behind each recommendation)
1. **Time-aware retrieval.** A small LLM step pulls a date range out of time-referencing questions; the system then filters memories and sessions by date before RRF. Expect about +7–11% recall on temporal questions with a strong model — [LongMemEval](https://arxiv.org/html/2410.10813v2).
2. **Fact-augmented keys for session search.** Index each past-chat chunk together with the summary_en of the memories extracted from it. Expect about +9% recall and +5% accuracy — [LongMemEval](https://arxiv.org/html/2410.10813v2).
3. **Feed both raw evidence and extracted memories to the answer step.** Put both in one labelled context block. In an independent rerun this was +3 points over raw evidence alone and well above extraction-only, with the gains concentrated on temporal and verbatim questions — [Redis](https://redis.io/resources/agent-memory-benchmark-report/).
4. **Chain-of-Note reading.** Before answering, the model writes short notes from the retrieved memories; memories are shown in structured form, and the model must say "I don't know" when the evidence is absent. Up to +10 points — [LongMemEval](https://arxiv.org/html/2410.10813v2). Abstention is also what LoCoMo-style harnesses hide — [dev.to](https://dev.to/gde03/the-ai-memory-benchmark-everyone-quotes-forbids-saying-i-dont-know-o1n).
5. **Script-normalized keywords at write time.** The extractor adds a Devanagari and a romanized form of key Marathi terms to the keywords. This works with the current FTS5 trigram index and needs no new dependency; the motivation is that embedders handle romanized script poorly — [arXiv 2511.22769](https://arxiv.org/abs/2511.22769); [CMIR 2025](https://ceur-ws.org/Vol-4173/T3-9.pdf).
- **Not recommended now:** a knowledge graph (small, contested gains — [Mem0 paper](https://arxiv.org/abs/2504.19413)), or a dense-only retriever (BM25 was stronger on accurate retrieval — [MemoryAgentBench](https://arxiv.org/html/2507.05257v3)).

### Inferences
**How to evaluate with the existing eval runner:**
- **Question categories:** tag each question with a LongMemEval-style category: single-fact, preference, knowledge-update (supersede), multi-session, temporal, and abstention (an unanswerable question about a real person or topic). Use made-up fixtures in all three scripts (Devanagari, romanized and English), including cross-script queries.
- **Two metrics, measured separately:**
  - Retrieval: Recall@5 against the gold memory or session IDs. This needs no LLM and is deterministic.
  - Answers: accuracy from an LLM judge with a strict prompt. Score abstention as correct only when the model declines.
- **Ablations:** run one change at a time with the same reader model. Repeat at least 3 times, or report per-category confidence intervals, because Redis's single-run numbers show how noisy this is.
- **Separate metric for supersede cases:** report the stale-answer rate on supersede questions on its own line, since conflict and update handling is the weakest area across all systems.
- **Retesting embeddings:** run BGE-M3 against the current FTS5 setup on the same cross-script recall set before adding it as a dependency.

### Gaps
- None of the effect sizes were measured on Marathi or code-mixed data, or with a small local model as the reader. Jarvis must measure its own.
