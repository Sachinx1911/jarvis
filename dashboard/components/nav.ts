// Pages of the dashboard, grouped for the sidebar. The order here is the order on screen.
// Groups follow what the user does: talk, work, teach, life, set up.

import type { IconName } from "./icons";

export type Tab =
  | "home"
  | "chat"
  | "tasks"
  | "projects"
  | "schedules"
  | "agents"
  | "teach"
  | "memory"
  | "india"
  | "connectors"
  | "grants"
  | "setup"
  | "settings";

export type Page = { key: Tab; label: string; icon: IconName; subtitle: string };

export const GROUPS: { title: string; pages: Page[] }[] = [
  {
    title: "Home",
    pages: [
      { key: "home", label: "Command Center", icon: "home", subtitle: "Your day at a glance; talk to Jarvis" },
      { key: "chat", label: "Chat", icon: "chat", subtitle: "Talk to Jarvis in English or मराठी" },
    ],
  },
  {
    title: "Work",
    pages: [
      { key: "tasks", label: "Tasks", icon: "tasks", subtitle: "Approvals, the task board and receipts" },
      { key: "projects", label: "Projects & Docs", icon: "folder", subtitle: "Project notes and the documents Jarvis may read" },
      { key: "schedules", label: "Schedules", icon: "calendar", subtitle: "Schedules, reminders, triggers and the morning brief" },
    ],
  },
  {
    title: "Jarvis learns",
    pages: [
      { key: "memory", label: "Memory", icon: "memory", subtitle: "Core memory, what Jarvis remembers, and where it came from" },
      { key: "teach", label: "Teach", icon: "teach", subtitle: "Show Jarvis a task once and turn it into a skill" },
      { key: "agents", label: "Agents", icon: "agents", subtitle: "What the agent team did, tool by tool" },
    ],
  },
  {
    title: "Life",
    pages: [{ key: "india", label: "India", icon: "rupee", subtitle: "Bills, mutual fund NAVs, tax dates and the document wallet" }],
  },
  {
    title: "Settings",
    pages: [
      { key: "setup", label: "Setup", icon: "wrench", subtitle: "Keys, voice models, downloads and checks" },
      { key: "connectors", label: "Connectors", icon: "plug", subtitle: "Tools, their risk tiers and connector health" },
      { key: "grants", label: "Standing approvals", icon: "shield", subtitle: "Actions Jarvis may repeat without asking, within rules" },
      { key: "settings", label: "Settings & Usage", icon: "sliders", subtitle: "Safety, model routes and usage" },
    ],
  },
];

export const PAGES: Page[] = GROUPS.flatMap((g) => g.pages);

export function pageOf(key: Tab): Page {
  return PAGES.find((p) => p.key === key) ?? PAGES[0];
}

export function isTab(value: string | null): value is Tab {
  return !!value && PAGES.some((p) => p.key === value);
}
