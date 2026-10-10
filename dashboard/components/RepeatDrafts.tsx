"use client";

// Repeat-this: turn a finished task into a skill + schedule. The draft is shown in full and
// saved only by the Save button on that exact draft (the button sends back the draft's hash).
// Drafts made in chat or on Telegram show up here too. Drafts expire after an hour.

import { useEffect, useRef, useState } from "react";
import { api, post } from "@/lib/api";
import { errText, usePoll } from "@/lib/hooks";

type Summary = {
  id: string;
  source: string;
  origin: "task" | "chat" | "other";
  goal: string;
  when: string;
  skill: string;
  cron: string;
  description: string;
  created_at: string;
  expires_in_s: number;
};
export type RepeatDraft = Summary & {
  skill_text: string;
  schedule: {
    name: string;
    kind: string;
    target: string;
    input: string;
    cron: string;
    timezone: string;
    description: string;
    output: string;
    budget: Record<string, unknown>;
    source: string;
  };
  held_steps: string[];
  skill_exists: boolean;
  show: string;
  draft_sha256: string;
};
type Saved = { saved: boolean; schedule_id: string | null; skill: string; message: string; running_here: boolean };

const minutes = (s: number) => Math.max(0, Math.ceil(s / 60));

// One draft can be open in two places (the task view and the waiting list): when one view
// saves or cancels it, the other closes instead of offering a stale Save button.
const ANSWERED = "jarvis-repeat-answered";
const announce = (id: string, from: string) =>
  window.dispatchEvent(new CustomEvent(ANSWERED, { detail: { id, from } }));

function useSecondsLeft(expiresIn: number): number {
  const [start] = useState(() => Date.now());
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = window.setInterval(() => setNow(Date.now()), 15000);
    return () => window.clearInterval(id);
  }, []);
  return expiresIn - (now - start) / 1000;
}

