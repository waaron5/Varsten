"use client";

// Dashboard root. The home view is intentionally executive: savings,
// proof status, and a single next action. Operational detail lives in the
// dedicated Automation, Guardrails, Proof, and Analysis pages.

import { RequireSession } from "@/components/RequireSession";
import type { DashboardSnapshot } from "@/lib/types";
import { DashboardProvider } from "./DashboardProvider";
import { SavingsDashboard } from "./panels";

export function Dashboard({ initialMonthSnapshot = null }: { initialMonthSnapshot?: DashboardSnapshot | null }) {
  return (
    <RequireSession>
      <DashboardProvider initialMonthSnapshot={initialMonthSnapshot}>
        <SavingsDashboard />
      </DashboardProvider>
    </RequireSession>
  );
}
