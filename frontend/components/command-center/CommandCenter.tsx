"use client";

// Command Center root. Full-bleed, no-scroll, fluid dashboard: it opts out of the
// scrolling .view and renders the fixed 12-col / 3-row .cc-canvas, which fills the
// shell's .content and reflows automatically when the sidebar collapses (the shell
// grid's 1fr column does the resizing). Panels fill their cells and clip.

import { RequireSession } from "@/components/RequireSession";
import { CommandCenterProvider } from "./CommandCenterProvider";
import {
  KpiStrip,
  MarginEnginePanel,
  ProxyHitRatePanel,
  ProxyLatencyPanel,
  QualityGuardrailsPanel,
} from "./panels";

function CommandCenterGrid() {
  return (
    <div className="cc-canvas">
      <KpiStrip />
      <MarginEnginePanel />
      <ProxyHitRatePanel />
      <QualityGuardrailsPanel />
      <ProxyLatencyPanel />
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
