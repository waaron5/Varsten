"use client";

// Owns the TanStack Query cache for the whole app. The client is created once
// per browser session via useState so it survives re-renders but never leaks
// between requests on the server. Reads flow through useProjectResource; this is
// what makes revisiting a page instant (served from cache, revalidated in the
// background) instead of a cold refetch with a spinner.

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState } from "react";

export function QueryProvider({ children }: { children: React.ReactNode }) {
  const [client] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            // Treat data as fresh for 30s, so rapid navigation back to a page
            // serves cache with no network. After that, refetch in the
            // background while showing the cached value.
            staleTime: 30_000,
            // Keep unused query data around for 5 minutes before garbage
            // collection, so brief detours keep the cache warm.
            gcTime: 5 * 60_000,
            refetchOnWindowFocus: true,
            retry: 2,
          },
        },
      }),
  );
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}
