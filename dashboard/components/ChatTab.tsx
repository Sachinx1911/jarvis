"use client";

import { useEffect, useRef, useState } from "react";
import { ApiError, api, post } from "@/lib/api";
import { errText } from "@/lib/hooks";
import { Icon } from "./icons";
import { notReadyText, SendResult, useStt, useVoice, VoicePrefs } from "./voice";
import { VoiceDock } from "./VoiceUI";

type Line = { who: "user" | "jarvis" | "system"; text: string; turn_id?: number | null };
type Session = { id: string; provider: string; model: string; project?: string | null };
type Reply = {
  reply: string;
  kind: string;
  project?: string | null;
  voice?: { spoken: boolean; detail?: string };
  turn_id?: number | null;
};
// What was in the model's context for one reply ("Why did Jarvis say that?").
type TurnContext = {
  turn_id: number;
  session_id: string;
  ts: string;
  memories: { id: string; name: string; summary_en: string; type: string; sensitivity: string; masked: boolean; status: string }[];
  excerpts: { message_id: string; session_id: string; ts: string; role: string; text: string }[];
  withheld: number;
};

// Something another tab asks the chat to do: send a message (run a skill) or set the project.
export type Inject = { type: "message"; text: string } | { type: "project"; name: string };

const KEY = "jarvis_chat";
export { NOT_INSTALLED } from "./voice";

const COMMANDS = ["/remember", "/remember-private", "/memory", "/project", "/repeat", "/why", "/note", "/help"];
const STARTERS = ["What is on my plate today?", "आज काय काम आहे?", "Summarise my open tasks", "Remind me at 6 pm to call home"];

function loadSaved(): { session: Session | null; lines: Line[]; project: string } {
  try {
    const raw = sessionStorage.getItem(KEY);
    if (raw) return { project: "", ...JSON.parse(raw) };
  } catch {
    /* ignore */
  }
  return { session: null, lines: [], project: "" };
}

