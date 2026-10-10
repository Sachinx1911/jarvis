"use client";

import { useEffect, useRef, useState } from "react";
import { Icon, IconName } from "./icons";
import { Page, Tab } from "./nav";
import { THEME_LABEL, ThemeMode } from "./theme";

export type Notice = {
  key: string;
  icon: IconName;
  tone: "red" | "amber" | "blue" | "green";
  what: string;
  detail: string;
  tab: Tab;
  count: number;
};

export default function TopBar({
  page,
  onMenu,
  mode,
  modeTitle,
  online,
  notices,
  onChoose,
  theme,
  onTheme,
  stopEngaged,
  onToggleStop,
  onPalette,
}: {
  page: Page;
  onMenu: () => void;
  mode: string;
  modeTitle: string;
  online: { label: string; tone: "ok" | "bad" | "warn" | "off" };
  notices: Notice[];
  onChoose: (t: Tab) => void;
  theme: ThemeMode;
  onTheme: () => void;
  stopEngaged: boolean;
  onToggleStop: (engaged: boolean) => void;
  onPalette: () => void;
}) {
  const [open, setOpen] = useState(false);
  const bellRef = useRef<HTMLDivElement>(null);
  const count = notices.reduce((n, x) => n + x.count, 0);

  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (bellRef.current && !bellRef.current.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    window.addEventListener("mousedown", onDown);
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("mousedown", onDown);
      window.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const themeIcon: IconName = theme === "dark" ? "moon" : theme === "light" ? "sun" : "monitor";

  return (
    <header className="topbar">
      <button className="ghost icon-btn menu-btn" onClick={onMenu} aria-label="Open the menu" title="Menu">
        <Icon name="menu" size={20} />
      </button>
      <div className="page-title">
        <h1>{page.label}</h1>
        <div className="sub">{page.subtitle}</div>
      </div>
      <div className="top-actions">
        <button className="ghost hide-md" onClick={onPalette} title="Jump to a page (Ctrl+K or ⌘K)">
          <Icon name="search" size={16} />
          <span>Jump to</span>
          <kbd>⌘K</kbd>
        </button>
        {mode && (
          <span className="status-chip mode-pill hide-phone" title={modeTitle}>
            <Icon name="sparkles" size={14} />
            {mode}
          </span>
        )}
        <span className={`status-chip ${online.tone} hide-phone`} title="From /api/health">
          <span className={`dot ${online.tone}`} />
          {online.label}
        </span>
        <div className="bell" ref={bellRef} style={{ position: "relative" }}>
          <button
            className="ghost icon-btn"
            onClick={() => setOpen(!open)}
            aria-expanded={open}
            aria-haspopup="true"
            aria-label={count ? `Notifications: ${count}` : "Notifications: none"}
            title="Notifications"
          >
            <Icon name="bell" size={19} />
          </button>
          {count > 0 && <span className="count">{count > 99 ? "99+" : count}</span>}
          {open && (
            <div className="popover" role="menu">
              <div className="popover-title">Notifications</div>
              {notices.length === 0 && (
                <div className="empty">
                  <Icon name="check" size={22} />
                  Nothing needs you right now.
                </div>
              )}
              {notices.map((n) => (
                <button
                  key={n.key}
                  className="popover-item"
                  role="menuitem"
                  onClick={() => {
                    setOpen(false);
                    onChoose(n.tab);
                  }}
                >
                  <span className={`tile ${n.tone}`}>
                    <Icon name={n.icon} size={16} />
                  </span>
                  <span className="grow">
                    <span className="what">{n.what}</span>
                    <span className="small muted" style={{ display: "block" }}>
                      {n.detail}
                    </span>
                  </span>
                </button>
              ))}
            </div>
          )}
        </div>
        <button
          className="ghost icon-btn"
          onClick={onTheme}
          title={`Theme: ${THEME_LABEL[theme]} (click to change)`}
          aria-label={`Theme: ${THEME_LABEL[theme]}. Change theme`}
        >
          <Icon name={themeIcon} size={18} />
        </button>
        {stopEngaged ? (
          <button className="stop-btn release" onClick={() => onToggleStop(false)}>
            <Icon name="play" size={16} />
            <span className="stop-long">Release stop</span>
            <span className="stop-short">Release</span>
          </button>
        ) : (
          <button
            className="danger stop-btn"
            onClick={() => onToggleStop(true)}
            title="Block every model and tool call now"
            aria-label="Emergency stop"
          >
            <Icon name="stop" size={17} />
            <span className="stop-long">Emergency stop</span>
            <span className="stop-short">Stop</span>
          </button>
        )}
      </div>
    </header>
  );
}
