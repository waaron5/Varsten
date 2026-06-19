import { HydrationBoundary } from "@tanstack/react-query";
import { Dashboard } from "@/components/dashboard/Dashboard";
import { api } from "@/lib/api";
import { loadServerBootstrap } from "@/lib/serverSession";
import { prefetchProjectQueries } from "@/lib/serverQuery";

// Server Component: prefetch the Dashboard's reads so the first paint shows real
// numbers instead of a skeleton. The query keys here must match DashboardProvider
// exactly. Falls back to the pure client render when there is no server session.
export default async function DashboardPage() {
  const boot = await loadServerBootstrap();
  if (!boot?.activeProjectId) return <Dashboard />;

  const state = await prefetchProjectQueries(boot.token, boot.activeProjectId, [
    { key: ["dashboard"], load: api.dashboard },
    { key: ["engineLevers"], load: api.engineLevers },
    { key: ["overview"], load: api.overview },
    { key: ["proofDataQuality"], load: api.proofDataQuality },
    { key: ["proofSavings"], load: api.proofSavings },
    { key: ["savingsTrend", "mtd"], load: (t, p) => api.savingsTrend(t, p, { period: "mtd" }) },
    {
      key: ["breakdown", "team", "mtd", 5],
      load: (t, p) => api.breakdown(t, p, "team", { period: "mtd", limit: 5 }),
    },
    {
      key: ["breakdown", "feature", "mtd", 5],
      load: (t, p) => api.breakdown(t, p, "feature", { period: "mtd", limit: 5 }),
    },
  ]);

  return (
    <HydrationBoundary state={state}>
      <Dashboard />
    </HydrationBoundary>
  );
}
