"use client";

// Voice input for Chat (and the Home ask box): push-to-talk and hands-free listening.
// Both send the same thing to the same endpoint: a 16 kHz mono 16-bit WAV posted to
// /api/voice/transcribe (built with lib/audio.ts). Audio is never stored in the browser.
// Voice only ever produces chat text. It never approves anything, and text that starts
// with "/" (a chat command, e.g. "/repeat yes") is put in the box instead of being sent.

import { useEffect, useRef, useState } from "react";
import { api, upload } from "@/lib/api";
import { micSupported, Recording, startRecording, toWav16k } from "@/lib/audio";
import { errText } from "@/lib/hooks";

export const NOT_INSTALLED = "speech-to-text not installed (run voice setup)";

export type Stt = { ready: boolean; detail: string };
export type Transcript = { status: string; text: string; heard?: string; language?: string; confidence?: number };

// The server answers "ok" for a clear transcript (its audit log calls it "transcribed").
export function isClear(status: string): boolean {
  return status === "ok" || status === "transcribed";
}

export function transcribe(wav: ArrayBuffer): Promise<Transcript> {
  return upload<Transcript>("/api/voice/transcribe", wav, "audio/wav");
}

export function isCommand(text: string): boolean {
  return text.trim().startsWith("/");
}

// "Jarvis, what's the weather?" -> "what's the weather?"; "Jarvis." -> ""; no wake word -> null.
// Case- and punctuation-insensitive. Accepts a greeting first ("hey/ok/hi Jarvis", "हे जार्विस")
// and the spellings speech-to-text often writes for an Indian "Jarvis" (Jervis, Javis, जर्विस...).
const NAME = "(?:jarvis|jarvice|jarviss|jarwis|jarves|jarbis|jervis|javis|jaarvis|जार्विस|जारविस|जर्विस|जार्वीस|जारवीस|जार्विज|जारवीज)";
const FILLER = "(?:(?:hey|hi|hello|ok|okay|हे|ए|हाय|ओके)[\\s\\p{P}]+)?";
const WAKE = new RegExp(`^[\\s\\p{P}\\p{S}]*${FILLER}${NAME}(?=$|[\\s\\p{P}\\p{S}])[\\s\\p{P}\\p{S}]*`, "iu");
export function stripWakeWord(text: string): string | null {
  const m = text.match(WAKE);
  return m ? text.slice(m[0].length).trim() : null;
}

export function useStt(): Stt | null {
  const [stt, setStt] = useState<Stt | null>(null);
  useEffect(() => {
    api<{ stt_ready: boolean; stt_detail: string }>("/api/voice/status")
      .then((r) => setStt({ ready: r.stt_ready, detail: r.stt_detail }))
      .catch(() => setStt({ ready: false, detail: NOT_INSTALLED }));
  }, []);
  return stt;
}

export function notReadyText(stt: Stt): string {
  return stt.detail.startsWith(NOT_INSTALLED) ? stt.detail : `${NOT_INSTALLED}: ${stt.detail}`;
}

// Push to talk: first press records, second press transcribes. onHeard gets the text and
// whether the server was sure (clear) or not (unclear: the caller leaves it for checking).
export function usePushToTalk(stt: Stt | null, onHeard: (text: string, clear: boolean) => void) {
  const [recording, setRecording] = useState<Recording | null>(null);
  const [note, setNote] = useState("");
  const recRef = useRef<Recording | null>(null);
  recRef.current = recording;
  const heard = useRef(onHeard);
  heard.current = onHeard;

  // Leaving the page while recording releases the microphone.
  useEffect(() => () => recRef.current?.cancel(), []);

  async function toggle() {
    setNote("");
    if (recording) {
      setRecording(null);
      setNote("Reading what you said…");
      try {
        const wav = await recording.stop();
        const r = await transcribe(wav);
        if (isClear(r.status)) {
          setNote("");
          heard.current(r.text, true);
        } else if (r.status === "no_audio") setNote("Nothing was recorded. Try again.");
        else if (r.heard) {
          setNote(`Not sure I heard that right (heard "${r.heard}"). Check the text, then press Send.`);
          heard.current(r.heard, false);
        } else setNote("Sorry, I did not catch that. Please say it again.");
      } catch (e) {
        setNote(errText(e));
      }
      return;
    }
    if (stt && !stt.ready) {
      setNote(notReadyText(stt));
      return;
    }
    if (!micSupported()) {
      setNote("This browser cannot record audio.");
      return;
    }
    try {
      setRecording(await startRecording());
      setNote("Listening… press the button again when you are done.");
    } catch (e) {
      setNote(`Microphone not available: ${errText(e)}`);
    }
  }

  return { recording, note, setNote, toggle };
}

