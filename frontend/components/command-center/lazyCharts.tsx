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

export const CacheHitMissChart = dynamic(() => import("./charts").then((m) => m.CacheHitMissChart), {
  ssr: false,
  loading: () => <PanelSkeleton />,
});

export const LatencyChart = dynamic(() => import("./charts").then((m) => m.LatencyChart), {
  ssr: false,
  loading: () => <PanelSkeleton />,
});
