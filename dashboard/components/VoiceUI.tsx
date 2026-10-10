"use client";

// Hands-free display pieces: the state word, a live waveform from the microphone level,
// and the big voice panel used on Home. The listening logic is in voice.ts.

import { RefObject, useEffect, useRef } from "react";
import { Icon } from "./icons";
import { HandsFreeMode, HandsFreePhase } from "./voice";

export type PauseReason = "approval" | "thinking" | "speaking" | null;
export type VoiceSettings = { on: boolean; mode: HandsFreeMode };

// Jarvis speaks a reply on the Mac speakers (not in the browser), so listening waits for
// about (characters / 12) seconds + 1.5 s, at most 60 s, before it starts again.
export function speakingMs(chars: number): number {
  return Math.min(60, chars / 12 + 1.5) * 1000;
}

export function voiceState(phase: HandsFreePhase, paused: PauseReason): { word: string; tone: string } {
  if (phase === "off") return { word: "Off", tone: "off" };
  if (phase === "starting") return { word: "Starting…", tone: "off" };
  if (paused === "approval") return { word: "Paused (approval waiting)", tone: "paused" };
  if (paused === "speaking") return { word: "Speaking", tone: "speaking" };
  if (paused === "thinking" || phase === "transcribing") return { word: "Thinking", tone: "thinking" };
  if (phase === "hearing") return { word: "Hearing you", tone: "hearing" };
  return { word: "Listening", tone: "listening" };
}

export const MODE_LABEL: Record<HandsFreeMode, string> = {
  wake: "Only when I say “Jarvis”",
  conversation: "Conversation",
};

export function ModeSelect({ mode, onMode, disabled }: { mode: HandsFreeMode; onMode: (m: HandsFreeMode) => void; disabled?: boolean }) {
  return (
    <select
      value={mode}
      onChange={(e) => onMode(e.target.value as HandsFreeMode)}
      aria-label="When hands-free sends what it hears"
      disabled={disabled}
    >
      <option value="wake">{MODE_LABEL.wake}</option>
      <option value="conversation">{MODE_LABEL.conversation}</option>
    </select>
  );
}

// Draws the microphone's waveform (AnalyserNode time-domain data). Flat when silent or paused.
export function Waveform({ analyserRef, live, height = 64 }: { analyserRef: RefObject<AnalyserNode | null>; live: boolean; height?: number }) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const liveRef = useRef(live);
  liveRef.current = live;

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const g = canvas.getContext("2d");
    if (!g) return;
    let raf = 0;
    let data = new Float32Array(1024);
    const draw = () => {
      const dpr = window.devicePixelRatio || 1;
      const w = canvas.clientWidth;
      const h = canvas.clientHeight;
      if (canvas.width !== Math.round(w * dpr) || canvas.height !== Math.round(h * dpr)) {
        canvas.width = Math.round(w * dpr);
        canvas.height = Math.round(h * dpr);
      }
      g.setTransform(dpr, 0, 0, dpr, 0, 0);
      g.clearRect(0, 0, w, h);
      const a = analyserRef.current;
      const points = 96;
      const ys: number[] = new Array(points).fill(0);
      if (a && liveRef.current) {
        if (data.length !== a.fftSize) data = new Float32Array(a.fftSize);
        a.getFloatTimeDomainData(data);
        const step = Math.floor(data.length / points);
        for (let i = 0; i < points; i++) {
          let peak = 0;
          for (let j = 0; j < step; j++) peak = Math.max(peak, Math.abs(data[i * step + j]));
          // gentle taper at both ends so the line starts and ends at the centre
          const taper = Math.sin((Math.PI * (i + 0.5)) / points);
          ys[i] = Math.min(1, peak * 4) * taper * (i % 2 ? 1 : -1);
        }
      }
      const grad = g.createLinearGradient(0, 0, w, 0);
      grad.addColorStop(0, "#3b82f6");
      grad.addColorStop(0.5, "#6d7bff");
      grad.addColorStop(1, "#a78bfa");
      g.strokeStyle = grad;
      g.lineWidth = 2.2;
      g.lineJoin = "round";
      g.shadowColor = "rgba(109, 123, 255, 0.65)";
      g.shadowBlur = 12;
      g.beginPath();
      const mid = h / 2;
      for (let i = 0; i < points; i++) {
        const x = (i / (points - 1)) * w;
        const y = mid + ys[i] * (h / 2 - 4);
        if (i === 0) g.moveTo(x, y);
        else {
          const px = ((i - 1) / (points - 1)) * w;
          const py = mid + ys[i - 1] * (h / 2 - 4);
          g.quadraticCurveTo(px, py, (px + x) / 2, (py + y) / 2);
        }
      }
      g.lineTo(w, mid);
      g.stroke();
      raf = window.requestAnimationFrame(draw);
    };
    raf = window.requestAnimationFrame(draw);
    return () => window.cancelAnimationFrame(raf);
  }, [analyserRef]);

  return <canvas ref={canvasRef} className="waveform" style={{ height }} aria-hidden />;
}

