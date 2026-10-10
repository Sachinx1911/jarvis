"use client";

import { useState } from "react";
import { api, patch, post } from "@/lib/api";
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
  last_used: string;
  use_count: number;
  masked: boolean;
  score?: number;
};

const TYPES = ["fact", "preference", "procedure", "constraint", "episode"];

export default function MemoryTab() {
  const [q, setQ] = useState("");
  const [query, setQuery] = useState("");
  const [type, setType] = useState("");
  const [all, setAll] = useState(false);
  const [selected, setSelected] = useState<Memory | null>(null);

  const params = new URLSearchParams();
  if (query) params.set("q", query);
  if (type) params.set("type", type);
  if (all) params.set("all", "true");
  const list = usePoll(() => api<{ items: Memory[] }>(`/api/memory?${params}`), 0, [query, type, all]);

  return (
    <div className="split">
      <section className="panel">
        <h2>Memories</h2>
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
          <select value={type} onChange={(e) => setType(e.target.value)} disabled={Boolean(query)}>
            <option value="">All types</option>
            {TYPES.map((t) => (
              <option key={t}>{t}</option>
            ))}
          </select>
          <label className="row">
            <input type="checkbox" checked={all} onChange={(e) => setAll(e.target.checked)} disabled={Boolean(query)} />
            include archived and superseded
          </label>
        </div>
        {list.error && <div className="error">{list.error}</div>}
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
      </section>
      {selected ? (
        <MemoryDetail
          key={selected.id}
          memory={selected}
          onChange={(m) => {
            setSelected(m);
            list.reload();
          }}
        />
      ) : (
        <section className="panel muted">Select a memory to see it.</section>
      )}
    </div>
  );
}

function MemoryDetail({ memory, onChange }: { memory: Memory; onChange: (m: Memory) => void }) {
  const [m, setM] = useState(memory);
  const [editing, setEditing] = useState(false);
  const [form, setForm] = useState({ name: "", summary_en: "", body: "", keywords: "", type: "", sensitivity: "" });
  const [error, setError] = useState("");

  async function reveal() {
    try {
      setM(await post<Memory>(`/api/memory/${m.id}/reveal`));
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
    try {
      onChange(await post<Memory>(`/api/memory/${m.id}/archive`));
    } catch (e) {
      setError(errText(e));
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
      </div>
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
              <dt>Your words</dt>
              <dd>{m.evidence}</dd>
              <dt>Keywords</dt>
              <dd>{m.keywords}</dd>
            </>
          )}
          <dt>Source</dt>
          <dd>
            {m.source}, confidence {m.confidence}
          </dd>
          <dt>Scope</dt>
          <dd>{m.scope || "-"}</dd>
          <dt>Valid from</dt>
          <dd>{m.valid_from}</dd>
          <dt>Used</dt>
          <dd>
            {m.use_count} times{m.last_used ? `, last ${m.last_used}` : ""}
          </dd>
        </dl>
      )}
    </section>
  );
}
