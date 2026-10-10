"use client";

import { useState } from "react";
import { api, post } from "@/lib/api";
import { errText, usePoll } from "@/lib/hooks";

// A rule per argument: {kind: value}, e.g. {"glob": "notes/*.md"} or {"max_chars": 2000}.
type Constraints = Record<string, Record<string, unknown>>;

type Grant = {
  id: string;
  tool: string;
  tier: string;
  constraints: Constraints;
  created: string;
  expires: string;
  max_uses: number;
  uses: number;
  revoked: boolean;
  note: string;
  active: boolean;
  last_used: string | null;
};

type GrantUse = { ts: string; task_id: string | null; arguments: Record<string, unknown> };

type GrantsData ={ items: Grant[]; tools: { name: string; tier: string }[]; kinds: string[] };

const KIND_HELP: Record<string, string> = {
  glob: "path pattern inside an allowed folder, e.g. notes/*.md",
  domain: "web host, also matches its subdomains, e.g. example.com",
  max_chars: "the value may be at most this many characters",
  equals: "exactly this text",
  one_of: "one of these, comma-separated",
  any: "any value is fine",
};

type RuleRow = { arg: string; kind: string; value: string };

export default function GrantsTab() {
  const grants = usePoll(() => api<GrantsData>("/api/grants"), 5000);
  const d = grants.data;

  return (
    <>
      <NewGrant data={d} onCreated={grants.reload} />
      <section className="panel">
        <h2>Standing approvals</h2>
        {grants.error && <div className="error">{grants.error}</div>}
        {d && d.items.length === 0 && <p className="muted">No standing approvals yet.</p>}
        {d && d.items.length > 0 && (
          <table>
            <thead>
              <tr>
                <th>ID</th>
                <th>Tool</th>
                <th>Rules</th>
                <th className="num">Uses</th>
                <th>Expires</th>
                <th>Status</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {d.items.map((g) => (
                <GrantRow key={g.id} g={g} onChange={grants.reload} />
              ))}
            </tbody>
          </table>
        )}
      </section>
    </>
  );
}

function grantStatus(g: Grant): string {
  if (g.revoked) return "revoked";
  if (g.active) return "active";
  if (g.uses >= g.max_uses) return "used up";
  return "expired";
}

function ruleText(c: Constraints): string {
  return Object.entries(c)
    .map(([arg, rule]) =>
      Object.entries(rule)
        .map(([kind, v]) => `${arg} ${kind} ${Array.isArray(v) ? v.join(", ") : kind === "any" ? "" : String(v)}`.trim())
        .join("; "),
    )
    .join("; ");
}

