"use client";

import { useState } from "react";
import { api, patch } from "@/lib/api";
import { errText, usePoll } from "@/lib/hooks";
import ModuleStatus, { Adapter } from "./ModuleStatus";

type ToolRow = { name: string; description: string; tier: string; builtin_tier: string; enabled: boolean; taints: boolean };
type ConnectorsData = {
  registry: string;
  tools: ToolRow[];
  tiers: string[];
  external: Adapter;
  documents: Adapter;
  telegram: Adapter;
  voice: Adapter;
};
type Health = { checks: { name: string; ok: boolean; detail: string }[] };

export default function ConnectorsTab() {
  const c = usePoll(() => api<ConnectorsData>("/api/connectors"), 0);
  const [health, setHealth] = useState<Health | null>(null);
  const [checking, setChecking] = useState(false);
  const [error, setError] = useState("");

  async function edit(name: string, body: { tier?: string; enabled?: boolean }, question: string) {
    if (!confirm(question)) return;
    setError("");
    try {
      await patch(`/api/connectors/tools/${name}`, body);
      c.reload();
    } catch (e) {
      setError(errText(e));
    }
  }

  async function check() {
    setChecking(true);
    try {
      setHealth(await api<Health>("/api/connectors/health"));
    } catch (e) {
      setError(errText(e));
    } finally {
      setChecking(false);
    }
  }

  const d = c.data;
  return (
    <>
      <section className="panel">
        <h2>Built-in tools</h2>
        <p className="small muted">
          From here you can only make a tool safer: disable it or raise its risk tier. Lowering a tier or turning a
          tool back on is done by editing the private registry file{d ? `: ${d.registry}` : ""}.
        </p>
        {(error || c.error) && <div className="error">{error || c.error}</div>}
        <table>
          <thead>
            <tr>
              <th>Tool</th>
              <th>Tier</th>
              <th>Built-in</th>
              <th>Status</th>
              <th>Change</th>
            </tr>
          </thead>
          <tbody>
            {(d?.tools ?? []).map((t) => {
              const higher = (d?.tiers ?? []).filter((x) => x > t.tier);
              return (
                <tr key={t.name}>
                  <td>
                    <strong>{t.name}</strong>
                    {t.taints && <span className="small muted"> · reads outside content</span>}
                    <div className="small muted">{t.description}</div>
                  </td>
                  <td>
                    <span className={`tier ${t.tier}`}>{t.tier}</span>
                  </td>
                  <td>
                    <span className={`tier ${t.builtin_tier}`}>{t.builtin_tier}</span>
                  </td>
                  <td>{t.enabled ? "enabled" : <strong>disabled</strong>}</td>
                  <td>
                    <div className="row">
                      <select
                        value=""
                        onChange={(e) =>
                          e.target.value &&
                          edit(t.name, { tier: e.target.value }, `Raise ${t.name} from ${t.tier} to ${e.target.value}?`)
                        }
                        disabled={higher.length === 0}
                        aria-label={`Raise tier of ${t.name}`}
                      >
                        <option value="">raise tier…</option>
                        {higher.map((x) => (
                          <option key={x}>{x}</option>
                        ))}
                      </select>
                      {t.enabled && (
                        <button onClick={() => edit(t.name, { enabled: false }, `Disable ${t.name}?`)}>Disable</button>
                      )}
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </section>
      <section className="panel">
        <div className="row">
          <h2 className="grow">Health</h2>
          <button onClick={check} disabled={checking}>
            {checking ? "Checking…" : "Run health checks"}
          </button>
        </div>
        {health && (
          <table>
            <tbody>
              {health.checks.map((h) => (
                <tr key={h.name}>
                  <td>{h.name}</td>
                  <td>{h.ok ? <span className="okbox">OK</span> : <span className="error">NOT OK</span>}</td>
                  <td className="small">{h.detail}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
      {d && (
        <section className="panel">
          <h2>Other connectors</h2>
          <ModuleStatus title="Calendar, Gmail and other connectors" a={d.external} />
          <ModuleStatus title="Document library" a={d.documents} />
          <ModuleStatus title="Telegram" a={d.telegram} />
          <ModuleStatus title="Voice" a={d.voice} />
        </section>
      )}
    </>
  );
}
