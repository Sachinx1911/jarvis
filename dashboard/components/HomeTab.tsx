"use client";

// Command Center: the day at a glance, built only from existing endpoints. Every number on
// this page comes from Jarvis; where there is no data the page says so instead of inventing it.

import { useEffect, useRef, useState } from "react";
import { api, post } from "@/lib/api";
import { errText, usePoll } from "@/lib/hooks";
import { Icon, IconName } from "./icons";
import { Tab } from "./nav";
import {
  FINAL_STATES,
  Health,
  hhmm,
  sameDay,
  SchedulesLite,
  SettingsLite,
  STATE_TONE,
  stateWord,
  TaskLite,
  TasksLite,
  taskStages,
  toDate,
} from "./system";
import { notReadyText, useStt, useVoice, VoicePrefs } from "./voice";
import { VoiceSettings, VoiceStage } from "./VoiceUI";

const NAME_KEY = "jarvis_display_name"; // kept in this browser only, never sent to the server

type Reminder = { id: string; text: string; due_at: string; status: string };
type Project = { name: string; goal: string; documents: number };
type TaskFull = TaskLite & { progress?: string[] };

const SUGGESTIONS = ["Check today's tasks", "What is on my calendar today?", "आज काय काम आहे?", "Summarise my open tasks"];

const QUICK: { label: string; icon: IconName; kind: "task" | "chat" | "tab"; prefix?: string; tab?: Tab; hint: string }[] = [
  { label: "Deep research", icon: "search", kind: "task", prefix: "Research: ", hint: "A team task: researchers, writer and checker" },
  { label: "Create report", icon: "report", kind: "task", prefix: "Write a report: ", hint: "A task that ends in a report file" },
  { label: "Plan task", icon: "listCheck", kind: "tab", tab: "tasks", hint: "Add a task to the board" },
  { label: "Automate", icon: "zap", kind: "tab", tab: "schedules", hint: "Schedules, reminders and triggers" },
];

function greeting(d: Date): string {
  const h = d.getHours();
  return h < 5 ? "Good night" : h < 12 ? "Good morning" : h < 17 ? "Good afternoon" : "Good evening";
}

// Who in the agent team is busy, from the running tasks' current step (jarvis/agents/orchestrator.py).
const AGENTS: { key: string; name: string; icon: IconName; tone: string; match: RegExp }[] = [
  { key: "planner", name: "Planner", icon: "compass", tone: "blue", match: /planning/i },
  { key: "researcher", name: "Researcher", icon: "search", tone: "teal", match: /research/i },
  { key: "writer", name: "Writer", icon: "pen", tone: "violet", match: /writer|drafting/i },
  { key: "checker", name: "Checker", icon: "shield", tone: "green", match: /check/i },
  { key: "coder", name: "Coder", icon: "code", tone: "amber", match: /coder/i },
  { key: "operator", name: "Operator", icon: "pointer", tone: "red", match: /operator/i },
];

