import type { Metadata } from "next";
import { CONTACT_EMAIL, ContentCallout, ContentPage, ContentSection } from "../content-page";

export const metadata: Metadata = {
  title: "Contact — Varsten",
  description: "Contact Varsten.",
};

export default function ContactPage() {
  return (
    <ContentPage
      eyebrow="Contact"
      title="Contact Varsten"
      description="Send us your provider, framework, and first route target."
    >
      <ContentSection title="Sales and integration help">
        <p>
          Email <a href={`mailto:${CONTACT_EMAIL}`}>{CONTACT_EMAIL}</a> for sales questions,
          integration help, or security review coordination.
        </p>
      </ContentSection>

      <ContentCallout title="Security">
        <p>
          For security reports, email <a href="mailto:security@varsten.ai">security@varsten.ai</a>.
        </p>
      </ContentCallout>
    </ContentPage>
  );
}
