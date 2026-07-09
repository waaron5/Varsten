import type { Metadata } from "next";
import { CONTACT_EMAIL } from "../site-links";
import { CardGrid, InfoCard, SecondaryHero, SecondarySection, SecondaryShell } from "@/components/varsten/SecondaryPage";
import { pageMetadata } from "@/lib/seo";

export const metadata: Metadata = pageMetadata({
  title: "Terms — Varsten",
  description: "Varsten website, app, proxy, AI optimization, billing, and acceptable use terms.",
  path: "/terms",
});

export default function TermsPage() {
  return (
    <SecondaryShell>
      <SecondaryHero
        eyebrow="Terms"
        title="The terms for using Varsten"
        description="Last updated July 9, 2026. These terms summarize the basic rules for the Varsten website, app, proxy, and related services."
      />
      <SecondarySection title="Service terms">
        <CardGrid columns={2}>
          <InfoCard title="The service">
            <p>Varsten provides AI spend monitoring, proxy routing, response reuse, evals, guardrails, and savings proof tools.</p>
          </InfoCard>
          <InfoCard title="Accounts and access">
            <p>You are responsible for protecting credentials, limiting access, and reporting lost or stolen keys promptly.</p>
          </InfoCard>
          <InfoCard title="Fees and savings">
            <p>Optimize plans may charge a percentage of verified savings. Estimates and recommendations are not invoices by themselves.</p>
          </InfoCard>
          <InfoCard title="Customer data">
            <p>You keep rights to prompts, responses, configurations, and application data, and allow Varsten to process data as needed to run the service.</p>
          </InfoCard>
        </CardGrid>
      </SecondarySection>
      <SecondarySection title="Questions" tone="muted">
        <p className="max-w-3xl text-[15px] leading-7 text-ink-soft">
          For legal, procurement, or contract questions, email{" "}
          <a className="text-blueprint underline underline-offset-4" href={`mailto:${CONTACT_EMAIL}`}>{CONTACT_EMAIL}</a>.
        </p>
      </SecondarySection>
    </SecondaryShell>
  );
}
