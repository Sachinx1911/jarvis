// Microphone capture for the dashboard and the Mac app.
//
// One path for everything (push-to-talk and hands-free): raw samples from the microphone at its
// own rate, cut into utterances by a small energy detector, and sent as plain 16-bit mono WAV.
// The server resamples to 16 kHz and evens out the level (jarvis/voice/audio_tools.py), so
// Chrome and the Mac app's WebKit view behave the same. No MediaRecorder, no compression.
//
// The microphone is opened without the browser's call processing: echo cancellation makes macOS
// turn every other sound down while the microphone is open ("ducking"), which made Jarvis's
// spoken replies waver. Jarvis speaks through the Mac's speakers, not the page, so it could not
// help anyway.

export const RAW_MIC: MediaTrackConstraints = { echoCancellation: false, noiseSuppression: false, autoGainControl: false };

export function micSupported(): boolean {
  return typeof window !== "undefined" && !!navigator.mediaDevices?.getUserMedia && typeof AudioContext !== "undefined";
}

export type MicFrame = { samples: Float32Array; rms: number };

/** An open microphone delivering ~43 ms frames (2048 samples at 48 kHz) until closed. */
export class MicCapture {
  private stream: MediaStream | null = null;
  private ctx: AudioContext | null = null;
  private source: MediaStreamAudioSourceNode | null = null;
  private proc: ScriptProcessorNode | null = null; // deprecated but supported everywhere, including WKWebView
  private mute: GainNode | null = null;
  readonly analyser: AnalyserNode;
  readonly rate: number;
  onFrame: ((f: MicFrame) => void) | null = null;

  private constructor(stream: MediaStream, ctx: AudioContext) {
    this.stream = stream;
    this.ctx = ctx;
    this.rate = ctx.sampleRate;
    this.source = ctx.createMediaStreamSource(stream);
    this.analyser = ctx.createAnalyser();
    this.analyser.fftSize = 1024;
    this.source.connect(this.analyser);
    this.proc = ctx.createScriptProcessor(2048, 1, 1);
    this.mute = ctx.createGain();
    this.mute.gain.value = 0; // the processor only runs when it reaches the output; nothing is played
    this.source.connect(this.proc);
    this.proc.connect(this.mute);
    this.mute.connect(ctx.destination);
    this.proc.onaudioprocess = (ev) => {
      const data = new Float32Array(ev.inputBuffer.getChannelData(0));
      let sum = 0;
      for (let i = 0; i < data.length; i++) sum += data[i] * data[i];
      this.onFrame?.({ samples: data, rms: Math.sqrt(sum / data.length) });
    };
  }

  static async open(): Promise<MicCapture> {
    if (!micSupported()) throw new Error("This browser cannot record audio.");
    const stream = await navigator.mediaDevices.getUserMedia({ audio: RAW_MIC });
    const ctx = new AudioContext();
    await ctx.resume().catch(() => undefined);
    return new MicCapture(stream, ctx);
  }

  close(): void {
    if (this.proc) this.proc.onaudioprocess = null;
    this.onFrame = null;
    this.proc?.disconnect();
    this.source?.disconnect();
    this.analyser.disconnect();
    this.mute?.disconnect();
    this.ctx?.close().catch(() => undefined);
    this.stream?.getTracks().forEach((t) => t.stop()); // releases the microphone (the indicator goes off)
    this.proc = this.source = this.mute = null;
    this.ctx = null;
    this.stream = null;
  }
}

/** Float samples at `rate` -> 16-bit mono WAV bytes at the same rate (the server resamples). */
export function encodeWav(chunks: Float32Array[], rate: number): ArrayBuffer {
  const n = chunks.reduce((a, c) => a + c.length, 0);
  const buf = new ArrayBuffer(44 + n * 2);
  const v = new DataView(buf);
  const str = (o: number, s: string) => [...s].forEach((c, i) => v.setUint8(o + i, c.charCodeAt(0)));
  str(0, "RIFF");
  v.setUint32(4, 36 + n * 2, true);
  str(8, "WAVE");
  str(12, "fmt ");
  v.setUint32(16, 16, true);
  v.setUint16(20, 1, true); // PCM
  v.setUint16(22, 1, true); // mono
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

// Two short earcons (Google's guidance: few, consistent, brief). Rising = listening started,
// falling = heard you / done. Played through Web Audio; no sound files.
export function earcon(kind: "start" | "end"): void {
  try {
    const ctx = new AudioContext();
    const notes = kind === "start" ? [660, 880] : [880, 587];
    notes.forEach((hz, i) => {
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.type = "sine";
      osc.frequency.value = hz;
      gain.gain.value = 0.0001;
      osc.connect(gain);
      gain.connect(ctx.destination);
      const t0 = ctx.currentTime + i * 0.09;
      gain.gain.exponentialRampToValueAtTime(0.12, t0 + 0.015);
      gain.gain.exponentialRampToValueAtTime(0.0001, t0 + 0.085);
      osc.start(t0);
      osc.stop(t0 + 0.09);
    });
    window.setTimeout(() => ctx.close().catch(() => undefined), 400);
  } catch {
    /* no audio output: silent is fine */
  }
}
