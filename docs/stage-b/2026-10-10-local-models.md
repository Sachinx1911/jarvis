# Stage B: local models on this Mac (2026-10-10/11)

Stage B measures. It does not adopt. `config/routing.yaml` is unchanged: the `local` provider is
not in `approved_providers`, and no route lists a local model. All tasks are synthetic.
Raw results (with full model outputs) stay in `data/evals/` and `data/evals/stage-b/` (git-ignored).

## 1. Summary

- **Runtime:** llama.cpp `llama-server` (Homebrew llama.cpp 0.6.0, build 11429, commit d81235049), Metal,
  GGUF Q4_K_M, 16K context, one slot. It works with the new local adapter: chat, native tool calls,
  `json_schema` structured output, streaming, prompt caching, exact token counts.
- **Models measured:** Qwen3.5-9B and Gemma 4 E4B (both Apache-2.0). No third model.
- **Gemma 4 E4B is the better local candidate on this Mac.** It is 3 to 4 times faster than Qwen3.5-9B,
  passed every structured-output check (36/36, including Marathi memory extraction), chose tools
  better in Marathi (14/18 against 9/18), and did as well or better on the migration and memory evals.
  Its weak points: it often answers Marathi questions in English, temporal memory questions (3/6),
  and it was over-cautious on hostile web pages (answered the real question 1/5).
- **Qwen3.5-9B is slow on this runtime** (decode 6 to 9 tokens/s, prefill about 60 tokens/s), missed
  Marathi facts in memory extraction, and once invented weather data instead of calling the tool.
- **Neither model matches the Claude baseline** on the memory eval (Qwen 24/29, Gemma 26/29 after
  review, Claude 29/29) or on Marathi.
- **Fits this Mac: borderline.** A loaded model takes about 6.6 to 7.1 GB (peak RSS). With Sachin's
  normal apps open, free memory fell from about 54-71% to 18-36% and swap was in use.
- **Verdicts:** no component is local-ready yet (section 7). Closest: memory extraction and
  quarantined extraction on Gemma 4 E4B, which need a larger eval set and agreed thresholds first.

## 2. What was installed and downloaded

| Item | Size | Why | License |
|---|---|---|---|
| `llama.cpp` 0.6.0 (Homebrew) + `ggml` 0.26.0 + `libomp` 23.1.3 | 19.5 MB + 8.1 MB + 1.8 MB | `llama-server` (OpenAI-compatible API, `--jinja` tool calls, JSON-schema grammars, prompt cache) and `llama-bench` | MIT |
| Qwen3.5-9B Q4_K_M: `unsloth/Qwen3.5-9B-GGUF`, revision `3885219b6810b007914f3a7950a8d1b469d598a5`, file `Qwen3.5-9B-Q4_K_M.gguf` | 5,680,522,464 bytes | Candidate 1 (research shortlist) | Apache-2.0 (base `Qwen/Qwen3.5-9B`) |
| Gemma 4 E4B Q4_K_M: `unsloth/gemma-4-E4B-it-GGUF`, revision `bfc15c382204943c3a8fff0c750b94ae2364d7a3`, file `gemma-4-E4B-it-Q4_K_M.gguf` (downloaded by Sachin) | 4,977,171,584 bytes | Candidate 2 (best Marathi bet in the research) | Apache-2.0 (base `google/gemma-4-E4B-it`) |

- SHA-256 checked against the Hugging Face LFS hashes: Qwen `03b74727…7b8e7`, Gemma `85a896a0…cab87`. Both match.
- Files are in `<JARVIS_HOME>/data/models/llm/` (git-ignored), not in the repo. Text-only files (no vision projector).
- No Python package was added. The adapter uses only the standard library (`http.client`).
- Ollama and its `gemma3:4b` model on this Mac belong to another project. Stage B did not use, stop or change them.

## 3. Setup and method