export default function HomeTab({
  tasks,
  tasksError,
  schedules,
  schedulesError,
  settings,
  health,
  healthError,
  pendingApprovals,
  prefs,
  onPrefs,
  handsFree,
  onHandsFree,
  stopEngaged,
  onChoose,
  onAsk,
  onOpenTask,
  onTaskCreated,
}: {
  tasks: TasksLite | null;
  tasksError: string;
  schedules: SchedulesLite | null;
  schedulesError: string;
  settings: SettingsLite | null;
  health: Health | null;
  healthError: string;
  pendingApprovals: number;
  prefs: VoicePrefs;
  onPrefs: (p: VoicePrefs) => void;
  handsFree: boolean;
  onHandsFree: (on: boolean) => void;
  stopEngaged: boolean;
  onChoose: (t: Tab) => void;
  onAsk: (text: string) => void;
  onOpenTask: (id: string) => void;
  onTaskCreated: () => void;
}) {
  const [now, setNow] = useState(() => new Date());
  const [name, setName] = useState("");
  const [editing, setEditing] = useState(false);
  const [draftName, setDraftName] = useState("");
  const [text, setText] = useState("");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const reminders = usePoll(() => api<{ items: Reminder[] }>("/api/reminders"), 60000);
  const projects = usePoll(() => api<{ items: Project[] }>("/api/projects"), 0);
  const full = usePoll(() => api<{ items: TaskFull[]; running: string[] }>("/api/tasks"), 4000);
  const stt = useStt();
  const askRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    const t = window.setInterval(() => setNow(new Date()), 15000);
    try {
      setName(localStorage.getItem(NAME_KEY) ?? "");
    } catch {
      /* ignore */
    }
    return () => window.clearInterval(t);
  }, []);

  function saveName() {
    const n = draftName.trim().slice(0, 40);
    setName(n);
    setEditing(false);
    try {
      if (n) localStorage.setItem(NAME_KEY, n);
      else localStorage.removeItem(NAME_KEY);
    } catch {
      /* ignore */
    }
  }

  // Voice on the Command Center: what is heard goes to Chat, like typing in the ask box.
  const [vsOpen, setVsOpen] = useState(false);
  const sttMissing = stt !== null && !stt.ready;
  const voice = useVoice({
    prefs,
    handsFree,
    blocked: stopEngaged ? "stop" : pendingApprovals > 0 ? "approval" : null,
    stt,
    onSend: async (t) => {
      onAsk(t);
      return { handoff: true };
    },
    onDraft: (t) => setText(t),
    onNote: (t) => setNote(t),
  });

  function ask() {
    const t = text.trim();
    if (!t) return;
    setText("");
    onAsk(t);
  }

  async function quick(q: (typeof QUICK)[number]) {
    setNote("");
    if (q.kind === "tab" && q.tab) return onChoose(q.tab);
    const goal = text.trim();
    if (!goal) {
      setText(q.prefix ?? "");
      askRef.current?.focus();
      setNote(`Write what it is about after "${q.prefix?.trim()}", then press ${q.label} again.`);
      return;
    }
    setBusy(true);
    try {
      const g = goal.startsWith(q.prefix ?? "") ? goal : `${q.prefix}${goal}`;
      const r = await post<{ id: string }>("/api/tasks", { goal: g, project: null, priority: "normal", run: true });
      setText("");
      setNote(`Task ${r.id} started. Follow it under Current tasks.`);
      onTaskCreated();
      full.reload();
    } catch (e) {
      setNote(errText(e));
    } finally {
      setBusy(false);
    }
  }

  // ---- derived data ----
  const items: TaskFull[] = full.data?.items ?? tasks?.items ?? [];
  const active = items.filter((t) => !FINAL_STATES.includes(t.state));
  const running = items.filter((t) => t.running);
  const focusTask = running[0] ?? active.find((t) => t.state === "WAITING_APPROVAL") ?? null;
  const recent = [...items].sort((a, b) => (a.updated_at < b.updated_at ? 1 : -1)).slice(0, 6);
  const projectList = projects.data?.items ?? [];
  const todayItems = [
    ...(schedules?.items ?? [])
      .filter((s) => s.enabled)
      .map((s) => ({ key: `s-${s.id}`, when: toDate(s.next_run_at), title: s.name, kind: s.kind, tone: "accent" }))
      .filter((x) => x.when && sameDay(x.when, now)),
    ...(reminders.data?.items ?? [])
      .map((r) => ({ key: `r-${r.id}`, when: toDate(r.due_at), title: r.text, kind: "reminder", tone: "violet" }))
      .filter((x) => x.when && sameDay(x.when, now)),
  ].sort((a, b) => a.when!.getTime() - b.when!.getTime());

  const steps = (() => {
    if (!focusTask) return null;
    const stages = taskStages(focusTask);
    const team = Array.isArray((focusTask.plan as { research?: unknown } | undefined)?.research);
    const names = team
      ? ["Planning the work", "Researching", "Writing the report", "Checking the result"]
      : ["Planning the work", "Doing the work", "Checking the result"];
    const done = stages?.done ?? 0;
    return names.map((n, i) => ({ name: n, state: i < done ? "done" : i === done ? "active" : "pending" }));
  })();
  const pct = steps ? Math.round((steps.filter((s) => s.state === "done").length / steps.length) * 100) : 0;

  const busyAgents = new Map<string, string>();
  for (const t of running) for (const a of AGENTS) if (t.current_step && a.match.test(t.current_step)) busyAgents.set(a.key, t.title);

  return (
    <div className="home">
      {/* ---- hero: greeting, clock, voice stage / ask box ---- */}
      <section className="panel hero span-8">
        <div className="hero-top">
          <div>
            <p className="hello">{greeting(now)},</p>
            {editing ? (
              <span className="name-edit">
                <input
                  autoFocus
                  value={draftName}
                  placeholder="What should Jarvis call you?"
                  onChange={(e) => setDraftName(e.target.value)}
                  onKeyDown={(e) => e.key === "Enter" && saveName()}
                  aria-label="Your name (kept in this browser only)"
                />
                <button className="primary sm" onClick={saveName}>
                  Save
                </button>
              </span>
            ) : (
              <h1
                onDoubleClick={() => {
                  setDraftName(name);
                  setEditing(true);
                }}
                title="Double-click to change (kept in this browser only)"
              >
                {name || (
                  <button
                    className="link"
                    style={{ fontSize: "inherit", fontWeight: "inherit", padding: 0 }}
                    onClick={() => {
                      setDraftName("");
                      setEditing(true);
                    }}
                  >
                    Set your name
                  </button>
                )}
              </h1>
            )}
            <p className="lead">I&apos;m Jarvis. How can I help you today?</p>
          </div>
          <div className="clock">
            <div className="date">{now.toLocaleDateString("en-IN", { weekday: "short", day: "numeric", month: "short", year: "numeric" })}</div>
            <div className="time">{hhmm(now)}</div>
          </div>
        </div>

        <VoiceStage
          phase={voice.phase}
          mode={prefs.mode}
          heard={voice.heard}
          note={note}
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
          disabledWhy={stopEngaged ? "Emergency stop is on" : stt && sttMissing ? notReadyText(stt) : ""}
        />
        <div className="voice-foot" style={{ marginBottom: 12, position: "relative" }}>
          <button className="ghost sm" onClick={() => setVsOpen((o) => !o)} aria-expanded={vsOpen}>
            <Icon name="sliders" size={14} /> Voice settings
          </button>
          {vsOpen && <VoiceSettings prefs={prefs} onChange={onPrefs} onClose={() => setVsOpen(false)} />}
        </div>

        <div className="ask">
          <div className="composer-box">
            <div className="ask-row">
              <textarea
                ref={askRef}
                rows={1}
                value={text}
                placeholder="Ask Jarvis or give a task…"
                onChange={(e) => setText(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
                    e.preventDefault();
                    ask();
                  }
                }}
                aria-label="Ask Jarvis"
              />
              <button className="primary" onClick={ask} disabled={!text.trim() || busy} aria-label="Send to Chat">
                <Icon name="send" size={16} />
              </button>
            </div>
          </div>
          <div className="ask-modes">
            {QUICK.map((q) => (
              <button key={q.label} className="mode-btn" onClick={() => quick(q)} disabled={busy} title={q.hint}>
                <Icon name={q.icon} size={16} /> {q.label}
              </button>
            ))}
          </div>
          <div className="chips suggest">
            {SUGGESTIONS.map((s) => (
              <button key={s} className="chip plain" onClick={() => onAsk(s)}>
                {s}
              </button>
            ))}
          </div>
          {note && <div className="infobox small" style={{ marginTop: 12, marginBottom: 0 }}>{note}</div>}
        </div>
      </section>

      {/* ---- stats ---- */}
      <div className="stats span-4">
        <Stat icon="tasks" tone="blue" label="Active tasks" value={active.length} hint={`${running.length} running`} onClick={() => onChoose("tasks")} />
        <Stat
          icon="clock"
          tone="amber"
          label="Pending approval"
          value={pendingApprovals}
          hint={pendingApprovals ? "Needs your review" : "Nothing waiting"}
          alert={pendingApprovals > 0}
          onClick={() => onChoose("tasks")}
        />
        <Stat
          icon="agents"
          tone="violet"
          label="AI agents"
          value={busyAgents.size}
          hint={busyAgents.size ? "working now" : "all idle"}
          onClick={() => onChoose("agents")}
        />
        <Stat icon="folder" tone="green" label="Projects" value={projectList.length} hint={projects.data ? "in Jarvis" : "…"} onClick={() => onChoose("projects")} />
        <section className="panel sys">
          <div className="card-head">
            <h2>System</h2>
            <button className="link small see-all" onClick={() => onChoose("setup")}>
              Details <Icon name="arrowRight" size={13} />
            </button>
          </div>
          <div className="sys-rows">
          <SvcRow name="Jarvis service" ok={!healthError && !!health} state={healthError ? "Offline" : health ? "Online" : "…"} />
          <SvcRow
            name="Scheduler"
            ok={!!schedules?.running_here}
            state={schedulesError ? "Unknown" : schedules ? (schedules.running_here ? "Running" : "Not running") : "…"}
          />
          <SvcRow name="Emergency stop" ok={!stopEngaged} state={stopEngaged ? "ON" : "Off"} />
          <SvcRow
            name="AI model"
            ok={!!settings}
            state={settings ? (settings.cloud.cloud_allowed ? "Claude (subscription)" : "Cloud off") : "…"}
          />
          </div>
        </section>
      </div>

      {/* ---- current task with steps and live activity ---- */}
      {focusTask && steps && (
        <section className="panel span-12">
          <div className="task-top">
            <span className="tile lg blue">
              <Icon name="report" size={24} />
            </span>
            <div className="grow">
              <div className="small muted">Current task · {focusTask.id}</div>
              <h3>{focusTask.title}</h3>
              <div className="small muted">{focusTask.current_step ?? stateWord(focusTask.state)}</div>
            </div>
            <div className="pct">
              <strong>{pct}%</strong>
              <div className="progress" style={{ marginTop: 8 }}>
                <span style={{ width: `${Math.max(pct, 4)}%` }} />
              </div>
              <button className="link small" style={{ marginTop: 8 }} onClick={() => onOpenTask(focusTask.id)}>
                View details <Icon name="arrowRight" size={13} />
              </button>
            </div>
          </div>
          <div className="split" style={{ marginTop: 8 }}>
            <ul className="steps">
              {steps.map((s) => (
                <li key={s.name} className={s.state}>
                  <span className="step-dot">{s.state === "done" && <Icon name="check" size={12} />}</span>
                  {s.name}
                  <span className="state">{s.state === "done" ? "Completed" : s.state === "active" ? "In progress" : "Pending"}</span>
                </li>
              ))}
            </ul>
            <div>
              <div className="small muted" style={{ margin: "12px 0 4px" }}>
                <Icon name="sparkles" size={13} /> Jarvis is working…
              </div>
              {(focusTask.progress ?? []).length === 0 ? (
                <div className="empty compact muted">No progress lines yet.</div>
              ) : (
                <ul className="activity">
                  {(focusTask.progress ?? []).slice(-8).map((p, i) => (
                    <li key={i}>
                      <span className="tl-dot" />
                      <span>{p}</span>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </div>
        </section>
      )}

      {/* ---- current tasks ---- */}
      <section className="panel span-7">
        <div className="card-head">
          <h2>Current tasks</h2>
          <button className="link small see-all" onClick={() => onChoose("tasks")}>
            View all <Icon name="arrowRight" size={13} />
          </button>
        </div>
        {tasksError && <div className="error">{tasksError}</div>}
        {recent.length === 0 ? (
          <Empty icon="tasks" title="No tasks yet" sub="Give Jarvis a task above, or use Deep research." />
        ) : (
          <div className="list">
            {recent.map((t) => {
              const st = taskStages(t);
              const p = st ? Math.round((st.done / st.total) * 100) : t.state === "COMPLETED" ? 100 : 0;
              return (
                <button key={t.id} className="list-item" onClick={() => onOpenTask(t.id)}>
                  <span className={`tile ${t.state === "FAILED" ? "red" : t.state === "COMPLETED" ? "green" : "blue"}`}>
                    <Icon name={t.state === "COMPLETED" ? "check" : t.state === "FAILED" ? "alert" : "report"} size={18} />
                  </span>
                  <span className="main-col">
                    <span className="title ellipsis">{t.title}</span>
                    {!FINAL_STATES.includes(t.state) && st ? (
                      <span className="progress" style={{ marginTop: 6 }}>
                        <span style={{ width: `${Math.max(p, 4)}%` }} />
                      </span>
                    ) : (
                      <span className="sub">{t.current_step ?? t.id}</span>
                    )}
                  </span>
                  <span className={`pill ${STATE_TONE[t.state] ?? "off"}`}>{stateWord(t.state)}</span>
                </button>
              );
            })}
          </div>
        )}
      </section>

      {/* ---- agents ---- */}
      <section className="panel span-5">
        <div className="card-head">
          <h2>AI agents</h2>
          <button className="link small see-all" onClick={() => onChoose("agents")}>
            Activity <Icon name="arrowRight" size={13} />
          </button>
        </div>
        {AGENTS.map((a) => {
          const doing = busyAgents.get(a.key);
          return (
            <div key={a.key} className="agent-row">
              <span className={`tile ${a.tone}`}>
                <Icon name={a.icon} size={18} />
              </span>
              <span className="who">
                <strong>{a.name}</strong>
                <span>
                  <span className={`dot ${doing ? "ok pulse" : "off"}`} /> {doing ? "Working" : "Idle"}
                </span>
              </span>
              <span className="doing">{doing ?? ""}</span>
            </div>
          );
        })}
      </section>

      {/* ---- schedule today ---- */}
      <section className="panel span-6">
        <div className="card-head">
          <h2>Schedule today</h2>
          <button className="link small see-all" onClick={() => onChoose("schedules")}>
            <Icon name="plus" size={13} /> Add
          </button>
        </div>
        {schedulesError && <div className="error">{schedulesError}</div>}
        {todayItems.length === 0 ? (
          <Empty icon="calendar" title="Nothing else today" sub="Schedules and reminders due today show up here." />
        ) : (
          <div className="list">
            {todayItems.slice(0, 7).map((x) => (
              <div key={x.key} className="list-item">
                <span className="mono small nowrap" style={{ minWidth: 76 }}>
                  {hhmm(x.when!)}
                </span>
                <span className={`dot ${x.tone}`} />
                <span className="main-col">
                  <span className="title ellipsis">{x.title}</span>
                </span>
                <span className="pill outline">{x.kind.replace("_", " ")}</span>
              </div>
            ))}
          </div>
        )}
      </section>

      {/* ---- projects ---- */}
      <section className="panel span-6">
        <div className="card-head">
          <h2>Projects &amp; documents</h2>
          <button className="link small see-all" onClick={() => onChoose("projects")}>
            View all <Icon name="arrowRight" size={13} />
          </button>
        </div>
        {projects.error && <div className="error">{projects.error}</div>}
        {projectList.length === 0 ? (
          <Empty icon="folder" title="No projects yet" sub="Create one in Projects & Docs; its notes and documents come first in chats." />
        ) : (
          <div className="folders">
            {projectList.slice(0, 6).map((p, i) => (
              <button key={p.name} className="folder" onClick={() => onChoose("projects")} title={p.goal}>
                <span className={`tile lg ${["blue", "violet", "amber", "green", "teal", "red"][i % 6]}`}>
                  <Icon name="folder" size={24} />
                </span>
                <span className="name ellipsis">{p.name}</span>
                <span className="count">
                  {p.documents} document{p.documents === 1 ? "" : "s"}
                </span>
              </button>
            ))}
          </div>
        )}
      </section>

      <BriefPanel />
    </div>
  );
}

function Stat({
  icon,
  tone,
  label,
  value,
  hint,
  alert,
  onClick,
}: {
  icon: IconName;
  tone: string;
  label: string;
  value: number;
  hint: string;
  alert?: boolean;
  onClick: () => void;
}) {
  return (
    <button className={`stat${alert ? " alert" : ""}`} onClick={onClick}>
      <span className="stat-top">
        <span className={`tile ${tone}`}>
          <Icon name={icon} size={18} />
        </span>
        <span className="label">{label}</span>
      </span>
      <span className="value">{value}</span>
      <span className="hint">{hint}</span>
    </button>
  );
}

function SvcRow({ name, ok, state }: { name: string; ok: boolean; state: string }) {
  return (
    <div className="svc">
      <span className={`dot ${ok ? "ok" : state === "…" ? "off" : "warn"}`} />
      <span className="grow">{name}</span>
      <span className={`state ${ok ? "ok" : state === "…" ? "off" : "warn"}`}>{state}</span>
    </div>
  );
}

function Empty({ icon, title, sub }: { icon: IconName; title: string; sub: string }) {
  return (
    <div className="empty compact">
      <Icon name={icon} size={22} />
      <strong>{title}</strong>
      <span className="small muted">{sub}</span>
    </div>
  );
}

// The morning brief, loaded only when asked (it may look up the weather).
function BriefPanel() {
  const [text, setText] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  async function load() {
    setLoading(true);
    setError("");
    try {
      setText((await api<{ text: string }>("/api/brief")).text);
    } catch (e) {
      setError(errText(e));
    } finally {
      setLoading(false);
    }
  }
  return (
    <section className="panel span-12">
      <div className="card-head">
        <h2>Today&apos;s brief</h2>
        <button className="sm" onClick={load} disabled={loading}>
          <Icon name="refresh" size={14} /> {text === null ? "Show brief" : "Refresh"}
        </button>
      </div>
      {error && <div className="error">{error}</div>}
      {text === null && !error && <p className="small muted">Weather, calendar, reminders, goals and tasks in one place.</p>}
      {text !== null && <pre className="brief-text">{text}</pre>}
    </section>
  );
}
