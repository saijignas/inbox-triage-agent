"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { ApiError } from "./api";

export interface Resource<T> {
  data: T | null;
  error: string | null;
  loading: boolean;
  reload: () => Promise<void>;
}

/**
 * Loads data with loading/error state. Redirects to /login on 401.
 * `load` and `pollWhile` must be stable (useCallback / module-level) to avoid refetch loops.
 * While `pollWhile(data)` is true the resource refetches every 1.5s (used for queued/running triage).
 */
export function useResource<T>(load: () => Promise<T>, pollWhile?: (data: T) => boolean): Resource<T> {
  const router = useRouter();
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const reload = useCallback(async () => {
    try {
      setData(await load());
      setError(null);
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) {
        router.replace("/login");
        return;
      }
      setError(e instanceof Error ? e.message : "Something went wrong");
    } finally {
      setLoading(false);
    }
  }, [load, router]);

  useEffect(() => {
    void reload();
  }, [reload]);

  useEffect(() => {
    if (data === null || !pollWhile || !pollWhile(data)) return;
    const t = setTimeout(() => void reload(), 1500);
    return () => clearTimeout(t);
  }, [data, pollWhile, reload]);

  return { data, error, loading, reload };
}