// ---- hands-free ----

export type HandsFreeMode = "wake" | "conversation";
export type HandsFreePhase = "off" | "starting" | "listening" | "hearing" | "transcribing";

const FRAME = 2048; // samples per audio callback (about 43 ms at 48 kHz)
const END_SILENCE_S = 0.9;
const MIN_SPEECH_S = 0.3;
const MAX_UTTERANCE_S = 30;
const PREROLL_S = 0.3;
const ARMED_MS = 8000; // after a bare "Jarvis", the next utterance needs no wake word

type Handlers = {
  onUtterance: (text: string) => void; // clear text, allowed to send
  onDraft: (text: string) => void; // put in the box for checking (commands)
  onNote: (text: string) => void;
  onError: (text: string) => void; // the caller turns hands-free off
};

// Keeps the microphone open while `enabled`. An energy detector (RMS of each audio frame
// against a running noise floor) cuts the stream into utterances: speech starts after two
// loud frames, ends after about 0.9 s of silence, needs about 0.3 s of speech, and is cut
// at 30 s. Nothing is captured while `paused` (sending, Jarvis speaking, approval waiting).
export function useHandsFree(opts: { enabled: boolean; mode: HandsFreeMode; paused: boolean } & Handlers) {
  const [phase, setPhaseState] = useState<HandsFreePhase>("off");
  const [armed, setArmed] = useState(false);
  const analyserRef = useRef<AnalyserNode | null>(null); // live mic level for the waveform
  const optsRef = useRef(opts);
  optsRef.current = opts;
  const phaseRef = useRef<HandsFreePhase>("off");
  const setPhase = (p: HandsFreePhase) => {
    if (phaseRef.current !== p) {
      phaseRef.current = p;
      setPhaseState(p);
    }
  };

  useEffect(() => {
    if (!opts.enabled) {
      setPhase("off");
      setArmed(false);
      return;
    }
    let cancelled = false;
    let stream: MediaStream | null = null;
    let ctx: AudioContext | null = null;
    let source: MediaStreamAudioSourceNode | null = null;
    let proc: ScriptProcessorNode | null = null;
    let mute: GainNode | null = null;
    let armedUntil = 0;
    let armTimer = 0;

    // detector state
    let noise = 0.004;
    let loudRun = 0;
    let speaking = false;
    let busy = false;
    let frames: Float32Array[] = [];
    let preroll: Float32Array[] = [];
    let speechFrames = 0;
    let silentFrames = 0;

    const reset = () => {
      speaking = false;
      loudRun = 0;
      frames = [];
      speechFrames = 0;
      silentFrames = 0;
    };

    const fail = (msg: string) => {
      if (cancelled) return;
      optsRef.current.onError(msg);
    };

    async function finish(chunks: Float32Array[], rate: number) {
      busy = true;
      setPhase("transcribing");
      try {
        const wav = await toWav16k(new Blob([pcmWav(chunks, rate)], { type: "audio/wav" }));
        if (cancelled) return;
        const r = await transcribe(wav);
        if (cancelled) return;
        const o = optsRef.current;
        if (!isClear(r.status)) {
          if (r.status !== "no_audio") o.onNote(`Did not catch that${r.heard ? ` (heard "${r.heard}")` : ""}.`);
          return;
        }
        let text = r.text.trim();
        if (o.mode === "wake") {
          const rest = stripWakeWord(text);
          if (rest === null) {
            if (Date.now() > armedUntil) {
              // not for Jarvis: ignore it, but say what was heard so it is clear why nothing happened
              o.onNote(`Heard “${text}”. Start with “Jarvis…” so I know it is for me (or switch to Conversation).`);
              return;
            }
          } else if (!rest) {
            armedUntil = Date.now() + ARMED_MS;
            setArmed(true);
            window.clearTimeout(armTimer);
            armTimer = window.setTimeout(() => setArmed(false), ARMED_MS);
            o.onNote("Yes? I am listening.");
            return;
          } else text = rest;
        }
        armedUntil = 0;
        setArmed(false);
        if (!text) return;
        if (isCommand(text)) {
          o.onDraft(text);
          o.onNote("Commands are never sent by voice. Check the text in the box and press Send.");
          return;
        }
        o.onUtterance(text);
      } catch (e) {
        fail(`Could not read speech: ${errText(e)}`);
      } finally {
        busy = false;
        reset();
        if (!cancelled) setPhase("listening");
      }
    }

    async function start() {
      setPhase("starting");
      if (!micSupported()) return fail("This browser cannot record audio.");
      try {
        stream = await navigator.mediaDevices.getUserMedia({
          audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
        });
      } catch (e) {
        return fail(`Microphone not available: ${errText(e)}`);
      }
      if (cancelled) {
        stream.getTracks().forEach((t) => t.stop());
        return;
      }
      ctx = new AudioContext();
      await ctx.resume().catch(() => undefined);
      const rate = ctx.sampleRate;
      const frameS = FRAME / rate;
      const prerollN = Math.ceil(PREROLL_S / frameS);
      source = ctx.createMediaStreamSource(stream);
      const analyser = ctx.createAnalyser();
      analyser.fftSize = 1024;
      source.connect(analyser);
      analyserRef.current = analyser;
      proc = ctx.createScriptProcessor(FRAME, 1, 1);
      mute = ctx.createGain();
      mute.gain.value = 0; // the processor must reach the output to run; nothing is played
      source.connect(proc);
      proc.connect(mute);
      mute.connect(ctx.destination);
      proc.onaudioprocess = (ev) => {
        if (cancelled || busy) return;
        if (optsRef.current.paused) {
          if (speaking || frames.length) reset();
          preroll = [];
          return;
        }
        const data = new Float32Array(ev.inputBuffer.getChannelData(0));
        let sum = 0;
        for (let i = 0; i < data.length; i++) sum += data[i] * data[i];
        const rms = Math.sqrt(sum / data.length);
        const threshold = Math.max(0.012, noise * 3);
        if (!speaking) {
          preroll.push(data);
          if (preroll.length > prerollN) preroll.shift();
          if (rms > threshold) {
            loudRun += 1;
            if (loudRun >= 2) {
              speaking = true;
              frames = [...preroll];
              preroll = [];
              speechFrames = loudRun;
              silentFrames = 0;
              setPhase("hearing");
            }
          } else {
            loudRun = 0;
            noise = noise * 0.95 + rms * 0.05;
            if (phaseRef.current !== "listening") setPhase("listening");
          }
          return;
        }
        frames.push(data);
        if (rms > threshold * 0.8) {
          speechFrames += 1;
          silentFrames = 0;
        } else silentFrames += 1;
        const ended = silentFrames * frameS >= END_SILENCE_S || frames.length * frameS >= MAX_UTTERANCE_S;
        if (!ended) return;
        const chunks = frames;
        const enough = speechFrames * frameS >= MIN_SPEECH_S;
        reset();
        if (enough) void finish(chunks, rate);
        else setPhase("listening");
      };
      setPhase("listening");
    }

    void start();
    return () => {
      cancelled = true;
      window.clearTimeout(armTimer);
      if (proc) proc.onaudioprocess = null;
      analyserRef.current?.disconnect();
      analyserRef.current = null;
      proc?.disconnect();
      source?.disconnect();
      mute?.disconnect();
      ctx?.close().catch(() => undefined);
      stream?.getTracks().forEach((t) => t.stop()); // release the microphone
      phaseRef.current = "off";
      setPhaseState("off");
      setArmed(false);
    };
    // Only switching on/off restarts the microphone; the rest is read through optsRef.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [opts.enabled]);

  return { phase, armed, analyserRef };
}

// Float samples at the AudioContext rate -> a plain WAV that toWav16k can decode and resample.
function pcmWav(chunks: Float32Array[], rate: number): ArrayBuffer {
  const n = chunks.reduce((a, c) => a + c.length, 0);
  const buf = new ArrayBuffer(44 + n * 2);
  const v = new DataView(buf);
  const str = (o: number, s: string) => [...s].forEach((c, i) => v.setUint8(o + i, c.charCodeAt(0)));
  str(0, "RIFF");
  v.setUint32(4, 36 + n * 2, true);
  str(8, "WAVE");
  str(12, "fmt ");
  v.setUint32(16, 16, true);
  v.setUint16(20, 1, true);
  v.setUint16(22, 1, true);
  v.setUint32(24, rate, true);
  v.setUint32(28, rate * 2, true);
  v.setUint16(32, 2, true);
  v.setUint16(34, 16, true);
  str(36, "data");
  v.setUint32(40, n * 2, true);
  let o = 44;
  for (const c of chunks) {
    for (let i = 0; i < c.length; i++, o += 2) {
      const s = Math.max(-1, Math.min(1, c[i]));
      v.setInt16(o, s < 0 ? s * 0x8000 : s * 0x7fff, true);
    }
  }
  return buf;
}
