"use client";

// Voice display pieces shared by the Command Center and Chat: the live waveform, the big voice
// stage, the compact voice dock in the chat composer, and one settings panel for every voice
// option. The logic lives in voice.ts (useVoice).

import { RefObject, useEffect, useRef, useState } from "react";
import { Icon } from "./icons";
import { MODE_HELP, MODE_LABEL, phaseHint, phaseWord, VoiceMode, VoicePhase, VoicePrefs } from "./voice";

export function toneOf(phase: VoicePhase): string {
  return phase === "off" ? "off" : phase;
}

// Mirrored bar waveform (the Command Center voice stage). Bars follow the live microphone level;
// when idle they settle into a row of faint dots.
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

// A small single-line waveform for the chat dock.
export function LineWave({ analyserRef, live, height = 26 }: { analyserRef: RefObject<AnalyserNode | null>; live: boolean; height?: number }) {
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
      const points = 48;
      const ys = new Array(points).fill(0);
      if (a && liveRef.current) {
        if (data.length !== a.fftSize) data = new Float32Array(a.fftSize);
        a.getFloatTimeDomainData(data);
        const step = Math.floor(data.length / points);
        for (let i = 0; i < points; i++) {
          let peak = 0;
          for (let j = 0; j < step; j++) peak = Math.max(peak, Math.abs(data[i * step + j]));
          ys[i] = Math.min(1, peak * 4) * Math.sin((Math.PI * (i + 0.5)) / points) * (i % 2 ? 1 : -1);
        }
      }
      g.strokeStyle = "#5b9bff";
      g.lineWidth = 2;
      g.beginPath();
      for (let i = 0; i < points; i++) {
        const x = (i / (points - 1)) * w;
        const y = h / 2 + ys[i] * (h / 2 - 3);
        if (i === 0) g.moveTo(x, y);
        else g.lineTo(x, y);
      }
      g.stroke();
      raf = window.requestAnimationFrame(draw);
    };
    raf = window.requestAnimationFrame(draw);
    return () => window.cancelAnimationFrame(raf);
  }, [analyserRef]);
  return <canvas ref={canvasRef} className="waveform" style={{ height }} aria-hidden />;
}

/** One panel for every voice option (mode, speak replies, auto-send, follow-up, sounds). */
export function VoiceSettings({ prefs, onChange, onClose }: { prefs: VoicePrefs; onChange: (p: VoicePrefs) => void; onClose: () => void }) {
  const set = (patch: Partial<VoicePrefs>) => onChange({ ...prefs, ...patch });
  const Row = ({ label, help, k }: { label: string; help: string; k: keyof Omit<VoicePrefs, "mode"> }) => (
    <label className="vs-row">
      <span className="vs-text">
        <strong>{label}</strong>
        <span className="small muted">{help}</span>
      </span>
      <span className="switch">
        <input type="checkbox" checked={prefs[k]} onChange={(e) => set({ [k]: e.target.checked } as Partial<VoicePrefs>)} />
        <span className="track" aria-hidden />
      </span>
    </label>
  );
  return (
    <div className="popover voice-settings" role="dialog" aria-label="Voice settings">
      <div className="popover-title">
        <span className="grow">Voice</span>
        <button className="icon-btn sm ghost" onClick={onClose} aria-label="Close">
          <Icon name="x" size={14} />
        </button>
      </div>
      <div className="vs-modes" role="radiogroup" aria-label="How Jarvis listens">
        {(["ptt", "wake", "conversation"] as VoiceMode[]).map((m) => (
          <button key={m} className="vs-mode" aria-pressed={prefs.mode === m} onClick={() => set({ mode: m })}>
            <strong>{MODE_LABEL[m]}</strong>
            <span className="small muted">{MODE_HELP[m]}</span>
          </button>
        ))}
      </div>
      <Row label="Speak replies" help="Jarvis reads replies aloud on this Mac's speakers." k="speak" />
      <Row label="Auto-send" help="Send what you said as soon as it is understood." k="autoSend" />
      <Row label="Follow-up listening" help="After a reply, listen 5 seconds more without a wake word." k="followUp" />
      <Row label="Sounds" help="A short tone when listening starts and ends." k="sounds" />
      <p className="small faint" style={{ margin: "8px 0 0" }}>
        Voice never approves actions, never sends “/” commands, and nothing is recorded in the browser.
      </p>
    </div>
  );
}

