"use client";

import { useEffect, useState } from "react";
import { api, clearToken, getToken, post, readTokenFromUrl, setToken } from "@/lib/api";
import { errText, usePoll } from "@/lib/hooks";
import Approvals, { ApprovalsData } from "./Approvals";
import ChatTab, { Inject } from "./ChatTab";
import ProjectsTab from "./ProjectsTab";
import TeachTab from "./TeachTab";
import SetupTab from "./SetupTab";
import MemoryTab from "./MemoryTab";
import TasksTab from "./TasksTab";
import AgentsTab from "./AgentsTab";
import ConnectorsTab from "./ConnectorsTab";
import SchedulesTab from "./SchedulesTab";
import SettingsTab from "./SettingsTab";
import GrantsTab from "./GrantsTab";
import IndiaTab from "./IndiaTab";

const TABS = [
  ["chat", "Chat"],
  ["memory", "Memory"],
  ["tasks", "Tasks & Approvals"],
  ["grants", "Standing approvals"],
  ["projects", "Projects & Docs"],
  ["teach", "Teach"],
  ["schedules", "Schedules & Reminders"],
  ["india", "India"],
  ["agents", "Agents"],
  ["connectors", "Connectors"],
  ["setup", "Setup"],
  ["settings", "Settings & Usage"],
] as const;
type Tab = (typeof TABS)[number][0];

export default function Dashboard() {
  const [ready, setReady] = useState(false);
  const [authed, setAuthed] = useState(false);

  useEffect(() => {
    readTokenFromUrl();
    setAuthed(Boolean(getToken()));
    setReady(true);
    const onUnauth = () => {
      clearToken();
      setAuthed(false);
    };
    window.addEventListener("jarvis-unauthorized", onUnauth);
    return () => window.removeEventListener("jarvis-unauthorized", onUnauth);
  }, []);

  if (!ready) return null;
  if (!authed) return <TokenGate onDone={() => setAuthed(true)} />;
  return <Main />;
}

function TokenGate({ onDone }: { onDone: () => void }) {
  const [value, setValue] = useState("");
  const [error, setError] = useState("");
  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setToken(value);
    try {
      await api("/api/health");
      onDone();
    } catch (err) {
      clearToken();
      setError(errText(err));
    }
  }
  return (
    <div className="app">
      <header className="top">
        <h1>Jarvis</h1>
      </header>
      <form className="panel" onSubmit={submit} style={{ maxWidth: 520 }}>
        <h2>Access token needed</h2>
        <p className="muted small">
          Start Jarvis with the Desktop shortcut or <code>jarvis app</code> (it opens this page with the token), or
          paste the token printed by <code>jarvis dashboard</code> here. It is kept only in this
          browser tab.
        </p>
        <div className="row">
          <input
            className="grow"
            type="password"
            autoComplete="off"
            value={value}
            onChange={(e) => setValue(e.target.value)}
            aria-label="Access token"
          />
          <button className="primary" disabled={!value.trim()}>
            Open
          </button>
        </div>
        {error && <div className="error">{error}</div>}
      </form>
    </div>
  );
}

function Main() {
  const [tab, setTab] = useState<Tab>("chat");
  const stop = usePoll(() => api<{ engaged: boolean; detail: string }>("/api/stop"), 3000);
  const approvals = usePoll(() => api<ApprovalsData>("/api/approvals"), 1500);
  const [stopError, setStopError] = useState("");
  const [inject, setInject] = useState<Inject | null>(null);
  const pending = approvals.data?.pending ?? [];

  useEffect(() => {
    try {
      const saved = localStorage.getItem("jarvis_tab") as Tab | null;
      if (saved && TABS.some(([k]) => k === saved)) setTab(saved);
    } catch {
      /* ignore */
    }
  }, []);

  function choose(t: Tab) {
    setTab(t);
    try {
      localStorage.setItem("jarvis_tab", t);
    } catch {
      /* ignore */
    }
  }

  async function toggleStop(engaged: boolean) {
    setStopError("");
    try {
      await post("/api/stop", { engaged, reason: engaged ? "stop button" : "" });
      await Promise.all([stop.reload(), approvals.reload()]);
    } catch (e) {
      setStopError(errText(e));
    }
  }

  const engaged = stop.data?.engaged ?? false;

  return (
    <div className="app">
      <header className="top">
        <h1>Jarvis</h1>
        <nav className="tabs" role="tablist">
          {TABS.map(([key, label]) => (
            <button key={key} role="tab" aria-selected={tab === key} onClick={() => choose(key)}>
              {label}
              {key === "tasks" && pending.length > 0 && (
                <>
                  {" "}
                  <span className="badge alert">{pending.length}</span>
                </>
              )}
            </button>
          ))}
        </nav>
        {engaged ? (
          <button onClick={() => toggleStop(false)}>Release stop</button>
        ) : (
          <button className="danger" onClick={() => toggleStop(true)} title="Block every model and tool call now">
            Emergency stop
          </button>
        )}
      </header>

      {engaged && (
        <div className="stopbar" role="alert">
          <strong>Emergency stop is ON.</strong>
          <span className="small">Jarvis will not call any model or tool. {stop.data?.detail}</span>
        </div>
      )}
      {(stopError || stop.error) && <div className="error">{stopError || stop.error}</div>}

      {pending.length > 0 && tab !== "tasks" && (
        <Approvals data={approvals.data!} reload={approvals.reload} compact />
      )}

      {tab === "chat" && <ChatTab inject={inject} onInjected={() => setInject(null)} />}
      {tab === "memory" && <MemoryTab />}
      {tab === "tasks" && <TasksTab approvals={approvals.data} reloadApprovals={approvals.reload} />}
      {tab === "grants" && <GrantsTab />}
      {tab === "agents" && <AgentsTab />}
      {tab === "connectors" && <ConnectorsTab />}
      {tab === "schedules" && <SchedulesTab />}
      {tab === "india" && <IndiaTab />}
      {tab === "projects" && (
        <ProjectsTab
          onUseInChat={(name) => {
            setInject({ type: "project", name });
            choose("chat");
          }}
        />
      )}
      {tab === "teach" && (
        <TeachTab
          onRunInChat={(text) => {
            setInject({ type: "message", text });
            choose("chat");
          }}
          onGoToChat={() => choose("chat")}
        />
      )}
      {tab === "setup" && <SetupTab />}
      {tab === "settings" && <SettingsTab stopEngaged={engaged} onToggleStop={toggleStop} />}
    </div>
  );
}
