"use client";

// Command Center root. Executive financial context leads, infrastructure health
// follows, and every card reads live project data through CommandCenterProvider.

import { RequireSession } from "@/components/RequireSession";
import { CommandCenterProvider } from "./CommandCenterProvider";
import { SetupBanner } from "./SetupBanner";
import {
  BudgetForecastPanel,
  ExecutiveRow,
  GuardrailRoutesPanel,
  ProxyEfficiencyPanel,
  SafetySummaryPanel,
  SavingsMixPanel,
  SavingsWedgePanel,
  TopOpportunitiesPanel,
  TopSpendDriversPanel,
} from "./panels";

function CommandCenterGrid() {
  return (
    <div className="command-center-view">
      <SetupBanner />
      <section className="cc-zone">
        <div className="cc-zone-head">
          <div>
            <span>Financials</span>
            <h2>Spend, savings, and the next dollars to recover.</h2>
          </div>
        </div>
        <ExecutiveRow />
        <div className="cc-financial-grid">
          <SavingsWedgePanel />
          <div className="cc-financial-side">
            <BudgetForecastPanel />
            <SavingsMixPanel />
          </div>
        </div>
        <div className="cc-lower-grid">
          <TopSpendDriversPanel />
          <TopOpportunitiesPanel />
        </div>
      </section>

      <section className="cc-zone">
        <div className="cc-zone-head">
          <div>
            <span>Infrastructure Health</span>
            <h2>Proxy efficiency, latency, and quality guardrails.</h2>
          </div>
        </div>
        <div className="cc-infra-grid">
          <ProxyEfficiencyPanel />
          <SafetySummaryPanel />
          <GuardrailRoutesPanel />
        </div>
      </section>
    </div>
  );
}

export function CommandCenter() {
  return (
    <RequireSession>
      <CommandCenterProvider>
        <CommandCenterGrid />
      </CommandCenterProvider>
    </RequireSession>
  );
}
