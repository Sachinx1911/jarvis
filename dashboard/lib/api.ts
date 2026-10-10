// API client. The access token comes from the URL fragment (#token=...) printed by
// `jarvis dashboard`; it is kept in sessionStorage (this tab only) and sent as a header.
// There is no cookie auth, so other sites cannot make requests on our behalf (CSRF).

const BASE = process.env.NEXT_PUBLIC_API_BASE ?? "";
const KEY = "jarvis_token";

export function readTokenFromUrl(): void {
  if (typeof window === "undefined") return;
  const m = window.location.hash.match(/token=([A-Za-z0-9_\-]+)/);
  if (m) {
    try {
      sessionStorage.setItem(KEY, m[1]);
    } catch {
      /* storage blocked: token stays in memory below */
    }
    memoryToken = m[1];
    history.replaceState(null, "", window.location.pathname + window.location.search);
  }
}

let memoryToken = "";

export function getToken(): string {
  try {
    return sessionStorage.getItem(KEY) || memoryToken;
  } catch {
    return memoryToken;
  }
}

export function setToken(t: string): void {
  memoryToken = t.trim();
  try {
    sessionStorage.setItem(KEY, memoryToken);
  } catch {
    /* ignore */
  }
}

export function clearToken(): void {
  memoryToken = "";
  try {
    sessionStorage.removeItem(KEY);
  } catch {
    /* ignore */
  }
}

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

export async function api<T = any>(path: string, opts: { method?: string; body?: unknown } = {}): Promise<T> {
  const res = await fetch(BASE + path, {
    method: opts.method ?? "GET",
    headers: {
      "X-Jarvis-Token": getToken(),
      ...(opts.body !== undefined ? { "Content-Type": "application/json" } : {}),
    },
    body: opts.body !== undefined ? JSON.stringify(opts.body) : undefined,
    cache: "no-store",
    credentials: "omit",
  });
  let data: any = null;
  try {
    data = await res.json();
  } catch {
    /* empty body */
  }
  if (!res.ok) {
    const detail = data?.detail;
    const msg = typeof detail === "string" ? detail : detail ? JSON.stringify(detail) : res.statusText;
    if (res.status === 401) window.dispatchEvent(new Event("jarvis-unauthorized"));
    throw new ApiError(res.status, msg);
  }
  return data as T;
}

export const post = <T = any>(path: string, body: unknown = {}) => api<T>(path, { method: "POST", body });
export const patch = <T = any>(path: string, body: unknown) => api<T>(path, { method: "PATCH", body });