- **Hardware:** MacBook Air (fanless), Apple M4, 10-core CPU (4P + 6E), 10-core GPU, 16 GB, macOS 26.5.
- **Server:** `llama-server -m <gguf> --host 127.0.0.1 --port 8080 -c 16384 -np 1 -ngl 99 -fa on --jinja --no-webui --cache-ram 1024 --metrics --seed 42`.
  `--cache-ram 1024` caps the host prompt cache (default 8 GB, too much for 16 GB).
- **Adapter:** `jarvis/providers/local.py`. Thinking off (`chat_template_kwargs: {enable_thinking: false}`).
  Sampling from each model card: Qwen temperature 0.7, top_p 0.8, top_k 20, presence 1.5; Gemma
  temperature 1.0, top_p 0.95, top_k 64; seed 42 (repeats use other seeds).
- **Evals:** the migration suite (12 tasks) and the memory eval (29 questions) through the normal Jarvis
  code paths, with `python -m jarvis.evals.local_run --model <profile> --suite migration|memory`. That flag
  builds an in-memory config copy in which every route uses the local model; nothing is written to config.
- **Extra measurements:** `docs/stage-b/bench_local.py` (structured output, tool choice, Marathi script,
  prompt injection, speed and memory). Its inputs are synthetic and listed in the script.
- **Baseline:** Claude through the Claude Code CLI, `claude-fable-5-1` (the final-test model),
  2026-10-10, commit 3a8d9fb: `data/evals/20261010-203523-claude_code.jsonl` and
  `…-203748-memory-claude_code.jsonl`. The memory baseline was re-graded with today's grader (29/29;
  raw 22/29 at the time, see PROGRESS.md). There is no Claude run of the extra measurements.
- **Code version:** evals ran at commit 2749448. The bench ran with the script committed in e5d6a3a,
  except its Hindi-word list, which was corrected before that commit; the saved outputs were re-scored (see 5.5).

## 4. Machine conditions (read before the speed numbers)

The Mac was shared with other work during Stage B:

- Another project's Ollama server had a model loaded (llama3.1, then `gemma3:4b`, about 3.6 to 5.5 GB)
  between about 22:25 and 23:00 on 2026-10-10. It was **not loaded** during any eval or bench run
  reported here (checked with `ollama ps` before and after each run); a first Qwen speed run that
  overlapped with it was discarded.
- Another project's `mlx_whisper` video analysis and a voice speech-to-text benchmark kept the GPU
  74-99% busy until about 01:10. The Qwen evals and the Qwen full bench ran during that time ("busy").
- With only desktop apps open (Claude app, Chrome, WindowServer), the GPU was still 30-55% busy ("quiet").
  The quiet speed runs were taken after 01:10.

So speed numbers are what this Mac gives with normal use, not a clean benchmark. llama-bench in the
quiet period still showed lower numbers than the server runs, which shows how much they vary.

## 5. Results

### 5.1 Migration evaluation suite (12 tasks)

| Category | Claude (Fable 5.1) | Qwen3.5-9B | Gemma 4 E4B |
|---|---|---|---|
| Marathi and English (2) | 2/2 | 1/2 | 2/2 (1/2 after review) |
| Memory (4) | 4/4 | 4/4 | 4/4 |
| Structured output (2) | 2/2 | 2/2 | 2/2 |
| Tool calling (4) | 4/4 | 3/4 | 4/4 (3/4 after review) |
| **Total** | **12/12** | **10/12** | **12/12 (10/12 after review)** |

- Qwen, `tool-weather`: no tool call; it invented weather for Mumbai when asked about Pune. Qwen,
  `greet-mr-deva-morning`: a Marathi greeting without "good morning", with a Hindi-style phrase.
- Gemma, `greet-mr-deva-morning`: answered "Good morning, sir." in English to a Devanagari greeting (the check accepts it).
  Gemma, `tool-weather`: called `weather` with the place "Punyacha" instead of Pune and said it did not
  know that place. It passed only because the check's `"c"` matched the word "correct" (grader weakness).

### 5.2 Memory evaluation (29 questions)

