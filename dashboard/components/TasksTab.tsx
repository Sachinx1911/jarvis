"use client";

import { useEffect, useState } from "react";
import { api, post } from "@/lib/api";
import { errText, money, num, usePoll } from "@/lib/hooks";
import Approvals, { ApprovalsData } from "./Approvals";
import { PendingRepeatDrafts, RepeatThis } from "./RepeatDrafts";
import { Icon } from "./icons";
import { STATE_TONE, stateWord } from "./system";

type Usage = { calls: number; input_tokens: number; output_tokens: number; notional_usd: number; billed_usd: number; models: string[] };
type Task = {
  id: string;
  title: string;
  goal: string;
  state: string;
  project: string | null;
  priority: number;
  deadline: string | null;
  owner: string;
  last_error: string | null;
  retries: number;
  current_step: string | null;
  created_at: string;
  updated_at: string;
  usage: Usage;
  running: boolean;
  progress: string[];
};
type TaskDetail = Task & {
  events: { ts: string; kind: string; detail: unknown }[];
  receipt: string | null;
  plan: Record<string, unknown>;
};

const COLUMNS: [string, string, string[]][] = [
  ["Backlog", "backlog", ["BACKLOG", "SCHEDULED", "PLANNED"]],
  ["Running", "running", ["RUNNING", "WAITING_APPROVAL", "VERIFYING"]],
  ["Paused", "paused", ["PAUSED"]],
  ["Completed", "completed", ["COMPLETED"]],
  ["Failed", "failed", ["FAILED"]],
  ["Cancelled", "cancelled", ["CANCELLED"]],
];
const PRIORITY = ["", "high", "normal", "low"];

