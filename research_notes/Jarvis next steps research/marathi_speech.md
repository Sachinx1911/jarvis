# Offline Marathi speech-to-text and text-to-speech for Jarvis (state as of Oct 2026)

Context: Jarvis uses faster-whisper (CTranslate2) for English STT, Windows System.Speech / macOS `say` for English TTS, and edge-tts (cloud, off by default) for Marathi TTS. Targets: Windows laptop now, Apple M4 MacBook (16 GB) later. Research done 2026-10-10 with a limited tool budget, so several speed numbers are gaps (see each Gaps section).

## STT: which models handle Marathi, how accurate, and can they run locally on CPU or Apple Silicon?

### Takeaway
Stock Whisper is weak on Marathi (large-v2 FLEURS WER 38.3%; medium 63.2%). Marathi-tuned models are much better: AI4Bharat IndicConformer (600M, MIT) scores 13.1% OI-WER on the April 2026 Voice of India benchmark. That is close to commercial APIs (Sarvam Audio 9.4%, Gemini 3 Pro 10.7%) and far ahead of Meta OmniASR LLM 7B (26.3%). IndicWhisper (Vistaar, MIT) averages 18.2% WER on Marathi and is Whisper-architecture, so it is the easiest fit for the existing faster-whisper pipeline. I found no published Marathi-English code-mixed WER for any model.