/** The mic button with its state colour, used in the stage and the dock. */
export function MicButton({ phase, size = 44, onClick, disabled, title }: { phase: VoicePhase; size?: number; onClick: () => void; disabled?: boolean; title?: string }) {
  const icon = phase === "speaking" ? "stop" : phase === "listening" || phase === "followup" ? "check" : "mic";
  return (
    <button className={`mic-main ${toneOf(phase)}`} style={{ width: size, height: size }} onClick={onClick} disabled={disabled} title={title} aria-label={title}>
      <Icon name={icon} size={Math.round(size * 0.46)} />
    </button>
  );
}

/** The big voice stage on the Command Center. */
export function VoiceStage({
  phase,
  mode,
  heard,
  note,
  analyserRef,
  onTap,
  handsFree,
  onHandsFree,
  disabled,
  disabledWhy,
}: {
  phase: VoicePhase;
  mode: VoiceMode;
  heard: string;
  note: string;
  analyserRef: RefObject<AnalyserNode | null>;
  onTap: () => void;
  handsFree: boolean;
  onHandsFree: (on: boolean) => void;
  disabled?: boolean;
  disabledWhy?: string;
}) {
  const live = phase === "waiting" || phase === "listening" || phase === "followup";
  const title = phase === "off" && disabled ? "Voice unavailable" : phaseWord(phase, mode);
  const hint = phase === "off" && disabled ? disabledWhy ?? "" : phaseHint(phase, mode);
  return (
    <div className={`voice-stage ${toneOf(phase)}`} aria-live="polite">
      <div className="stage-row">
        <BarWave analyserRef={analyserRef} live={live} side="left" />
        <button className={`stage-orb ${toneOf(phase)}`} onClick={onTap} disabled={disabled} title={title} aria-label={title}>
          <Icon name={phase === "speaking" ? "stop" : "mic"} size={44} />
        </button>
        <BarWave analyserRef={analyserRef} live={live} side="right" />
      </div>
      <div className={`stage-title ${toneOf(phase)}`}>{title}</div>
      <div className="stage-hint">{hint}</div>
      {heard && phase !== "off" && <div className="stage-heard">“{heard}”</div>}
      {note && <div className="stage-note">{note}</div>}
      <div className="stage-foot">
        {mode !== "ptt" && (
          <label className="switch field-inline" title="Keep the microphone open">
            <input type="checkbox" checked={handsFree} disabled={disabled} onChange={(e) => onHandsFree(e.target.checked)} />
            <span className="track" aria-hidden />
            Hands-free ({MODE_LABEL[mode]})
          </label>
        )}
        {phase !== "off" && (
          <span className="mic-live">
            <span className="dot bad pulse" /> mic on
          </span>
        )}
      </div>
    </div>
  );
}

/** The compact voice row in the chat composer. */
export function VoiceDock({
  phase,
  mode,
  prefs,
  onPrefs,
  analyserRef,
  onTap,
  handsFree,
  onHandsFree,
  disabled,
  disabledWhy,
}: {
  phase: VoicePhase;
  mode: VoiceMode;
  prefs: VoicePrefs;
  onPrefs: (p: VoicePrefs) => void;
  analyserRef: RefObject<AnalyserNode | null>;
  onTap: () => void;
  handsFree: boolean;
  onHandsFree: (on: boolean) => void;
  disabled?: boolean;
  disabledWhy?: string;
}) {
  const [open, setOpen] = useState(false);
  const live = phase === "waiting" || phase === "listening" || phase === "followup";
  return (
    <div className="voice-dock">
      <MicButton phase={phase} size={40} onClick={onTap} disabled={disabled} title={disabled ? disabledWhy : phaseHint(phase, mode)} />
      <span className={`hf-state ${toneOf(phase)}`}>{phase === "off" && disabled ? disabledWhy : phaseWord(phase, mode)}</span>
      {phase !== "off" && (
        <span style={{ width: 120 }}>
          <LineWave analyserRef={analyserRef} live={live} />
        </span>
      )}
      {mode !== "ptt" && (
        <label className="switch field-inline" title="Keep the microphone open">
          <input type="checkbox" checked={handsFree} disabled={disabled} onChange={(e) => onHandsFree(e.target.checked)} />
          <span className="track" aria-hidden />
          Hands-free
        </label>
      )}
      {phase !== "off" && (
        <span className="mic-live">
          <span className="dot bad pulse" /> mic on
        </span>
      )}
      <span className="grow" />
      <span style={{ position: "relative" }}>
        <button className="ghost sm" onClick={() => setOpen((o) => !o)} aria-expanded={open} title="Voice settings">
          <Icon name="sliders" size={14} /> Voice: {MODE_LABEL[mode]}
        </button>
        {open && <VoiceSettings prefs={prefs} onChange={onPrefs} onClose={() => setOpen(false)} />}
      </span>
    </div>
  );
}
