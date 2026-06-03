"use client";

import { useCallback, useState } from "react";
import type { Dispatch, SetStateAction } from "react";
import { useSession } from "@/components/session";
import { useDeferredLoad } from "@/components/viewPrimitives";

type ProjectResourceLoader<T> = (token: string, projectId: string | undefined) => Promise<T>;

export function useProjectResource<T>(
  loadResource: ProjectResourceLoader<T>,
  initialData: T | null = null,
): {
  activeProjectId: string | null;
  data: T | null;
  error: string | null;
  getToken: () => Promise<string>;
  loading: boolean;
  reload: () => Promise<void>;
  setData: Dispatch<SetStateAction<T | null>>;
  setError: Dispatch<SetStateAction<string | null>>;
} {
  const { activeProjectId, getToken } = useSession();
  const [data, setData] = useState<T | null>(initialData);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const reload = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setData(await loadResource(await getToken(), activeProjectId ?? undefined));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, [activeProjectId, getToken, loadResource]);

  useDeferredLoad(reload);

  return { activeProjectId, data, error, getToken, loading, reload, setData, setError };
}
