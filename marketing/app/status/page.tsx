import type { Metadata } from "next";
import { pageMetadata } from "@/lib/seo";
import { CardGrid, InfoCard, SecondaryHero, SecondarySection, SecondaryShell } from "@/components/varsten/SecondaryPage";

export const metadata: Metadata = pageMetadata({
  title: "Status — Varsten",
  description: "Varsten service status and status endpoint behavior.",
  path: "/status",
});

export default function StatusPage() {
  return (
    <SecondaryShell>
      <SecondaryHero
        eyebrow="Status"
        title="Service status"
        description="The public footer reads a normalized status endpoint before it claims systems are nominal. If no upstream is configured, the UI says status is unavailable."
      />
      <SecondarySection title="Status behavior" tone="muted">
        <CardGrid columns={2}>
          <InfoCard title="Configured upstream">
            <p>The marketing API normalizes health or status provider responses into operational, degraded, outage, maintenance, or unknown.</p>
          </InfoCard>
          <InfoCard title="No upstream">
            <p>The footer avoids false confidence and shows “Status unavailable” until a production status source is configured.</p>
          </InfoCard>
        </CardGrid>
      </SecondarySection>
    </SecondaryShell>
  );
}
