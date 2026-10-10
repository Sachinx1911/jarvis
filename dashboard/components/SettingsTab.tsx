"use client";

import { useState } from "react";
import { api } from "@/lib/api";
import { money, num, usePoll } from "@/lib/hooks";
import ModuleStatus, { Adapter } from "./ModuleStatus";

type Settings = {
  stop: { engaged: boolean };
  cloud: { cloud_allowed: boolean; mode: string; approved_providers: string[]; switch: Adapter };
  routes: { route: string; provider: string; model: string; effort: string; max_privacy: string }[];
  dashboard: { host: string; port: number; approval_timeout_s: number; provider_override: string | null };
  home: string;
  modules: Record<string, boolean>;
};
type UsageItem = { day: string; route: string; provider: string; model: string; calls: number; input_tokens: number; output_tokens: number; notional_usd: number; billed_usd: number };
type UsageData = {
  days: number;
  items: UsageItem[];
  per_day: { day: string; calls: number; notional_usd: number; billed_usd: number; tokens: number }[];
  totals: { calls: number; notional_usd: number; billed_usd: number; input_tokens: number; output_tokens: number };
};

export default function SettingsTab({
  stopEngaged,
  onToggleStop,
}: {
  stopEngaged: boolean;
  onToggleStop: (engaged: boolean) => void;
}) {
  const s = usePoll(() => api<Settings>("/api/settings"), 0);
  const [days, setDays] = useState(30);
  const u = usePoll(() => api<UsageData>(`/api/usage?days=${days}`), 15000, [days]);
  const maxDay = Math.max(0.0001, ...(u.data?.per_day ?? []).map((d) => d.notional_usd));

  return (
    <>
      <div className="split">
        <section className="panel">
          <h2>Safety</h2>
          <div className="row">
            <span className="grow">
              Emergency stop: <strong>{stopEngaged ? "ON" : "off"}</strong>
            </span>
            {stopEngaged ? (
              <button onClick={() => onToggleStop(false)}>Release stop</button>
            ) : (
              <button className="danger" onClick={() => onToggleStop(true)}>
                Emergency stop
              </button>
            )}
          </div>
          {s.data && (
            <dl className="kv">
              <dt>Cloud AI</dt>
              <dd>
                {s.data.cloud.cloud_allowed ? "allowed" : "off"} (config/routing.yaml, mode {s.data.cloud.mode})
              </dd>
              <dt>Approved providers</dt>
              <dd>{s.data.cloud.approved_providers.join(", ") || "-"}</dd>
              <dt>Approval timeout</dt>
              <dd>{s.data.dashboard.approval_timeout_s}s, then deny</dd>
              <dt>Dashboard</dt>
              <dd>
                {s.data.dashboard.host}:{s.data.dashboard.port}
                {s.data.dashboard.provider_override ? ` · provider ${s.data.dashboard.provider_override}` : ""}
              </dd>
              <dt>Jarvis home</dt>
              <dd className="small">{s.data.home}</dd>
            </dl>
          )}
          {s.data && <ModuleStatus title="Cloud on/off switch" a={s.data.cloud.switch} />}
          {s.error && <div className="error">{s.error}</div>}
        </section>
        <section className="panel">
          <h2>Model routes</h2>
          <table>
            <thead>
              <tr>
                <th>Route</th>
                <th>Model</th>
                <th>Effort</th>
                <th>Max privacy</th>
              </tr>
            </thead>
            <tbody>
              {(s.data?.routes ?? []).map((r) => (
                <tr key={r.route}>
                  <td>{r.route}</td>
                  <td className="small">
                    {r.provider}/{r.model}
                  </td>
                  <td>{r.effort}</td>
                  <td>{r.max_privacy}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      </div>
      <section className="panel">
        <div className="row">
          <h2 className="grow">Usage</h2>
          <select value={days} onChange={(e) => setDays(Number(e.target.value))} aria-label="Period">
            <option value={1}>today</option>
            <option value={7}>7 days</option>
            <option value={30}>30 days</option>
            <option value={90}>90 days</option>
          </select>
        </div>
        <p className="small muted">
          Notional = what the calls would cost at API prices. Calls through the Claude subscription are not billed per
          call.
        </p>
        {u.error && <div className="error">{u.error}</div>}
        {u.data && (
          <>
            <dl className="kv">
              <dt>Calls</dt>
              <dd>{u.data.totals.calls}</dd>
              <dt>Tokens</dt>
              <dd>
                {num(u.data.totals.input_tokens)} in, {num(u.data.totals.output_tokens)} out
              </dd>
              <dt>Notional</dt>
              <dd>{money(u.data.totals.notional_usd)}</dd>
              <dt>Billed</dt>
              <dd>{money(u.data.totals.billed_usd)}</dd>
            </dl>
            <h3>Per day</h3>
            <table>
              <tbody>
                {u.data.per_day.map((d) => (
                  <tr key={d.day}>
                    <td style={{ width: 110 }}>{d.day}</td>
                    <td>
                      <div className="bar" style={{ width: `${(d.notional_usd / maxDay) * 100}%` }} />
                    </td>
                    <td className="num" style={{ width: 90 }}>
                      {money(d.notional_usd)}
                    </td>
                    <td className="num" style={{ width: 90 }}>
                      {d.calls} calls
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            <h3>By day, route and model</h3>
            <table>
              <thead>
                <tr>
                  <th>Day</th>
                  <th>Route</th>
                  <th>Model</th>
                  <th className="num">Calls</th>
                  <th className="num">Tokens</th>
                  <th className="num">Notional</th>
                  <th className="num">Billed</th>
                </tr>
              </thead>
              <tbody>
                {u.data.items.map((it, i) => (
                  <tr key={i}>
                    <td>{it.day}</td>
                    <td>{it.route}</td>
                    <td className="small">
                      {it.provider}/{it.model}
                    </td>
                    <td className="num">{it.calls}</td>
                    <td className="num">{num(it.input_tokens + it.output_tokens)}</td>
                    <td className="num">{money(it.notional_usd)}</td>
                    <td className="num">{money(it.billed_usd)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            {u.data.items.length === 0 && <p className="muted">No model calls in this period.</p>}
          </>
        )}
      </section>
    </>
  );
}
