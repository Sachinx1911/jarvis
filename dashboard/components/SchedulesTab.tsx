"use client";

import { useState } from "react";
import { api, post } from "@/lib/api";
import { errText, usePoll } from "@/lib/hooks";

type Schedule = {
  id: string;
  name: string;
  kind: string;
  target: string;
  input: string;
  cron: string;
  timezone: string;
  output: string;
  enabled: boolean;
  source: string;
  next_run_at: string | null;
  last_run_at: string | null;
  last_status: string | null;
  last_detail: string | null;
};
type Run = { id: number; trigger: string; started_at: string; status: string; detail: string | null; model_calls: number };
type Job = { status: string; key: string; result: { status: string; text: string } | null; error: string } | null;
type SchedData = { items: Schedule[]; pending_approvals: number; running_here: boolean; job: Job };
type Draft = { draft_id: string | null; question?: string; show?: string };
type Reminder = { id: number; text: string; due_at: string };
type Pending = {
  id: number;
  schedule_id: string | null;
  created_at: string;
  tool: string;
  tier: string;
  arguments: Record<string, unknown>;
  reason: string;
  args_sha256: string;
};

type Trigger = {
  id: string;
  what: string;
  source: string;
  action: string;
  enabled: boolean;
  every_minutes: number;
  cooldown_minutes: number;
  last_check: string | null;
  next_check: string | null;
  last_status: string | null;
  last_detail: string | null;
  last_fired: string | null;
  failures: number;
};
type TriggersData = {
  installed: boolean;
  wired?: boolean;
  detail?: string;
  error?: string;
  items?: Trigger[];
  running_here: boolean;
};
type Fire = {
  id: number;
  started_at: string;
  finished_at: string | null;
  status: string;
  events: number;
  detail: string | null;
  output_path: string | null;
  pending_approvals: number;
  model_calls: number;
};

type TriggerDraft = {
  draft_id: string | null;
  question?: string;
  show?: string;
  draft?: {
    source: string;
    description: string;
    condition: Record<string, unknown>;
    action: string;
    target: string;
    input: string;
    output: string;
    every_s: number;
    cooldown_s: number;
    read_by: string;
    private_hidden: boolean;
  };
};

const short = (s: string | null) => (s ? s.replace("T", " ").slice(0, 16) : "-");

function human(seconds: number): string {
  if (seconds >= 3600 && seconds % 3600 === 0) return `${seconds / 3600} h`;
  if (seconds % 60 === 0) return `${seconds / 60} min`;
  return `${seconds} s`;
}

// Colour class for a status word; the word itself is always shown next to the colour.
function tone(status: string | null): string {
  if (!status) return "off";
  if (["ok", "fired", "baseline", "done"].includes(status)) return "ok";
  if (["waiting", "cooldown", "running", "budget"].includes(status)) return "warn";
  if (["error", "failed", "stopped"].includes(status)) return "bad";
  return "off";
}

const SOURCE_TEXT: Record<string, string> = {
  file_new: "new file",
  web_price: "price drop",
  email_from: "email",
  calendar_soon: "meeting soon",
  web_search_new: "new search results",
};

export default function SchedulesTab() {
  const s = usePoll(() => api<SchedData>("/api/schedules/all"), 5000);
  return (
    <>
      {s.data && !s.data.running_here && (
        <div className="notice">
          Schedules and reminders run while Jarvis runs in the background: start it with the Desktop shortcut or{" "}
          <code>jarvis app</code>.
        </div>
      )}
      <Unattended reloadSchedules={s.reload} />
      <div className="split">
        <NewSchedule onSaved={s.reload} />
        <Reminders />
      </div>
      <ScheduleList data={s.data} error={s.error} reload={s.reload} />
      <Triggers />
      <Brief />
    </>
  );
}

