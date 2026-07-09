import type { Metadata } from "next";
import { CONTACT_EMAIL, DPA_REQUEST_HREF } from "../site-links";
import { pageMetadata } from "@/lib/seo";
import {
  CardGrid,
  InfoCard,
  NumberedList,
  PageCta,
  SecondaryHero,
  SecondarySection,
  SecondaryShell,
} from "@/components/varsten/SecondaryPage";

export const metadata: Metadata = pageMetadata({
  title: "Security — Varsten",
  description: "Varsten security, data handling, access control, reliability, and enterprise review posture.",
  path: "/security",
});

export default function SecurityPage() {
  return (
    <SecondaryShell>
      <SecondaryHero
        eyebrow="Security"
        title="Built for AI traffic that has to keep serving."
        description="Varsten is designed around explicit route policies, metadata-first proof, direct fallback through the SDK path, and honest compliance boundaries."
      >
        <p className="mono text-[10px] uppercase tracking-[0.24em] text-ink-soft">Current posture</p>
        <div className="mt-5 text-[34px] font-semibold tracking-[-0.02em] text-ink">SOC 2-compatible controls</div>
        <p className="mt-2 text-[14px] leading-6 text-ink-soft">
          Varsten does not claim SOC 2 certification until a signed report exists.
        </p>
      </SecondaryHero>

      <SecondarySection title="Security model" tone="muted">
        <CardGrid columns={2}>
          <InfoCard title="Metadata-first ledger">
            <p>Savings proof records cost, attribution, pricing, and optimization decisions without making prompt text the default record.</p>
          </InfoCard>
          <InfoCard title="Bounded content stores">
            <p>Semantic cache, replay, or batch staging content should be governed by route policy and retention boundaries.</p>
          </InfoCard>
          <InfoCard title="Fail-open SDK path">
            <p>The SDK can call the provider directly when Varsten is unavailable before output starts.</p>
          </InfoCard>
          <InfoCard title="Access controls">
            <p>Production access should use scoped API keys, tenant isolation, least privilege, and audit trails.</p>
          </InfoCard>
        </CardGrid>
      </SecondarySection>

      <SecondarySection title="Enterprise review checklist">
        <NumberedList
          items={[
            {
              title: "Data handling",
              body: "Review route policies, retention, metadata fields, content stores, subprocessors, and DPA requirements.",
            },
            {
              title: "Provider key handling",
              body: "The production SDK path keeps provider fallback explicit; key storage and rotation should match your existing secret process.",
            },
            {
              title: "Reliability",
              body: "Test fallback, circuit breaker behavior, timeouts, and monitoring before the first production workload.",
            },
            {
              title: "Compliance claims",
              body: "Use current artifacts and roadmaps honestly. Do not treat roadmap controls as completed certifications.",
            },
          ]}
        />
      </SecondarySection>

      <SecondarySection title="Security contacts" tone="muted">
        <CardGrid columns={2}>
          <InfoCard title="Security review">
            <p>
              Email <a className="text-blueprint underline underline-offset-4" href={`mailto:${CONTACT_EMAIL}`}>{CONTACT_EMAIL}</a>{" "}
              for security questionnaires, DPA requests, and enterprise review artifacts.
            </p>
          </InfoCard>
          <InfoCard title="DPA">
            <p>
              <a className="text-blueprint underline underline-offset-4" href={DPA_REQUEST_HREF}>Request a DPA</a>{" "}
              before sending regulated or contract-sensitive production traffic.
            </p>
          </InfoCard>
        </CardGrid>
      </SecondarySection>

      <PageCta
        title="Review the integration path before production traffic moves."
        description="For sensitive workloads, start with metadata-only analysis or a narrow SDK rollout with explicit fallback tests."
        href="/docs/data-handling"
        label="Read data handling docs"
        intent="sales"
      />
    </SecondaryShell>
  );
}
