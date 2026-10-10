// Shapes of the existing endpoints the shell and Home read (only the fields used here),
// plus small helpers that turn them into honest status words.

export type Health = {
  ok: boolean;
  stop_engaged: boolean;
  pending_approvals: number;
  running_tasks: string[];
  chats: number;
};

export type Route = { route: string; provider: string | null; model: string | null; effort: string | null };
export type SettingsLite = {
  routes: Route[];
  cloud: { cloud_allowed: boolean; mode: string | null };
  dashboard: { provider_override: string | null };
};

export type ScheduleLite = {
  id: string;
  name: string;
  kind: string;
  cron: string;
  enabled: boolean;
  output: string;
  next_run_at: string | null;
  last_status: string | null;
};
export type SchedulesLite = { items: ScheduleLite[]; pending_approvals: number; running_here: boolean };

export type TaskLite = {
  id: string;
  title: string;
  state: string;
  project: string | null;
  priority: number;
  current_step: string | null;
  running: boolean;
  updated_at: string;
  plan?: Record<string, unknown>;
  checkpoint?: Record<string, unknown>;
};
export type TasksLite = { items: TaskLite[]; running: string[] };

export const FINAL_STATES = ["COMPLETED", "FAILED", "CANCELLED"];

const PROVIDER_NAMES: Record<string, string> = {
  claude_code: "Claude",
  claude: "Claude API",
  local: "Local model",
  fake: "Test provider",
};
const PROVIDER_DETAIL: Record<string, string> = {
  claude_code: "Claude subscription, through the Claude Code CLI",
  claude: "Anthropic API (API key)",
  local: "Local model on this computer",
  fake: "Fake provider for tests (no real model)",
};

export function providerName(p: string | null | undefined): string {
  return p ? (PROVIDER_NAMES[p] ?? p) : "unknown";
}

// What actually answers chats and tasks started here: the dashboard override, else the main_chat route.
export function aiMode(s: SettingsLite | null) {
  if (!s) return null;
  const main = s.routes.find((r) => r.route === "main_chat") ?? s.routes[0];
  const provider = s.dashboard.provider_override || main?.provider || "";
  const model = s.dashboard.provider_override ? "" : (main?.model ?? "");
  const local = provider === "local" || s.routes.some((r) => r.provider === "local");
  return {
    provider,
    model,
    name: providerName(provider),
    detail: PROVIDER_DETAIL[provider] ?? provider,
    local,
    pill: `${providerName(provider)} · local ${local ? "on" : "off"}`,
  };
}

// "2026-10-11T09:00:00+05:30" -> Date (or null).
export function toDate(iso: string | null | undefined): Date | null {
  if (!iso) return null;
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? null : d;
}

export function hhmm(d: Date): string {
  return d.toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit", hour12: true });
}

export function sameDay(a: Date, b: Date): boolean {
  return a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate();
}

// Stages a task has passed, from its saved plan and checkpoint (jarvis/agents/orchestrator.py):
// team = planned, research, report, checked; solo = planned, report, checked. Null when there is no plan yet.
export function taskStages(t: TaskLite): { done: number; total: number; label: string } | null {
  const plan = t.plan ?? {};
  const cp = t.checkpoint ?? {};
  if (!plan || Object.keys(plan).length === 0) return null;
  const team = Array.isArray((plan as { research?: unknown }).research);
  const total = team ? 4 : 3;
  let done = 1;
  if (team && "research" in cp) done += 1;
  if ("report" in cp) done += 1;
  if (t.state === "COMPLETED") done = total;
  const names = team ? ["planned", "research done", "report written", "checked"] : ["planned", "report written", "checked"];
  return { done, total, label: names[done - 1] ?? "" };
}

export const STATE_TONE: Record<string, string> = {
  BACKLOG: "off",
  SCHEDULED: "info",
  PLANNED: "info",
  RUNNING: "accent",
  WAITING_APPROVAL: "warn",
  VERIFYING: "accent",
  PAUSED: "warn",
  COMPLETED: "ok",
  FAILED: "bad",
  CANCELLED: "off",
};

export function stateWord(state: string): string {
  return state === "WAITING_APPROVAL" ? "needs approval" : state.toLowerCase();
}
