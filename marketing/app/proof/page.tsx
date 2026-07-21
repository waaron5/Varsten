import type { Metadata } from "next";
import { EARLY_ACCESS_HREF } from "../site-links";
import { pageMetadata } from "@/lib/seo";
import {
  CardGrid,
  InfoCard,
  NumberedList,
  PageCta,
  SecondaryHero,
  SecondarySection,
  SecondaryShell,
  StatBand,
} from "@/components/varsten/SecondaryPage";

export const metadata: Metadata = pageMetadata({
  title: "Savings Proof — Varsten",
  description:
    "Varsten savings proof methodology for direct avoided cost, holdback A/B, replay evidence, overhead subtraction, and invoice traceability.",
  path: "/proof",
});

export default function ProofPage() {
  return (
    <SecondaryShell>
      <SecondaryHero
        eyebrow="Proof"
        title="Savings should survive engineering and finance review."
        description="Varsten separates opportunity estimates from verified savings. The proof model explains the baseline, the optimization, the quality decision, and the dollars that can be claimed."
      >
        <p className="mono text-[10px] uppercase tracking-[0.24em] text-ink-soft">Proof posture</p>
        <div className="mt-5 text-[42px] font-semibold tracking-[-0.02em] text-ink">Traceable</div>
        <p className="mt-2 text-[14px] leading-6 text-ink-soft">
          Each claim should connect to provider pricing, workload labels, and an accepted measurement method.
        </p>
      </SecondaryHero>

      <SecondarySection title="Accepted evidence types" tone="muted">
        <CardGrid columns={2}>
          <InfoCard eyebrow="01" title="Direct avoided cost">
            <p>Exact cache hits or equivalent eliminated calls can be measured against the provider call that did not happen.</p>
          </InfoCard>
          <InfoCard eyebrow="02" title="Holdback A/B">
            <p>A controlled slice of traffic keeps the original path so Varsten can compare optimized and baseline behavior.</p>
          </InfoCard>
          <InfoCard eyebrow="03" title="Replay evidence">
            <p>Approved replay corpora can estimate counterfactual cost and quality when direct holdback is not appropriate.</p>
          </InfoCard>
          <InfoCard eyebrow="04" title="Overhead subtraction">
            <p>Any approved Varsten processing or extra provider work is subtracted before net savings are claimed.</p>
          </InfoCard>
        </CardGrid>
      </SecondarySection>

      <SecondarySection
        title="From request to report"
        description="The proof path has to be legible to the people operating the system and the people paying for it."
      >
        <NumberedList
          items={[
            {
              title: "Tag the workload",
              body: "Requests should carry safe labels such as team, feature, environment, provider, and model.",
            },
            {
              title: "Apply an approved lever",
              body: "The mechanism records whether savings came from cache, routing, downshift, batching, token trim, or compression.",
            },
            {
              title: "Compare against the baseline",
              body: "The baseline method depends on the lever and workload risk, not a single universal formula.",
            },
            {
              title: "Publish traceable totals",
              body: "Reports should reconcile baseline cost, actual spend, net savings, pricing coverage, and attribution coverage.",
            },
          ]}
        />
      </SecondarySection>

      <SecondarySection title="Integrity checks" tone="muted">
        <StatBand
          stats={[
            {
              label: "Pricing coverage",
              value: "Required",
              detail: "Savings should be priced against real provider catalogs or accepted contracted rates.",
            },
            {
              label: "Attribution",
              value: "Required",
              detail: "Finance needs team or feature labels to allocate savings to the right owner.",
            },
            {
              label: "Quality proof",
              value: "Contextual",
              detail: "Quality gates depend on the route, model, and accepted risk of each optimization lever.",
            },
          ]}
        />
      </SecondarySection>

      <PageCta
        title="Verify one lever before expanding the rollout."
        description="Start with a narrow workload where the baseline, fallback path, and savings ledger are easy to audit."
        href={EARLY_ACCESS_HREF}
        label="Request early access"
        intent="early-access"
      />
    </SecondaryShell>
  );
}
