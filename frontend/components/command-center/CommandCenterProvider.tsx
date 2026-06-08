"use client";

// Fetches the four Command Center reads in parallel and exposes each as its own
// {data, loading, error} slice. Each panel reads its slice and shows a skeleton in
// its fixed grid cell until that slice resolves, so panels fill in independently
// with zero layout shift (the grid never changes size). Reuses the proven
// useProjectResource (token + activeProjectId, deferred until the session is
// ready); the four hooks fire their effects in parallel.

import { createContext, useContext } from "react";
import type { ReactNode } from "react";
import { useProjectResource } from "@/components/useProjectResource";
import { api } from "@/lib/api";
import type { ActiveRoute, CommandCenter, ProxyTraffic, SavingsTrend } from "@/lib/types";

type Resource<T> = { data: T | null; loading: boolean; error: string | null };

interface CommandCenterData {
  commandCenter: Resource<CommandCenter>;
  savingsTrend: Resource<SavingsTrend>;
  proxyTraffic: Resource<ProxyTraffic>;
  routes: Resource<ActiveRoute[]>;
}

function slice<T>(r: { data: T | null; loading: boolean; error: string | null }): Resource<T> {
  return { data: r.data, loading: r.loading, error: r.error };
}

const Ctx = createContext<CommandCenterData | null>(null);

export function CommandCenterProvider({ children }: { children: ReactNode }) {
  const commandCenter = useProjectResource<CommandCenter>(api.commandCenter);
  const savingsTrend = useProjectResource<SavingsTrend>(api.savingsTrend);
  const proxyTraffic = useProjectResource<ProxyTraffic>(api.proxyTraffic);
  const routes = useProjectResource<ActiveRoute[]>(api.engineRoutes, []);

  const value: CommandCenterData = {
    commandCenter: slice(commandCenter),
    savingsTrend: slice(savingsTrend),
    proxyTraffic: slice(proxyTraffic),
    routes: slice(routes),
  };
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useCommandCenter(): CommandCenterData {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("useCommandCenter must be used within CommandCenterProvider");
  return ctx;
}
