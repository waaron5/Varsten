"use client";

// Shared dashboard chrome state. The period toggle and Export live in the top
// navbar (AppShell's Topbar) to match the mockup, but the dashboard page reads the
// same period to drive its snapshot query. Both sit inside AppShell, so the state
// lives here, one level above both, instead of inside the page's DashboardProvider.

import { createContext, useContext, useState } from "react";
import type { ReactNode } from "react";
import type { DashboardPeriod } from "@/lib/types";

interface DashboardChrome {
  period: DashboardPeriod;
  setPeriod: (period: DashboardPeriod) => void;
}

const Ctx = createContext<DashboardChrome | null>(null);

export function DashboardChromeProvider({ children }: { children: ReactNode }) {
  const [period, setPeriod] = useState<DashboardPeriod>("month");
  return <Ctx.Provider value={{ period, setPeriod }}>{children}</Ctx.Provider>;
}

export function useDashboardChrome(): DashboardChrome {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("useDashboardChrome must be used within DashboardChromeProvider");
  return ctx;
}

export function periodSubtitle(period: DashboardPeriod): string {
  if (period === "quarter") return "Quarter to date · benchmarked against prior quarter";
  if (period === "year") return "Year to date · benchmarked against prior year";
  return "Month to date · benchmarked against prior month";
}
