"use client";

// Fetches the few reads the simplified Dashboard needs: live project
// summary, spend overview, proof savings, and month-to-date chart data. Detailed
// operational reads live on Engine, Guardrails, Proof, and Analysis.

import { createContext, useContext } from "react";
import type { ReactNode } from "react";
import { useProjectResource } from "@/components/useProjectResource";
import { api } from "@/lib/api";
import type { Breakdown, Dashboard, LeverConfig, MetricsOverview, ProofDataQuality, ProofSavings, SavingsTrend } from "@/lib/types";

type Resource<T> = { data: T | null; loading: boolean; error: string | null };

interface DashboardData {
  dashboard: Resource<Dashboard>;
  engineLevers: Resource<LeverConfig[]>;
  overview: Resource<MetricsOverview>;
  proofDataQuality: Resource<ProofDataQuality>;
  proofSavings: Resource<ProofSavings>;
  savingsTrend: Resource<SavingsTrend>;
  spendDrivers: Resource<Breakdown>;
  spendDriversByFeature: Resource<Breakdown>;
}

function slice<T>(r: { data: T | null; loading: boolean; error: string | null }): Resource<T> {
  return { data: r.data, loading: r.loading, error: r.error };
}

const Ctx = createContext<DashboardData | null>(null);

export function DashboardProvider({ children }: { children: ReactNode }) {
  const dashboard = useProjectResource<Dashboard>(["dashboard"], api.dashboard);
  const engineLevers = useProjectResource<LeverConfig[]>(["engineLevers"], api.engineLevers);
  const overview = useProjectResource<MetricsOverview>(["overview"], api.overview);
  const proofDataQuality = useProjectResource<ProofDataQuality>(["proofDataQuality"], api.proofDataQuality);
  const proofSavings = useProjectResource<ProofSavings>(["proofSavings"], api.proofSavings);
  const savingsTrend = useProjectResource<SavingsTrend>(["savingsTrend", "mtd"], (token, projectId) => api.savingsTrend(token, projectId, { period: "mtd" }));
  const spendDrivers = useProjectResource<Breakdown>(["breakdown", "team", "mtd", 5], (token, projectId) => api.breakdown(token, projectId, "team", { period: "mtd", limit: 5 }));
  const spendDriversByFeature = useProjectResource<Breakdown>(["breakdown", "feature", "mtd", 5], (token, projectId) => api.breakdown(token, projectId, "feature", { period: "mtd", limit: 5 }));

  const value: DashboardData = {
    dashboard: slice(dashboard),
    engineLevers: slice(engineLevers),
    overview: slice(overview),
    proofDataQuality: slice(proofDataQuality),
    proofSavings: slice(proofSavings),
    savingsTrend: slice(savingsTrend),
    spendDrivers: slice(spendDrivers),
    spendDriversByFeature: slice(spendDriversByFeature),
  };
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useDashboard(): DashboardData {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("useDashboard must be used within DashboardProvider");
  return ctx;
}
