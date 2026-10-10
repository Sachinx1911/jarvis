"use client";

// The voice engine of the dashboard: one state machine for push-to-talk, "Hey Jarvis" and
// conversation mode, shared by the Command Center and Chat.
//
// States follow the attention system voice assistants use (Alexa's Idle / Listening / Thinking /
// Speaking, plus Alexa's Follow-Up Mode):
//   off       microphone closed
//   waiting   hands-free: microphone open, waiting for "Hey Jarvis" (judged by the server's
//             wake-word model from the sound, not from the words)
//   listening a request is being recorded; it ends after ~0.7 s of silence, at the latest after
//             15 s, and gives up after 8 s with no speech at all
//   thinking  the request was sent; waiting for Jarvis
//   speaking  Jarvis is talking on the Mac's speakers (the server says when it ends)
//   followup  5 s after a reply: the next request needs no wake word
//   paused    an approval is waiting or the emergency stop is on
// Rules: voice only ever produces chat text. It never approves anything, and "/" commands are put
// in the box instead of being sent. Audio is never stored in the browser.

import { useEffect, useRef, useState } from "react";
import { api, post, upload } from "@/lib/api";
import { earcon, encodeWav, MicCapture, micSupported } from "@/lib/audio";
import { errText } from "@/lib/hooks";

export type VoiceMode = "ptt" | "wake" | "conversation";
export type VoicePhase = "off" | "waiting" | "listening" | "thinking" | "speaking" | "followup" | "paused";
export type VoicePrefs = { mode: VoiceMode; speak: boolean; autoSend: boolean; followUp: boolean; sounds: boolean };
export const DEFAULT_PREFS: VoicePrefs = { mode: "wake", speak: true, autoSend: true, followUp: true, sounds: true };
export const PREFS_KEY = "jarvis_voice_prefs";

export const MODE_LABEL: Record<VoiceMode, string> = {
  ptt: "Push to talk",
  wake: "“Hey Jarvis”",
  conversation: "Conversation",
};
export const MODE_HELP: Record<VoiceMode, string> = {
  ptt: "Tap the mic, speak, done. The mic is closed in between.",
  wake: "The mic stays open; Jarvis only answers after “Hey Jarvis”.",
  conversation: "The mic stays open and everything clear is sent. Mind other voices and the TV.",
};

export function loadPrefs(): VoicePrefs {
  try {
    const raw = localStorage.getItem(PREFS_KEY);
    if (raw) return { ...DEFAULT_PREFS, ...JSON.parse(raw) };
  } catch {
    /* ignore */
  }
  return DEFAULT_PREFS;
}

export function savePrefs(p: VoicePrefs): void {
  try {
    localStorage.setItem(PREFS_KEY, JSON.stringify(p));
  } catch {
    /* ignore */
  }
}

export const NOT_INSTALLED = "speech-to-text not installed (run voice setup)";
export type Stt = { ready: boolean; detail: string };

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

export type Transcript = {
  status: string; // ok | unclear | no_audio | wake_only
  text: string;
  heard?: string;
  language?: string;
  confidence?: number;
  wake?: number;
  wake_hit?: boolean;
};

export function isCommand(text: string): boolean {
  return text.trim().startsWith("/");
}

// "Jarvis, what's the weather?" -> "what's the weather?"; "Jarvis." -> ""; no name -> null.
const NAME = "(?:jarvis|jarvice|jarviss|jarwis|jarves|jarbis|jervis|javis|jaarvis|जार्विस|जारविस|जर्विस|जार्वीस|जारवीस|जार्विज|जारवीज)";
const FILLER = "(?:(?:hey|hi|hello|ok|okay|हे|ए|हाय|ओके)[\\s\\p{P}]+)?";
const WAKE = new RegExp(`^[\\s\\p{P}\\p{S}]*${FILLER}${NAME}(?=$|[\\s\\p{P}\\p{S}])[\\s\\p{P}\\p{S}]*`, "iu");
export function stripWakeWord(text: string): string | null {
  const m = text.match(WAKE);
  return m ? text.slice(m[0].length).trim() : null;
}

// ---- timing (seconds) ----
const PREROLL = 0.5; // audio kept from before speech was noticed (the start of "Hey Jarvis")
const END_SILENCE = 0.7; // silence that ends a request
const MIN_SPEECH = 0.3; // shorter sounds are ignored (a cough, a click)
const MAX_UTTERANCE = 15; // a request is cut here at the latest
const NO_SPEECH_TIMEOUT = 8; // listening with nothing said gives up (Alexa's rule)
const FOLLOW_UP = 5; // seconds after a reply without a wake word (Alexa's Follow-Up Mode)
const WAKE_MIN_CONFIDENCE = 0.28; // an unsure transcript is still used after "Hey Jarvis"

