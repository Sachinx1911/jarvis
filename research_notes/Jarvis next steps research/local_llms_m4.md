# Local LLM options for Jarvis on an Apple M4 MacBook (16 GB), as of October 2026

Scope: runtimes, candidate models, M4 speeds, tool calling / JSON reliability, Marathi quality, licenses, and a Stage B evaluation shortlist.
Research date: 2026-10-10. About 16 tool calls. Many numbers come from third-party trackers, not the original sources, and are marked as such. No source measured Marathi quality for any small (under 15B) 2026 model. That is the biggest gap.

## Runtimes: versions, OpenAI API, tool calling, constrained decoding, speed, memory

### Takeaway
llama.cpp `llama-server` is the most complete local server for Jarvis's needs. It has an OpenAI-compatible API, tool calling (`--jinja`), and real grammar/JSON-schema constrained decoding through `response_format`. MLX decodes about 10–20% faster on Apple Silicon, but the `mlx_lm.server` docs do not document `response_format`, and its maintainers say the server is not for production. Ollama (MLX backend in preview since 0.19, March 2026) and LM Studio (Outlines for MLX models, llama.cpp grammars for GGUF) wrap these engines and are easier to install, at the cost of less control.

### Cited Findings
**llama.cpp (llama-server)**
- It offers OpenAI-compatible routes: chat completions, responses, embeddings, `/v1/completions`, `/v1/models`, `/v1/rerank`. The docs make "no strong claims" of full spec compatibility. — [llama.cpp server README](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md)
- "OpenAI-style function calling is supported with the `--jinja` flag". Some models may need a `--chat-template-file` override. — [llama.cpp server README](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md)
- `/v1/chat/completions` accepts `response_format` `{"type":"json_object"}` and `{"type":"json_schema","schema":...}`. It also supports `--grammar` / `--grammar-file` (BNF-like grammars) and `-j/--json-schema`. Not every JSON-schema feature is supported; the docs point to a test file for the list. — [llama.cpp server README](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md)
- `cache_prompt` defaults to true, so a repeated prefix such as the system prompt or tool list is reused. Other options: `--cache-reuse`, `--cache-ram` (default 8192 MiB), parallel slots (`-np`), and continuous batching on by default. — [llama.cpp server README](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md)
- llama.cpp supports grammar-constrained decoding via GBNF. — [d-central local agent guide, Jul 2026](https://d-central.tech/local-llm-agent-capability/)

**MLX-LM (mlx_lm.server)**
- Endpoints: `POST /v1/chat/completions` and `GET /v1/models`, on localhost:8080 by default. The API is "intended to be similar to the OpenAI chat API". The docs say the server "is not recommended for production as it only implements basic security checks". A quantized KV cache (`--kv-bits`) turns batching off. — [mlx-lm SERVER.md](https://github.com/ml-explore/mlx-lm/blob/main/mlx_lm/SERVER.md)
- The server doc lists no `response_format`/JSON-schema parameter. It does list `logit_bias`, `logprobs`, and a `draft_model` for speculative decoding. — [mlx-lm SERVER.md](https://github.com/ml-explore/mlx-lm/blob/main/mlx_lm/SERVER.md)
- The Python API takes custom `sampler` and `logits_processors`, which is a hook for constrained decoding, but there is no built-in JSON-schema mode. Prompt caching: `mlx_lm.cache_prompt` / `--prompt-cache-file`, and a rotating KV cache via `--max-kv-size`. — [mlx-lm GitHub README](https://github.com/ml-explore/mlx-lm)
- Server tool calling exists and is still changing. v0.31.3 (22 Apr 2026) fixed server tool calls, parallel tool calls, and Gemma 4 / Mistral tool parsing. A GitHub issue on 0.31.2 reported that the Gemma 4 26B-A4B 4-bit model could not make tool calls (parser error). — [Releasebot mlx-lm notes](https://releasebot.io/updates/ml-explore/mlx-lm); [mlx-lm issue #1125](https://github.com/ml-explore/mlx-lm/issues/1125)
- A maintainer called tool calling "a fast moving target", with no settled standard across model providers. A user reported that Qwen3-Coder-30B 4-bit on MLX failed tool calls where similar GGUF models worked. — [mlx-lm discussion #371](https://github.com/ml-explore/mlx-lm/discussions/371)
- For schema enforcement on MLX outside LM Studio, a third-party library (`llm-structured-output`) exists. — [PyPI llm-structured-output](https://pypi.org/project/llm-structured-output/)

**Ollama**
- Structured outputs: `format` takes `"json"` or a JSON schema (works with Pydantic `model_json_schema()`). The OpenAI-compatible API supports this through `response_format`. Ollama Cloud does not support structured outputs. — [Ollama docs: structured outputs](https://docs.ollama.com/capabilities/structured-outputs)
- Ollama 0.19, released as a preview on about 30–31 March 2026, moved the Apple Silicon backend from llama.cpp Metal to MLX. Ollama's own benchmark (Qwen3.5-35B-A3B on an **M5 Max**, not M4): decode 58 → 112 tok/s, prefill 1,154 → 1,810 tok/s. — [Ollama blog via search snippet](https://registry.ollama.ai/blog/mlx) (the page returned 404 when fetched); [lilting.ch summary](https://lilting.ch/en/articles/ollama-mlx-apple-silicon-preview)
- One third-party writeup says only safetensors models (for example NVFP4 Qwen3.5) use MLX, while GGUF models still run on llama.cpp. This is unconfirmed in Ollama's docs. — [lilting.ch](https://lilting.ch/en/articles/ollama-mlx-apple-silicon-preview)
- Not established: whether the MLX backend has left preview, and the current stable Ollama version in October 2026.

**LM Studio**
- OpenAI-compatible `/v1/chat/completions` on localhost:1234. It takes `response_format.json_schema`, and the result comes back as a string in `choices[0].message.content`. — [LM Studio structured output docs](https://lmstudio.ai/docs/developer/openai-compat/structured-output)
- Constrained decoding: llama.cpp grammar sampling for GGUF models, Outlines for MLX models (via lmstudio-ai/mlx-engine). The docs warn that models under about 7B may not handle structured output well. — [LM Studio structured output docs](https://lmstudio.ai/docs/app/api/structured-output)
- The developer docs list tool calling and MCP. No per-backend (MLX vs GGUF) tool-calling details were found. — [LM Studio developer docs](https://www.lmstudio.ai/docs/developer)

**MLX vs GGUF speed and memory (third-party, not verified)**
- A MacBook Air M4 comparison says MLX beats llama.cpp by 10–18% on every model it tested. Qwen3 8B at about 4-bit: 14.1 tok/s on 16 GB, 16.4 tok/s on 24 GB, about 5.1 GB resident. The method is not stated. — [bestllmfor.com](https://bestllmfor.com/best/macbook-air-m4-16gb/)
- TechPlained: M4 has 120 GB/s memory bandwidth. About 75% of unified memory is usable for the GPU, so about 12 GB on a 16 GB M4. It suggests `sudo sysctl iogpu.wired_limit_mb=14000` to raise the limit. Under memory pressure (above 85% used), tok/s falls 3–6x. A MacBook Air throttles after about 3 minutes of sustained decode. — [TechPlained Qwen 3.5 on Apple Silicon](https://www.techplained.com/qwen-3-5-apple-silicon)

### Inferences
- For Jarvis's JSON-schema routes (memory extraction, receipts, labels), constrained decoding is the main reliability lever. llama.cpp (GGUF) and Ollama `format` offer it today. Plain `mlx_lm.server` does not document it.
- Jarvis uses a provider interface, and all four runtimes speak an OpenAI-style chat API, so one "openai-compatible local" provider class can target any of them. The real differences are in tool-call parsing and schema enforcement.
- Suggested Stage B runtime: **llama.cpp llama-server**, for grammar/JSON-schema enforcement, `--jinja` tool calls, prompt cache, and fine control over memory (context size, KV quantization). Re-test against Ollama (MLX backend) or mlx-lm only if the speed gap turns out to matter. The roughly 10–20% MLX advantage is less important than JSON validity for these routes.
- Because macOS caps GPU-wired memory and Jarvis plus normal apps need room, a practical model budget on 16 GB is about 5–7 GB of weights plus KV cache. That makes 4B–9B dense models at 4-bit the main tier. A 12B model at 4-bit (about 7 GB) is borderline.

### Gaps
- No exact current version numbers were confirmed for llama.cpp (build tags change daily), Ollama (0.19 or later?), or LM Studio as of October 2026.
- It is not confirmed whether mlx-lm (after 0.31.3) added `response_format` JSON-schema support to the server. Check the repo before Stage B.
- No first-party measurement of each runtime's own memory overhead was found.

## Candidate models (fit in about 8–10 GB at 4-bit): tool calling, instruction following, structured output, licenses

### Takeaway
The strongest small open model with official tool-calling numbers is **Qwen3.5-9B**: BFCL-V4 66.1, IFEval 91.5, MMMLU 81.2, Apache-2.0, about 5.5 GB at Q4. **Gemma 4** (E4B; 12B "Unified") is the main alternative. It is Apache-2.0, supports 140+ languages, and has native tool use, but Google publishes no official BFCL score. **IBM Granite 4.1 8B** (Apache-2.0) is a third option focused on tool calling. Sub-4B models are considered marginal or unreliable for agent work.

### Cited Findings
**Qwen3.5 (Alibaba, Feb 2026)**
- Qwen3.5-9B: Apache-2.0. 262K native context. Hybrid Gated DeltaNet + Gated Attention architecture. Claims support for 201 languages and dialects (Marathi not named on the card). BFCL-V4 66.1, IFEval 91.5, MMMLU 81.2, INCLUDE 75.6. — [HF model card Qwen/Qwen3.5-9B](https://huggingface.co/Qwen/Qwen3.5-9B)
- Thinking is on by default. Turn it off with `chat_template_kwargs: {enable_thinking: False}`. The `/think` and `/nothink` soft switches from Qwen3 are not supported. Tool use needs a tool-call parser (`qwen3_coder` in the examples). — [HF model card Qwen/Qwen3.5-9B](https://huggingface.co/Qwen/Qwen3.5-9B)
- Open sizes: 2B, 4B, 9B, 27B dense, plus MoE models (35B-A3B, 122B-A10B, 397B-A17B). BFCL-v4: 9B 0.661, 4B 0.503, 2B 0.436, 27B 0.685. Reliability verdict: "9B usable, 27B recommended; 4B marginal; 2B or below unreliable". — [d-central, reviewed 18 Jul 2026](https://d-central.tech/local-llm-agent-capability/)

**Gemma 4 (Google, technical report July 2026)**
- Family: E2B, E4B, 12B Unified, 26B-A4B MoE, 31B dense. E4B has 4.5B effective parameters (8B total with embeddings) and a 128K context. Apache 2.0. Pre-trained on 140+ languages, with out-of-the-box support for 35+. Native structured tool use. E4B scores MMMLU 76.6% and Tau2 (avg of 3) 42.2%. No BFCL score is on the card. — [HF model card google/gemma-4-E4B-it](https://huggingface.co/google/gemma-4-E4B-it)
- A third-party source reports BFCL v4 scores of about 89% (non-live) for 26B-A4B and the mid-to-high 80s for E4B, and calls E4B the "smallest reliable" Gemma for tools. These figures are not official, and their scale is inconsistent with the official Qwen numbers above. — [d-central](https://d-central.tech/local-llm-agent-capability/)
- Gemma 2 and 3 had no native tool support (grammar-only) and were released under the Gemma Terms of Use, not Apache. — [d-central](https://d-central.tech/local-llm-agent-capability/)

**Others**
- IBM Granite 4.1: 8B scores BFCL-v3 68.27% and 30B scores 73.68%. Granite 4.0 has H-Tiny 7B, Micro 3B, and Nano models. Apache-2.0. Verdict: "~7–8B reliable". — [d-central](https://d-central.tech/local-llm-agent-capability/)
- BFCL-v4 third-party table (updated 27 Sep 2026): Granite 4.2 3B 52.4%, MiniCPM5-2B 66.6%, LFM2.5-2.6B 56.9%, LFM2.5-8B-A1B 49.7%. — [BenchLM BFCL v4](https://benchlm.ai/md/benchmarks/bfcl-v4.md)
- Phi-4-mini (3.8B, MIT) has native tool tokens. Its BFCL v4 score is reported only by third parties ("low-to-mid 80s"), with no official Berkeley row. — [d-central](https://d-central.tech/local-llm-agent-capability/)
- Qwen3 dense on tau2-Telecom: 14B scores 32% and 4B-2507 scores 27% (arXiv 2511.15718), which shows that multi-step agent tasks remain hard at this size. — [d-central](https://d-central.tech/local-llm-agent-capability/)
- Mistral Small 3.x/4 (24B, Apache-2.0) has no clean public BFCL entry, and at 4-bit (about 14 GB) it is too big for this Mac. Hermes 4 14B is Apache-2.0. Command R7B is CC-BY-NC (non-commercial, but fine for personal use). — [d-central](https://d-central.tech/local-llm-agent-capability/)
- The official BFCL page calls V4 a holistic agentic evaluation. The last update seen on it was 16 Dec 2025. — [Berkeley BFCL leaderboard](https://gorilla.cs.berkeley.edu/leaderboard)
- LM Studio warns that models under about 7B often struggle with structured output. — [LM Studio docs](https://lmstudio.ai/docs/app/api/structured-output)

### Inferences
- Under 16 GB with Jarvis running, the realistic set is Qwen3.5-4B/9B, Gemma 4 E4B/12B, Granite 4.x 3B–8B, and Phi-4-mini. Gemma 4 26B-A4B (about 15 GB at 4-bit) and Sarvam 30B do not fit.
- For single-step JSON actions with schema-constrained decoding, a 9B model plus a grammar should give near-100% syntactically valid JSON. Choosing the right tool and arguments is the real risk, and it needs a Jarvis-specific eval set.
- All of the main candidates are Apache-2.0 or MIT, so licensing is not an issue for personal use.

### Gaps
- There is no official BFCL row for Gemma 4 or Phi-4-mini. The d-central Gemma figures conflict in scale with the official Qwen card numbers.
- No measured JSON-schema validity rates per model and runtime were found. Jarvis must measure these itself.
- IFEval numbers for Gemma 4 E4B and Granite 4.1 were not found.

## Marathi / Indic language quality

### Takeaway
No public benchmark gives Marathi scores for the small 2026 candidates (Qwen3.5 4B/9B, Gemma 4 E4B/12B). The evidence we do have points one way. Older 8B-class models are weak in Marathi. Accuracy drops 7.9–20.5% on romanized Marathi. Models confuse Marathi case markers with Hindi ones. The Indic-specialist models that do well (Sarvam 30B/105B, Sarvam-M 24B) are too big for 16 GB. Marathi chat should stay on Claude unless Jarvis's own eval proves otherwise.

### Cited Findings
- Patil & Chetia, MeLLM 2026, tested Llama-3.1-8B, Llama-3.3-70B, Mistral-7B, and Qwen3-32B. All models dropped 7.9–20.5% on romanized Marathi versus Devanagari. Every model ignored the negative subjunctive marker "nasta", and vibhakti case markers were often replaced with Hindi equivalents. — [ACL Anthology 2026.mellm-1.11](https://aclanthology.org/2026.mellm-1.11/)
- MILU (exam-style Indic benchmark covering Marathi among 11 languages, NAACL 2025): GPT-4o led with about 72–74% average. Open multilingual models beat language-specific fine-tunes, and scores are higher in high-resource languages. It covers older models (Gemma 2, Llama), not Gemma 4 or Qwen3.5. — [MILU arXiv 2411.02538](https://arxiv.org/html/2411.02538v1)
- L3Cube/IIT Madras (Jadhav et al.): Gemma 2 2B/9B and Llama 3.1 8B fall short on Marathi annotation tasks compared with English. — [arXiv 2411.17637](https://arxiv.org/abs/2411.17637v1)
- L3Cube-IndicQuest v2 (2026, factual knowledge in 19 Indic languages): Gemma 4 31B (about 62%) beat Sarvam 30B (about 49%) in every evaluated language, and a frontier commercial model led "by a wide margin". The per-language Marathi score is not in the abstract. — [arXiv 2608.15535](https://arxiv.org/abs/2608.15535)
- Sarvam 30B is a MoE (30B total, 2.4B active), Apache-2.0, 64K context, released March 2026. It is trained on 10 Indian languages and handles native script, romanized, and code-mixed input. Sarvam claims an 89% pairwise win rate on Indic benchmarks, with no per-language breakdown. — [Sarvam docs](https://docs.sarvam.ai/api/models/sarvam-30b)
- Sarvam-M (24B, Mistral-based) beats Gemma 3 27B on Indic MMLU, 0.79 vs 0.75 (vendor-reported). — [Sarvam blog](https://sarvam.ai/blogs/sarvam-m)
- Qwen3.5-9B INCLUDE (multilingual regional knowledge) is 75.6 and MMMLU is 81.2. Gemma 4 E4B MMMLU is 76.6. Neither breaks out Marathi. — [Qwen3.5-9B card](https://huggingface.co/Qwen/Qwen3.5-9B); [Gemma 4 E4B card](https://huggingface.co/google/gemma-4-E4B-it)

### Inferences
- Gemma 4's strong IndicQuest result at 31B, together with the Gemma family's broad multilingual pre-training, makes Gemma 4 E4B/12B the most promising small Marathi candidates. Qwen3.5-9B is the other one to test. This is an inference from the larger-model data, not a measurement.
- Romanized Marathi and Hindi interference are the known failure modes. Jarvis's Marathi eval should include romanized input, negation ("nasta"), and vibhakti checks.
- Sarvam 30B at 4-bit is about 17 GB, so it cannot run on this Mac. Sarvam-1 (2B, older) was not re-verified in this pass.

### Gaps
- No Marathi scores exist for Qwen3.5 4B/9B, Gemma 4 E2B/E4B/12B, or Granite 4.x on MILU, IndicGenBench, or IndicXTREME.
- Airavata and Krutrim were not re-checked in this pass. Both are older (2024) and probably superseded.

## Measured speed (tok/s, TTFT) on base M4 16 GB

### Takeaway
No rigorous first-party M4 16 GB benchmark was found for the 2026 models. Third-party figures put decode speed for an about 8–9B model at 4-bit around 14–31 tok/s and a 3–4B model around 50–58 tok/s on M4 16 GB. 14B-class models are not benchmarked on 16 GB by the main source and are memory-tight. No TTFT numbers for M4 16 GB were found. Jarvis should measure these on its own machine with `llama-bench` or `mlx_lm.benchmark`.

### Cited Findings
- TechPlained (published Dec 2025, updated about Aug–Oct 2026, Q4_K_M, 2K prompt, 512-token output, cold start). On **M4 16 GB**: "Qwen 3.5 3B" (1.9 GB) runs at MLX 58 / llama.cpp 49 / Ollama 47 tok/s, and "Qwen 3.5 7B" (4.3 GB) at MLX 31 / llama.cpp 26 / Ollama 25. The 9B (5.5 GB) is listed only for M4 **24 GB**: MLX 28 / llama.cpp 23 / Ollama 22. The 14B (8.7 GB) has no M4 16 GB row. No TTFT is given. **Caution:** the model sizes this article names (3B, 7B, 14B, 32B) do not match the official Qwen3.5 lineup (2B, 4B, 9B, 27B), so these numbers may be estimated or mislabeled. Treat them as unverified. — [TechPlained](https://www.techplained.com/qwen-3-5-apple-silicon)
- MacBook Air M4 16 GB, Qwen3 8B at about Q4 on MLX: 14.1 tok/s, about 5.1 GB resident. The method is not given. — [bestllmfor.com](https://bestllmfor.com/best/macbook-air-m4-16gb/)
- WillItRunAI estimates Qwen3 8B on MacBook Pro M4 16 GB at about 17.5 tok/s. This is a modeled estimate, not a measurement. — [WillItRunAI](https://willitrunai.com/de/can-run/qwen-3-4b-on-m4-16gb)
- For scale on older chips (crowd-sourced, measured): Llama 3.1 8B Q4_K_M runs at 12 tok/s on M1 16 GB with Ollama and 18 tok/s on M2 16 GB. — [kunalganglani.com LLM benchmarks](https://kunalganglani.com/llm-benchmarks)
- The oMLX community benchmark table has an M4 (10-core) 16 GB entry for Qwen3.5-9B 4-bit with a 4K prompt. Its values could not be read reliably. — [oMLX community benchmarks](https://omlx.ai/benchmarks?page=258)
- Decode speed on Apple Silicon is bound by memory bandwidth (M4: 120 GB/s). Prefill is several times faster than decode. — [TechPlained](https://www.techplained.com/qwen-3-5-apple-silicon)

### Inferences
- Rough ceiling: 120 GB/s ÷ 5.5 GB of weights gives at most about 22 tok/s for a 9B Q4 model. So the 14–22 tok/s figures are plausible and the 31 tok/s "7B" figure is plausible only for a smaller model. Expect about 15–20 tok/s for 9B and about 30–40 tok/s for 4B on base M4. This is an inference, not a measurement.
- For short routes (query rewrite, labels, single tool step) with outputs under 100 tokens, a 4B–9B model should finish in about 1–5 s. Prompt prefill of a long tool list or web page will dominate TTFT, so prompt caching (llama.cpp `cache_prompt`) matters.
- A fanless MacBook Air throttles under sustained load, so benchmarks should state which machine was used.

### Gaps
- No credible measured TTFT for 4B/8B/14B on base M4 16 GB.
- No measured 14B-at-4-bit numbers on M4 16 GB were found. It is likely to fit only with a small context and with apps closed.

## Recommendation for Stage B (per route) and what stays on Claude

### Takeaway
Evaluate on **llama.cpp llama-server (GGUF Q4_K_M)** first, with **Qwen3.5-9B**, **Gemma 4 E4B** (with Gemma 4 12B as a stretch), and **Qwen3.5-4B** as the fast option. Strong local candidates are query rewrite, labels, and schema-constrained extraction. Main Marathi chat and higher-risk multi-step tool calling should probably stay on Claude. Untrusted-web extraction can go local if it is schema-constrained and has no tool access.

### Cited Findings
- Qwen3.5-9B has the best official small-model tool score (BFCL-V4 66.1) and IFEval 91.5, under Apache-2.0. — [Qwen3.5-9B card](https://huggingface.co/Qwen/Qwen3.5-9B)
- Gemma 4 E4B has native tool use, 140+ pre-training languages, and Apache-2.0. — [Gemma 4 E4B card](https://huggingface.co/google/gemma-4-E4B-it)
- llama.cpp supports `--jinja` tool calls and `response_format` JSON-schema. — [llama.cpp server README](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md)
- Small models degrade on romanized Marathi and mix in Hindi grammar. — [ACL Anthology 2026.mellm-1.11](https://aclanthology.org/2026.mellm-1.11/)
- Qwen 4B is "marginal" for agents and 2B and below are "unreliable". — [d-central](https://d-central.tech/local-llm-agent-capability/)

### Inferences (proposed shortlist, to be checked by Jarvis's own measurements)
| Route | Models to evaluate first | Runtime | Expectation |
|---|---|---|---|
| Query rewrite | Qwen3.5-4B (thinking off), Gemma 4 E4B | llama-server | Good local candidate. Short output, low risk. |
| JSON-schema structured output (memory extraction, receipts, labels) | Qwen3.5-9B, Gemma 4 E4B, Granite 4.1 8B | llama-server with `response_format: json_schema` | Good candidate. Grammar makes JSON valid, so measure field accuracy. Marathi-language source text is a risk. |
| Quarantined extraction of untrusted web text | Qwen3.5-9B, Gemma 4 E4B | llama-server, schema-constrained, no tools | Plausible. Constrained output limits what a prompt injection can emit. Long pages hit prefill time and KV memory limits. |
| Tool calling (single JSON action per step) | Qwen3.5-9B, Gemma 4 E4B (Granite 4.1 8B third) | llama-server `--jinja`, or a grammar-forced action schema | Medium risk. Keep Claude for high-impact or approval-gated actions until the local model matches on a Jarvis eval. |
| Main chat (Marathi Devanagari + romanized + English) | Gemma 4 E4B / 12B, Qwen3.5-9B (as a test only) | llama-server | Probably stays on Claude. No small-model Marathi evidence, and known romanized/Hindi-interference failures. |

- Memory plan: one resident 9B Q4 (about 5.5 GB) plus KV for about 8K context fits in about 7 GB. Running two models at once (for example 9B and 4B) is tight with Jarvis and normal apps open. Prefer one shared model with per-route prompts, or swap models on demand.
- Stage B measurements to record per model and runtime: decode tok/s, TTFT at 1K/4K prompts, peak RSS, JSON-valid %, schema-field accuracy, tool-choice accuracy, and a Marathi rubric (Devanagari, romanized, negation, vibhakti).

### Gaps
- All recommendations are provisional until Jarvis's own on-device evals run. Speed numbers are third-party and partly unverified, and Marathi quality is unmeasured for these model sizes.
