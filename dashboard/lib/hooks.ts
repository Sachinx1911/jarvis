"use client";

import { useCallback, useEffect, useRef, useState } from "react";

// Load data now and every `ms` milliseconds (0 = once). Returns data, error and a reload function.
export function usePoll<T>(load: () => Promise<T>, ms: number, deps: unknown[] = []) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string>("");
  const loadRef = useRef(load);
  loadRef.current = load;

  const reload = useCallback(async () => {
    try {
      setData(await loadRef.current());
      setError("");
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, []);

  useEffect(() => {
    reload();
    if (!ms) return;
    const id = window.setInterval(reload, ms);
    return () => window.clearInterval(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [reload, ms, ...deps]);

  return { data, error, reload };
}

export function errText(e: unknown): string {
  return e instanceof Error ? e.message : String(e);
}

export function money(n: number | null | undefined): string {
  return `$${(n ?? 0).toFixed(2)}`;
}

export function num(n: number | null | undefined): string {
  return (n ?? 0).toLocaleString("en-IN");
}
