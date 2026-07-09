import type { Metadata } from "next";
import { LeadForm } from "@/components/varsten/LeadForm";
import {
  CardGrid,
  InfoCard,
  NumberedList,
  SecondaryHero,
  SecondarySection,
  SecondaryShell,
} from "@/components/varsten/SecondaryPage";
import { pageMetadata } from "@/lib/seo";

export const metadata: Metadata = pageMetadata({
  title: "Enterprise — Varsten",
  description:
    "Enterprise AI cost optimization rollout planning for governance, security review, support posture, and pilot expectations.",
  path: "/enterprise",
});

export default function EnterprisePage() {
  return (
    <SecondaryShell>
      <SecondaryHero
        eyebrow="Enterprise"
        title="Govern AI cost optimization like production infrastructure."
        description="Enterprise rollouts need more than a proxy. They need review artifacts, safe rollout boundaries, security posture, procurement clarity, and savings proof that finance can audit."
      >
        <LeadForm source="enterprise" />
      </SecondaryHero>

      <SecondarySection title="What enterprise teams review" tone="muted">
        <CardGrid columns={2}>
          <InfoCard title="Governance">
            <p>Route policies, approval gates, admin access, audit logs, and rollback expectations.</p>
          </InfoCard>
          <InfoCard title="Security posture">
            <p>Data handling, subprocessors, retention, DPA review, provider key handling, and incident contact paths.</p>
          </InfoCard>
          <InfoCard title="Support posture">
            <p>Setup support, pilot checkpoints, fallback monitoring, and escalation channels during rollout.</p>
          </InfoCard>
          <InfoCard title="Finance artifacts">
            <p>Verified savings methodology, invoice traceability, pricing coverage, and attribution coverage.</p>
          </InfoCard>
        </CardGrid>
      </SecondarySection>

      <SecondarySection
        title="Pilot expectations"
        description="A good enterprise pilot is narrow, instrumented, and easy to unwind."
      >
        <NumberedList
          items={[
            {
              title: "Pick one high-volume, low-surprise OpenAI workload",
              body: "Avoid starting with the most sensitive workflow or the least understood provider path.",
            },
            {
              title: "Choose integration mode",
              body: "Use metadata-only for visibility, base URL for low-risk evaluation, or the SDK for production fallback.",
            },
            {
              title: "Define proof and quality checks",
              body: "Agree which savings methods, quality gates, and reports will be accepted before broad rollout.",
            },
            {
              title: "Expand only after fallback and reporting are boring",
              body: "The goal is a repeatable rollout pattern, not a one-off demo that cannot survive production traffic.",
            },
          ]}
        />
      </SecondarySection>
    </SecondaryShell>
  );
}
