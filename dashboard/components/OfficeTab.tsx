"use client";

// The Office (PLAN.md 18.2 "Agent HQ", section 27): every loka (office) as rooms with its teams, the
// Brain in the middle, "N agents · M running", and what waits for you. Every number comes from
// /api/office (tables and files); nothing is invented here.

import { useState } from "react";
import { api, ApiError, post } from "@/lib/api";
import { errText, usePoll } from "@/lib/hooks";
import { Icon } from "./icons";
import { STATE_TONE, stateWord } from "./system";

type Member = { name: string; role: string; profile: string };
type RunningNow = { task_id: string; title: string; current_step: string | null; member?: string };
type Room = {
  slug: string;
  name: string;
  purpose: string;
  colour: string;
  members: Member[];
  tasks: { done: number; running: number; waiting: number; failed: number };
  last_run: string | null;
  running_now: RunningNow[];
};
type Office = {
  slug: string;
  name: string;
  kind: string;
  archived: boolean;
  brief: string;
  language: string;
  today: { line: string; used: Record<string, number>; caps: Record<string, number | null>; over: string | null };
  needs_regrant: string[];
  teams: Room[];
  tasks_total: Record<string, number>;
  memories: number;
};
type OfficeData = {
  offices: Office[];
  brain: {
    memories: number;
    documents: number;
    core_memory: { present: boolean; files: { name: string; lines: number; chars: number }[]; lines: number; chars: number };
    skills: { name: string; uses: number }[];
  };
  agents: { total: number; running: number };
  waiting: { approvals: number; scheduled_approvals: number; needs_choice: number; tasks_waiting_approval: number };
  ts: string;
};
type Panel = {
  office: { slug: string; name: string; archived: boolean };
  team: { slug: string; name: string; purpose: string; colour: string; lead_brief: string; archived: boolean };
  overview: { done: number; running: number; waiting: number; failed: number; total: number; last_run: string | null; members: number };
  agents: { name: string; role: string; profile: string; brief: string; tools: string[]; status: "idle" | "running"; current_step: string | null; task_id: string | null }[];
  running_unassigned: RunningNow[];
  tools: { name: string; tier: string | null; enabled: boolean | null; registered: boolean }[];
  skills: { name: string; uses: number }[];
  recent_tasks: { id: string; title: string; state: string; updated_at: string; current_step: string | null; team_label: string | null }[];
};
type Candidate = { slug: string; name: string; score: number; matched: string[] };
type Created = { id: string; workspace: string; started: boolean };