export function VoicePanel({
  state,
  hint,
  armed,
  mode,
  onMode,
  onStop,
  analyserRef,
  live,
  chips,
  onChip,
  note,
}: {
  state: { word: string; tone: string };
  hint: string;
  armed: boolean;
  mode: HandsFreeMode;
  onMode: (m: HandsFreeMode) => void;
  onStop: () => void;
  analyserRef: RefObject<AnalyserNode | null>;
  live: boolean;
  chips: string[];
  onChip: (text: string) => void;
  note: string;
}) {
  return (
    <div className="voice-panel" aria-live="polite">
      <div className="voice-main">
        <div className={`voice-orb ${state.tone}`} aria-hidden>
          <Icon name="mic" size={30} />
        </div>
        <div className="voice-center">
          <div className={`voice-title ${state.tone}`}>{state.word === "Listening" ? "Listening…" : state.word}</div>
          <div className="voice-hint">{armed ? "Yes? Say your request." : hint}</div>
          <Waveform analyserRef={analyserRef} live={live} />
        </div>
        <button className="voice-stop" onClick={onStop} aria-label="Stop hands-free and release the microphone">
          <span className="ring" aria-hidden>
            <span className="square" />
          </span>
          <span className="label">Tap to stop</span>
        </button>
      </div>
      <div className="voice-foot">
        <ModeSelect mode={mode} onMode={onMode} />
        <span className="small faint">Voice never approves actions: approvals stay click-only.</span>
      </div>
      {note && <div className="infobox small" style={{ marginBottom: 0 }}>{note}</div>}
      {chips.length > 0 && (
        <div className="chips voice-chips">
          {chips.map((c) => (
            <button key={c} className="chip plain" onClick={() => onChip(c)}>
              {c}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

// Mirrored bar waveform (the look of the Command Center voice stage). Bars follow the live
// microphone level; when idle they settle into a row of faint dots.
export function BarWave({ analyserRef, live, side }: { analyserRef: RefObject<AnalyserNode | null>; live: boolean; side: "left" | "right" }) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const liveRef = useRef(live);
  liveRef.current = live;

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const g = canvas.getContext("2d");
    if (!g) return;
    let raf = 0;
    let data = new Uint8Array(512);
    const smooth: number[] = [];
    const draw = () => {
      const dpr = window.devicePixelRatio || 1;
      const w = canvas.clientWidth;
      const h = canvas.clientHeight;
      if (canvas.width !== Math.round(w * dpr) || canvas.height !== Math.round(h * dpr)) {
        canvas.width = Math.round(w * dpr);
        canvas.height = Math.round(h * dpr);
      }
      g.setTransform(dpr, 0, 0, dpr, 0, 0);
      g.clearRect(0, 0, w, h);
      const gap = 7;
      const n = Math.max(8, Math.floor(w / gap));
      const a = analyserRef.current;
      const levels = new Array(n).fill(0);
      if (a && liveRef.current) {
        if (data.length !== a.frequencyBinCount) data = new Uint8Array(a.frequencyBinCount);
        a.getByteFrequencyData(data);
        const usable = Math.floor(data.length * 0.6); // speech lives in the lower bins
        for (let i = 0; i < n; i++) {
          // bar 0 sits next to the orb; it gets the strongest (lowest) bins
          const k = Math.floor((i / n) * usable);
          levels[i] = Math.pow(data[k] / 255, 1.4);
        }
      }
      const mid = h / 2;
      for (let i = 0; i < n; i++) {
        const prev = smooth[i] ?? 0;
        const target = levels[i] * (1 - i / (n * 1.15));
        smooth[i] = prev + (target - prev) * (target > prev ? 0.55 : 0.12);
        const x = side === "left" ? w - 4 - i * gap : 4 + i * gap;
        const bar = Math.max(2, smooth[i] * (h - 8));
        const fade = 1 - i / n;
        g.fillStyle = `rgba(${Math.round(59 + 40 * fade)}, ${Math.round(130 + 60 * fade)}, 255, ${0.25 + 0.75 * fade})`;
        g.shadowColor = "rgba(59, 130, 246, 0.8)";
        g.shadowBlur = smooth[i] > 0.05 ? 8 : 0;
        g.fillRect(x - 1, mid - bar / 2, 2, bar);
      }
      raf = window.requestAnimationFrame(draw);
    };
    raf = window.requestAnimationFrame(draw);
    return () => window.cancelAnimationFrame(raf);
  }, [analyserRef, side]);

  return <canvas ref={canvasRef} className="stage-bars" aria-hidden />;
}

// The big voice stage on the Command Center: orb in the middle, waveform on both sides,
// the state word under it, and a red stop button. Off: the orb is a button that starts listening.
export function VoiceStage({
  on,
  state,
  hint,
  armed,
  analyserRef,
  live,
  onStart,
  onStop,
  disabled,
  disabledWhy,
  note,
}: {
  note?: string;
  on: boolean;
  state: { word: string; tone: string };
  hint: string;
  armed: boolean;
  analyserRef: RefObject<AnalyserNode | null>;
  live: boolean;
  onStart: () => void;
  onStop: () => void;
  disabled?: boolean;
  disabledWhy?: string;
}) {
  const title = !on ? "Tap to talk" : state.word === "Listening" ? "Listening…" : state.word;
  return (
    <div className={`voice-stage ${on ? state.tone : "off"}`} aria-live="polite">
      <div className="stage-row">
        <BarWave analyserRef={analyserRef} live={on && live} side="left" />
        <button
          className={`stage-orb ${on ? state.tone : "off"}`}
          onClick={on ? onStop : onStart}
          disabled={!on && disabled}
          title={!on && disabled ? disabledWhy : on ? "Stop listening" : "Start hands-free listening"}
          aria-label={on ? "Stop listening" : "Start hands-free listening"}
        >
          <Icon name="mic" size={44} />
        </button>
        <BarWave analyserRef={analyserRef} live={on && live} side="right" />
      </div>
      <div className={`stage-title ${on ? state.tone : ""}`}>{title}</div>
      <div className="stage-hint">
        {!on ? (disabled ? disabledWhy : hint) : armed ? "Yes? Say your request." : "Speak naturally. Tap to stop."}
      </div>
      {on && note && <div className="stage-note">{note}</div>}
      {on && (
        <button className="stage-stop" onClick={onStop} aria-label="Stop hands-free and release the microphone">
          <span className="square" aria-hidden />
        </button>
      )}
    </div>
  );
}