export type SendResult = { spoken?: boolean; chars?: number; handoff?: boolean };

export type VoiceOptions = {
  prefs: VoicePrefs;
  handsFree: boolean; // the hands-free switch (wake or conversation mode)
  blocked: "approval" | "stop" | null; // approvals stay click-only; the emergency stop closes the mic
  stt: Stt | null;
  onSend: (text: string) => Promise<SendResult>; // sends a request; resolves when the reply is in
  onDraft: (text: string) => void; // text to show in the box (commands, unsure text)
  onNote: (text: string) => void;
};

export function useVoice(opts: VoiceOptions) {
  const [phase, setPhaseState] = useState<VoicePhase>("off");
  const [heard, setHeard] = useState("");
  const analyserRef = useRef<AnalyserNode | null>(null);
  const micRef = useRef<MicCapture | null>(null);
  const phaseRef = useRef<VoicePhase>("off");
  const optsRef = useRef(opts);
  optsRef.current = opts;
  const timers = useRef<number[]>([]);

  const setPhase = (p: VoicePhase) => {
    if (phaseRef.current !== p) {
      phaseRef.current = p;
      setPhaseState(p);
    }
  };
  const later = (ms: number, fn: () => void) => {
    const id = window.setTimeout(fn, ms);
    timers.current.push(id);
    return id;
  };
  const clearTimers = () => {
    timers.current.forEach((t) => window.clearTimeout(t));
    timers.current = [];
  };
  const sound = (k: "start" | "end") => {
    if (optsRef.current.prefs.sounds) earcon(k);
  };

  // ---- the recording session (one open microphone, cut into utterances) ----
  const session = useRef<{
    frames: Float32Array[];
    preroll: Float32Array[];
    speaking: boolean;
    speechFrames: number;
    silentFrames: number;
    loudRun: number;
    noise: number;
    listenStart: number;
    wantWake: boolean; // true while waiting for "Hey Jarvis" (server checks the sound)
    busy: boolean;
  } | null>(null);

  async function openMic(): Promise<boolean> {
    if (micRef.current) return true;
    const o = optsRef.current;
    if (o.stt && !o.stt.ready) {
      o.onNote(notReadyText(o.stt));
      return false;
    }
    if (!micSupported()) {
      o.onNote("This browser cannot record audio.");
      return false;
    }
    try {
      const mic = await MicCapture.open();
      micRef.current = mic;
      analyserRef.current = mic.analyser;
      mic.onFrame = onFrame;
      session.current = { frames: [], preroll: [], speaking: false, speechFrames: 0, silentFrames: 0, loudRun: 0,
        noise: 0.003, listenStart: 0, wantWake: false, busy: false };
      return true;
    } catch (e) {
      o.onNote(`Microphone not available: ${errText(e)}`);
      return false;
    }
  }

  function closeMic() {
    micRef.current?.close();
    micRef.current = null;
    analyserRef.current = null;
    session.current = null;
  }

  // Begin a request: either armed (after a tap, "Hey Jarvis" or during follow-up) or waiting
  // for the wake word (hands-free in wake mode).
  function beginListening(wantWake: boolean) {
    const s = session.current;
    if (!s) return;
    clearTimers();
    s.frames = [];
    s.preroll = [];
    s.speaking = false;
    s.speechFrames = s.silentFrames = s.loudRun = 0;
    s.listenStart = Date.now();
    s.wantWake = wantWake;
    setPhase(wantWake ? "waiting" : "listening");
    if (!wantWake) {
      sound("start");
      later(NO_SPEECH_TIMEOUT * 1000, () => {
        if (phaseRef.current === "listening" && !session.current?.speaking) {
          optsRef.current.onNote("I did not hear anything.");
          afterRequest();
        }
      });
    }
  }

  // What happens when a request is over: hands-free goes back to waiting, push-to-talk closes.
  function afterRequest() {
    const o = optsRef.current;
    if (o.handsFree && o.prefs.mode !== "ptt" && o.blocked === null) beginListening(o.prefs.mode === "wake");
    else {
      closeMic();
      setPhase("off");
    }
  }

  function onFrame({ samples, rms }: { samples: Float32Array; rms: number }) {
    const s = session.current;
    const mic = micRef.current;
    if (!s || !mic || s.busy) return;
    const ph = phaseRef.current;
    if (ph !== "waiting" && ph !== "listening" && ph !== "followup") return;
    const frameS = samples.length / mic.rate;
    const prerollN = Math.ceil(PREROLL / frameS);
    const threshold = Math.max(0.008, s.noise * 3);
    if (!s.speaking) {
      s.preroll.push(samples);
      if (s.preroll.length > prerollN) s.preroll.shift();
      if (rms > threshold) {
        s.loudRun += 1;
        if (s.loudRun >= 2) {
          s.speaking = true;
          s.frames = [...s.preroll];
          s.preroll = [];
          s.speechFrames = s.loudRun;
          s.silentFrames = 0;
          if (ph !== "waiting") clearTimers(); // speech arrived: no no-speech timeout
        }
      } else {
        s.loudRun = 0;
        s.noise = s.noise * 0.95 + rms * 0.05;
      }
      return;
    }
    s.frames.push(samples);
    if (rms > threshold * 0.8) {
      s.speechFrames += 1;
      s.silentFrames = 0;
    } else s.silentFrames += 1;
    const ended = s.silentFrames * frameS >= END_SILENCE || s.frames.length * frameS >= MAX_UTTERANCE;
    if (!ended) return;
    const chunks = s.frames;
    const enough = s.speechFrames * frameS >= MIN_SPEECH;
    s.frames = [];
    s.speaking = false;
    s.speechFrames = s.silentFrames = s.loudRun = 0;
    if (enough) void finish(chunks, mic.rate, ph === "waiting" && s.wantWake);
  }

  async function finish(chunks: Float32Array[], rate: number, needWake: boolean) {
    const s = session.current;
    if (!s) return;
    s.busy = true;
    const o = optsRef.current;
    try {
      const wav = encodeWav(chunks, rate);
      const r = await upload<Transcript>(`/api/voice/transcribe${needWake ? "?wake=1" : ""}`, wav, "audio/wav");
      if (!session.current) return;
      if (needWake) {
        if (r.status === "wake_only") {
          s.busy = false;
          beginListening(false); // "Hey Jarvis" alone: now listen for the request
          o.onNote("Yes?");
          return;
        }
        if (!r.wake_hit) {
          // Not for Jarvis (no wake word in the sound). Say what was heard, keep waiting.
          if (r.heard && r.status !== "no_audio") setHeard(r.heard);
          return;
        }
      }
      let text = (r.status === "ok" ? r.text : "").trim();
      if (!text && r.heard && (needWake || ph() === "listening" || ph() === "followup")) {
        if ((r.confidence ?? 0) >= WAKE_MIN_CONFIDENCE && (needWake || stripWakeWord(r.heard) !== null)) text = r.heard.trim();
      }
      if (!text) {
        if (r.status !== "no_audio") o.onNote(`I did not catch that${r.heard ? ` (heard “${r.heard}”)` : ""}. Please say it again.`);
        return;
      }
      text = stripWakeWord(text) ?? text;
      if (!text) {
        beginListening(false);
        o.onNote("Yes?");
        return;
      }
      sound("end");
      setHeard(text);
      if (isCommand(text)) {
        o.onDraft(text);
        o.onNote("Commands are never sent by voice. Check the text in the box and press Send.");
        return;
      }
      if (!o.prefs.autoSend) {
        o.onDraft(text);
        o.onNote("Check the text, then press Send.");
        return;
      }
      await sendAndSpeak(text);
      return; // sendAndSpeak decides what comes next
    } catch (e) {
      o.onNote(`Could not read speech: ${errText(e)}`);
    } finally {
      if (session.current) session.current.busy = false;
    }
    // back to the state we were in (waiting / listening continues)
    if (phaseRef.current === "listening" && !needWake) afterRequest();
  }

  const ph = () => phaseRef.current;

  async function sendAndSpeak(text: string) {
    const o = optsRef.current;
    clearTimers();
    setPhase("thinking");
    let res: SendResult = {};
    try {
      res = await o.onSend(text);
    } catch (e) {
      o.onNote(errText(e));
    }
    if (res.handoff) return; // another page took over (Command Center -> Chat)
    if (res.spoken) {
      setPhase("speaking");
      await waitForSpeech(res.chars ?? 0);
    }
    const p = optsRef.current;
    if (p.prefs.followUp && micRef.current && p.blocked === null) {
      setPhase("followup");
      const s = session.current;
      if (s) {
        s.frames = [];
        s.preroll = [];
        s.speaking = false;
        s.wantWake = false;
        s.busy = false;
      }
      later(FOLLOW_UP * 1000, () => {
        if (phaseRef.current === "followup" && !session.current?.speaking) afterRequest();
      });
      return;
    }
    afterRequest();
  }

  // Jarvis speaks on the Mac's speakers; the server knows when the sound ends.
  async function waitForSpeech(chars: number) {
    const cap = Math.min(60, chars / 12 + 3) * 1000;
    const start = Date.now();
    while (Date.now() - start < cap) {
      await new Promise((r) => window.setTimeout(r, 350));
      if (phaseRef.current !== "speaking") return; // interrupted
      try {
        const r = await api<{ speaking: boolean }>("/api/voice/speaking");
        if (!r.speaking) return;
      } catch {
        return;
      }
    }
  }

  // ---- public actions ----

  /** The mic button. Listening -> finish now. Speaking -> interrupt. Otherwise start a request. */
  async function tap() {
    const p = phaseRef.current;
    const o = optsRef.current;
    if (o.blocked === "stop") return o.onNote("Emergency stop is on.");
    if (o.blocked === "approval") return o.onNote("An approval is waiting. Approvals are click-only.");
    if (p === "speaking") {
      await post("/api/voice/stop").catch(() => undefined);
      setPhase("thinking"); // waitForSpeech sees the change and ends
      return;
    }
    if (p === "listening") {
      const s = session.current;
      const mic = micRef.current;
      if (s && mic && s.speaking && s.frames.length) {
        const chunks = s.frames;
        s.frames = [];
        s.speaking = false;
        void finish(chunks, mic.rate, false);
      } else afterRequest();
      return;
    }
    if (p === "thinking") return;
    if (!(await openMic())) return;
    beginListening(false);
  }

  /** A request that arrived from elsewhere (the Command Center's stage): run it through the
   * same thinking -> speaking -> follow-up path, with the mic open when hands-free is on. */
  async function submit(text: string) {
    const o = optsRef.current;
    if (o.handsFree && o.prefs.mode !== "ptt" && o.blocked === null && !micRef.current) await openMic();
    setHeard(text);
    await sendAndSpeak(text);
  }

  /** Stop everything and close the microphone. */
  function stopAll() {
    clearTimers();
    closeMic();
    setPhase("off");
    setHeard("");
  }

  // Hands-free switch and blocking (approval / emergency stop).
  useEffect(() => {
    const o = opts;
    if (o.blocked !== null) {
      if (phaseRef.current !== "off") {
        clearTimers();
        closeMic();
        setPhase(o.blocked === "stop" ? "off" : "paused");
      }
      return;
    }
    if (o.handsFree && o.prefs.mode !== "ptt") {
      if (!micRef.current && phaseRef.current !== "thinking" && phaseRef.current !== "speaking") {
        void openMic().then((ok) => {
          if (ok) beginListening(o.prefs.mode === "wake");
        });
      } else if (phaseRef.current === "waiting" || phaseRef.current === "paused") {
        beginListening(o.prefs.mode === "wake");
      }
    } else if (phaseRef.current === "waiting" || phaseRef.current === "paused") {
      stopAll();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [opts.handsFree, opts.prefs.mode, opts.blocked]);

  // Leaving the page releases the microphone.
  useEffect(() => () => stopAll(), []); // eslint-disable-line react-hooks/exhaustive-deps

  return { phase, heard, analyserRef, tap, submit, stopAll, micOpen: micRef.current !== null };
}

export function phaseWord(phase: VoicePhase, mode: VoiceMode): string {
  switch (phase) {
    case "waiting":
      return mode === "conversation" ? "Listening" : "Say “Hey Jarvis”";
    case "listening":
      return "Listening…";
    case "thinking":
      return "Thinking…";
    case "speaking":
      return "Speaking";
    case "followup":
      return "Listening (follow-up)";
    case "paused":
      return "Paused";
    default:
      return mode === "ptt" ? "Tap to talk" : "Voice off";
  }
}

export function phaseHint(phase: VoicePhase, mode: VoiceMode): string {
  switch (phase) {
    case "waiting":
      return mode === "conversation" ? "Just talk. Tap to stop." : "The mic is open. Say “Hey Jarvis” and your request.";
    case "listening":
      return "Speak naturally. Tap to send now.";
    case "thinking":
      return "Working on it…";
    case "speaking":
      return "Tap to interrupt.";
    case "followup":
      return "Ask the next thing; no wake word needed.";
    case "paused":
      return "An approval is waiting. Approvals are click-only.";
    default:
      return mode === "ptt" ? "Tap the mic and speak." : "Turn on hands-free, or tap the mic.";
  }
}