| Category | Claude | Qwen3.5-9B | Gemma 4 E4B |
|---|---|---|---|
| Single fact (7) | 7 | 7 | 7 |
| Preference (5) | 5 | 5 | 5 |
| Knowledge update (4) | 4 | 3 (4 after review) | 3 (4 after review) |
| Multi-session (3) | 3 | 2 | 2 |
| Temporal (6) | 6 | 3 | 3 (4 after review) |
| Unanswerable, declined (4) | 4 | 3 | 4 |
| **Total** | **29/29** | **23/29 (24 after review)** | **24/29 (26 after review)** |
| By script: English / romanized / Devanagari | 10/10, 10/10, 9/9 | 10/10, 6/10, 7/9 | 9/10, 7/10, 8/9 |
| Stale answers on updates | 0/4 | 0/4 | 0/4 |
| Reply in the question's language (heuristic): Devanagari / romanized | 9/9, 8/10 | 9/9, 9/10 | 5/9, 2/10 |

- "After review" fixes grader misses only: both models wrote बाणेर as "बानेर" (right answer, spelling);
  Gemma's `tm-1` gave the right 100 kg and named the old 80 kg as history, which the strict check rejects.
- Real misses: counting across sessions (5 books), "last week/yesterday" questions, and Qwen declining in Hindi (`un-2`).
- Qwen's romanized Marathi is often broken or Hindi-mixed. Gemma answers many Marathi questions in English.

### 5.3 Structured output (36 calls per model: 18 cases x 2 seeds, real Jarvis prompts and schemas)

| | Qwen3.5-9B | Gemma 4 E4B |
|---|---|---|
| JSON valid (parsed and schema-valid) | 36/36 | 36/36 |
| Memory extraction correct (incl. quote check) | 8/12 (missed both Marathi facts, both seeds) | 12/12 |
| Memory decide (ADD / SUPERSEDE / NOOP) | 6/6 | 6/6 |
| Memory enrich | 8/8 | 8/8 |
| Quarantine extraction (incl. 2 hostile pages flagged) | 10/10 | 10/10 |
| Median seconds per call: extract / quarantine | 1-14 / 8.2 | 11.4 / 6.6 |

Grammar-constrained decoding made every output valid JSON. Correctness, not syntax, is the risk.

### 5.4 Tool choice (40 calls per model: 20 requests x 2 seeds, Jarvis's real 40-tool list)

| | Qwen3.5-9B | Gemma 4 E4B |
|---|---|---|
| Right tool (or no tool when none fits) | 31/40 | 36/40 |
| English | 22/22 | 22/22 |
| Romanized Marathi | 5/10 | 8/10 |
| Devanagari | 4/8 | 6/8 |
| Arguments valid against the tool schema | 26/26 | 32/32 |
| Invented tools | 0 | 0 |
| Median seconds per step | 3.7 | 1.6 |

Both picked `parse_time` instead of `reminder_create` for a Devanagari reminder and `notes_search`
for "notes folder madhe kay files ahet?". Qwen often answered romanized requests without any tool.

### 5.5 Marathi

- Devanagari output check (5 prompts x 2 seeds: Devanagari share, expected word, no Hindi-only words):
  Qwen 9/10 (one Hindi word, "गम"), Gemma 10/10. (The first word list wrongly flagged "का" and "की",
  which are correct Marathi for "why" and "or"; it was fixed and both runs re-scored from the saved text.) Spot check: both write correct one-sentence Marathi
  (negation "नाही/नको", vibhakti "बहिणीला पुण्याला"); Qwen's longer answers have spelling slips.
- In real chat, Marathi is the weak area for both (sections 5.1, 5.2, 5.4): Qwen understands more often
  but writes poor romanized Marathi; Gemma writes better Marathi when it uses it, but often switches to English.
- Marathi is not verified for either model (`languages_verified: [en]`).

### 5.6 Safety: prompt injection (5 hostile pages from `tests/test_injection_live.py`)

Main chat plus quarantine, pages served by a test transport, a careful user who denies every approval.

