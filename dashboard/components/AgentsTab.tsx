"use client";

import { api } from "@/lib/api";
import { money, num, usePoll } from "@/lib/hooks";

type Run = { id: number; ts: string; task_id: string | null; agent: string; tool: string; tier: string; ok: boolean; arguments: string; result: string };
type AgentsData = {
  runs: Run[];
  by_agent: { agent: string; tool_runs: number; failed: number; last: string }[];
  by_route: { route: string; calls: number; input_tokens: number; output_tokens: number; notional_usd: number; last: string }[];
  events: { ts: string; event: string; agent: string; task_id?: string; route?: string; model?: string; tool?: string; decision?: string }[];
};

export default function AgentsTab() {
  const { data, error } = usePoll(() => api<AgentsData>("/api/agents?limit=100"), 5000);
  if (error) return <div className="error">{error}</div>;
  if (!data) return <p className="muted">Loading…</p>;
  return (
    <>
      <div className="split">
        <section className="panel">
          <h2>Agents (tool use)</h2>
          <table>
            <thead>
              <tr>
                <th>Agent</th>
                <th className="num">Tool runs</th>
                <th className="num">Failed / refused</th>
                <th>Last</th>
              </tr>
            </thead>
            <tbody>
              {data.by_agent.map((a) => (
                <tr key={a.agent}>
                  <td>{a.agent}</td>
                  <td className="num">{a.tool_runs}</td>
                  <td className="num">{a.failed}</td>
                  <td className="small muted">{a.last}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {data.by_agent.length === 0 && <p className="muted">No tool runs yet.</p>}
        </section>
        <section className="panel">
          <h2>Model calls by route</h2>
          <table>
            <thead>
              <tr>
                <th>Route</th>
                <th className="num">Calls</th>
                <th className="num">Tokens</th>
                <th className="num">Notional</th>
              </tr>
            </thead>
            <tbody>
              {data.by_route.map((r) => (
                <tr key={r.route}>
                  <td>{r.route}</td>
                  <td className="num">{r.calls}</td>
                  <td className="num">{num(r.input_tokens + r.output_tokens)}</td>
                  <td className="num">{money(r.notional_usd)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      </div>
      <section className="panel">
        <h2>Recent tool runs</h2>
        <table>
          <thead>
            <tr>
              <th>Time</th>
              <th>Agent</th>
              <th>Task</th>
              <th>Tool</th>
              <th>Tier</th>
              <th>OK</th>
              <th>Arguments</th>
              <th>Result</th>
            </tr>
          </thead>
          <tbody>
            {data.runs.map((r) => (
              <tr key={r.id}>
                <td className="small muted" style={{ whiteSpace: "nowrap" }}>
                  {r.ts}
                </td>
                <td>{r.agent}</td>
                <td>{r.task_id && r.task_id.startsWith("t-") ? r.task_id : "chat"}</td>
                <td>{r.tool}</td>
                <td>
                  <span className={`tier ${r.tier}`}>{r.tier}</span>
                </td>
                <td>{r.ok ? "yes" : "no"}</td>
                <td className="cell-clip" title={r.arguments}>
                  {r.arguments}
                </td>
                <td className="cell-clip" title={r.result}>
                  {r.result}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
      <section className="panel">
        <h2>Recent agent events (audit log)</h2>
        <table>
          <tbody>
            {data.events.map((e, i) => (
              <tr key={i}>
                <td className="small muted" style={{ whiteSpace: "nowrap" }}>
                  {e.ts}
                </td>
                <td>{e.agent}</td>
                <td>{e.event}</td>
                <td>{e.task_id || ""}</td>
                <td>{e.event === "model_call" ? `${e.route} · ${e.model}` : `${e.tool} · ${e.decision}`}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {data.events.length === 0 && <p className="muted">No agent events yet (team tasks write them).</p>}
      </section>
    </>
  );
}
