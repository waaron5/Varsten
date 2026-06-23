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
    {
      key: ["dashboardSnapshot", "month"],
      load: (t, p) => api.dashboardSnapshot(t, p, { period: "month" }),
    },
  ]);

  return (
    <HydrationBoundary state={state}>
      <Dashboard />
    </HydrationBoundary>
  );
}
