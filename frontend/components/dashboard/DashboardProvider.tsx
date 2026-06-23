"use client";

// One consolidated read for the whole Dashboard: GET /dashboard/snapshot. The
// backend reconciles every panel (KPIs, levers, chart, drivers, proof) to a
// single window/fee/savings source, so the client no longer fans out to eight
// endpoints. Period state lives here; switching it re-keys the query (period is
// part of the cache key) and refetches just the snapshot.

import { createContext, useContext } from "react";
import type { ReactNode } from "react";
import { useProjectResource } from "@/components/useProjectResource";
import { useDashboardChrome } from "@/components/dashboardChrome";
import { api } from "@/lib/api";
import type { DashboardPeriod, DashboardSnapshot } from "@/lib/types";

type Resource<T> = { data: T | null; loading: boolean; error: string | null };

interface DashboardData {
  snapshot: Resource<DashboardSnapshot>;
  period: DashboardPeriod;
}

const Ctx = createContext<DashboardData | null>(null);

export function DashboardProvider({ children }: { children: ReactNode }) {
  // Period is owned by the top-navbar control (DashboardChrome); the page reacts to
  // it. Including it in the query key re-fetches the snapshot on a period switch.
  const { period } = useDashboardChrome();
  const snapshot = useProjectResource<DashboardSnapshot>(
    ["dashboardSnapshot", period],
    (token, projectId) => api.dashboardSnapshot(token, projectId, { period }),
  );

  const value: DashboardData = {
    snapshot: { data: snapshot.data, loading: snapshot.loading, error: snapshot.error },
    period,
  };
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useDashboard(): DashboardData {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("useDashboard must be used within DashboardProvider");
  return ctx;
}