export default function ChatTab({
  inject,
  onInjected,
  prefs,
  onPrefs,
  handsFree,
  onHandsFree,
  pendingApprovals = 0,
  stopEngaged = false,
}: {
  inject?: Inject | null;
  onInjected?: () => void;
  prefs: VoicePrefs;
  onPrefs: (p: VoicePrefs) => void;
  handsFree: boolean;
  onHandsFree: (on: boolean) => void;
  pendingApprovals?: number;
  stopEngaged?: boolean;
}) {
  const [session, setSession] = useState<Session | null>(null);
  const [lines, setLines] = useState<Line[]>([]);
  const [project, setProject] = useState("");
  const [projects, setProjects] = useState<string[]>([]);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [loaded, setLoaded] = useState(false);
  const [note, setNote] = useState("");
  const [menu, setMenu] = useState(false);
  const logRef = useRef<HTMLDivElement>(null);
  const sessionRef = useRef<Session | null>(null);
  sessionRef.current = session;
  const prefsRef = useRef(prefs);
  prefsRef.current = prefs;
  const stt = useStt();
  const sttMissing = stt !== null && !stt.ready;
  const voiceRef = useRef<{ submit: (t: string) => Promise<void> } | null>(null);

  useEffect(() => {
    const saved = loadSaved();
    setSession(saved.session);
    setLines(saved.lines);
    setProject(saved.project || saved.session?.project || "");
    setLoaded(true);
    api<{ items: { name: string }[] }>("/api/projects")
      .then((r) => setProjects(r.items.map((p) => p.name)))
      .catch(() => setProjects([]));
  }, []);

  useEffect(() => {
    if (!loaded) return;
    try {
      sessionStorage.setItem(KEY, JSON.stringify({ session, lines: lines.slice(-200), project }));
    } catch {
      /* ignore */
    }
    logRef.current?.scrollTo({ top: logRef.current.scrollHeight });
  }, [session, lines, project, loaded, busy]);

  // Requests from other tabs (run a skill, use a project, a voice request from the Command
  // Center) once the saved chat is loaded.
  useEffect(() => {
    if (!loaded || !inject) return;
    const req = inject;
    onInjected?.();
    if (req.type === "project") chooseProject(req.name);
    else if (voiceRef.current) void voiceRef.current.submit(req.text);
    else void sendText(req.text);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [loaded, inject]);

  const voice = useVoice({
    prefs,
    handsFree,
    blocked: stopEngaged ? "stop" : pendingApprovals > 0 ? "approval" : null,
    stt,
    onSend: (t) => sendText(t),
    onDraft: (t) => setText(t),
    onNote: (t) => setNote(t),
  });
  voiceRef.current = voice;

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

  async function sendText(msg: string): Promise<SendResult> {
    msg = msg.trim();
    if (!msg) return {};
    setBusy(true);
    setError("");
    setNote("");
    const speak = prefsRef.current.speak;
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
      setLines((l) => [
        ...l,
        { who: res.kind === "command" ? "system" : "jarvis", text: res.reply, turn_id: res.turn_id ?? null },
      ]);
      if (res.project !== undefined) {
        setProject(res.project ?? "");
        setSession({ ...s, project: res.project });
      }
      if (res.voice && !res.voice.spoken && res.voice.detail) setNote(`Not spoken: ${res.voice.detail}`);
      return { spoken: !!res.voice?.spoken, chars: res.reply.length };
    } catch (e) {
      setError(errText(e));
      setText(msg); // keep the message so it can be sent again
      return {};
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

  const disabledWhy = stopEngaged ? "Emergency stop is on" : sttMissing && stt ? notReadyText(stt) : "";

  return (
    <section className="panel chat">
      <div className="chat-toolbar">
        <label className="field-inline" title="Its memories and documents come first">
          <Icon name="folder" size={15} />
          <select value={project} onChange={(e) => chooseProject(e.target.value)} aria-label="Active project">
            <option value="">No project</option>
            {projects.map((p) => (
              <option key={p} value={p}>
                {p}
              </option>
            ))}
          </select>
        </label>
        <span className="grow" />
        <span className="pill outline small">{session ? `${session.provider} · ${session.model}` : "no chat yet"}</span>
        <span style={{ position: "relative" }}>
          <button className="icon-btn sm ghost" onClick={() => setMenu((m) => !m)} aria-expanded={menu} aria-label="More" title="More">
            <Icon name="menu" size={16} />
          </button>
          {menu && (
            <div className="popover" style={{ right: 0, top: "calc(100% + 6px)", minWidth: 200 }}>
              <button className="popover-item" onClick={() => { setLines([]); setMenu(false); }} disabled={busy}>
                <Icon name="refresh" size={15} /> Clear screen
              </button>
              <button className="popover-item" onClick={() => { void end(); setMenu(false); }} disabled={!session || busy} title="End the chat; Jarvis saves what it learned">
                <Icon name="check" size={15} /> End chat (save memories)
              </button>
            </div>
          )}
        </span>
      </div>

      <div className="chat-log" ref={logRef} aria-live="polite">
        {lines.length === 0 && (
          <div className="chat-empty">
            <span className="tile lg blue">
              <Icon name="chat" size={26} />
            </span>
            <h2>Talk to Jarvis</h2>
            <p className="muted">Write or speak in English or मराठी. Actions that need your approval appear above the chat.</p>
            <div className="chips" style={{ justifyContent: "center", marginTop: 16 }}>
              {STARTERS.map((s) => (
                <button key={s} className="chip plain" onClick={() => sendText(s)} disabled={busy}>
                  {s}
                </button>
              ))}
            </div>
            <details>
              <summary>Chat commands</summary>
              <p>
                <code>/remember …</code> saves a memory, <code>/remember-private …</code> saves one that never goes to the
                cloud. <code>/memory</code>, <code>/project</code>, <code>/repeat</code>, <code>/why</code>,{" "}
                <code>/note</code> and <code>/help</code> work too.
              </p>
            </details>
          </div>
        )}
        {lines.map((l, i) => {
          const lang = /[ऀ-ॿ]/.test(l.text) ? "mr" : undefined;
          if (l.who === "system")
            return (
              <div key={i} className="msg system" lang={lang}>
                {l.text}
              </div>
            );
          const bubble = (
            <div className={`msg ${l.who}`} lang={lang}>
              {l.text}
            </div>
          );
          return (
            <div key={i} className={`msg-line ${l.who}`}>
              {l.who === "jarvis" && (
                <span className="avatar" aria-hidden>
                  J
                </span>
              )}
              {l.who === "jarvis" && l.turn_id != null ? (
                <div className="msg-wrap">
                  {bubble}
                  <Why turnId={l.turn_id} />
                </div>
              ) : (
                bubble
              )}
            </div>
          );
        })}
        {busy && (
          <div className="msg-line jarvis">
            <span className="avatar" aria-hidden>
              J
            </span>
            <span className="typing">
              <span className="dots" aria-hidden>
                <span />
                <span />
                <span />
              </span>
              Jarvis is working…
            </span>
          </div>
        )}
      </div>

      <div className="composer">
        <div className="notes">
          {error && <div className="error">{error}</div>}
          {note && <div className="infobox small">{note}</div>}
        </div>
        <div className="composer-box">
          <textarea
            rows={2}
            value={text}
            placeholder="Message Jarvis… (Enter to send, Shift+Enter for a new line)"
            onChange={(e) => setText(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
                e.preventDefault();
                send();
              }
            }}
          />
          <div className="composer-actions">
            <div className="chips">
              {COMMANDS.map((c) => (
                <button key={c} className="chip" onClick={() => setText((t) => (t ? t : `${c} `))} title={`Start with ${c}`}>
                  {c}
                </button>
              ))}
            </div>
            <button className="primary" onClick={send} disabled={busy || !text.trim()} aria-label="Send">
              <Icon name="send" size={16} /> Send
            </button>
          </div>
        </div>
        <VoiceDock
          phase={voice.phase}
          mode={prefs.mode}
          prefs={prefs}
          onPrefs={onPrefs}
          analyserRef={voice.analyserRef}
          onTap={() => {
            setNote("");
            void voice.tap();
          }}
          handsFree={handsFree}
          onHandsFree={(on) => {
            setNote("");
            onHandsFree(on);
          }}
          disabled={stopEngaged || sttMissing}
          disabledWhy={disabledWhy}
        />
      </div>
    </section>
  );
}

// "Why?" under a Jarvis reply: the memories and past-chat excerpts that were in its context.
function Why({ turnId }: { turnId: number }) {
  const [open, setOpen] = useState(false);
  const [data, setData] = useState<TurnContext | null>(null);
  const [error, setError] = useState("");

  async function toggle() {
    const next = !open;
    setOpen(next);
    if (!next || data) return;
    setError("");
    try {
      setData(await api<TurnContext>(`/api/chat/turns/${turnId}`));
    } catch (e) {
      setError(errText(e));
    }
  }

  const empty = data && data.memories.length === 0 && data.excerpts.length === 0;
  return (
    <div className="why">
      <button className="link small" onClick={toggle} aria-expanded={open}>
        {open ? "Hide why" : "Why?"}
      </button>
      {open && (
        <div className="subpanel">
          {error && <div className="error">{error}</div>}
          {!data && !error && <span className="muted">Loading…</span>}
          {empty && <p className="muted">No memories or past-chat excerpts were used for this reply.</p>}
          {data && data.memories.length > 0 && (
            <>
              <h3>Memories used</h3>
              <ul>
                {data.memories.map((m) => (
                  <li key={m.id}>
                    <code>{m.id}</code>{" "}
                    {m.masked ? <span className="muted">(sensitive)</span> : m.summary_en || m.name}
                    {m.status && m.status !== "active" && <span className="muted"> · {m.status}</span>}
                  </li>
                ))}
              </ul>
            </>
          )}
          {data && data.excerpts.length > 0 && (
            <>
              <h3>Past-chat excerpts used</h3>
              <ul>
                {data.excerpts.map((x, i) => (
                  <li key={`${x.message_id}-${i}`}>
                    <span className="muted">
                      {x.ts} · {x.role} · chat {x.session_id}:
                    </span>{" "}
                    {x.text}
                  </li>
                ))}
              </ul>
            </>
          )}
          {data && data.withheld > 0 && (
            <div className="notice small">
              {data.withheld} sensitive item{data.withheld === 1 ? " was" : "s were"} withheld.
            </div>
          )}
        </div>
      )}
    </div>
  );
}
