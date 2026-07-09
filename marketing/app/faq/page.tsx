import type { Metadata } from "next";
import { pageMetadata } from "@/lib/seo";
import {
  CardGrid,
  InfoCard,
  PageCta,
  SecondaryHero,
  SecondarySection,
  SecondaryShell,
} from "@/components/varsten/SecondaryPage";
import { START_OBSERVE_HREF } from "../site-links";

export const metadata: Metadata = pageMetadata({
  title: "FAQ — Varsten",
  description:
    "Answers to common Varsten questions about AI cost optimization, provider support, fail-open behavior, data handling, and verified savings.",
  path: "/faq",
});

export default function FaqPage() {
  return (
    <SecondaryShell>
      <SecondaryHero
        eyebrow="FAQ"
        title="Questions teams ask before putting Varsten near AI traffic."
        description="Short answers for engineering, finance, security, and procurement. The safe starting point is usually visibility first, then one controlled optimization rollout."
      />

      <SecondarySection title="Product and rollout">
        <CardGrid columns={2}>
          <InfoCard title="What is Varsten?">
            <p>An AI cost optimization engine that observes AI spend, applies approved savings levers, and proves verified savings.</p>
          </InfoCard>
          <InfoCard title="Where should we start?">
            <p>Start with metadata-only analysis or one stable OpenAI workload using the SDK fallback path.</p>
          </InfoCard>
          <InfoCard title="Does Varsten replace our provider SDK?">
            <p>No. The production path wraps the provider SDK pattern and keeps your provider key available for fallback.</p>
          </InfoCard>
          <InfoCard title="Which providers are production-ready?">
            <p>OpenAI is the recommended production path today. Anthropic and Gemini are beta/founder-supervised pilots.</p>
          </InfoCard>
        </CardGrid>
      </SecondarySection>

      <SecondarySection title="Security and finance" tone="muted">
        <CardGrid columns={2}>
          <InfoCard title="Do you need prompt text to measure savings?">
            <p>No for metadata-only analysis. Some optimization features may need bounded content stores governed by route policy.</p>
          </InfoCard>
          <InfoCard title="What happens if Varsten is unavailable?">
            <p>The SDK can fail open to the provider before output starts. Base URL mode does not provide that direct fallback.</p>
          </InfoCard>
          <InfoCard title="Do estimates become invoices?">
            <p>No. Estimates and recommendations are not billable savings without accepted proof.</p>
          </InfoCard>
          <InfoCard title="Are you SOC 2 certified?">
            <p>Not yet. Varsten should not be represented as SOC 2 certified until a signed report exists.</p>
          </InfoCard>
        </CardGrid>
      </SecondarySection>

      <PageCta
        title="Get spend visibility before changing production traffic."
        description="Observe mode gives the team a low-risk way to understand spend, attribution, and optimization opportunities."
        href={START_OBSERVE_HREF}
        label="Start Observe"
        intent="observe"
      />
    </SecondaryShell>
  );
}
