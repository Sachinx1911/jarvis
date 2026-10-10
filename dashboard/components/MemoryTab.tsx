"use client";

import { useEffect, useState } from "react";
import { api, patch, post, put } from "@/lib/api";
import { Icon } from "./icons";
import { errText, usePoll } from "@/lib/hooks";

type Memory = {
  id: string;
  name: string;
  type: string;
  status: string;
  body: string;
  subject: string;
  summary_en: string;
  keywords: string;
  evidence: string;
  sensitivity: string;
  source: string;
  confidence: string;
  scope: string;
  valid_from: string;
  valid_until?: string | null;
  superseded_by?: string | null;
  last_used: string;
  use_count: number;
  expires?: string | null;
  masked: boolean;
  score?: number;
};

// Where a memory came from: GET /api/memory/{id}/source
type Source = {
  id: string;
  masked: boolean;
  evidence: string;
  method: "remember" | "extract" | "interview" | "import" | "unknown" | string;
  saved_at: string;
  last_used: string;
  use_count: number;
  sessions: { session_id: string; message_id: string; ts: string; role: string; excerpt: string }[];
  chain: {
    id: string;
    name: string;
    summary_en: string;
    status: string;
    valid_from: string;
    valid_until: string | null;
    superseded_by: string | null;
  }[];
  newer: string | null;
};

type TrashItem = { file: string; id: string; name: string; type: string; sensitivity: string; masked: boolean; trashed_at: string };

const TYPES = ["fact", "preference", "procedure", "constraint", "episode"];

const METHODS: Record<string, string> = {
  remember: "You asked Jarvis to remember it (/remember)",
  extract: "Jarvis picked it up from a chat",
  interview: "From a profile interview",
  import: "Imported from a file",
  unknown: "Unknown",
};