export function RepeatDraftView({ draft, onDone }: { draft: RepeatDraft; onDone: (message: string) => void }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [me] = useState(() => Math.random().toString(36).slice(2));
  const done = useRef(onDone);
  done.current = onDone;
  const left = useSecondsLeft(draft.expires_in_s);
  const expired = left <= 0;
  const sc = draft.schedule;

  useEffect(() => {
    const on = (e: Event) => {
      const d = (e as CustomEvent<{ id: string; from: string }>).detail;
      if (d?.id === draft.id && d.from !== me) done.current(`Draft ${draft.id} was answered in another view.`);
    };
    window.addEventListener(ANSWERED, on);
    return () => window.removeEventListener(ANSWERED, on);
  }, [draft.id, me]);

  async function save() {
    setBusy(true);
    setError("");
    try {
      const r = await post<Saved>(`/api/repeat/drafts/${encodeURIComponent(draft.id)}/save`, {
        draft_sha256: draft.draft_sha256,
      });
      announce(draft.id, me);
      onDone(
        `Saved skill ${r.skill} and schedule ${r.schedule_id ?? ""}.` +
          (r.running_here ? "" : " It runs while Jarvis runs in the background (the app or jarvis daemon)."),
      );
    } catch (e) {
      setError(errText(e));
    } finally {
      setBusy(false);
    }
  }

  async function cancel() {
    setBusy(true);
    setError("");
    try {
      await post(`/api/repeat/drafts/${encodeURIComponent(draft.id)}/cancel`);
      announce(draft.id, me);
      onDone("Draft cancelled; nothing was saved.");
    } catch (e) {
      setError(errText(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="subpanel" aria-label={`Automation draft ${draft.id}`}>
      <div className="row">
        <h3 className="grow">
          Draft {draft.id} · from {draft.source}
        </h3>
        <span className={`pill ${expired ? "bad" : left < 600 ? "warn" : "off"}`}>
          {expired ? "expired" : `expires in ${minutes(left)} min`}
        </span>
      </div>
      <dl className="kv">
        <dt>Goal</dt>
        <dd>{draft.goal}</dd>
        <dt>Skill</dt>
        <dd>
          {draft.skill}
          {draft.skill_exists && <span className="muted small"> (a skill with this name exists; it is kept as an older version)</span>}
        </dd>
        <dt>When</dt>
        <dd>
          {sc.description} <span className="muted small">({sc.timezone})</span>
        </dd>
        <dt>Cron</dt>
        <dd>
          <code>{sc.cron}</code>
        </dd>
        <dt>Output</dt>
        <dd>{sc.output}</dd>
      </dl>
      {draft.held_steps.length > 0 ? (
        <div className="notice small">
          These steps need approval, so scheduled runs will NOT do them on their own. Each time they are refused,
          queued for you and listed in the run&apos;s receipt:
          <ul>
            {draft.held_steps.map((h) => (
              <li key={h}>{h}</li>
            ))}
          </ul>
        </div>
      ) : (
        <p className="small muted">Every step is read-only or writes new files (T0/T1), so scheduled runs can do all of it.</p>
      )}
      <h3>Skill text (SKILL.md)</h3>
      <pre>{draft.skill_text}</pre>
      <details>
        <summary className="small">Full draft as Jarvis shows it in the terminal (with the next runs)</summary>
        <pre>{draft.show}</pre>
      </details>
      <p className="small">Nothing is saved until you press Save. Save applies to exactly this draft.</p>
      <div className="row">
        <button className="primary" onClick={save} disabled={busy || expired}>
          Save skill and schedule
        </button>
        <button onClick={cancel} disabled={busy}>
          Cancel draft
        </button>
      </div>
      {expired && <div className="notice small">This draft expired. Draft it again to save it.</div>}
      {error && <div className="error">{error}</div>}
    </div>
  );
}

// "Repeat this…" on a completed task.
export function RepeatThis({ taskId, onChange }: { taskId: string; onChange?: () => void }) {
  const [open, setOpen] = useState(false);
  const [when, setWhen] = useState("");
  const [draft, setDraft] = useState<RepeatDraft | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [msg, setMsg] = useState("");

  async function propose(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    setMsg("");
    setDraft(null);
    try {
      setDraft(await post<RepeatDraft>("/api/repeat/propose", { task_id: taskId, when: when.trim() }));
      onChange?.();
    } catch (err) {
      setError(errText(err));
    } finally {
      setBusy(false);
    }
  }

  if (!open)
    return (
      <div className="row">
        <button onClick={() => setOpen(true)}>Repeat this…</button>
        {msg && <span className="okbox small">{msg}</span>}
      </div>
    );
  return (
    <div className="subpanel" aria-label="Repeat this task">
      <h3>Repeat this task automatically</h3>
      <p className="small muted">
        Jarvis drafts a skill from what this task did and a schedule from your words, then shows both. Automations run
        at most every 30 minutes and only do read-only work and new files on their own.
      </p>
      <form className="row" onSubmit={propose}>
        <input
          className="grow"
          value={when}
          onChange={(e) => setWhen(e.target.value)}
          placeholder="When? e.g. every Monday at 9 · roj sakali 8 la"
          maxLength={200}
          aria-label="When should it run"
        />
        <button className="primary" disabled={busy || !when.trim()}>
          {busy ? "Drafting… (one model call)" : "Draft it"}
        </button>
        <button
          type="button"
          onClick={() => {
            setOpen(false);
            setDraft(null);
            setError("");
          }}
          disabled={busy}
        >
          Close
        </button>
      </form>
      {error && <div className="error">{error}</div>}
      {draft && (
        <RepeatDraftView
          key={draft.id}
          draft={draft}
          onDone={(m) => {
            setDraft(null);
            setOpen(false);
            setWhen("");
            setMsg(m);
            onChange?.();
          }}
        />
      )}
    </div>
  );
}

// Drafts waiting for a yes (from chat, Telegram or this dashboard).
export function PendingRepeatDrafts({ refresh = 0 }: { refresh?: number }) {
  const list = usePoll(() => api<{ items: Summary[]; ttl_s: number }>("/api/repeat/drafts"), 15000, [refresh]);
  const [open, setOpen] = useState<RepeatDraft | null>(null);
  const [msg, setMsg] = useState("");
  const [error, setError] = useState("");
  const items = list.data?.items ?? [];

  // The open draft was answered elsewhere (chat, Telegram, another view) or expired: close it.
  useEffect(() => {
    if (open && list.data && !list.data.items.some((i) => i.id === open.id)) setOpen(null);
  }, [list.data, open]);

  if (!items.length && !open && !msg && !error && !list.error) return null;

  async function show(id: string) {
    setError("");
    setMsg("");
    try {
      setOpen(await api<RepeatDraft>(`/api/repeat/drafts/${encodeURIComponent(id)}`));
    } catch (e) {
      setError(errText(e));
      list.reload();
    }
  }

  async function cancel(s: Summary) {
    if (!confirm(`Cancel draft ${s.id} (${s.skill}, ${s.description})? Nothing will be saved.`)) return;
    setError("");
    try {
      await post(`/api/repeat/drafts/${encodeURIComponent(s.id)}/cancel`);
      announce(s.id, "list");
      if (open?.id === s.id) setOpen(null);
      setMsg(`Draft ${s.id} cancelled.`);
    } catch (e) {
      setError(errText(e));
    }
    list.reload();
  }

  return (
    <section className="panel" aria-label="Automation drafts waiting">
      <h2>Automation drafts waiting ({items.length})</h2>
      <p className="small muted">
        Drafts from &quot;Repeat this…&quot;, <code>/repeat</code> in chat or on Telegram. Open one to read the full skill
        and schedule before saving. Drafts expire after an hour.
      </p>
      {items.length > 0 && (
        <table>
          <thead>
            <tr>
              <th>Draft</th>
              <th>From</th>
              <th>Skill</th>
              <th>When</th>
              <th>Expires</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {items.map((s) => (
              <tr key={s.id}>
                <td className="small">{s.id}</td>
                <td className="small">
                  {s.source}
                  <div className="muted cell-wrap">{s.goal}</div>
                </td>
                <td className="small">{s.skill}</td>
                <td className="small">
                  {s.description}
                  <div className="muted">
                    <code>{s.cron}</code>
                  </div>
                </td>
                <td className="small">in {minutes(s.expires_in_s)} min</td>
                <td>
                  <div className="row">
                    <button onClick={() => show(s.id)}>Open</button>
                    <button onClick={() => cancel(s)}>Cancel</button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {open && (
        <RepeatDraftView
          key={open.id}
          draft={open}
          onDone={(m) => {
            setOpen(null);
            setMsg(m);
            list.reload();
          }}
        />
      )}
      {msg && <div className="okbox small">{msg}</div>}
      {(error || list.error) && <div className="error">{error || list.error}</div>}
    </section>
  );
}
