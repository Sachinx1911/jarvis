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
import HomeTab from "./HomeTab";
import OfficeTab from "./OfficeTab";
import Sidebar, { NavBadge, Service } from "./Sidebar";
import TopBar, { Notice } from "./TopBar";
import CommandPalette from "./CommandPalette";
import { Icon } from "./icons";
import { isTab, pageOf, Tab } from "./nav";
import { getTheme, nextTheme, setTheme, ThemeMode } from "./theme";
import { aiMode, FINAL_STATES, Health, SchedulesLite, SettingsLite, TasksLite } from "./system";
import { DEFAULT_PREFS, loadPrefs, savePrefs, VoicePrefs } from "./voice";

const PAGE_KEY = "jarvis_page";
const RAIL_KEY = "jarvis_sidebar";

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
    <div className="gate">
      <form className="panel" onSubmit={submit}>
        <div className="brand">
          <div className="brand-mark" aria-hidden>
            J
          </div>
          <div className="brand-text">
            <div className="brand-name">JARVIS</div>
            <div className="brand-sub">Personal AI assistant</div>
          </div>
        </div>
        <h2>Access token needed</h2>
        <p className="muted small">
          Start Jarvis with the Desktop shortcut or <code>jarvis app</code> (it opens this page with the token), or
          paste the token printed by <code>jarvis dashboard</code> here. It is kept only in this
          browser tab.
        </p>
        <div className="row" style={{ marginTop: 16 }}>
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
  const [tab, setTab] = useState<Tab>("home");
  const stop = usePoll(() => api<{ engaged: boolean; detail: string }>("/api/stop"), 3000);
  const approvals = usePoll(() => api<ApprovalsData>("/api/approvals"), 1500);
  const health = usePoll(() => api<Health>("/api/health"), 10000);
  const settings = usePoll(() => api<SettingsLite>("/api/settings"), 0);
  const schedules = usePoll(() => api<SchedulesLite>("/api/schedules/all"), 30000);
  const tasks = usePoll(() => api<TasksLite>("/api/tasks"), 5000);
  const [stopError, setStopError] = useState("");
  const [inject, setInject] = useState<Inject | null>(null);
  const [focusTask, setFocusTask] = useState<string | null>(null);
  const [collapsed, setCollapsed] = useState(false);
  const [navOpen, setNavOpen] = useState(false);
  const [theme, setThemeState] = useState<ThemeMode>("dark");
  const [palette, setPalette] = useState(false);
  const [prefs, setPrefs] = useState<VoicePrefs>(DEFAULT_PREFS);
  const [handsFree, setHandsFree] = useState(false);
  const pending = approvals.data?.pending ?? [];

  useEffect(() => {
    try {
      const saved = localStorage.getItem(PAGE_KEY);
      if (isTab(saved)) setTab(saved);
      setCollapsed(localStorage.getItem(RAIL_KEY) === "rail");
      setPrefs(loadPrefs());
    } catch {
      /* ignore */
    }
    setThemeState(getTheme());
  }, []);

  // Ctrl+K / ⌘K opens the page jumper; Escape closes the mobile menu.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setPalette((p) => !p);
      } else if (e.key === "Escape") setNavOpen(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  function updatePrefs(p: VoicePrefs) {
    setPrefs(p);
    savePrefs(p);
    if (p.mode === "ptt") setHandsFree(false);
  }

  function choose(t: Tab) {
    setTab(t);
    setNavOpen(false);
    // Hands-free lives on Command Center and Chat only; any other page releases the microphone.
    if (t !== "home" && t !== "chat") setHandsFree(false);
    try {
      localStorage.setItem(PAGE_KEY, t);
    } catch {
      /* ignore */
    }
  }

  function toggleCollapsed() {
    const next = !collapsed;
    setCollapsed(next);
    try {
      localStorage.setItem(RAIL_KEY, next ? "rail" : "full");
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

  // The emergency stop also switches hands-free off (and so releases the microphone).
  useEffect(() => {
    if (engaged) setHandsFree(false);
  }, [engaged]);

  const mode = aiMode(settings.data);
  const unattended = schedules.data?.pending_approvals ?? 0;
  const active = (tasks.data?.items ?? []).filter((t) => !FINAL_STATES.includes(t.state));

  const badges: Partial<Record<Tab, NavBadge>> = {};
  if (pending.length > 0)
    badges.tasks = { count: pending.length, tone: "alert", title: `${pending.length} waiting for approval` };
  else if (active.length > 0) badges.tasks = { count: active.length, tone: "accent", title: `${active.length} active tasks` };
  if (unattended > 0)
    badges.schedules = { count: unattended, tone: "warn", title: `${unattended} from scheduled runs waiting` };

  const services: Service[] = [
    health.error
      ? { name: "Jarvis service", state: "Offline", tone: "bad" }
      : { name: "Jarvis service", state: health.data ? "Online" : "…", tone: health.data ? "ok" : "off" },
    schedules.data
      ? schedules.data.running_here
        ? { name: "Scheduler", state: "Running", tone: "ok" }
        : { name: "Scheduler", state: "Not running", tone: "warn" }
      : { name: "Scheduler", state: "…", tone: "off" },
    engaged ? { name: "Emergency stop", state: "ON", tone: "bad" } : { name: "Emergency stop", state: "Off", tone: "ok" },
  ];

  const notices: Notice[] = [];
  if (pending.length > 0)
    notices.push({
      key: "approvals",
      icon: "shield",
      tone: "amber",
      what: `${pending.length} action${pending.length === 1 ? "" : "s"} waiting for your approval`,
      detail: pending.map((a) => `${a.tool} (${a.tier})`).join(", "),
      tab: "tasks",
      count: pending.length,
    });
  if (unattended > 0)
    notices.push({
      key: "unattended",
      icon: "calendar",
      tone: "amber",
      what: `${unattended} action${unattended === 1 ? "" : "s"} from scheduled runs waiting`,
      detail: "Open Schedules & Reminders to approve or deny",
      tab: "schedules",
      count: unattended,
    });
  if (engaged)
    notices.push({ key: "stop", icon: "stop", tone: "red", what: "Emergency stop is ON", detail: "Jarvis will not call any model or tool", tab: "settings", count: 1 });
  if (health.error)
    notices.push({ key: "health", icon: "alert", tone: "red", what: "Jarvis service not answering", detail: health.error, tab: "setup", count: 1 });

  const online: { label: string; tone: "ok" | "bad" | "warn" | "off" } = health.error
    ? { label: "Offline", tone: "bad" }
    : engaged
      ? { label: "Stopped", tone: "warn" }
      : health.data
        ? { label: "System online", tone: "ok" }
        : { label: "Checking…", tone: "off" };

  return (
    <div className={`shell${collapsed ? " collapsed" : ""}${navOpen ? " nav-open" : ""}`}>
      <Sidebar
        tab={tab}
        onChoose={choose}
        badges={badges}
        collapsed={collapsed}
        onToggleCollapse={toggleCollapsed}
        provider={mode ? { name: mode.name, model: mode.model, detail: mode.detail, local: mode.local } : null}
        services={services}
      />
      <div className="scrim" onClick={() => setNavOpen(false)} aria-hidden />
      <div className="main">
        <TopBar
          page={pageOf(tab)}
          onMenu={() => setNavOpen(true)}
          mode={mode?.pill ?? ""}
          modeTitle={
            mode
              ? `${mode.detail}${mode.model ? ` · ${mode.model}` : ""}. Local models: ${mode.local ? "in use" : "measured, not in use"}.`
              : ""
          }
          online={online}
          notices={notices}
          onChoose={choose}
          theme={theme}
          onTheme={() => {
            const t = nextTheme(theme);
            setTheme(t);
            setThemeState(t);
          }}
          stopEngaged={engaged}
          onToggleStop={toggleStop}
          onPalette={() => setPalette(true)}
        />
        <main className="content">
          {engaged && (
            <div className="stopbar" role="alert">
              <span className="tile sm">
                <Icon name="stop" size={16} />
              </span>
              <span>
                <strong>Emergency stop is ON.</strong>{" "}
                <span className="small">Jarvis will not call any model or tool. {stop.data?.detail}</span>
              </span>
            </div>
          )}
          {(stopError || stop.error) && <div className="error">{stopError || stop.error}</div>}

          {pending.length > 0 && tab !== "tasks" && (
            <Approvals data={approvals.data!} reload={approvals.reload} compact />
          )}

          {tab === "home" && (
            <HomeTab
              tasks={tasks.data}
              tasksError={tasks.error}
              schedules={schedules.data}
              schedulesError={schedules.error}
              settings={settings.data}
              health={health.data}
              healthError={health.error}
              pendingApprovals={pending.length}
              prefs={prefs}
              onPrefs={updatePrefs}
              handsFree={handsFree}
              onHandsFree={setHandsFree}
              stopEngaged={engaged}
              onChoose={choose}
              onAsk={(text) => {
                setInject({ type: "message", text });
                choose("chat");
              }}
              onOpenTask={(id) => {
                setFocusTask(id);
                choose("tasks");
              }}
              onTaskCreated={tasks.reload}
            />
          )}
          {tab === "chat" && (
            <ChatTab
              inject={inject}
              onInjected={() => setInject(null)}
              prefs={prefs}
              onPrefs={updatePrefs}
              handsFree={handsFree}
              onHandsFree={setHandsFree}
              pendingApprovals={pending.length}
              stopEngaged={engaged}
            />
          )}
          {tab === "office" && <OfficeTab />}
          {tab === "memory" && <MemoryTab />}
          {tab === "tasks" && (
            <TasksTab
              approvals={approvals.data}
              reloadApprovals={approvals.reload}
              focus={focusTask}
              onFocused={() => setFocusTask(null)}
            />
          )}
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
        </main>
      </div>
      {palette && <CommandPalette onChoose={choose} onClose={() => setPalette(false)} />}
    </div>
  );
}
