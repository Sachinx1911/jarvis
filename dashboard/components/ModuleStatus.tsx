"use client";

// Status of a part of Jarvis built in another phase (jarvis/web/adapters.py).
export type Adapter = {
  installed: boolean;
  wired?: boolean;
  module: string;
  detail?: string;
  error?: string;
  items?: Record<string, unknown>[];
  [key: string]: unknown;
};

export default function ModuleStatus({ title, a }: { title: string; a: Adapter }) {
  const { installed, wired, module, detail, error, items, ...rest } = a;
  const extra = Object.fromEntries(Object.entries(rest).filter(([, v]) => v !== undefined));
  return (
    <div style={{ marginBottom: 12 }}>
      <div className="row">
        <strong>{title}</strong>
        <span className="badge">{!installed ? "not installed" : wired === false ? "not wired" : "installed"}</span>
        <span className="small muted">{module}</span>
      </div>
      {detail && <div className="small muted">{detail}</div>}
      {error && <div className="error">{error}</div>}
      {items && items.length > 0 && (
        <table>
          <thead>
            <tr>
              {Object.keys(items[0]).map((k) => (
                <th key={k}>{k}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {items.map((it, i) => (
              <tr key={i}>
                {Object.keys(items[0]).map((k) => (
                  <td key={k}>{typeof it[k] === "object" ? JSON.stringify(it[k]) : String(it[k] ?? "")}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {installed && wired !== false && Object.keys(extra).length > 0 && <pre>{JSON.stringify(extra, null, 2)}</pre>}
    </div>
  );
}
