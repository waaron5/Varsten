"use client";

// next/dynamic with ssr:false is only valid inside a Client Component (per the
// bundled app-router lazy-loading docs), which is why these wrappers live here and
// not in a Server Component. ssr:false keeps Recharts out of SSR entirely (no
// hydration mismatch); the loading skeleton fills the cell so the chunk-load is
// invisible.

import dynamic from "next/dynamic";
import { PanelSkeleton } from "./primitives";

export const CumulativeSavingsChart = dynamic(() => import("./charts").then((m) => m.CumulativeSavingsChart), {
  ssr: false,
  loading: () => <PanelSkeleton />,
});

export const HitRateChart = dynamic(() => import("./charts").then((m) => m.HitRateChart), {
  ssr: false,
  loading: () => <PanelSkeleton />,
});

export const LatencyChart = dynamic(() => import("./charts").then((m) => m.LatencyChart), {
  ssr: false,
  loading: () => <PanelSkeleton />,
});

// KPI-tile sparkline. Same ssr:false discipline; its loader is an empty cell-filler
// (not the shimmer) so a tile is just a number until the tiny chunk lands.
export const Sparkline = dynamic(() => import("./charts").then((m) => m.Sparkline), {
  ssr: false,
  loading: () => <div className="cc-kpi-spark-load" aria-hidden="true" />,
});
