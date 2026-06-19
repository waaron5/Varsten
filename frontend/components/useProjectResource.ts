"use client";

import { useCallback, useState } from "react";
import type { Dispatch, SetStateAction } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useSession } from "@/components/session";

type ProjectResourceLoader<T> = (token: string, projectId: string | undefined) => Promise<T>;

// Backed by TanStack Query. The return shape matches the previous local-state
// implementation so consumers did not have to change, but reads are now cached,
// deduped, and revalidated in the background. The `key` discriminates the
// resource (and any params baked into the loader); activeProjectId is folded in
// automatically so the cache is isolated per project and cannot leak across
// tenants when the active project switches.
export function useProjectResource<T>(
  key: readonly unknown[],
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
  const { activeProjectId, getToken, status } = useSession();
  const queryClient = useQueryClient();
  // Lets callers surface a mutation error in the same slot the old hook used,
  // layered over the query's own fetch error.
  const [overrideError, setOverrideError] = useState<string | null>(null);

  const enabled = status === "ready" && Boolean(activeProjectId);
  const queryKey = ["projectResource", activeProjectId, ...key] as const;
  const queryKeyId = JSON.stringify(queryKey);

  const query = useQuery<T>({
    queryKey,
    queryFn: async () => loadResource(await getToken(), activeProjectId ?? undefined),
    enabled,
  });

  const setData = useCallback<Dispatch<SetStateAction<T | null>>>(
    (update) => {
      queryClient.setQueryData<T>(queryKey, (prev) => {
        const current = (prev ?? initialData) as T;
        return typeof update === "function"
          ? (update as (p: T | null) => T)(current)
          : (update as T);
      });
    },
    // queryKey is recreated each render; key it by its serialized identity.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [queryClient, queryKeyId, initialData],
  );

  const reload = useCallback(async () => {
    setOverrideError(null);
    if (!enabled) return;
    await query.refetch();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [enabled, queryKeyId]);

  const queryError =
    query.error instanceof Error ? query.error.message : query.error ? String(query.error) : null;

  return {
    activeProjectId,
    data: query.data ?? initialData,
    error: overrideError ?? queryError,
    getToken,
    loading: status === "loading" || query.isLoading,
    reload,
    setData,
    setError: setOverrideError,
  };
}