### Cited Findings
**Whisper (OpenAI), zero-shot. Older results, 2023.**
- FLEURS Marathi WER: Whisper medium 63.2, Whisper large-v2 38.3. For comparison, Meta MMS L-1107 scores 20.9 without an LM and 13.4 with an n-gram LM (2023 table "Comparison to Whisper", Table A1) — [MMS paper, arXiv 2305.13516](https://arxiv.org/pdf/2305.13516)
- For Whisper large-v3 zero-shot, only CER was found: 23.26% on FLEURS Marathi and 21.35% on Common Voice, self-reported on a model card for a large-v3 fine-tune. That fine-tune itself reports FLEURS WER 54.92% and CV25 WER 62.98%, and cites an unverified "Findings of EMNLP 2026" venue — [BuzzASR/marathi model card](https://huggingface.co/BuzzASR/marathi)
- Common Voice Marathi has under 30 hours, about 70% of it validated. Dialect variation makes generic models harder to generalize — [Lamarr Institute blog](https://lamarr-institute.org/blog/fine-tuning-whisper-marathi-asr)
- PolyWhisper (a GitHub project) reports Marathi FLEURS WER of 170.1, then 96.7. Values above 100 point to an evaluation problem, so this source is unreliable — [PolyWhisper releases](https://github.com/eulogik/PolyWhisper/releases)

**IndicWhisper / Vistaar (AI4Bharat, INTERSPEECH 2023; older).**
- Marathi WER by test set: Kathbath 19.9, Kathbath-Hard 22.1, CommonVoice 22.8, FLEURS 20.5, IndicTTS 11.4, MUCS 12.8; average 18.2 — [AI4Bharat/vistaar GitHub](https://github.com/AI4Bharat/vistaar)
- The repo states "Vistaar is MIT-licensed. The license applies to all the fine-tuned language models." The Marathi checkpoint is a zip at `https://indicwhisper.objectstore.e2enetworks.net/marathi_models.zip` — [AI4Bharat/vistaar GitHub](https://github.com/AI4Bharat/vistaar)
- IndicWhisper had the lowest WER on 39 of the 59 Vistaar benchmarks — [Vistaar paper, arXiv 2305.15386](https://arxiv.org/abs/2305.15386)

**IndicConformer (AI4Bharat).**
- `ai4bharat/indic-conformer-600m-multilingual`: 600M parameters, MIT license, 22 Indian languages including Marathi. It is gated (you share contact info to download). It loads with `AutoModel.from_pretrained(..., trust_remote_code=True)`, needs 16 kHz mono input, and supports both "ctc" and "rnnt" decoding. The install line lists onnxruntime (the `-gpu` variant). No Marathi WER and no CPU guidance on the card. The card points to "Indic-Transcribe" (25 languages) as having better quality — [HF model card](https://huggingface.co/ai4bharat/indic-conformer-600m-multilingual)
- Voice of India benchmark (Josh Talks, April 2026; private test set; metric is OI-WER, an orthography-aware WER), Marathi results: Sarvam Audio 9.4, Saarika 2.5 10.0, Gemini 3 Pro 10.7, Amazon Transcribe 11.3, ElevenLabs Scribe v2 12.9, **IndicConformer 13.1**, Gemini 3 Flash 16.0, OmniASR LLM 7B 26.3, Gemma E4B 26.6, GPT-4o Mini Transcribe 30.7, OmniASR LLM 1B 31.2, Microsoft STT 31.9, Deepgram Nova 3 43.7, GPT-4o Transcribe 55.6, AssemblyAI 87.6. No Whisper results and no code-mixed breakdown — [Voice of India blog](https://voiceofindiablogs.ai.joshtalks.com/)
- The OI-WER reference code is at [AI4Bharat/OIWER](https://github.com/AI4Bharat/OIWER-Orthographically-Informed-Benchmarking-for-ASR) (linked from the [Voice of India blog](https://voiceofindiablogs.ai.joshtalks.com/))

**Meta MMS / Omnilingual ASR.**
- Omnilingual ASR was released 2025-11-10. Apache-2.0 for code and weights. Checkpoints at 300M, 1B, 3B and 7B (wav2vec2-CTC plus LLM-decoder variants); the 7B needs about 15 GiB of VRAM — [omniASR-LLM-7B model card](https://huggingface.co/facebook/omniASR-LLM-7B/blob/main/README.md); [Meta AI blog](https://ai.meta.com/blog/omnilingual-asr-advancing-automatic-speech-recognition/)
- Marathi OI-WER: OmniASR LLM 7B 26.3, LLM 1B 31.2. Both are far behind IndicConformer — [Voice of India blog](https://voiceofindiablogs.ai.joshtalks.com/)

**Sarvam (Saarika / Saaras).**
- Sarvam's speech models (Saaras v3 STT, Bulbul v3 TTS) are API-only. Saarika v2.5 is deprecated. Sarvam's open-weight releases are text models (sarvam-m, sarvam-translate, Sarvam-1) — [Sarvam docs, models](https://docs.sarvam.ai/api/getting-started/models); [Caller.Digital overview, June 2026 (vendor blog)](https://caller.digital/blog/open-source-voice-ai-india-sarvam-ai4bharat-bhasini-2026)

**Code-mixed speech.**
- The Voice of India authors argue that plain WER over-penalizes valid spelling and script variants in Indic code-mixed text, which is why they use OI-WER. They give no Marathi-English numbers — [Voice of India blog](https://voiceofindiablogs.ai.joshtalks.com/)

### Inferences
- IndicWhisper checkpoints are Hugging Face Whisper models. That means they should convert with `ct2-transformers-converter` and run in faster-whisper, reusing Jarvis's existing STT code. This is unverified, and the checkpoint's base size (likely medium) still needs checking after download.
- IndicConformer is the accuracy leader among open models (about 13% versus about 18–20% for IndicWhisper, though the test sets differ). Its integration cost is higher: `trust_remote_code`, a gated download, and ONNX/torch rather than CTranslate2. A conformer-CTC model of 600M parameters is likely faster than real time on M4 and on a modern laptop CPU. This is not measured.
- Stock Whisper (large-v3 or turbo) should not be the Marathi path. Its Marathi errors are 2–3 times higher than Indic-tuned models.
- English terms in Marathi speech may come out in Devanagari or Latin script, depending on the model. Scoring needs normalization (OI-WER or transliteration-aware CER).

### Gaps
- No Marathi WER found for Whisper large-v3 or large-v3-turbo zero-shot (only a third-party CER).
- No measured CPU or Apple Silicon real-time factor for IndicConformer or IndicWhisper.
- I did not confirm that IndicConformer runs in NeMo or has an official ONNX CPU path; the card shows only transformers plus onnxruntime-gpu. "Indic-Transcribe" (newer, recommended on the card) was not checked for license or size.
- No public Marathi-English code-mixed benchmark found.
- No whisper.cpp or MLX ports of IndicWhisper found (not searched in depth).

## TTS: which offline Marathi voices exist, and what are their quality, size and license?

### Takeaway
The best-documented open option is AI4Bharat Indic Parler-TTS: 0.9B parameters, Apache-2.0, six Marathi speakers, Marathi Native Speaker Score 76.96%. It is heavy for CPU real-time use. Meta MMS-TTS-mar is tiny (36M, VITS) and fast on CPU, but it is CC-BY-NC 4.0 and has no published quality score. IndicF5 (0.4B, MIT) needs a reference clip for voice cloning. I found no Piper Marathi voice. Veena does not support Marathi. Sarvam Bulbul is API-only.

### Cited Findings
- **Indic Parler-TTS** (`ai4bharat/indic-parler-tts`): Apache 2.0; 0.9B parameters (F32 safetensors). Marathi speakers: Sanjay, Sunita (recommended), Nikhil, Radha, Varun, Isha. Marathi NSS 73.81% (pretrained) and 76.96% (fine-tuned). Install with `pip install git+https://github.com/huggingface/parler-tts.git`, then load `ParlerTTSForConditionalGeneration`. The voice is steered by a text description. No speed numbers; INFERENCE.md covers SDPA, torch.compile and streaming — [HF model card](https://huggingface.co/ai4bharat/indic-parler-tts)
- On the license, one government portal listing says MIT, which conflicts with the HF card's Apache 2.0 (use the HF card) — [AIKosh listing](https://aikosh.indiaai.gov.in/home/models/details/ai4bharat_indic_parler_tts_text_to_speech_model.html)
- Indic Parler-TTS was trained on RASMALAI: 13,000 hours across 24 languages for pretraining, then 1,804 hours across 18 languages for fine-tuning — [RASMALAI paper, arXiv 2505.18609](https://arxiv.org/pdf/2505.18609)
- **Meta MMS-TTS Marathi** (`facebook/mms-tts-mar`): CC-BY-NC 4.0 (non-commercial); 36.3M parameters; VITS architecture. Runs with `transformers.VitsModel`. Output is non-deterministic unless you fix the seed. No quality metrics on the card — [HF model card](https://huggingface.co/facebook/mms-tts-mar)
- **IndicF5** (`ai4bharat/IndicF5`): MIT; about 0.4B parameters; 11 languages including Marathi. Needs a reference audio clip plus its transcript (voice cloning). Gated download; 24 kHz output. No speed or eval numbers on the card. The card says to clone only voices you have permission to use, and recommends the newer "Indic-Speak" (22 languages) — [HF model card](https://huggingface.co/ai4bharat/IndicF5)
- **Vyom TTS Marathi 3B** (ATX Labs): MIT; fine-tuned from Orpheus-3B; SNAC vocoder at 24 kHz; one male voice. The card says to write numbers as Marathi words — [HF model card](https://huggingface.co/atx-labs/Vyom-TTS-Marathi-3B)
- **Veena** (Maya Research): 3B, Llama-based, Apache 2.0, Hindi and English only, so no Marathi — [HF model card](https://huggingface.co/maya-research/Veena)
- **Svara TTS** (Kenpath): Apache-2.0 and 19 languages per an aggregator listing. Marathi support and parameter count are unconfirmed. Orpheus-style, with a GGUF export for CPU — [dev.co listing (aggregator)](https://dev.co/ai/llms/svara-tts-v1)
- **Piper**: about 15M-parameter ONNX models that run on CPU. No Marathi voice was confirmed in any source I found — [tts.ai Piper page (aggregator)](https://tts.ai/voices/piper/?lang=mr)
- **Sarvam Bulbul v3**: API only, not open weights — [Sarvam docs](https://docs.sarvam.ai/api/getting-started/models)
- **MahaTTS** is another multilingual Indic TTS framework (2025 paper). I did not evaluate it — [arXiv 2508.14049](https://arxiv.org/pdf/2508.14049)

### Inferences
- For a personal (non-commercial) assistant, MMS-TTS-mar is the fastest offline path (VITS, 36M parameters; it should run faster than real time on CPU) but may sound robotic. Indic Parler-TTS is the quality path, but at 0.9B parameters and autoregressive it may be slower than real time on CPU. On M4 (MPS) it is more plausible. Neither is measured.
- 3B speech-LLM TTS models (Vyom, Svara) would need GGUF or 4-bit quantization to be practical on 16 GB, and add latency.

### Gaps
- No measured CPU or Apple Silicon speed (RTF) for Indic Parler-TTS, MMS-TTS-mar or IndicF5.
- No MOS or NSS for MMS-TTS-mar, so there is no direct quality comparison with Parler.
- Coqui XTTS-v2 was not checked. From memory, its supported language list did not include Marathi, but this is unverified. It is also under the non-commercial CPML license, and Coqui (the company) shut down.
- AI4Bharat "Indic-Speak" (newer, recommended on the IndicF5 card) was not checked.

## OS-native voices: macOS 26 `say` and Windows 11 Marathi TTS

### Takeaway
macOS Tahoe (26) lists Marathi under Spoken Content, so a system Marathi voice very likely exists. It may be a Siri-style voice that `say -v` cannot select by name; check on the Mac with `say -v '?'`. Windows 11 has no Marathi Narrator or SAPI voice: Microsoft's voice list for Indian languages covers only English (India), Hindi and Tamil. Marathi is only a Language Interface Pack, not a full language pack.

### Cited Findings
- Apple's macOS Tahoe feature-availability page lists Marathi under "VoiceOver, Live Speech, Spoken Content" — [Apple macOS feature availability](https://www.apple.com/ca/macos/feature-availability)
- Siri voices cannot be selected with `say -v`. Running `say` without `-v` uses the system default voice, which can be set via `defaults write com.apple.speech.voice.prefs SystemTTSLanguage` after downloading the voice in Accessibility > Spoken Content (third-party source) — [clawhub say skill](https://clawhub.ai/tobihagemann/say); [alanwsmith voice list](https://www.alanwsmith.com/en/2w/gw/r3/4n/)
- Windows Narrator voices for Indian languages: English (India) Ravi/Heera, Hindi Hemant/Kalpana, Tamil Valluvar. Natural voices: English (India) Prabhat/Neerja only. Marathi is not listed — [Microsoft Support, Appendix A: supported languages and voices](https://support.microsoft.com/en-us/windows/appendix-a-supported-languages-and-voices-4486e345-7730-53da-fcfe-55cc64300f01)
- Marathi (mr-IN) is a Language Interface Pack on English base, not a full language pack. "You cannot add languages to Home Single Language" editions. This laptop runs Windows 11 Home Single Language — [Microsoft Learn, available language packs](https://learn.microsoft.com/en-us/windows-hardware/manufacture/desktop/available-language-packs-for-windows)
- Some third-party guides suggest that adding any language installs text-to-speech. Microsoft's own voice list contradicts this for Marathi — [geekrewind guide](https://geekrewind.com/how-to-add-custom-text-to-speech-voices-in-windows-11-time-and-language-settings/) vs [Microsoft Support Appendix A](https://support.microsoft.com/en-us/windows/appendix-a-supported-languages-and-voices-4486e345-7730-53da-fcfe-55cc64300f01)

### Inferences
- On Windows, Marathi TTS must come from a model (or edge-tts cloud), not from System.Speech.
- On the Mac, the Marathi system voice is worth testing first because it costs nothing. If it is a Siri voice, Jarvis may need AVSpeechSynthesizer (via pyobjc) instead of `say -v`.

### Gaps
- Not verified on an actual macOS 26 machine: the Marathi voice name, whether `say -v` can select it, and its quality.

## Recommendation and evaluation plan

### Takeaway
- **STT:** try IndicWhisper-Marathi converted to CTranslate2 in faster-whisper first. It is the lowest-friction path and is MIT. Benchmark it against IndicConformer-600M (CTC, onnxruntime CPU), which has the best open accuracy (13.1 OI-WER). Keep the winner behind `jarvis/providers/`.
- **TTS:** try Indic Parler-TTS (Apache-2.0, speaker "Sunita" or "Sanjay") first for quality, with MMS-TTS-mar as the fast, low-RAM fallback (non-commercial is fine for personal use). On the Mac, also test the built-in Marathi Spoken Content voice.

### Cited Findings
- Accuracy ranking basis: IndicConformer 13.1 vs OmniASR 7B 26.3 OI-WER — [Voice of India](https://voiceofindiablogs.ai.joshtalks.com/). IndicWhisper averages 18.2 WER — [Vistaar](https://github.com/AI4Bharat/vistaar). Whisper large-v2 scores 38.3 on FLEURS — [MMS paper](https://arxiv.org/pdf/2305.13516)
- TTS basis: Parler Marathi NSS 76.96%, Apache-2.0 — [HF](https://huggingface.co/ai4bharat/indic-parler-tts). MMS-TTS-mar is 36.3M and CC-BY-NC — [HF](https://huggingface.co/facebook/mms-tts-mar)
- OI-WER scorer for scoring code-mixed and spelling variants — [AI4Bharat OIWER](https://github.com/AI4Bharat/OIWER-Orthographically-Informed-Benchmarking-for-ASR)

### Inferences (suggested evaluation; not from a source)
- **STT test set:** 1) the FLEURS Marathi test split (public, comparable to published numbers); 2) about 30–50 of Sachin's own recorded commands using made-up content. These should cover pure Marathi, Marathi-English code-mixed speech (for example "उद्या सकाळी 9 वाजता meeting चा reminder लाव", "माझा laptop चा battery किती आहे?"), numbers, dates and times, and names; quiet room versus fan noise; laptop mic.
- **STT metrics:** WER and CER after normalization; OI-WER for code-mixed lines; command intent accuracy (did Jarvis do the right thing?); RTF and first-token latency on the Windows CPU and on M4; peak RAM.
- **TTS test set:** about 20 sentences covering numbers ("३ वाजून १५ मिनिटे" vs "3:15"), English loanwords inside Marathi, questions, and long sentences.
- **TTS metrics:** RTF and time to first audio; RAM; Sachin's 1–5 naturalness and intelligibility rating (blind A/B against edge-tts as the reference); round-trip intelligibility (CER when the chosen STT transcribes the TTS output).
- **Pass bar (proposal):** STT CER at or below about 10% on his own commands with RTF under 0.5 on M4; TTS rated 3.5 or higher with first audio within about 1.5 s.

### Gaps
- No source gives measured CPU or Apple Silicon latency for any of the recommended Marathi models, so the pass bar is a proposal to validate on the machines.
