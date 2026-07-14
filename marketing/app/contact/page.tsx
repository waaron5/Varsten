import type { Metadata } from "next";
import { CONTACT_EMAIL } from "../site-links";
import { LeadForm } from "@/components/varsten/LeadForm";
import { CardGrid, InfoCard, SecondaryHero, SecondarySection, SecondaryShell } from "@/components/varsten/SecondaryPage";
import { pageMetadata } from "@/lib/seo";

export const metadata: Metadata = pageMetadata({
  title: "Contact — Varsten",
  description: "Contact Varsten for sales, integration help, security review, procurement, or support.",
  path: "/contact",
});

export default function ContactPage() {
  return (
    <SecondaryShell>
      <SecondaryHero
        eyebrow="Contact"
        title="How can we help?"
        description="Fill out the form below and we will get back to you as soon as possible. If you'd like to speak with our sales team, follow the link here."
      >
        <LeadForm source="contact" />
      </SecondaryHero>
      <SecondarySection title="Direct contacts" tone="muted">
        <CardGrid columns={3}>
          <InfoCard title="Sales and pilots">
            <p>
              <a className="text-blueprint underline underline-offset-4" href={`mailto:${CONTACT_EMAIL}`}>{CONTACT_EMAIL}</a>
            </p>
          </InfoCard>
          <InfoCard title="Security">
            <p>
              <a className="text-blueprint underline underline-offset-4" href="mailto:security@varsten.ai">security@varsten.ai</a>
            </p>
          </InfoCard>
          <InfoCard title="Support">
            <p>
              <a className="text-blueprint underline underline-offset-4" href="mailto:support@varsten.ai">support@varsten.ai</a>
            </p>
          </InfoCard>
        </CardGrid>
      </SecondarySection>
    </SecondaryShell>
  );
}
