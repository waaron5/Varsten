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
import type { ActiveRoute, Breakdown, CommandCenter, MetricsOverview, ProofAttribution, ProxyTraffic, SavingsTrend } from "@/lib/types";

type Resource<T> = { data: T | null; loading: boolean; error: string | null };

interface CommandCenterData {
  commandCenter: Resource<CommandCenter>;
  overview: Resource<MetricsOverview>;
  savingsTrend: Resource<SavingsTrend>;
  proxyTraffic: Resource<ProxyTraffic>;
  spendDrivers: Resource<Breakdown>;
  proofAttribution: Resource<ProofAttribution>;
  routes: Resource<ActiveRoute[]>;
}

function slice<T>(r: { data: T | null; loading: boolean; error: string | null }): Resource<T> {
  return { data: r.data, loading: r.loading, error: r.error };
}

const Ctx = createContext<CommandCenterData | null>(null);

function loadModelSpendDrivers(token: string, projectId: string | undefined): Promise<Breakdown> {
  return api.breakdown(token, projectId, "model", { days: 30, limit: 6 });
}

export function CommandCenterProvider({ children }: { children: ReactNode }) {
  const commandCenter = useProjectResource<CommandCenter>(api.commandCenter);
  const overview = useProjectResource<MetricsOverview>(api.overview);
  const savingsTrend = useProjectResource<SavingsTrend>(api.savingsTrend);
  const proxyTraffic = useProjectResource<ProxyTraffic>(api.proxyTraffic);
  const spendDrivers = useProjectResource<Breakdown>(loadModelSpendDrivers);
  const proofAttribution = useProjectResource<ProofAttribution>(api.proofAttribution);
  const routes = useProjectResource<ActiveRoute[]>(api.engineRoutes, []);

  const value: CommandCenterData = {
    commandCenter: slice(commandCenter),
    overview: slice(overview),
    savingsTrend: slice(savingsTrend),
    proxyTraffic: slice(proxyTraffic),
    spendDrivers: slice(spendDrivers),
    proofAttribution: slice(proofAttribution),
    routes: slice(routes),
  };
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useCommandCenter(): CommandCenterData {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("useCommandCenter must be used within CommandCenterProvider");
  return ctx;
}
