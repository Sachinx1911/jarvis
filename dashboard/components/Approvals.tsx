"use client";

import { useEffect, useState } from "react";
import { post } from "@/lib/api";
import { errText } from "@/lib/hooks";

export type Approval = {
  id: number;
  source: string;
  task_id: string | null;
  tool: string;
  tier: string;
  arguments: Record<string, unknown>;
  reason: string;
  created: number;
  expires: number;
  args_sha256: string;
  outcome: string;
};

export type ApprovalsData = { pending: Approval[]; recent: Approval[]; timeout_s: number; now: number };

// Each pending action shows the exact arguments. Approving sends back the hash of those
// arguments, so a click always refers to what is on screen. T3 needs an extra tick.
export default function Approvals({
  data,
  reload,
  compact = false,
}: {
  data: ApprovalsData;
  reload: () => void;
  compact?: boolean;
}) {
  return (
    <section className="panel" aria-label="Pending approvals">
      <h2>Waiting for your approval ({data.pending.length})</h2>
      {data.pending.length === 0 && <p className="muted">Nothing waiting.</p>}
      {data.pending.map((a) => (
        <ApprovalCard key={a.id} a={a} skew={data.now * 1000 - Date.now()} reload={reload} />
      ))}
      {!compact && data.recent.length > 0 && (
        <>
          <h3>Recent answers</h3>
          <table>
            <thead>
              <tr>
                <th>#</th>
                <th>Tool</th>
                <th>Tier</th>
                <th>From</th>
                <th>Answer</th>
              </tr>
            </thead>
            <tbody>
              {data.recent.map((a) => (
                <tr key={a.id}>
                  <td>{a.id}</td>
                  <td>{a.tool}</td>
                  <td>
                    <span className={`tier ${a.tier}`}>{a.tier}</span>
                  </td>
                  <td>{a.source}</td>
                  <td>{a.outcome}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
    </section>
  );
}

function ApprovalCard({ a, skew, reload }: { a: Approval; skew: number; reload: () => void }) {
  const [checked, setChecked] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [left, setLeft] = useState(0);
  const needsTick = a.tier === "T3" || a.tier === "T4";

  useEffect(() => {
    const tick = () => setLeft(Math.max(0, Math.round(a.expires - (Date.now() + skew) / 1000)));
    tick();
    const id = window.setInterval(tick, 1000);
    return () => window.clearInterval(id);
  }, [a.expires, skew]);

  async function answer(decision: "approve" | "deny") {
    setBusy(true);
    setError("");
    try {
      await post(`/api/approvals/${a.id}`, { decision, args_sha256: decision === "approve" ? a.args_sha256 : "" });
      reload();
    } catch (e) {
      setError(errText(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className={`approval ${a.tier}`}>
      <div className="row">
        <strong>{a.tool}</strong>
        <span className={`tier ${a.tier}`}>{a.tier}</span>
        <span className="small muted">{a.reason}</span>
        <span className="grow" />
        <span className="small muted">
          from {a.source} · auto-deny in {left}s
        </span>
      </div>
      <div className="small muted">Exact arguments:</div>
      <pre>{JSON.stringify(a.arguments, null, 2)}</pre>
      {needsTick && (
        <label className="row small">
          <input type="checkbox" checked={checked} onChange={(e) => setChecked(e.target.checked)} />
          I have read these exact arguments. This action is external or cannot be undone.
        </label>
      )}
      <div className="row" style={{ marginTop: 6 }}>
        <button className="primary" disabled={busy || (needsTick && !checked)} onClick={() => answer("approve")}>
          Approve
        </button>
        <button disabled={busy} onClick={() => answer("deny")}>
          Deny
        </button>
        <span className="small muted">sha256 {a.args_sha256.slice(0, 12)}…</span>
      </div>
      {error && <div className="error">{error}</div>}
    </div>
  );
}
