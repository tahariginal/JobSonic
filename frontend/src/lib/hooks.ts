"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "./api";

/** Fetch + optional polling. `data` stays on screen while refreshing (no flicker). */
export function useApi<T = any>(path: string | null, pollMs = 0) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string>("");
  const [loading, setLoading] = useState(!!path);
  const pathRef = useRef(path);
  pathRef.current = path;
  const load = useCallback(async () => {
    if (!pathRef.current) return;
    const p = pathRef.current;
    try {
      const d = await api<T>(p);
      if (pathRef.current === p) { setData(d); setError(""); }
    } catch (e: any) {
      if (pathRef.current === p && e?.status !== 401) setError(e?.message ?? "Failed to load");
    } finally { if (pathRef.current === p) setLoading(false); }
  }, []);
  useEffect(() => {
    if (!path) { setData(null); setLoading(false); return; }
    setLoading(true);
    load();
    if (!pollMs) return;
    const t = setInterval(() => { if (document.visibilityState === "visible") load(); }, pollMs);
    return () => clearInterval(t);
  }, [path, pollMs, load]);
  return { data, error, loading, reload: load, setData };
}

export function useDebounced<T>(value: T, ms = 300): T {
  const [v, setV] = useState(value);
  useEffect(() => { const t = setTimeout(() => setV(value), ms); return () => clearTimeout(t); }, [value, ms]);
  return v;
}
