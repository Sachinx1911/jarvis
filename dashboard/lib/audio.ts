// Microphone recording for push-to-talk in Chat.
// MediaRecorder gives compressed audio (webm/opus or mp4); the Web Audio API decodes it and
// resamples to 16 kHz mono, and we send a plain 16-bit WAV. So the server needs no audio
// decoder: the existing speech-to-text engine reads the WAV directly.

export type Recording = { stop: () => Promise<ArrayBuffer>; cancel: () => void };

export function micSupported(): boolean {
  return typeof window !== "undefined" && !!navigator.mediaDevices?.getUserMedia && typeof MediaRecorder !== "undefined";
}

// The microphone without the browser's call processing. Echo cancellation makes macOS turn
// down every other sound while the microphone is open ("ducking"), so Jarvis's spoken replies
// got quieter and louder. Jarvis speaks through the Mac's speakers, not the page, so echo
// cancellation could not help anyway. The level is evened out in toWav16k instead.
export const RAW_MIC: MediaTrackConstraints = { echoCancellation: false, noiseSuppression: false, autoGainControl: false };

export async function startRecording(): Promise<Recording> {
  const stream = await navigator.mediaDevices.getUserMedia({ audio: RAW_MIC });
  const rec = new MediaRecorder(stream);
  const chunks: Blob[] = [];
  rec.ondataavailable = (e) => {
    if (e.data.size > 0) chunks.push(e.data);
  };
  const done = new Promise<Blob>((resolve) => {
    rec.onstop = () => {
      stream.getTracks().forEach((t) => t.stop());
      resolve(new Blob(chunks, { type: rec.mimeType }));
    };
  });
  rec.start();
  return {
    stop: async () => {
      if (rec.state !== "inactive") rec.stop();
      return toWav16k(await done);
    },
    cancel: () => {
      if (rec.state !== "inactive") rec.stop();
      stream.getTracks().forEach((t) => t.stop());
    },
  };
}

const RATE = 16000;

export async function toWav16k(blob: Blob): Promise<ArrayBuffer> {
  const ctx = new AudioContext();
  let decoded: AudioBuffer;
  try {
    decoded = await ctx.decodeAudioData(await blob.arrayBuffer());
  } finally {
    ctx.close();
  }
  const frames = Math.max(1, Math.ceil(decoded.duration * RATE));
  const offline = new OfflineAudioContext(1, frames, RATE); // 1 channel: the browser mixes down
  const src = offline.createBufferSource();
  src.buffer = decoded;
  src.connect(offline.destination);
  src.start();
  const rendered = await offline.startRendering();
  return encodeWav(normalize(rendered.getChannelData(0)), RATE);
}

// Brings quiet speech up to a steady level (peak about 0.9) so speech-to-text hears it well.
// Near-silence is left alone so background noise is not blown up.
function normalize(samples: Float32Array): Float32Array {
  let peak = 0;
  for (let i = 0; i < samples.length; i++) peak = Math.max(peak, Math.abs(samples[i]));
  if (peak < 0.01 || peak >= 0.9) return samples;
  const gain = Math.min(0.9 / peak, 12);
  const out = new Float32Array(samples.length);
  for (let i = 0; i < samples.length; i++) out[i] = samples[i] * gain;
  return out;
}

function encodeWav(samples: Float32Array, rate: number): ArrayBuffer {
  const buf = new ArrayBuffer(44 + samples.length * 2);
  const v = new DataView(buf);
  const str = (o: number, s: string) => [...s].forEach((c, i) => v.setUint8(o + i, c.charCodeAt(0)));
  str(0, "RIFF");
  v.setUint32(4, 36 + samples.length * 2, true);
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
  v.setUint32(40, samples.length * 2, true);
  for (let i = 0; i < samples.length; i++) {
    const s = Math.max(-1, Math.min(1, samples[i]));
    v.setInt16(44 + i * 2, s < 0 ? s * 0x8000 : s * 0x7fff, true);
  }
  return buf;
}
