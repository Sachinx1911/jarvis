"use client";

// Ctrl+K / ⌘K: jump to a page by typing part of its name. It only moves between pages.

import { useEffect, useRef, useState } from "react";
import { Icon } from "./icons";
import { PAGES, Tab } from "./nav";

export default function CommandPalette({ onChoose, onClose }: { onChoose: (t: Tab) => void; onClose: () => void }) {
  const [q, setQ] = useState("");
  const [sel, setSel] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const words = q.trim().toLowerCase();
  const items = PAGES.filter(
    (p) => !words || p.label.toLowerCase().includes(words) || p.subtitle.toLowerCase().includes(words),
  );

  useEffect(() => inputRef.current?.focus(), []);
  useEffect(() => setSel(0), [q]);

  function go(t: Tab) {
    onChoose(t);
    onClose();
  }

  return (
    <div className="palette-scrim" onMouseDown={onClose}>
      <div
        className="palette"
        role="dialog"
        aria-modal="true"
        aria-label="Jump to a page"
        onMouseDown={(e) => e.stopPropagation()}
      >
        <div className="palette-input">
          <Icon name="search" size={18} className="faint" />
          <input
            ref={inputRef}
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Jump to a page…"
            aria-label="Page name"
            onKeyDown={(e) => {
              if (e.key === "Escape") onClose();
              else if (e.key === "ArrowDown") {
                e.preventDefault();
                setSel((s) => Math.min(items.length - 1, s + 1));
              } else if (e.key === "ArrowUp") {
                e.preventDefault();
                setSel((s) => Math.max(0, s - 1));
              } else if (e.key === "Enter" && items[sel]) go(items[sel].key);
            }}
          />
          <kbd>Esc</kbd>
        </div>
        <div className="palette-list" role="listbox">
          {items.length === 0 && <div className="empty compact">No page matches.</div>}
          {items.map((p, i) => (
            <button
              key={p.key}
              className="palette-item"
              role="option"
              aria-selected={i === sel}
              onMouseEnter={() => setSel(i)}
              onClick={() => go(p.key)}
            >
              <Icon name={p.icon} size={18} />
              <span className="grow">
                {p.label}
                <span className="sub" style={{ display: "block" }}>
                  {p.subtitle}
                </span>
              </span>
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}
