"use client";

// Dashboard root. The home view is intentionally executive: savings,
// proof status, and a single next action. Operational detail lives in the
// dedicated Engine, Guardrails, Proof, and Analysis pages.

import { RequireSession } from "@/components/RequireSession";
import { DashboardProvider } from "./DashboardProvider";
import { SavingsDashboard } from "./panels";

export function Dashboard() {
  return (
    <RequireSession>
      <DashboardProvider>
        <SavingsDashboard />
      </DashboardProvider>
    </RequireSession>
  );
}
