"use client";

import { useEffect, useRef, useState } from "react";
import { ApiError, post } from "@/lib/api";
import { errText } from "@/lib/hooks";

type Line = { who: "user" | "jarvis" | "system"; text: string };
type Session = { id: string; provider: string; model: string };

const KEY = "jarvis_chat";

function loadSaved(): { session: Session | null; lines: Line[] } {
  try {
    const raw = sessionStorage.getItem(KEY);
    if (raw) return JSON.parse(raw);
  } catch {
    /* ignore */
  }
  return { session: null, lines: [] };
}

export default function ChatTab() {
  const [session, setSession] = useState<Session | null>(null);
  const [lines, setLines] = useState<Line[]>([]);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const logRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const saved = loadSaved();
    setSession(saved.session);
    setLines(saved.lines);
  }, []);

  useEffect(() => {
    try {
      sessionStorage.setItem(KEY, JSON.stringify({ session, lines: lines.slice(-200) }));
    } catch {
      /* ignore */
    }
    logRef.current?.scrollTo({ top: logRef.current.scrollHeight });
  }, [session, lines]);

  async function start(): Promise<Session> {
    const s = await post<Session>("/api/chat/sessions");
    setSession(s);
    setLines((l) => [...l, { who: "system", text: `New chat (${s.provider}/${s.model})` }]);
    return s;
  }

  async function send() {
    const msg = text.trim();
    if (!msg || busy) return;
    setBusy(true);
    setError("");
    setText("");
    try {
      let s = session ?? (await start());
      setLines((l) => [...l, { who: "user", text: msg }]);
      let res: { reply: string; kind: string };
      try {
        res = await post(`/api/chat/sessions/${s.id}/messages`, { text: msg });
      } catch (e) {
        if (e instanceof ApiError && e.status === 404) {
          s = await start(); // the old chat expired on the server
          res = await post(`/api/chat/sessions/${s.id}/messages`, { text: msg });
        } else throw e;
      }
      setLines((l) => [...l, { who: res.kind === "command" ? "system" : "jarvis", text: res.reply }]);
    } catch (e) {
      setError(errText(e));
      setText(msg); // keep the message so it can be sent again
    } finally {
      setBusy(false);
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

  return (
    <section className="panel">
      <div className="row">
        <h2 className="grow">Chat</h2>
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
            <code>/remember-private …</code> saves one that never goes to the cloud. Actions that need approval
            appear above the chat.
          </p>
        )}
        {lines.map((l, i) => (
          <div key={i} className={`msg ${l.who}`}>
            {l.text}
          </div>
        ))}
        {busy && <div className="msg system">Jarvis is working…</div>}
      </div>
      {error && <div className="error">{error}</div>}
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
        <button className="primary" onClick={send} disabled={busy || !text.trim()}>
          Send
        </button>
      </div>
    </section>
  );
}