export default function TasksTab({
  approvals,
  reloadApprovals,
  focus,
  onFocused,
}: {
  approvals: ApprovalsData | null;
  reloadApprovals: () => void;
  focus?: string | null;
  onFocused?: () => void;
}) {
  const tasks = usePoll(() => api<{ items: Task[]; running: string[] }>("/api/tasks"), 3000);
  const [selected, setSelected] = useState<string | null>(null);

  // Another page (Command Center) asked to open one task.
  useEffect(() => {
    if (!focus) return;
    setSelected(focus);
    onFocused?.();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [focus]);
  const [message, setMessage] = useState("");
  const [draftsChanged, setDraftsChanged] = useState(0);
  const items = tasks.data?.items ?? [];

  async function resumeAll() {
    try {
      const r = await post<{ started: string[]; waiting: string[] }>("/api/tasks/resume-all");
      setMessage(
        r.started.length ? `Started ${r.started.join(", ")}` : "Nothing to resume (or 2 tasks already running).",
      );
      tasks.reload();
    } catch (e) {
      setMessage(errText(e));
    }
  }

  return (
    <>
      {approvals && <Approvals data={approvals} reload={reloadApprovals} />}
      <PendingRepeatDrafts refresh={draftsChanged} />
      <NewTask
        onCreated={(id) => {
          setSelected(id);
          tasks.reload();
        }}
      />
      <section className="panel">
        <div className="card-head">
          <h2>Task board</h2>
          <button className="sm" onClick={resumeAll}>
            <Icon name="refresh" size={15} /> Resume waiting tasks
          </button>
        </div>
        {message && <div className="notice small">{message}</div>}
        {tasks.error && <div className="error">{tasks.error}</div>}
        <div className="board-wrap">
          <div className="kanban">
            {COLUMNS.map(([name, cls, states]) => {
              const col = items.filter((t) => states.includes(t.state));
              return (
                <div className={`kanban-col ${cls}`} key={name}>
                  <div className="kanban-head">
                    <span className="dot" />
                    <span className="grow">{name}</span>
                    <span className="badge">{col.length}</span>
                  </div>
                  <div className="kanban-list">
                    {col.length === 0 && <div className="empty compact muted">Nothing here</div>}
                    {col.map((t) => (
                      <button
                        key={t.id}
                        className={`task-card${selected === t.id ? " selected" : ""}`}
                        onClick={() => setSelected(t.id)}
                      >
                        <span className="title">{t.title}</span>
                        <span className="meta">
                          <span className={`pill ${STATE_TONE[t.state] ?? "off"}`}>{stateWord(t.state)}</span>
                          <span className="pill outline">{PRIORITY[t.priority] ?? t.priority}</span>
                          {t.project && <span className="pill violet">{t.project}</span>}
                          {t.running && (
                            <span className="pill accent">
                              <span className="dot accent pulse" /> live
                            </span>
                          )}
                          <span className="id">{t.id}</span>
                        </span>
                        {t.current_step && (
                          <span className="step">
                            <Icon name="chevronRight" size={12} />
                            {t.current_step}
                          </span>
                        )}
                        {t.running && (
                          <span className="progress indeterminate">
                            <span />
                          </span>
                        )}
                      </button>
                    ))}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      </section>
      {selected && (
        <TaskView id={selected} onChange={tasks.reload} onDraftsChanged={() => setDraftsChanged((n) => n + 1)} />
      )}
    </>
  );
}

function NewTask({ onCreated }: { onCreated: (id: string) => void }) {
  const [goal, setGoal] = useState("");
  const [project, setProject] = useState("");
  const [priority, setPriority] = useState("normal");
  const [run, setRun] = useState(false);
  const [error, setError] = useState("");

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    try {
      const r = await post<{ id: string }>("/api/tasks", { goal, project: project || null, priority, run });
      setGoal("");
      onCreated(r.id);
    } catch (err) {
      setError(errText(err));
    }
  }

  return (
    <form className="panel" onSubmit={submit}>
      <h2>New task</h2>
      <div className="row">
        <input className="grow" value={goal} onChange={(e) => setGoal(e.target.value)} placeholder="Goal, e.g. compare 3 laptops under Rs 80,000" />
        <input value={project} onChange={(e) => setProject(e.target.value)} placeholder="project (optional)" style={{ width: 170 }} />
        <select value={priority} onChange={(e) => setPriority(e.target.value)}>
          <option>high</option>
          <option>normal</option>
          <option>low</option>
        </select>
        <label className="row small">
          <input type="checkbox" checked={run} onChange={(e) => setRun(e.target.checked)} /> run now
        </label>
        <button className="primary" disabled={!goal.trim()}>
          Add
        </button>
      </div>
      {error && <div className="error">{error}</div>}
    </form>
  );
}

function TaskView({
  id,
  onChange,
  onDraftsChanged,
}: {
  id: string;
  onChange: () => void;
  onDraftsChanged: () => void;
}) {
  const t = usePoll(() => api<TaskDetail>(`/api/tasks/${id}`), 2500, [id]);
  const [error, setError] = useState("");
  const d = t.data;

  async function act(action: "run" | "resume" | "cancel") {
    if (action === "cancel" && !confirm(`Cancel ${id}?`)) return;
    setError("");
    try {
      await post(`/api/tasks/${id}/${action}`);
      t.reload();
      onChange();
    } catch (e) {
      setError(errText(e));
    }
  }

  if (!d) return <section className="panel muted">{t.error || "Loading…"}</section>;
  const final = ["COMPLETED", "CANCELLED"].includes(d.state);
  return (
    <section className="panel">
      <div className="row">
        <h2 className="grow">
          {d.id} · {d.title}
        </h2>
        <span className="badge">{d.state}</span>
        {!final && !d.running && (
          <button className="primary" onClick={() => act(d.state === "PAUSED" || d.state === "FAILED" ? "resume" : "run")}>
            {d.state === "PAUSED" || d.state === "FAILED" ? "Resume" : "Run"}
          </button>
        )}
        {!["COMPLETED", "FAILED", "CANCELLED"].includes(d.state) && <button onClick={() => act("cancel")}>Cancel</button>}
      </div>
      {error && <div className="error">{error}</div>}
      {d.state === "COMPLETED" && <RepeatThis key={d.id} taskId={d.id} onChange={onDraftsChanged} />}
      <div className="split">
        <div>
          <dl className="kv">
            <dt>Goal</dt>
            <dd>{d.goal}</dd>
            <dt>Project</dt>
            <dd>{d.project || "-"}</dd>
            <dt>Priority</dt>
            <dd>{PRIORITY[d.priority] ?? d.priority}</dd>
            <dt>Deadline</dt>
            <dd>{d.deadline || "-"}</dd>
            <dt>Step</dt>
            <dd>{d.current_step || "-"}</dd>
            <dt>Last error</dt>
            <dd>{d.last_error || "-"}</dd>
            <dt>Retries</dt>
            <dd>{d.retries}</dd>
            <dt>Model calls</dt>
            <dd>
              {d.usage.calls} · {num(d.usage.input_tokens + d.usage.output_tokens)} tokens · {money(d.usage.notional_usd)} notional
              {d.usage.billed_usd ? ` (${money(d.usage.billed_usd)} billed)` : ""}
            </dd>
            <dt>Models</dt>
            <dd>{d.usage.models.join(", ") || "-"}</dd>
          </dl>
          {d.progress.length > 0 && (
            <>
              <h3>Live progress</h3>
              <pre>{d.progress.join("\n")}</pre>
            </>
          )}
          <h3>Events</h3>
          <table>
            <tbody>
              {d.events.map((e, i) => (
                <tr key={i}>
                  <td className="small muted" style={{ whiteSpace: "nowrap" }}>
                    {e.ts}
                  </td>
                  <td>{e.kind}</td>
                  <td className="cell-clip" title={typeof e.detail === "string" ? e.detail : JSON.stringify(e.detail)}>
                    {typeof e.detail === "string" ? e.detail : JSON.stringify(e.detail)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div>
          <h3>Receipt</h3>
          {d.receipt ? <pre>{d.receipt}</pre> : <p className="muted">No receipt yet (written when the task ends or pauses).</p>}
        </div>
      </div>
    </section>
  );
}
