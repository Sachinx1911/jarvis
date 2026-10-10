"use client";

import { useEffect, useRef, useState } from "react";
import { ApiError, api, post, upload } from "@/lib/api";
import { micSupported, Recording, startRecording } from "@/lib/audio";
import { errText } from "@/lib/hooks";

type Line = { who: "user" | "jarvis" | "system"; text: string };
type Session = { id: string; provider: string; model: string; project?: string | null };
type Reply = { reply: string; kind: string; project?: string | null; voice?: { spoken: boolean; detail?: string } };

// Something another tab asks the chat to do: send a message (run a skill) or set the project.
export type Inject = { type: "message"; text: string } | { type: "project"; name: string };

const KEY = "jarvis_chat";
const SPEAK_KEY = "jarvis_speak";
export const NOT_INSTALLED = "speech-to-text not installed (run voice setup)";

function loadSaved(): { session: Session | null; lines: Line[]; project: string } {
  try {
    const raw = sessionStorage.getItem(KEY);
    if (raw) return { project: "", ...JSON.parse(raw) };
  } catch {
    /* ignore */
  }
  return { session: null, lines: [], project: "" };
}

export default function ChatTab({ inject, onInjected }: { inject?: Inject | null; onInjected?: () => void }) {
  const [session, setSession] = useState<Session | null>(null);
  const [lines, setLines] = useState<Line[]>([]);
  const [project, setProject] = useState("");
  const [projects, setProjects] = useState<string[]>([]);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [loaded, setLoaded] = useState(false);
  const [speak, setSpeak] = useState(false);
  const [stt, setStt] = useState<{ ready: boolean; detail: string } | null>(null);
  const [recording, setRecording] = useState<Recording | null>(null);
  const [voiceNote, setVoiceNote] = useState("");
  const logRef = useRef<HTMLDivElement>(null);
  const sessionRef = useRef<Session | null>(null);
  sessionRef.current = session;

  useEffect(() => {
    const saved = loadSaved();
    setSession(saved.session);
    setLines(saved.lines);
    setProject(saved.project || saved.session?.project || "");
    try {
      setSpeak(localStorage.getItem(SPEAK_KEY) === "1");
    } catch {
      /* ignore */
    }
    setLoaded(true);
    api<{ items: { name: string }[] }>("/api/projects")
      .then((r) => setProjects(r.items.map((p) => p.name)))
      .catch(() => setProjects([]));
    api<{ stt_ready: boolean; stt_detail: string }>("/api/voice/status")
      .then((r) => setStt({ ready: r.stt_ready, detail: r.stt_detail }))
      .catch(() => setStt({ ready: false, detail: NOT_INSTALLED }));
  }, []);

  useEffect(() => {
    if (!loaded) return;
    try {
      sessionStorage.setItem(KEY, JSON.stringify({ session, lines: lines.slice(-200), project }));
    } catch {
      /* ignore */
    }
    logRef.current?.scrollTo({ top: logRef.current.scrollHeight });
  }, [session, lines, project, loaded]);

  // Requests from other tabs (run a skill, use a project) once the saved chat is loaded.
  useEffect(() => {
    if (!loaded || !inject) return;
    const req = inject;
    onInjected?.();
    if (req.type === "project") chooseProject(req.name);
    else sendText(req.text);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [loaded, inject]);

  function toggleSpeak(on: boolean) {
    setSpeak(on);
    try {
      localStorage.setItem(SPEAK_KEY, on ? "1" : "0");
    } catch {
      /* ignore */
    }
  }

  async function start(): Promise<Session> {
    const s = await post<Session>("/api/chat/sessions", { project: project || null });
    setSession(s);
    setLines((l) => [
      ...l,
      { who: "system", text: `New chat (${s.provider}/${s.model})${s.project ? ` · project ${s.project}` : ""}` },
    ]);
    return s;
  }

  async function chooseProject(name: string) {
    setError("");
    setProject(name);
    const s = sessionRef.current;
    if (!s) return;
    try {
      const r = await post<{ project: string | null }>(`/api/chat/sessions/${s.id}/project`, { project: name || null });
      setSession({ ...s, project: r.project });
      setLines((l) => [...l, { who: "system", text: r.project ? `Active project: ${r.project}` : "No active project." }]);
    } catch (e) {
      if (e instanceof ApiError && e.status === 404) setSession(null); // expired: the next message starts one
      else setError(errText(e));
    }
  }

  async function sendText(msg: string) {
    msg = msg.trim();
    if (!msg) return;
    setBusy(true);
    setError("");
    try {
      let s = sessionRef.current ?? (await start());
      setLines((l) => [...l, { who: "user", text: msg }]);
      let res: Reply;
      try {
        res = await post<Reply>(`/api/chat/sessions/${s.id}/messages`, { text: msg, speak });
      } catch (e) {
        if (e instanceof ApiError && e.status === 404) {
          s = await start(); // the old chat expired on the server
          res = await post<Reply>(`/api/chat/sessions/${s.id}/messages`, { text: msg, speak });
        } else throw e;
      }
      setLines((l) => [...l, { who: res.kind === "command" ? "system" : "jarvis", text: res.reply }]);
      if (res.project !== undefined) {
        setProject(res.project ?? "");
        setSession({ ...s, project: res.project });
      }
      if (res.voice && !res.voice.spoken && res.voice.detail) setVoiceNote(`Not spoken: ${res.voice.detail}`);
      else setVoiceNote("");
    } catch (e) {
      setError(errText(e));
      setText(msg); // keep the message so it can be sent again
    } finally {
      setBusy(false);
    }
  }

  async function send() {
    const msg = text.trim();
    if (!msg || busy) return;
    setText("");
    await sendText(msg);
  }

  async function mic() {
    setVoiceNote("");
    if (recording) {
      setRecording(null);
      setVoiceNote("Reading what you said…");
      try {
        const wav = await recording.stop();
        const r = await upload<{ status: string; text: string; heard: string }>(
          "/api/voice/transcribe",
          wav,
          "audio/wav",
        );
        if (r.status === "ok") {
          setText((t) => (t ? `${t} ${r.text}` : r.text));
          setVoiceNote("Check the text, then press Send.");
        } else if (r.status === "no_audio") setVoiceNote("Nothing was recorded. Try again.");
        else setVoiceNote(`Sorry, I did not catch that${r.heard ? ` (heard "${r.heard}")` : ""}. Please say it again.`);
      } catch (e) {
        setVoiceNote(errText(e));
      }
      return;
    }
    if (stt && !stt.ready) {
      setVoiceNote(stt.detail.startsWith(NOT_INSTALLED) ? stt.detail : `${NOT_INSTALLED}: ${stt.detail}`);
      return;
    }
    if (!micSupported()) {
      setVoiceNote("This browser cannot record audio.");
      return;
    }
    try {
      setRecording(await startRecording());
      setVoiceNote("Listening… press the button again when you are done.");
    } catch (e) {
      setVoiceNote(`Microphone not available: ${errText(e)}`);
    }
  }

  async function end() {
    if (!session) return;
    setBusy(true);
    setError("");
    try {
      const r = await post<{ learned: { action: string; id: string }[]; error?: string }>(
        `/api/chat/sessions/${session.id}/end`,
      );
      const learned = r.learned.filter((x) => ["ADD", "UPDATE", "SUPERSEDE"].includes(x.action));
      setLines((l) => [
        ...l,
        {
          who: "system",
          text: r.error
            ? `Chat ended. Could not save memories: ${r.error}`
            : learned.length
              ? `Chat ended. Learned: ${learned.map((x) => `${x.action.toLowerCase()} ${x.id}`).join(", ")}`
              : "Chat ended. Nothing new to remember.",
        },
      ]);
    } catch (e) {
      setError(errText(e));
    } finally {
      setSession(null);
      setBusy(false);
    }
  }

  const micLabel = recording ? "■ Stop" : "🎤 Talk";
  const micTitle =
    stt && !stt.ready ? NOT_INSTALLED : recording ? "Stop recording and read it" : "Push to talk (speech-to-text on this computer)";

  return (
    <section className="panel">
      <div className="row">
        <h2 className="grow">Chat</h2>
        <label className="small row" title="Its memories and documents come first">
          Project
          <select value={project} onChange={(e) => chooseProject(e.target.value)} aria-label="Active project">
            <option value="">none</option>
            {projects.map((p) => (
              <option key={p} value={p}>
                {p}
              </option>
            ))}
          </select>
        </label>
        <label className="small row" title="Speak replies on this computer's speakers">
          <input type="checkbox" checked={speak} onChange={(e) => toggleSpeak(e.target.checked)} />
          Speak replies
        </label>
        <span className="small muted">{session ? `${session.provider}/${session.model}` : "no chat yet"}</span>
        <button onClick={() => setLines([])} disabled={busy}>
          Clear screen
        </button>
        <button onClick={end} disabled={!session || busy} title="End the chat; Jarvis saves what it learned">
          End chat
        </button>
      </div>
      <div className="chat-log" ref={logRef} aria-live="polite">
        {lines.length === 0 && (
          <p className="muted">
            Write in English or Marathi (मराठी). <code>/remember …</code> saves a memory,{" "}
            <code>/remember-private …</code> saves one that never goes to the cloud. <code>/memory</code>,{" "}
            <code>/project</code>, <code>/record</code>, <code>/note</code> and <code>/help</code> work too. Actions that
            need approval appear above the chat.
          </p>
        )}
        {lines.map((l, i) => (
          <div key={i} className={`msg ${l.who}`} lang={/[ऀ-ॿ]/.test(l.text) ? "mr" : undefined}>
            {l.text}
          </div>
        ))}
        {busy && <div className="msg system">Jarvis is working…</div>}
      </div>
      {error && <div className="error">{error}</div>}
      {voiceNote && <div className="notice small">{voiceNote}</div>}
      <div className="row" style={{ marginTop: 8, alignItems: "flex-end" }}>
        <textarea
          className="grow"
          rows={3}
          value={text}
          placeholder="Message Jarvis (Enter to send, Shift+Enter for a new line)"
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
              e.preventDefault();
              send();
            }
          }}
        />
        <button
          onClick={mic}
          disabled={busy}
          title={micTitle}
          aria-label={micTitle}
          className={recording ? "danger" : stt && !stt.ready ? "muted" : ""}
        >
          {micLabel}
        </button>
        <button className="primary" onClick={send} disabled={busy || !text.trim()}>
          Send
        </button>
      </div>
      {stt && !stt.ready && <div className="small muted">Microphone: {NOT_INSTALLED}. See the Setup tab.</div>}
    </section>
  );
}
