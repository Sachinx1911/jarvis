"use client";

import { Icon } from "./icons";
import { GROUPS, Tab } from "./nav";

export type NavBadge = { count: number; tone: "alert" | "accent" | "warn" | "neutral"; title: string };
export type Service = { name: string; state: string; tone: "ok" | "warn" | "bad" | "off" };
export type ProviderInfo = { name: string; model: string; detail: string; local: boolean } | null;

export default function Sidebar({
  tab,
  onChoose,
  badges,
  collapsed,
  onToggleCollapse,
  provider,
  services,
}: {
  tab: Tab;
  onChoose: (t: Tab) => void;
  badges: Partial<Record<Tab, NavBadge>>;
  collapsed: boolean;
  onToggleCollapse: () => void;
  provider: ProviderInfo;
  services: Service[];
}) {
  const worst = services.some((s) => s.tone === "bad") ? "bad" : services.some((s) => s.tone === "warn") ? "warn" : "ok";
  return (
    <aside className="sidebar" aria-label="Main navigation">
      <div className="brand">
        <div className="brand-mark" aria-hidden>
          J
        </div>
        <div className="brand-text">
          <div className="brand-name">JARVIS</div>
          <div className="brand-sub">Personal AI assistant</div>
        </div>
        <button
          className="ghost icon-btn sm collapse-btn"
          onClick={onToggleCollapse}
          title="Collapse the sidebar to icons"
          aria-label="Collapse the sidebar to icons"
        >
          <Icon name="chevronLeft" size={16} />
        </button>
      </div>
      <nav className="nav">
        {GROUPS.map((g) => (
          <div className="nav-group" key={g.title}>
            <div className="nav-title">{g.title}</div>
            {g.pages.map((p) => {
              const b = badges[p.key];
              return (
                <button
                  key={p.key}
                  className="nav-item"
                  aria-current={tab === p.key ? "page" : undefined}
                  onClick={() => onChoose(p.key)}
                  title={b ? `${p.label} (${b.title})` : p.label}
                >
                  <Icon name={p.icon} size={19} />
                  <span className="nav-label">{p.label}</span>
                  {b && b.count > 0 && (
                    <>
                      <span className={`badge ${b.tone === "neutral" ? "" : b.tone}`} aria-label={b.title}>
                        {b.count}
                      </span>
                      {b.tone === "alert" && <span className="badge-dot" aria-hidden />}
                    </>
                  )}
                </button>
              );
            })}
          </div>
        ))}
      </nav>
      {collapsed && (
        <button
          className="ghost icon-btn sm expand-btn"
          onClick={onToggleCollapse}
          title="Expand the sidebar"
          aria-label="Expand the sidebar"
        >
          <Icon name="chevronRight" size={16} />
        </button>
      )}
      <div className="side-card" aria-label="AI provider and services">
        <div className="rail-only" title={services.map((s) => `${s.name}: ${s.state}`).join("\n")}>
          <span className={`dot ${worst}`} />
        </div>
        <div className="hide-rail">
          <div className="label">AI provider</div>
          <div className="provider" title={provider?.detail}>
            <Icon name="sparkles" size={15} />
            <span>{provider ? provider.name : "…"}</span>
          </div>
          {provider?.model && <div className="model">{provider.model}</div>}
          <div className="model" style={{ fontFamily: "inherit" }}>
            {provider ? `Local models: ${provider.local ? "in use" : "off"}` : ""}
          </div>
          <div className="label" style={{ marginTop: 10, marginBottom: 2 }}>
            Services
          </div>
          {services.map((s) => (
            <div className="svc" key={s.name}>
              <span className={`dot ${s.tone}`} />
              <span className="grow">{s.name}</span>
              <span className={`state ${s.tone}`}>{s.state}</span>
            </div>
          ))}
        </div>
      </div>
    </aside>
  );
}
