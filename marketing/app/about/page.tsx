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
  title: "About — Varsten",
  description: "Varsten builds AI cost optimization infrastructure for teams that need savings and proof.",
  path: "/about",
});

export default function AboutPage() {
  return (
    <SecondaryShell>
      <SecondaryHero
        eyebrow="About"
        title="AI spend should be engineered, not hand-waved."
        description="Varsten exists for teams whose AI usage is now large enough that cost, quality, and finance proof need production infrastructure."
      />
      <SecondarySection title="What Varsten builds">
        <CardGrid columns={3}>
          <InfoCard title="Observe">
            <p>Attribute AI spend by provider, model, team, feature, and environment without changing the product experience.</p>
          </InfoCard>
          <InfoCard title="Optimize">
            <p>Apply approved levers such as cache, routing, batching, token trim, downshift, and compression.</p>
          </InfoCard>
          <InfoCard title="Prove">
            <p>Turn savings into evidence that engineering, finance, and procurement can review.</p>
          </InfoCard>
        </CardGrid>
      </SecondarySection>
      <PageCta
        title="Start with visibility, then optimize where the evidence is strongest."
        description="Observe mode gives the team a clean baseline before production optimization decisions."
        href={START_OBSERVE_HREF}
        label="Start Observe"
        intent="observe"
      />
    </SecondaryShell>
  );
}