export default function MemoryTab() {
  const [q, setQ] = useState("");
  const [query, setQuery] = useState("");
  const [type, setType] = useState("");
  const [sensitivity, setSensitivity] = useState("all");
  const [all, setAll] = useState(false);
  const [view, setView] = useState<"list" | "trash">("list");
  const [selected, setSelected] = useState<Memory | null>(null);
  const [openError, setOpenError] = useState("");

  const params = new URLSearchParams();
  if (query) params.set("q", query);
  if (type) params.set("type", type);
  if (all) params.set("all", "true");
  if (sensitivity !== "all") params.set("sensitivity", sensitivity);
  const list = usePoll(() => api<{ items: Memory[] }>(`/api/memory?${params}`), 0, [query, type, all, sensitivity]);

  // Open a memory by id (e.g. an older version in the supersede chain).
  async function openId(id: string) {
    setOpenError("");
    try {
      setSelected(await api<Memory>(`/api/memory/${encodeURIComponent(id)}`));
    } catch (e) {
      setOpenError(errText(e));
    }
  }

  return (
    <>
    <CoreMemoryPanel />
    <div className="split">
      <section className="panel">
        <div className="row">
          <h2 className="grow">{view === "list" ? "Memories" : "Deleted memories (trash)"}</h2>
          <button onClick={() => setView(view === "list" ? "trash" : "list")}>
            {view === "list" ? "Show trash" : "Back to memories"}
          </button>
        </div>
        {view === "trash" ? (
          <TrashList
            onRestored={(m) => {
              setSelected(m);
              setView("list");
              list.reload();
            }}
          />
        ) : (
          <>
            <form
              className="row"
              onSubmit={(e) => {
                e.preventDefault();
                setQuery(q.trim());
              }}
            >
              <input className="grow" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search (English or मराठी)" />
              <button className="primary">Search</button>
              {query && (
                <button
                  type="button"
                  onClick={() => {
                    setQ("");
                    setQuery("");
                  }}
                >
                  Clear
                </button>
              )}
            </form>
            <div className="row small" style={{ margin: "8px 0" }}>
              <select value={type} onChange={(e) => setType(e.target.value)} disabled={Boolean(query)} aria-label="Type">
                <option value="">All types</option>
                {TYPES.map((t) => (
                  <option key={t}>{t}</option>
                ))}
              </select>
              <select value={sensitivity} onChange={(e) => setSensitivity(e.target.value)} aria-label="Sensitivity">
                <option value="all">All</option>
                <option value="sensitive">Sensitive only</option>
                <option value="normal">Not sensitive</option>
              </select>
              <label className="row">
                <input type="checkbox" checked={all} onChange={(e) => setAll(e.target.checked)} disabled={Boolean(query)} />
                include archived and superseded
              </label>
            </div>
            {list.error && <div className="error">{list.error}</div>}
            {openError && <div className="error">{openError}</div>}
            <table>
              <thead>
                <tr>
                  <th>ID</th>
                  <th>Type</th>
                  <th>Summary</th>
                  <th>Status</th>
                </tr>
              </thead>
              <tbody>
                {(list.data?.items ?? []).map((m) => (
                  <tr
                    key={m.id}
                    className={`clickable ${selected?.id === m.id ? "selected" : ""}`}
                    onClick={() => setSelected(m)}
                  >
                    <td>{m.id}</td>
                    <td>{m.type}</td>
                    <td>{m.masked ? <span className="muted">(sensitive, hidden)</span> : m.summary_en || m.name}</td>
                    <td>{m.status}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            {list.data && list.data.items.length === 0 && <p className="muted">No memories found.</p>}
          </>
        )}
      </section>
      {selected ? (
        <MemoryDetail
          key={selected.id}
          memory={selected}
          onOpen={openId}
          onChange={(m) => {
            setSelected(m);
            list.reload();
          }}
          onDeleted={() => {
            setSelected(null);
            list.reload();
          }}
        />
      ) : (
        <section className="panel muted">Select a memory to see it.</section>
      )}
    </div>
    </>
  );
}

function TrashList({ onRestored }: { onRestored: (m: Memory) => void }) {
  const trash = usePoll(() => api<{ items: TrashItem[] }>("/api/memory-trash"), 0);
  const [error, setError] = useState("");

  async function restore(t: TrashItem) {
    setError("");
    try {
      onRestored(await post<Memory>(`/api/memory-trash/${encodeURIComponent(t.file)}/restore`));
    } catch (e) {
      setError(errText(e));
    }
  }

  return (
    <>
      <p className="small muted">
        Deleted memories are moved to <code>memory/.trash</code>. Jarvis does not use them. Restore puts one back.
      </p>
      {(trash.error || error) && <div className="error">{trash.error || error}</div>}
      <table>
        <thead>
          <tr>
            <th>ID</th>
            <th>Type</th>
            <th>Name</th>
            <th>Deleted</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {(trash.data?.items ?? []).map((t) => (
            <tr key={t.file}>
              <td>{t.id}</td>
              <td>{t.type}</td>
              <td>{t.masked ? <span className="muted">(sensitive, hidden)</span> : t.name}</td>
              <td className="small muted">{t.trashed_at}</td>
              <td>
                <button onClick={() => restore(t)}>Restore</button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {trash.data && trash.data.items.length === 0 && <p className="muted">Trash is empty.</p>}
    </>
  );
}

function MemoryDetail({
  memory,
  onChange,
  onOpen,
  onDeleted,
}: {
  memory: Memory;
  onChange: (m: Memory) => void;
  onOpen: (id: string) => void;
  onDeleted: () => void;
}) {
  const [m, setM] = useState(memory);
  const [revealed, setRevealed] = useState(false);
  const [editing, setEditing] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [form, setForm] = useState({ name: "", summary_en: "", body: "", keywords: "", type: "", sensitivity: "" });
  const [error, setError] = useState("");

  async function reveal() {
    setError("");
    try {
      setM(await post<Memory>(`/api/memory/${m.id}/reveal`));
      setRevealed(true);
    } catch (e) {
      setError(errText(e));
    }
  }

  function startEdit() {
    setForm({ name: m.name, summary_en: m.summary_en, body: m.body, keywords: m.keywords, type: m.type, sensitivity: m.sensitivity });
    setEditing(true);
  }

  async function save() {
    setError("");
    try {
      const saved = await patch<Memory>(`/api/memory/${m.id}`, form);
      setM(saved);
      setEditing(false);
      onChange(saved);
    } catch (e) {
      setError(errText(e));
    }
  }

  async function archive() {
    if (!confirm(`Archive ${m.id}? Jarvis will stop using it (the file is kept).`)) return;
    setError("");
    try {
      onChange(await post<Memory>(`/api/memory/${m.id}/archive`));
    } catch (e) {
      setError(errText(e));
    }
  }

  async function activate() {
    setError("");
    try {
      onChange(await post<Memory>(`/api/memory/${m.id}/activate`));
    } catch (e) {
      setError(errText(e));
    }
  }

  async function remove() {
    setError("");
    try {
      await post(`/api/memory/${m.id}/trash`, { confirm: true });
      onDeleted();
    } catch (e) {
      setError(errText(e));
      setConfirmDelete(false);
    }
  }

  return (
    <section className="panel">
      <div className="row">
        <h2 className="grow">
          {m.id} · {m.masked ? "(sensitive)" : m.name}
        </h2>
        {m.masked && <button onClick={reveal}>Reveal on this screen</button>}
        {!m.masked && !editing && <button onClick={startEdit}>Edit</button>}
        {m.status === "active" && <button onClick={archive}>Archive</button>}
        {m.status === "archived" && <button onClick={activate}>Make active again</button>}
        {!confirmDelete && (
          <button className="danger" onClick={() => setConfirmDelete(true)}>
            Delete
          </button>
        )}
      </div>
      {confirmDelete && (
        <div className="notice small">
          <div>
            Delete {m.id}? It is moved to <code>memory/.trash</code> and Jarvis stops using it. You can restore it later
            from <strong>Show trash</strong>.
          </div>
          <div className="row" style={{ marginTop: 6 }}>
            <button className="danger" onClick={remove}>
              Really delete
            </button>
            <button onClick={() => setConfirmDelete(false)}>Cancel</button>
          </div>
        </div>
      )}
      {m.masked && (
        <div className="notice small">This memory is marked sensitive. Revealing it is written to the audit log.</div>
      )}
      {error && <div className="error">{error}</div>}
      {editing ? (
        <div>
          <label className="field">
            Name
            <input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
          </label>
          <label className="field">
            Summary (English)
            <input value={form.summary_en} onChange={(e) => setForm({ ...form, summary_en: e.target.value })} />
          </label>
          <label className="field">
            Body
            <textarea rows={5} value={form.body} onChange={(e) => setForm({ ...form, body: e.target.value })} />
          </label>
          <label className="field">
            Keywords
            <input value={form.keywords} onChange={(e) => setForm({ ...form, keywords: e.target.value })} />
          </label>
          <div className="row">
            <label className="field">
              Type
              <select value={form.type} onChange={(e) => setForm({ ...form, type: e.target.value })}>
                {TYPES.map((t) => (
                  <option key={t}>{t}</option>
                ))}
              </select>
            </label>
            <label className="field">
              Sensitivity
              <select value={form.sensitivity} onChange={(e) => setForm({ ...form, sensitivity: e.target.value })}>
                <option>public</option>
                <option>normal</option>
                <option>sensitive</option>
              </select>
            </label>
          </div>
          <div className="row">
            <button className="primary" onClick={save}>
              Save
            </button>
            <button onClick={() => setEditing(false)}>Cancel</button>
          </div>
        </div>
      ) : (
        <dl className="kv">
          <dt>Type</dt>
          <dd>{m.type}</dd>
          <dt>Status</dt>
          <dd>{m.status}</dd>
          <dt>Sensitivity</dt>
          <dd>{m.sensitivity}</dd>
          {!m.masked && (
            <>
              <dt>Summary</dt>
              <dd>{m.summary_en}</dd>
              <dt>Body</dt>
              <dd style={{ whiteSpace: "pre-wrap" }}>{m.body}</dd>
              <dt>Keywords</dt>
              <dd>{m.keywords}</dd>
            </>
          )}
          <dt>Confidence</dt>
          <dd>{m.confidence}</dd>
          <dt>Scope</dt>
          <dd>{m.scope || "-"}</dd>
          <dt>Valid</dt>
          <dd>
            from {m.valid_from || "-"}
            {m.valid_until ? ` until ${m.valid_until}` : ""}
          </dd>
          {m.expires && (
            <>
              <dt>Expires</dt>
              <dd>{m.expires}</dd>
            </>
          )}
        </dl>
      )}
      <SourcePanel id={m.id} revealed={revealed} onReveal={reveal} onOpen={onOpen} />
    </section>
  );
}

// "Source" panel: the user's own words, how and when it was saved, which chats it came from,
// and older versions it replaced.
function SourcePanel({
  id,
  revealed,
  onReveal,
  onOpen,
}: {
  id: string;
  revealed: boolean;
  onReveal: () => void;
  onOpen: (id: string) => void;
}) {
  const src = usePoll(
    () => api<Source>(`/api/memory/${encodeURIComponent(id)}/source?reveal=${revealed ? "true" : "false"}`),
    0,
    [id, revealed],
  );
  const s = src.data;

  return (
    <div className="subpanel">
      <h3>Source</h3>
      {src.error && <div className="error">{src.error}</div>}
      {!s && !src.error && <span className="muted">Loading…</span>}
      {s && (
        <>
          {s.newer && (
            <div className="notice small">
              This memory was replaced by{" "}
              <button className="link" onClick={() => onOpen(s.newer!)}>
                {s.newer}
              </button>
              .
            </div>
          )}
          {s.masked ? (
            <div className="row small">
              <span className="muted">Your words and chat lines are hidden (sensitive).</span>
              <button onClick={onReveal}>Reveal</button>
            </div>
          ) : (
            s.evidence && <blockquote className="evidence">{s.evidence}</blockquote>
          )}
          <dl className="kv">
            <dt>How saved</dt>
            <dd>{METHODS[s.method] ?? s.method}</dd>
            <dt>Saved</dt>
            <dd>{s.saved_at || "-"}</dd>
            <dt>Last used</dt>
            <dd>{s.last_used || "never"}</dd>
            <dt>Use count</dt>
            <dd>{s.use_count}</dd>
          </dl>
          <h3>From chat{s.sessions.length === 1 ? "" : "s"}</h3>
          {s.sessions.length === 0 && <p className="small muted">Not linked to a saved chat.</p>}
          {s.sessions.map((x, i) => (
            <SessionRef key={`${x.session_id}-${x.message_id}-${i}`} item={x} masked={s.masked} />
          ))}
          {s.chain.length > 0 && (
            <>
              <h3>Older versions (newest first)</h3>
              <ul>
                {s.chain.map((c) => (
                  <li key={c.id} className="small">
                    <button className="link" onClick={() => onOpen(c.id)}>
                      {c.id}
                    </button>{" "}
                    {c.summary_en || c.name}{" "}
                    <span className="muted">
                      · {c.status} · {c.valid_from || "?"} → {c.valid_until || "?"}
                    </span>
                  </li>
                ))}
              </ul>
            </>
          )}
        </>
      )}
    </div>
  );
}

type ChatLine = { id: string; ts: string; role: string; text: string };

function SessionRef({ item, masked }: { item: Source["sessions"][number]; masked: boolean }) {
  const [lines, setLines] = useState<ChatLine[] | null>(null);
  const [open, setOpen] = useState(false);
  const [error, setError] = useState("");

  async function toggle() {
    const next = !open;
    setOpen(next);
    if (!next || lines) return;
    setError("");
    try {
      const r = await api<{ session_id: string; items: ChatLine[] }>(
        `/api/sessions/${encodeURIComponent(item.session_id)}/messages?around=${encodeURIComponent(item.message_id)}&n=6`,
      );
      setLines(r.items);
    } catch (e) {
      setError(errText(e));
    }
  }

  return (
    <div className="small" style={{ marginBottom: 6 }}>
      <div className="row">
        <span>
          chat <code>{item.session_id}</code> · {item.ts} · {item.role}
        </span>
        <button className="link" onClick={toggle} aria-expanded={open}>
          {open ? "Hide chat lines" : "Show chat lines"}
        </button>
      </div>
      {!masked && item.excerpt && !open && <div className="muted">“{item.excerpt}”</div>}
      {open && (
        <>
          {error && <div className="error">{error}</div>}
          {!lines && !error && <span className="muted">Loading…</span>}
          {lines && lines.length === 0 && <span className="muted">No lines found.</span>}
          {lines && lines.length > 0 && (
            <div className="chat-lines">
              {lines.map((l) => (
                <div key={l.id} className={`line ${l.id === item.message_id ? "hit" : ""}`}>
                  <span className="muted">
                    {l.ts} · {l.role}:
                  </span>{" "}
                  {l.text}
                </div>
              ))}
            </div>
          )}
        </>
      )}
    </div>
  );
}


// ---- core memory (profile/USER.md + profile/MEMORY.md, always in the prompt) ----

type CoreStatus = Record<"user" | "memory", { file: string; entries: string[]; used: number; limit: number }>;

const CORE_TITLES = {
  user: { title: "USER.md: who you are", help: "Your lasting preferences, habits and how you like answers. Jarvis reads this with every message." },
  memory: { title: "MEMORY.md: Jarvis's notes", help: "Facts, conventions, lessons and the active project Jarvis keeps in front of itself." },
} as const;

function CoreMemoryPanel() {
  const status = usePoll(() => api<CoreStatus>("/api/core-memory"), 0);
  return (
    <section className="panel">
      <div className="card-head">
        <h2>
          <Icon name="sparkles" size={16} /> Core memory
        </h2>
        <span className="small muted">Two small files in every prompt (idea from Hermes Agent). One entry per paragraph, separated by a line with §.</span>
      </div>
      {status.error && <div className="error">{status.error}</div>}
      {status.data && (
        <div className="split">
          {(["user", "memory"] as const).map((target) => (
            <CoreEditor key={target} target={target} data={status.data![target]} onSaved={status.reload} />
          ))}
        </div>
      )}
    </section>
  );
}

function CoreEditor({ target, data, onSaved }: { target: "user" | "memory"; data: CoreStatus["user"]; onSaved: () => void }) {
  const [text, setText] = useState(data.entries.join("\n§\n"));
  const [dirty, setDirty] = useState(false);
  const [msg, setMsg] = useState("");
  const [err, setErr] = useState("");
  useEffect(() => {
    if (!dirty) setText(data.entries.join("\n§\n"));
  }, [data, dirty]);
  const pct = Math.min(100, Math.round((100 * data.used) / data.limit));
  async function save() {
    setErr("");
    setMsg("");
    try {
      const r = await put<{ saved: string }>(`/api/core-memory/${target}`, { text });
      setMsg(r.saved);
      setDirty(false);
      onSaved();
    } catch (e) {
      setErr(errText(e));
    }
  }
  return (
    <div className="subpanel">
      <h3>{CORE_TITLES[target].title}</h3>
      <p className="small muted" style={{ marginTop: 0 }}>{CORE_TITLES[target].help}</p>
      <div className="row small muted" style={{ marginBottom: 6 }}>
        <span className="grow">
          {data.used}/{data.limit} characters · {data.entries.length} entr{data.entries.length === 1 ? "y" : "ies"}
        </span>
        <span className={pct > 90 ? "warn" : ""}>{pct}%</span>
      </div>
      <div className={`progress${pct > 90 ? " warn" : ""}`} style={{ marginBottom: 8 }}>
        <span style={{ width: `${pct}%` }} />
      </div>
      <textarea
        rows={7}
        value={text}
        placeholder={target === "user" ? "e.g. Prefers short answers in Marathi\n§\nWorks best in the morning" : "e.g. Active project: kitchen renovation\n§\nUses tabs in Python files"}
        onChange={(e) => {
          setText(e.target.value);
          setDirty(true);
        }}
      />
      <div className="row" style={{ marginTop: 8 }}>
        <button className="primary sm" onClick={save} disabled={!dirty}>
          Save
        </button>
        {dirty && (
          <button className="ghost sm" onClick={() => setDirty(false)}>
            Undo changes
          </button>
        )}
        {msg && <span className="small okbox">{msg}</span>}
      </div>
      {err && <div className="error">{err}</div>}
      <p className="small faint" style={{ marginBottom: 0 }}>
        Only everyday facts (P0/P1). Secrets, health, money or ID details are refused here: use /remember-private in Chat.
      </p>
    </div>
  );
}