function NewSchedule({ onSaved }: { onSaved: () => void }) {
  const [text, setText] = useState("");
  const [kind, setKind] = useState("prompt");
  const [target, setTarget] = useState("");
  const [output, setOutput] = useState("");
  const [rulesOnly, setRulesOnly] = useState(false);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [msg, setMsg] = useState("");

  async function read(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    setMsg("");
    setDraft(null);
    try {
      setDraft(
        await post<Draft>("/api/schedules/draft", {
          text,
          kind,
          target,
          output: output || null,
          use_model: !rulesOnly,
        }),
      );
    } catch (err) {
      setError(errText(err));
    } finally {
      setBusy(false);
    }
  }

  async function save() {
    if (!draft?.draft_id) return;
    setBusy(true);
    setError("");
    try {
      const r = await post<{ saved: Schedule }>("/api/schedules/confirm", { draft_id: draft.draft_id });
      setMsg(`Saved as ${r.saved.id}.`);
      setDraft(null);
      setText("");
      onSaved();
    } catch (err) {
      setError(errText(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="panel">
      <h2>New schedule</h2>
      <form onSubmit={read}>
        <label className="field">
          What and when (English or Marathi)
          <input
            value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder="every Monday at 9 project summary · roj sakali 8 la ..."
            maxLength={1000}
          />
        </label>
        <div className="row">
          <label className="field">
            Kind
            <select value={kind} onChange={(e) => setKind(e.target.value)}>
              <option value="prompt">ask Jarvis</option>
              <option value="skill">run a skill</option>
              <option value="agent">agent task</option>
              <option value="brief">daily brief</option>
              <option value="heartbeat">heartbeat</option>
            </select>
          </label>
          {(kind === "skill" || kind === "agent") && (
            <label className="field">
              {kind === "skill" ? "Skill name" : "Agent name"}
              <input value={target} onChange={(e) => setTarget(e.target.value)} maxLength={80} />
            </label>
          )}
          <label className="field">
            Send result to
            <select value={output} onChange={(e) => setOutput(e.target.value)}>
              <option value="">default</option>
              <option value="telegram">Telegram</option>
              <option value="file">file</option>
              <option value="both">both</option>
            </select>
          </label>
        </div>
        <label className="small row">
          <input type="checkbox" checked={rulesOnly} onChange={(e) => setRulesOnly(e.target.checked)} />
          read the time with the rules only (no model call)
        </label>
        <button className="primary" disabled={busy}>
          Read it
        </button>
      </form>
      {draft?.question && <div className="notice">{draft.question}</div>}
      {draft?.show && (
        <>
          <pre>{draft.show}</pre>
          <p className="small">Nothing is saved until you confirm.</p>
          <div className="row">
            <button className="primary" onClick={save} disabled={busy}>
              Save this schedule
            </button>
            <button onClick={() => setDraft(null)} disabled={busy}>
              Discard
            </button>
          </div>
        </>
      )}
      {msg && <div className="okbox small">{msg}</div>}
      {error && <div className="error">{error}</div>}
    </section>
  );
}

function ScheduleList({ data, error, reload }: { data: SchedData | null; error: string; reload: () => void }) {
  const [runs, setRuns] = useState<{ id: string; items: Run[] } | null>(null);
  const [err, setErr] = useState("");

  async function act(sc: Schedule, action: string) {
    const questions: Record<string, string> = {
      delete: `Archive schedule ${sc.id} (${sc.name})? It stops and leaves the list; nothing is deleted (jarvis schedule unarchive reopens it).`,
      "run-now": `Run ${sc.id} (${sc.name}) now? It may call the model and send the result to ${sc.output}.`,
    };
    if (questions[action] && !confirm(questions[action])) return;
    setErr("");
    try {
      await post(`/api/schedules/${sc.id}/${action}`);
      reload();
      if (runs?.id === sc.id) showRuns(sc.id);
    } catch (e) {
      setErr(errText(e));
    }
  }

  async function showRuns(id: string) {
    setErr("");
    try {
      const r = await api<{ runs: Run[] }>(`/api/schedules/${id}/runs`);
      setRuns({ id, items: r.runs });
    } catch (e) {
      setErr(errText(e));
    }
  }

  const job = data?.job;
  return (
    <section className="panel">
      <div className="row">
        <h2 className="grow">Schedules</h2>
        <button onClick={reload}>Refresh</button>
      </div>
      {(error || err) && <div className="error">{error || err}</div>}
      {job && (
        <div className={job.status === "error" ? "error" : job.status === "done" ? "okbox" : "notice"}>
          <span className="small">
            Run now {job.key}: {job.status}
            {job.result ? ` (${job.result.status})` : ""}
            {job.error ? ` ${job.error}` : ""}
          </span>
          {job.result?.text && <pre>{job.result.text}</pre>}
        </div>
      )}
      <table>
        <thead>
          <tr>
            <th>Id</th>
            <th>What</th>
            <th>When</th>
            <th>Next</th>
            <th>Last</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          {(data?.items ?? []).map((sc) => (
            <tr key={sc.id}>
              <td>
                {sc.id}
                {!sc.enabled && <div className="badge">paused</div>}
              </td>
              <td>
                <strong>{sc.name}</strong>
                <div className="small muted">
                  {sc.kind}
                  {sc.target ? `: ${sc.target}` : ""} → {sc.output}
                </div>
              </td>
              <td className="small">
                <code>{sc.cron}</code>
                <div className="muted">{sc.timezone}</div>
              </td>
              <td className="small">{sc.enabled ? short(sc.next_run_at) : "-"}</td>
              <td className="small">
                {sc.last_status ?? "-"} {short(sc.last_run_at)}
              </td>
              <td>
                <div className="row">
                  {sc.enabled ? (
                    <button onClick={() => act(sc, "pause")}>Pause</button>
                  ) : (
                    <button onClick={() => act(sc, "resume")}>Resume</button>
                  )}
                  <button onClick={() => act(sc, "run-now")}>Run now</button>
                  <button onClick={() => showRuns(sc.id)}>Runs</button>
                  <button className="danger" onClick={() => act(sc, "delete")}>
                    Archive
                  </button>
                </div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {data && data.items.length === 0 && <p className="muted">No schedules yet.</p>}
      {runs && (
        <>
          <h3>Runs of {runs.id}</h3>
          <table>
            <tbody>
              {runs.items.map((r) => (
                <tr key={r.id}>
                  <td className="small">{short(r.started_at)}</td>
                  <td className="small">{r.trigger}</td>
                  <td className="small">{r.status}</td>
                  <td className="small num">{r.model_calls} calls</td>
                  <td className="small cell-clip">{r.detail}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {runs.items.length === 0 && <p className="muted small">No runs yet.</p>}
        </>
      )}
    </section>
  );
}

function triggerAction(d: NonNullable<TriggerDraft["draft"]>): string {
  if (d.action === "notify") return "send you a message (no AI model)";
  if (d.action === "prompt") return `ask Jarvis: "${d.input}"`;
  if (d.action === "skill") return `run skill ${d.target}` + (d.input ? ` with "${d.input}"` : "");
  return `give agent ${d.target} the task "${d.input}"`;
}

function NewTrigger({ onSaved, onClose }: { onSaved: (msg: string) => void; onClose: () => void }) {
  const [text, setText] = useState("");
  const [kind, setKind] = useState("");
  const [target, setTarget] = useState("");
  const [output, setOutput] = useState("");
  const [every, setEvery] = useState("");
  const [cooldown, setCooldown] = useState("");
  const [draft, setDraft] = useState<TriggerDraft | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function read(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    setDraft(null);
    if ([every, cooldown].some((v) => v.trim() && !Number.isFinite(Number(v)))) {
      setError("Check every and cooldown are numbers of minutes (or leave them empty for the default).");
      return;
    }
    setBusy(true);
    try {
      setDraft(
        await post<TriggerDraft>("/api/triggers/draft", {
          text,
          kind: kind || null,
          target,
          output: output || null,
          every_minutes: every.trim() ? Number(every) : null,
          cooldown_minutes: cooldown.trim() ? Number(cooldown) : null,
        }),
      );
    } catch (err) {
      setError(errText(err));
    } finally {
      setBusy(false);
    }
  }

  async function save() {
    if (!draft?.draft_id) return;
    setBusy(true);
    setError("");
    try {
      const r = await post<{ saved: { id: string; name: string } }>("/api/triggers/confirm", { draft_id: draft.draft_id });
      setDraft(null);
      setText("");
      onSaved(`Saved as ${r.saved.id}: ${r.saved.name}.`);
    } catch (err) {
      setError(errText(err));
    } finally {
      setBusy(false);
    }
  }

  async function discard() {
    const id = draft?.draft_id;
    setDraft(null);
    if (id) await post("/api/triggers/discard", { draft_id: id }).catch(() => undefined);
  }

  const d = draft?.draft;
  return (
    <div className="subpanel" aria-label="New trigger">
      <h3>New trigger</h3>
      <form onSubmit={read}>
        <label className="field">
          What to watch and what to do (English or Marathi)
          <input
            value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder="when a new file arrives in workspace/inbox tell me"
            maxLength={1000}
          />
        </label>
        <div className="row">
          <label className="field">
            Then
            <select value={kind} onChange={(e) => setKind(e.target.value)}>
              <option value="">as the sentence says</option>
              <option value="notify">just tell me</option>
              <option value="prompt">ask Jarvis</option>
              <option value="skill">run a skill</option>
              <option value="agent">agent task</option>
            </select>
          </label>
          {(kind === "skill" || kind === "agent") && (
            <label className="field">
              {kind === "skill" ? "Skill name" : "Agent name"}
              <input value={target} onChange={(e) => setTarget(e.target.value)} maxLength={80} />
            </label>
          )}
          <label className="field">
            Send result to
            <select value={output} onChange={(e) => setOutput(e.target.value)}>
              <option value="">default</option>
              <option value="telegram">Telegram</option>
              <option value="file">file</option>
              <option value="both">both</option>
            </select>
          </label>
          <label className="field">
            Check every (min)
            <input value={every} onChange={(e) => setEvery(e.target.value)} placeholder="default" inputMode="decimal" style={{ width: 90 }} />
          </label>
          <label className="field">
            Cooldown (min)
            <input value={cooldown} onChange={(e) => setCooldown(e.target.value)} placeholder="default" inputMode="decimal" style={{ width: 90 }} />
          </label>
        </div>
        <div className="row">
          <button className="primary" disabled={busy || !text.trim()}>
            Read it
          </button>
          <button type="button" onClick={onClose} disabled={busy}>
            Close
          </button>
        </div>
      </form>
      {draft?.question && <div className="notice">{draft.question}</div>}
      {d && (
        <>
          <dl className="kv">
            <dt>Watches</dt>
            <dd>
              {SOURCE_TEXT[d.source] ?? d.source}: {d.description}
            </dd>
            <dt>Condition</dt>
            <dd className="small">
              {Object.entries(d.condition)
                .filter(([, v]) => v !== "" && v !== null)
                .map(([k, v]) => `${k}=${String(v)}`)
                .join(", ")}
            </dd>
            <dt>Then</dt>
            <dd>{triggerAction(d)}</dd>
            <dt>Checks</dt>
            <dd>
              every {human(d.every_s)}; at most one run per {human(d.cooldown_s)}
            </dd>
            <dt>Output</dt>
            <dd>{d.output}</dd>
          </dl>
          {d.private_hidden && (
            <p className="small muted">
              The sender and subject are private (P2) and are not shown again here or in the list; they are saved
              exactly as you typed them above.
            </p>
          )}
          <details>
            <summary className="small">Full draft</summary>
            <pre>{draft?.show}</pre>
          </details>
          <p className="small">
            Runs unattended: only read-only work and new files; anything else waits for your approval. Nothing is saved
            until you confirm.
          </p>
          <div className="row">
            <button className="primary" onClick={save} disabled={busy}>
              Save this trigger
            </button>
            <button onClick={discard} disabled={busy}>
              Discard
            </button>
          </div>
        </>
      )}
      {error && <div className="error">{error}</div>}
    </div>
  );
}

function Triggers() {
  const t = usePoll(() => api<TriggersData>("/api/triggers"), 10000);
  const [runs, setRuns] = useState<{ id: string; items: Fire[] } | null>(null);
  const [err, setErr] = useState("");
  const [msg, setMsg] = useState("");
  const [adding, setAdding] = useState(false);
  const [deleting, setDeleting] = useState<Trigger | null>(null);
  const d = t.data;
  const items = d?.items ?? [];

  async function act(tr: Trigger, action: "pause" | "resume") {
    setErr("");
    try {
      await post(`/api/triggers/${encodeURIComponent(tr.id)}/${action}`);
      t.reload();
    } catch (e) {
      setErr(errText(e));
    }
  }

  async function remove(tr: Trigger) {
    setErr("");
    try {
      await post(`/api/triggers/${encodeURIComponent(tr.id)}/delete`, { confirm: tr.id });
      setDeleting(null);
      if (runs?.id === tr.id) setRuns(null);
      setMsg(`Archived ${tr.id}.`);
      t.reload();
    } catch (e) {
      setErr(errText(e));
    }
  }

  async function showRuns(id: string) {
    setErr("");
    try {
      const r = await api<{ runs: Fire[] }>(`/api/triggers/${encodeURIComponent(id)}/runs`);
      setRuns({ id, items: r.runs });
    } catch (e) {
      setErr(errText(e));
    }
  }

  return (
    <section className="panel" aria-label="Event triggers">
      <div className="row">
        <h2 className="grow">Event triggers</h2>
        {!adding && (
          <button
            className="primary"
            onClick={() => {
              setAdding(true);
              setMsg("");
            }}
          >
            New trigger
          </button>
        )}
        <button onClick={t.reload}>Refresh</button>
      </div>
      <p className="small muted">
        A trigger does something when something happens (a new file, a price drop on a store page, an email, a meeting
        soon, new search results). Triggers run unattended: only read-only actions run; anything else waits above for
        your approval.
      </p>
      {adding && (
        <NewTrigger
          onClose={() => setAdding(false)}
          onSaved={(m) => {
            setMsg(m);
            setAdding(false);
            t.reload();
          }}
        />
      )}
      {msg && <div className="okbox small">{msg}</div>}
      {deleting && (
        <div className="notice" role="alertdialog" aria-label={`Archive ${deleting.id}`}>
          <div>
            Archive trigger <strong>{deleting.id}</strong> ({deleting.what})? It stops and leaves the list; nothing is deleted (jarvis trigger unarchive reopens it).
          </div>
          <div className="row">
            <button className="danger" onClick={() => remove(deleting)}>
              Yes, delete {deleting.id}
            </button>
            <button onClick={() => setDeleting(null)}>Keep it</button>
          </div>
        </div>
      )}
      {d && !d.running_here && items.length > 0 && (
        <div className="notice small">
          Triggers are checked only while Jarvis runs in the background (the app or jarvis daemon).
        </div>
      )}
      {d && !d.installed && <div className="notice small">Triggers are not installed: {d.detail}</div>}
      {(t.error || err || d?.error) && <div className="error">{t.error || err || d?.error}</div>}
      {items.length > 0 && (
        <table>
          <thead>
            <tr>
              <th>Id</th>
              <th>When / then</th>
              <th>Checks</th>
              <th>Status</th>
              <th>Last check</th>
              <th>Last fired</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {items.map((tr) => (
              <tr key={tr.id}>
                <td>{tr.id}</td>
                <td>
                  <strong>{tr.what}</strong>
                  <div className="small muted">
                    {SOURCE_TEXT[tr.source] ?? tr.source} → {tr.action === "notify" ? "tell you" : tr.action}
                  </div>
                </td>
                <td className="small">
                  every {tr.every_minutes} min
                  <div className="muted">cooldown {tr.cooldown_minutes} min</div>
                </td>
                <td className="small">
                  {tr.enabled ? <span className="pill ok">active</span> : <span className="pill off">paused</span>}
                  {tr.last_status && (
                    <div>
                      <span className={`pill ${tone(tr.last_status)}`}>{tr.last_status}</span>
                      {tr.failures > 0 && <span className="muted"> {tr.failures} failure(s) in a row</span>}
                    </div>
                  )}
                  {tr.last_detail && <div className="muted cell-wrap">{tr.last_detail}</div>}
                </td>
                <td className="small">
                  {short(tr.last_check)}
                  {tr.enabled && <div className="muted">next {short(tr.next_check)}</div>}
                </td>
                <td className="small">{short(tr.last_fired)}</td>
                <td>
                  <div className="row">
                    {tr.enabled ? (
                      <button onClick={() => act(tr, "pause")}>Pause</button>
                    ) : (
                      <button onClick={() => act(tr, "resume")}>Resume</button>
                    )}
                    <button onClick={() => showRuns(tr.id)}>Runs</button>
                    <button
                      className="danger"
                      onClick={() => {
                        setDeleting(tr);
                        setMsg("");
                      }}
                    >
                      Archive
                    </button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {d && d.installed && items.length === 0 && <p className="muted">No triggers yet.</p>}
      {runs && (
        <>
          <h3>Runs of {runs.id}</h3>
          {runs.items.length > 0 && (
            <table>
              <thead>
                <tr>
                  <th>Started</th>
                  <th>Status</th>
                  <th className="num">Events</th>
                  <th className="num">Model calls</th>
                  <th className="num">Waiting approvals</th>
                  <th>Result</th>
                </tr>
              </thead>
              <tbody>
                {runs.items.map((f) => (
                  <tr key={f.id}>
                    <td className="small">{short(f.started_at)}</td>
                    <td className="small">
                      <span className={`pill ${tone(f.status)}`}>{f.status}</span>
                    </td>
                    <td className="small num">{f.events}</td>
                    <td className="small num">{f.model_calls}</td>
                    <td className="small num">{f.pending_approvals}</td>
                    <td className="small cell-clip" title={f.detail ?? ""}>
                      {f.detail ?? <span className="muted">details hidden (private email rule)</span>}
                      {f.output_path && <div className="muted">{f.output_path}</div>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          {runs.items.length === 0 && <p className="muted small">Not fired yet.</p>}
        </>
      )}
    </section>
  );
}

function Reminders() {
  const r = usePoll(() => api<{ items: Reminder[] }>("/api/reminders"), 15000);
  const [text, setText] = useState("");
  const [msg, setMsg] = useState("");
  const [error, setError] = useState("");

  async function add(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    setMsg("");
    try {
      const x = await post<Reminder>("/api/reminders", { text });
      setMsg(`Reminder #${x.id} for ${short(x.due_at)}: ${x.text}`);
      setText("");
      r.reload();
    } catch (err) {
      setError(errText(err));
    }
  }

  async function cancel(x: Reminder) {
    if (!confirm(`Cancel reminder #${x.id}: ${x.text}?`)) return;
    try {
      await post(`/api/reminders/${x.id}/cancel`);
      r.reload();
    } catch (err) {
      setError(errText(err));
    }
  }

  return (
    <section className="panel">
      <h2>Reminders</h2>
      <form className="row" onSubmit={add}>
        <input
          className="grow"
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder="in 10 minutes call back · udya sakali 9 la bill bhar"
          maxLength={500}
        />
        <button className="primary" disabled={!text.trim()}>
          Add
        </button>
      </form>
      {msg && <div className="okbox small">{msg}</div>}
      {(error || r.error) && <div className="error">{error || r.error}</div>}
      <table>
        <tbody>
          {(r.data?.items ?? []).map((x) => (
            <tr key={x.id}>
              <td className="small">#{x.id}</td>
              <td className="small">{short(x.due_at)}</td>
              <td>{x.text}</td>
              <td>
                <button onClick={() => cancel(x)}>Cancel</button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {r.data && r.data.items.length === 0 && <p className="muted">No pending reminders.</p>}
    </section>
  );
}

function Unattended({ reloadSchedules }: { reloadSchedules: () => void }) {
  const u = usePoll(() => api<{ items: Pending[] }>("/api/unattended"), 10000);
  const [msg, setMsg] = useState("");
  const [error, setError] = useState("");
  const items = u.data?.items ?? [];
  if (!items.length && !msg && !error) return null;

  async function answer(p: Pending, decision: "approve" | "deny") {
    if (
      decision === "approve" &&
      !confirm(`Run this exact call once now?\n\n${p.tool} [${p.tier}]\n${JSON.stringify(p.arguments, null, 2)}`)
    )
      return;
    setError("");
    try {
      const r = await post<{ message: string }>(`/api/unattended/${p.id}`, { decision, args_sha256: p.args_sha256 });
      setMsg(r.message);
      u.reload();
      reloadSchedules();
    } catch (e) {
      setError(errText(e));
    }
  }

  return (
    <section className="panel" aria-label="Waiting from scheduled runs">
      <h2>Waiting from scheduled runs ({items.length})</h2>
      <p className="small muted">
        A scheduled run may only read and write new files. These actions it wanted wait for you; approving runs the
        exact call once.
      </p>
      {items.map((p) => (
        <div key={p.id} className={`approval ${p.tier}`}>
          <div className="row">
            <strong className="grow">
              #{p.id} {p.tool} <span className={`tier ${p.tier}`}>{p.tier}</span>
            </strong>
            <span className="small muted">
              {p.schedule_id} · {short(p.created_at)}
            </span>
          </div>
          <pre>{JSON.stringify(p.arguments, null, 2)}</pre>
          <div className="small muted">{p.reason}</div>
          <div className="row">
            <button className="primary" onClick={() => answer(p, "approve")}>
              Approve
            </button>
            <button onClick={() => answer(p, "deny")}>Deny</button>
          </div>
        </div>
      ))}
      {msg && <pre>{msg}</pre>}
      {(error || u.error) && <div className="error">{error || u.error}</div>}
    </section>
  );
}

function Brief() {
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function show() {
    setBusy(true);
    setError("");
    try {
      setText((await api<{ text: string }>("/api/brief")).text);
    } catch (e) {
      setError(errText(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="panel">
      <div className="row">
        <h2 className="grow">Morning brief</h2>
        <button className="primary" onClick={show} disabled={busy}>
          {busy ? "Building…" : "Show morning brief"}
        </button>
      </div>
      {error && <div className="error">{error}</div>}
      {text && <pre lang="mr">{text}</pre>}
    </section>
  );
}
