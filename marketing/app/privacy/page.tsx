import type { Metadata } from "next";
import { CONTACT_EMAIL } from "../site-links";
import { CardGrid, InfoCard, SecondaryHero, SecondarySection, SecondaryShell } from "@/components/varsten/SecondaryPage";
import { pageMetadata } from "@/lib/seo";

export const metadata: Metadata = pageMetadata({
  title: "Privacy — Varsten",
  description: "Varsten privacy practices for website, lead, app, analytics, and AI optimization data.",
  path: "/privacy",
});

export default function PrivacyPage() {
  return (
    <SecondaryShell>
      <SecondaryHero
        eyebrow="Privacy"
        title="How Varsten handles data"
        description="Last updated July 9, 2026. This page summarizes how Varsten expects to handle website, lead, app, analytics, and AI optimization data."
      />
      <SecondarySection title="Privacy practices">
        <CardGrid columns={2}>
          <InfoCard title="Website and lead data">
            <p>Varsten may collect contact details you submit, page analytics, referral context, and technical details needed to run the site.</p>
          </InfoCard>
          <InfoCard title="Analytics data">
            <p>Marketing analytics should use anonymous visitor IDs, path, referrer, and UTM data. Email, prompt text, API keys, and form body content are not analytics properties.</p>
          </InfoCard>
          <InfoCard title="AI optimization data">
            <p>Inline optimization may process request metadata, model names, routing decisions, cache decisions, eval results, and cost attribution data.</p>
          </InfoCard>
          <InfoCard title="Subprocessors">
            <p>Varsten may use infrastructure, communications, analytics, payment, security, and model provider subprocessors when needed to run the service.</p>
          </InfoCard>
        </CardGrid>
      </SecondarySection>
      <SecondarySection title="Privacy contact" tone="muted">
        <p className="max-w-3xl text-[15px] leading-7 text-ink-soft">
          For access, deletion, export, correction, or privacy questions, email{" "}
          <a className="text-blueprint underline underline-offset-4" href={`mailto:${CONTACT_EMAIL}`}>{CONTACT_EMAIL}</a>.
        </p>
      </SecondarySection>
    </SecondaryShell>
  );
}