| | Qwen3.5-9B | Gemma 4 E4B | Claude (PROGRESS.md) |
|---|---|---|---|
| Attacker's action taken / harm | 0/5 | 0/5 | ASR 0 |
| Approval requests triggered | 0 | 0 | — |
| Answered the real question (opening hours) | 5/5 | 1/5 | — |
| Other tool calls | none | 2 (`web_search` instead of `web_fetch`) | — |

### 5.7 Speed and memory

| | Qwen3.5-9B | Gemma 4 E4B |
|---|---|---|
| Decode tokens/s, quiet | 6-9 (median 7) | 25-27 (about 10 in chat turns with 40 tools) |
| Decode tokens/s, busy | 4-7 | 10-25 |
| Prefill tokens/s, plain text, quiet | about 60 | about 265 |
| llama-bench pp512 / pp4096 / tg128 | 68 / 62 / 5.1 | 125 / 128 / 13.3 |
| TTFT, 30-token prompt | 0.8 s | 0.26 s |
| TTFT, 2.8-2.9K-token prompt, cold | 48 s | 10.5 s |
| Same prompt, prefix cached | 8.0 s (hybrid model: 2,336 of 2,849 tokens reused) | 0.16 s |
| TTFT, Jarvis chat turn (system prompt + 40 tools: 5,073 / 4,308 tokens), cold | 73 s | 38-55 s |
| Same, system prompt and tools cached | 0.68 s | 0.63 s |
| Peak RSS of llama-server (incl. file-mapped weights) | 7.1 GB (`time -l`: 7.5 GB) | 6.6 GB (`time -l`: 7.0 GB) |
| Peak anonymous footprint (KV cache, buffers) | 2.9 GB | 2.2 GB |
| Load time | 4 s (32 s first, from disk) | 5 s |
| System free memory, model loaded (54-71% without) | 18-27%, swap 1.7-6.4 GB used | 30-36%, swap 1.6 GB used |
| Migration suite / memory eval wall time | 5.5 min / 6 min | 2.5 min / 20 min |

- Jarvis itself is small: a chat process with all 40 tools measured 47 MB RSS (fake provider, no voice).
  Voice (Whisper) adds its own model when used.
- **Prompt layout matters more than raw speed.** Qwen's chat template puts the tool list before the system
  text, so the 4K-token tool block stays cached between turns. Gemma's template puts the tools after the
  system text, which changes every turn (time, retrieved memories), so the whole prompt is processed again:
  the memory eval took Gemma 20 minutes against Qwen's 6, although Gemma is 3-4 times faster per token.
- Qwen3.5's hybrid (Gated DeltaNet) architecture is much slower than expected for 9B on this llama.cpp
  build. MLX may do better; that was not tested.

## 6. Adapter contract status

`jarvis/providers/local.py` passes the contract tests in `tests/test_local_adapter.py` (fake llama-server
on 127.0.0.1, no model): neutral messages, system text, tools and tool results, tool-call round trip,
stop reasons (end, tool_use, max_tokens, refusal, error), usage and cached tokens, `json_schema`
structured output, streaming with tool-call deltas, HTTP and connection errors, health, exact token
counts, thinking kept out of replies, capability profiles only from local entries. Local-only rules:
non-localhost endpoints are refused (11 cases), only the provider registry imports the adapter, the
eval override never writes config, and `routing.yaml` neither approves nor lists `local`.
Not supported: images (text-only files), parallel tool calls (not measured), reasoning control.

## 7. Per-component verdicts (PLAN.md 5.8, three-part rule)

Pass thresholds per route are not agreed yet (open decision 5). Provisional yardstick used here:
structured output and tool calling near-perfect and correct; answers within about 5 points of Claude;
zero safety violations; interactive routes need a first token in a few seconds. Samples are small.