function when(iso: string | null | undefined): string {
  if (!iso) return "never";
  const s = /[zZ]|[+-]\d\d:?\d\d$/.test(iso) ? iso : iso.replace(" ", "T") + "Z";
  const d = new Date(s);
  return isNaN(d.getTime()) ? iso : d.toLocaleString("en-IN", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
}

export default function OfficeTab() {
  const office = usePoll(() => api<OfficeData>("/api/office"), 4000);
  const [open, setOpen] = useState<{ office: string; team: string } | null>(null);
  const d = office.data;
  const offices = d?.offices ?? [];
  const waiting = d ? d.waiting.approvals + d.waiting.scheduled_approvals + d.waiting.tasks_waiting_approval : 0;
  const mid = Math.ceil(offices.length / 2);

  return (
    <div className="office">
      <div className="office-top">
        <div className="office-count">
          <span className="tile sm blue">
            <Icon name="agents" size={16} />
          </span>
          {d ? (
            <span>
              <strong>{d.agents.total}</strong> agents · <strong>{d.agents.running}</strong> running ·{" "}
              <strong className={waiting > 0 ? "office-warn" : ""}>{waiting}</strong> waiting for you
            </span>
          ) : (
            <span className="muted">{office.error ? "Jarvis not answering" : "Loading…"}</span>
          )}
        </div>
        {d && <span className="small muted">as of {when(d.ts)}</span>}
      </div>
      {office.error && <div className="error">{office.error}</div>}

      <AskBox offices={offices.filter((o) => !o.archived)} onCreated={office.reload} />

      <div className="home office-grid">
        {offices.slice(0, mid).map((o) => (
          <OfficeCard key={o.slug} office={o} onRoom={(team) => setOpen({ office: o.slug, team })} />
        ))}
        {d && <BrainCard brain={d.brain} />}
        {offices.slice(mid).map((o) => (
          <OfficeCard key={o.slug} office={o} onRoom={(team) => setOpen({ office: o.slug, team })} />
        ))}
      </div>

      {open && <TeamPanel office={open.office} team={open.team} onClose={() => setOpen(null)} />}
    </div>
  );
}

function AskBox({ offices, onCreated }: { offices: Office[]; onCreated: () => void }) {
  const [goal, setGoal] = useState("");
  const [workspace, setWorkspace] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [choices, setChoices] = useState<{ line: string; candidates: Candidate[] } | null>(null);
  const [created, setCreated] = useState<Created | null>(null);
  const [runNote, setRunNote] = useState("");

  async function submit(ws: string) {
    const text = goal.trim();
    if (!text) return;
    setBusy(true);
    setError("");
    setChoices(null);
    setCreated(null);
    setRunNote("");
    try {
      const r = await post<Created>("/api/tasks", ws ? { goal: text, workspace: ws } : { goal: text });
      setCreated(r);
      setGoal("");
      onCreated();
    } catch (e) {
      if (e instanceof ApiError && e.status === 409) {
        // Dharma routing was unsure: the same read-only route gives the candidates to choose from.
        try {
          const r = await post<{ line: string; candidates: Candidate[] }>("/api/workspaces/route", { goal: text });
          setChoices({ line: r.line, candidates: r.candidates.length ? r.candidates : offices.map((o) => ({ slug: o.slug, name: o.name, score: 0, matched: [] })) });
        } catch (e2) {
          setError(errText(e2));
        }
      } else setError(errText(e));
    } finally {
      setBusy(false);
    }
  }

  async function run(id: string) {
    setRunNote("");
    try {
      const r = await post<{ started: boolean }>(`/api/tasks/${id}/run`);
      setRunNote(r.started ? `${id} is running` : `${id} could not start`);
      onCreated();
    } catch (e) {
      setRunNote(errText(e));
    }
  }

  const officeName = (slug: string) => offices.find((o) => o.slug === slug)?.name ?? slug;

  return (
    <section className="panel office-ask">
      <div className="card-head">
        <h2>Ask any team</h2>
        <span className="small muted">Jarvis routes the task to the loka (office) whose duties match, or asks you</span>
      </div>
      <form
        className="row"
        onSubmit={(e) => {
          e.preventDefault();
          submit(workspace);
        }}
      >
        <input
          className="grow"
          value={goal}
          onChange={(e) => setGoal(e.target.value)}
          placeholder="What should a team do? e.g. compare three laptops under 60k"
          aria-label="Task for a team"
          maxLength={4000}
        />
        <select value={workspace} onChange={(e) => setWorkspace(e.target.value)} aria-label="Office">
          <option value="">Let Jarvis route</option>
          {offices.map((o) => (
            <option key={o.slug} value={o.slug}>
              {o.name}
            </option>
          ))}
        </select>
        <button className="primary" disabled={busy || !goal.trim()}>
          {busy ? "…" : "Create task"}
        </button>
      </form>
      {error && <div className="error">{error}</div>}
      {choices && (
        <div className="notice small office-choices">
          <div>{choices.line || "Which office should take this?"}</div>
          <div className="chips">
            {choices.candidates.map((c) => (
              <button key={c.slug} className="chip" disabled={busy} onClick={() => submit(c.slug)} title={c.matched.join(", ")}>
                {c.name}
              </button>
            ))}
          </div>
        </div>
      )}
      {created && (
        <div className="okbox small row">
          <span className="grow">
            Task <code>{created.id}</code> created in {officeName(created.workspace)}
            {created.started ? " and started" : ""}
          </span>
          {!created.started && (
            <button className="sm" onClick={() => run(created.id)}>
              Run
            </button>
          )}
          {runNote && <span className="muted">{runNote}</span>}
        </div>
      )}
    </section>
  );
}

function BrainCard({ brain }: { brain: OfficeData["brain"] }) {
  const top = brain.skills.slice(0, 5);
  return (
    <section className="panel office-brain span-4">
      <div className="card-head">
        <span className="tile sm violet">
          <Icon name="memory" size={16} />
        </span>
        <h2>The Brain</h2>
        <span className="small muted">Saraswati</span>
      </div>
      <div className="office-brain-stats">
        <div>
          <strong>{brain.memories}</strong>
          <span>memories</span>
        </div>
        <div>
          <strong>{brain.documents}</strong>
          <span>documents</span>
        </div>
        <div>
          <strong>{brain.core_memory.present ? brain.core_memory.lines : 0}</strong>
          <span>core memory lines</span>
        </div>
      </div>
      <div className="small muted" style={{ marginTop: 8 }}>
        {brain.core_memory.present
          ? brain.core_memory.files.map((f) => `${f.name} ${f.lines} lines`).join(" · ")
          : "No core memory yet (profile/USER.md, profile/MEMORY.md)"}
      </div>
      <h3 style={{ marginTop: 14 }}>Skills</h3>
      {top.length === 0 ? (
        <div className="small muted">No skills learned yet.</div>
      ) : (
        <div className="list">
          {top.map((s) => (
            <div key={s.name} className="list-item">
              <span className="main-col title">{s.name}</span>
              <span className="pill outline">{s.uses} uses</span>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}

function OfficeCard({ office, onRoom }: { office: Office; onRoom: (team: string) => void }) {
  const running = office.teams.reduce((n, t) => n + t.tasks.running, 0);
  const states = Object.entries(office.tasks_total);
  return (
    <section className={`panel office-card span-4${office.archived ? " archived" : ""}`}>
      <div className="office-roof">
        <div className="office-roof-inner">
          <h2>{office.name}</h2>
          <span className="small">
            Loka (office) · {office.kind}
            {office.archived ? " · ended" : ""}
          </span>
        </div>
      </div>
      <div className="small muted office-today">
        <span title="Kubera (budget): today's spend against this office's caps">Kubera (budget) · {office.today.line || "no usage today"}</span>
        {office.today.over && <span className="pill warn">{office.today.over}</span>}
      </div>
      {office.needs_regrant.length > 0 && (
        <div className="notice small">
          Needs your fresh grant: {office.needs_regrant.join(", ")} (see Standing approvals)
        </div>
      )}
      <div className="small muted office-meta">
        {office.memories} memories · {states.length === 0 ? "no tasks" : states.map(([s, n]) => `${n} ${stateWord(s)}`).join(" · ")}
        {running > 0 ? ` · ${running} running in teams` : ""}
      </div>
      {office.teams.length === 0 ? (
        <div className="empty compact muted">
          <span>No teams in this office yet. Add one with the Workspaces API or `jarvis team add`.</span>
        </div>
      ) : (
        <div className="office-rooms">
          {office.teams.map((t) => (
            <RoomCard key={t.slug} room={t} onOpen={() => onRoom(t.slug)} />
          ))}
        </div>
      )}
    </section>
  );
}

function RoomCard({ room, onOpen }: { room: Room; onOpen: () => void }) {
  const busy = room.tasks.running > 0;
  const busyMembers = new Set(room.running_now.map((r) => r.member).filter(Boolean));
  return (
    <button className={`office-room tone-${room.colour}${busy ? " busy" : ""}`} onClick={onOpen} title={room.purpose}>
      <div className="office-room-head">
        <strong>{room.name}</strong>
        {room.tasks.waiting > 0 && <span className="pill warn">{room.tasks.waiting} waiting for you</span>}
      </div>
      <div className="office-dots" aria-label={`${room.members.length} members`}>
        {room.members.map((m) => (
          <span
            key={m.name}
            className={`dot${busyMembers.has(m.name) || (busy && busyMembers.size === 0) ? " pulse" : ""}`}
            title={`${m.name} (${m.role})`}
          />
        ))}
      </div>
      <div className="small office-room-counts">
        {room.tasks.done} done · {room.tasks.running} running · {room.tasks.waiting} waiting
        {room.tasks.failed > 0 ? ` · ${room.tasks.failed} failed` : ""}
      </div>
      <div className="small muted">
        {busy && room.running_now[0]?.current_step ? room.running_now[0].current_step : `last run ${when(room.last_run)}`}
      </div>
    </button>
  );
}

function TeamPanel({ office, team, onClose }: { office: string; team: string; onClose: () => void }) {
  const panel = usePoll(() => api<Panel>(`/api/office/${office}/teams/${team}`), 4000, [office, team]);
  const p = panel.data;
  return (
    <aside className="office-drawer" role="dialog" aria-label="Team panel">
      <div className="card-head">
        <h2>{p ? p.team.name : team}</h2>
        {p && <span className="small muted">{p.office.name}</span>}
        <button className="sm" onClick={onClose} aria-label="Close">
          <Icon name="x" size={14} />
        </button>
      </div>
      {panel.error && <div className="error">{panel.error}</div>}
      {!p && !panel.error && <div className="small muted">Loading…</div>}
      {p && (
        <>
          {p.team.purpose && <p className="small muted">{p.team.purpose}</p>}
          <h3>Overview</h3>
          <div className="small">
            {p.overview.total} tasks · {p.overview.done} done · {p.overview.running} running · {p.overview.waiting} waiting ·{" "}
            {p.overview.failed} failed · last run {when(p.overview.last_run)}
          </div>

          <h3>Adhipati (lead)</h3>
          <div className="small muted">{p.team.lead_brief || "No lead brief in the team file."}</div>

          <h3>Gana (members)</h3>
          <div className="list">
            {p.agents.map((a) => (
              <div key={a.name} className="list-item">
                <span className={`dot ${a.status === "running" ? "accent pulse" : "off"}`} />
                <span className="main-col">
                  <span className="title">
                    {a.name} <span className="muted">· {a.role}</span>
                  </span>
                  <div className="small muted">{a.status === "running" ? a.current_step || "running" : "idle"}</div>
                </span>
                {a.task_id && <code className="small">{a.task_id}</code>}
              </div>
            ))}
            {p.running_unassigned.map((r) => (
              <div key={r.task_id} className="list-item">
                <span className="dot accent pulse" />
                <span className="main-col small">
                  {r.task_id}: {r.current_step || r.title}
                </span>
              </div>
            ))}
          </div>

          <h3>Tools</h3>
          {p.tools.length === 0 ? (
            <div className="small muted">Members use their role&apos;s full allowlist (no narrower tool set in the team file).</div>
          ) : (
            <div className="chips">
              {p.tools.map((t) => (
                <span key={t.name} className={`pill ${t.registered ? (t.enabled ? "ok" : "bad") : "off"}`} title={t.tier ? `tier ${t.tier}` : "not registered"}>
                  {t.name}
                  {t.tier ? ` · ${t.tier}` : ""}
                  {t.registered && t.enabled === false ? " · disabled" : ""}
                </span>
              ))}
            </div>
          )}

          <h3>Skills</h3>
          {p.skills.length === 0 ? (
            <div className="small muted">No team skills.</div>
          ) : (
            <div className="chips">
              {p.skills.map((s) => (
                <span key={s.name} className="pill outline">
                  {s.name} · {s.uses} uses
                </span>
              ))}
            </div>
          )}

          <h3>Recent tasks</h3>
          {p.recent_tasks.length === 0 ? (
            <div className="small muted">This team has not run a task yet.</div>
          ) : (
            <div className="list">
              {p.recent_tasks.map((t) => (
                <div key={t.id} className="list-item">
                  <span className="main-col">
                    <span className="title">{t.title}</span>
                    <div className="small muted">
                      {t.id} · {when(t.updated_at)}
                    </div>
                  </span>
                  <span className={`pill ${STATE_TONE[t.state] ?? "off"}`}>{stateWord(t.state)}</span>
                </div>
              ))}
            </div>
          )}
        </>
      )}
    </aside>
  );
}
