import { HydrationBoundary } from "@tanstack/react-query";
import { ProofSavingsView } from "@/components/ProofGuardrailsViews";
import { api } from "@/lib/api";
import { loadServerBootstrap } from "@/lib/serverSession";
import { prefetchProjectQueries } from "@/lib/serverQuery";

// Server Component: Proof is the load-bearing page, so prefetch realized savings
// on the server for an instant, board-ready first paint. Key must match
// ProofSavingsBody. Falls back to the client render with no server session.
export default async function ProofSavingsPage() {
  const boot = await loadServerBootstrap();
  if (!boot?.activeProjectId) return <ProofSavingsView />;

  const state = await prefetchProjectQueries(boot.token, boot.activeProjectId, [
    { key: ["proofSavings"], load: api.proofSavings },
  ]);

  return (
    <HydrationBoundary state={state}>
      <ProofSavingsView />
    </HydrationBoundary>
  );
}