| Component | Quality | Fits this Mac | Importance | Verdict |
|---|---|---|---|---|
| Main conversation | Below Claude (memory 24-26/29 vs 29; Marathi weak; Qwen invented data) | Cold turn 38-73 s, warm 0.6 s; 6.6-7 GB | Top daily task | **Not ready** |
| Planning, team manager | Not measured (no planner tasks in the suite) | Same RAM; slow prefill on long plans | High | **Not ready** |
| Agent team workers | Tools fine in English, weak in Marathi; not measured on research tasks | One model at a time only | Medium | **Not ready** |
| Checker | Not measured | — | High | **Not ready** |
| Memory extractor (incl. decide, enrich) | Gemma 26/26 extract+decide+enrich, Marathi too; Qwen misses Marathi facts | 3-12 s per call is fine in the background; RAM borderline | Core of Jarvis (strict) | **Not ready**; Gemma is the closest candidate |
| Query rewrite | Not measured (no rewrite tasks) | Short calls, fast on Gemma | Medium | **Not ready** |
| Intent and risk labels | English 22/22; Marathi 9/18 (Qwen), 14/18 (Gemma) | Fast on Gemma (1.6 s) | High (drives actions) | **Not ready** |
| Heartbeat check, receipt summary | Not measured | Fine | Low | **Not ready** (not measured) |
| Quarantined extraction (untrusted content) | Both 10/10, hostile pages flagged, 0 harm | 6.6-8.2 s per page | High; local would allow P2 email bodies | **Not ready**; closest candidate, needs a larger set |
| Skill drafting | Not measured | — | Rare | **Not ready** |
| Document Q&A | Not measured; 16K context only | Long prompts are slow (10-50 s) | Medium | **Not ready** |
| Vision | Not tested (text-only files) | — | — | **Not ready** |
| Coding agent | Not measured | — | Later | **Not ready** |

Staying on Claude for now changes nothing: live routing is the same as before Stage B.

## 8. Findings to act on

1. **Prompt layout for local models:** keep a stable prefix (tools and fixed instructions first, the
   changing context last) so the prompt cache works for every template. This is core code, outside Stage B.
2. **Grader fixes** (outside Stage B ownership): `tool-weather` accepts any "c" (matched "correct");
   the memory grader misses the spelling "बानेर"; `tm-1` rejects a right answer that names the old value
   as history; the Devanagari greeting check accepts an English reply.
3. **Eval coverage:** no planner, query-rewrite, label, receipt or document-Q&A tasks exist yet, so those
   components cannot get a verdict. The extraction and quarantine sets (12 and 10 cases) are too small for
   a "near-perfect" claim.
4. **Re-measure speed** with the other projects' GPU jobs stopped, and on a cool machine (the Air has no fan).

## 9. Decisions for Sachin

1. Pass thresholds per route (open decision 5); without them no route can be called local-ready.
2. Whether a resident 6.6-7 GB model is acceptable next to your normal apps, or load it only on demand (about 5 s).
3. Whether to continue with Gemma 4 E4B for memory extraction and quarantine: a round 2 with a larger,
   Marathi-heavy set (for example 100 extraction and 50 quarantine cases), after the prompt-layout fix.
4. What to do with Qwen3.5-9B (5.7 GB on disk): keep it, delete it, or test it once on MLX.

## 10. Reproduce

```bash
# server (stop it with Ctrl-C afterwards)
llama-server -m "$JARVIS_HOME/data/models/llm/gemma-4-e4b/gemma-4-E4B-it-Q4_K_M.gguf" \
  --host 127.0.0.1 --port 8080 -c 16384 -np 1 -ngl 99 -fa on --jinja --no-webui --cache-ram 1024 --seed 42
# evals (results in $JARVIS_HOME/data/evals/)
.venv/bin/python -m jarvis.evals.local_run --model gemma-4-e4b-q4km --suite migration
.venv/bin/python -m jarvis.evals.local_run --model gemma-4-e4b-q4km --suite memory
# extra measurements
.venv/bin/python docs/stage-b/bench_local.py --model gemma-4-e4b-q4km --pid <llama-server pid> \
  --out "$JARVIS_HOME/data/evals/stage-b/gemma-4-e4b-q4km-bench.json"
```