function GrantRow({ g, onChange }: { g: Grant; onChange: () => void }) {
  const [open, setOpen] = useState(false);
  const [uses, setUses] = useState<GrantUse[] | null>(null);
  const [error, setError] = useState("");
  const status = grantStatus(g);

  async function toggle() {
    const next = !open;
    setOpen(next);
    if (!next) return;
    setError("");
    try {
      const r = await api<{ items: GrantUse[] }>(`/api/grants/${encodeURIComponent(g.id)}/uses`);
      setUses(r.items ?? []);
    } catch (e) {
      setError(errText(e));
    }
  }

  async function revoke() {
    if (!confirm(`Revoke ${g.id}? Jarvis will ask you again before using ${g.tool}.`)) return;
    setError("");
    try {
      await post(`/api/grants/${encodeURIComponent(g.id)}/revoke`);
      onChange();
    } catch (e) {
      setError(errText(e));
    }
  }

  return (
    <>
      <tr className="clickable" onClick={toggle}>
        <td>{g.id}</td>
        <td>
          {g.tool} <span className={`tier ${g.tier}`}>{g.tier}</span>
          {g.note && <div className="small muted">{g.note}</div>}
        </td>
        <td className="small" style={{ fontFamily: "var(--mono)" }}>
          {ruleText(g.constraints)}
        </td>
        <td className="num">
          {g.uses}/{g.max_uses}
        </td>
        <td className="small">{g.expires}</td>
        <td className={status === "active" ? "status-active" : "status-off"}>{status}</td>
        <td>
          {status === "active" && (
            <button
              className="danger"
              onClick={(e) => {
                e.stopPropagation();
                revoke();
              }}
            >
              Revoke
            </button>
          )}
        </td>
      </tr>
      {(open || error) && (
        <tr>
          <td colSpan={7}>
            {error && <div className="error">{error}</div>}
            {open && (
              <div className="small">
                Created {g.created}
                {g.last_used ? ` · last used ${g.last_used}` : " · never used"}
                {uses === null && !error && <div className="muted">Loading uses…</div>}
                {uses && uses.length === 0 && <div className="muted">Not used yet.</div>}
                {uses && uses.length > 0 && (
                  <table>
                    <thead>
                      <tr>
                        <th>When</th>
                        <th>Task</th>
                        <th>Arguments</th>
                      </tr>
                    </thead>
                    <tbody>
                      {uses.map((u, i) => (
                        <tr key={i}>
                          <td className="small muted" style={{ whiteSpace: "nowrap" }}>
                            {u.ts}
                          </td>
                          <td>{u.task_id || "-"}</td>
                          <td className="cell-clip" title={JSON.stringify(u.arguments)}>
                            {JSON.stringify(u.arguments)}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
              </div>
            )}
          </td>
        </tr>
      )}
    </>
  );
}

function NewGrant({ data, onCreated }: { data: GrantsData | null; onCreated: () => void }) {
  const [tool, setTool] = useState("");
  const [rows, setRows] = useState<RuleRow[]>([{ arg: "", kind: "glob", value: "" }]);
  const [days, setDays] = useState(7);
  const [maxUses, setMaxUses] = useState(20);
  const [note, setNote] = useState("");
  const [error, setError] = useState("");
  const [done, setDone] = useState("");
  const kinds = data?.kinds?.length ? data.kinds : Object.keys(KIND_HELP);

  function setRow(i: number, change: Partial<RuleRow>) {
    setRows(rows.map((r, j) => (j === i ? { ...r, ...change } : r)));
  }

  // Turn the form rows into {arg: {kind: value}}. Returns an error message instead when a row is bad.
  function buildConstraints(): Constraints | string {
    const out: Constraints = {};
    for (const r of rows) {
      const arg = r.arg.trim();
      if (!arg) return "Every rule needs an argument name.";
      let value: unknown;
      if (r.kind === "any") value = true;
      else if (r.kind === "max_chars") {
        const n = Number(r.value);
        if (!Number.isInteger(n) || n <= 0) return `${arg}: max_chars needs a whole number above 0.`;
        value = n;
      } else if (r.kind === "one_of") {
        const list = r.value.split(",").map((x) => x.trim()).filter(Boolean);
        if (!list.length) return `${arg}: one_of needs at least one value.`;
        value = list;
      } else {
        if (!r.value.trim()) return `${arg}: ${r.kind} needs a value.`;
        value = r.value.trim();
      }
      out[arg] = { ...(out[arg] ?? {}), [r.kind]: value };
    }
    return out;
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    setDone("");
    const constraints = buildConstraints();
    if (typeof constraints === "string") {
      setError(constraints);
      return;
    }
    try {
      const g = await post<Grant>("/api/grants", { tool, constraints, days, max_uses: maxUses, note });
      setDone(`Created ${g.id} for ${g.tool}.`);
      setRows([{ arg: "", kind: "glob", value: "" }]);
      setNote("");
      onCreated();
    } catch (err) {
      setError(errText(err));
    }
  }

  return (
    <form className="panel" onSubmit={submit}>
      <h2>New standing approval</h2>
      <div className="notice small">
        Jarvis runs this action without asking only when <strong>every</strong> argument matches a rule. Never for
        send/pay/delete, never in a session that read a prompt injection. Only T1/T2 tools can be granted; T3/T4 actions
        always ask you.
      </div>
      <div className="row" style={{ margin: "8px 0" }}>
        <label className="field">
          Tool
          <select value={tool} onChange={(e) => setTool(e.target.value)}>
            <option value="">choose a tool…</option>
            {(data?.tools ?? []).map((t) => (
              <option key={t.name} value={t.name}>
                {t.name} ({t.tier})
              </option>
            ))}
          </select>
        </label>
        <label className="field">
          Days (1–90)
          <input type="number" min={1} max={90} value={days} onChange={(e) => setDays(Number(e.target.value))} style={{ width: 90 }} />
        </label>
        <label className="field">
          Max uses (1–1000)
          <input
            type="number"
            min={1}
            max={1000}
            value={maxUses}
            onChange={(e) => setMaxUses(Number(e.target.value))}
            style={{ width: 110 }}
          />
        </label>
        <label className="field grow">
          Note (optional)
          <input value={note} onChange={(e) => setNote(e.target.value)} placeholder="why this is allowed" />
        </label>
      </div>
      <h3>Rules (one per argument)</h3>
      {rows.map((r, i) => (
        <div className="rule-row" key={i}>
          <input value={r.arg} onChange={(e) => setRow(i, { arg: e.target.value })} placeholder="argument, e.g. path" aria-label="Argument name" />
          <select value={r.kind} onChange={(e) => setRow(i, { kind: e.target.value })} aria-label="Rule kind" title={KIND_HELP[r.kind]}>
            {kinds.map((k) => (
              <option key={k} value={k}>
                {k}
              </option>
            ))}
          </select>
          {r.kind === "any" ? (
            <span className="small muted">any value</span>
          ) : (
            <input
              type={r.kind === "max_chars" ? "number" : "text"}
              min={r.kind === "max_chars" ? 1 : undefined}
              value={r.value}
              onChange={(e) => setRow(i, { value: e.target.value })}
              placeholder={KIND_HELP[r.kind] ?? "value"}
              aria-label="Rule value"
            />
          )}
          <button type="button" onClick={() => setRows(rows.filter((_, j) => j !== i))} disabled={rows.length === 1}>
            Remove
          </button>
        </div>
      ))}
      <div className="row">
        <button type="button" onClick={() => setRows([...rows, { arg: "", kind: "glob", value: "" }])}>
          Add rule
        </button>
        <span className="grow" />
        <button className="primary" disabled={!tool}>
          Create standing approval
        </button>
      </div>
      {error && <div className="error">{error}</div>}
      {done && <div className="okbox small">{done}</div>}
    </form>
  );
}
