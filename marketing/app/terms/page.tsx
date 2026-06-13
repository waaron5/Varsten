import type { Metadata } from "next";
import { CONTACT_EMAIL, ContentCallout, ContentPage, ContentSection } from "../content-page";

export const metadata: Metadata = {
  title: "Terms — Varsten",
  description: "Varsten website, app, and proxy service terms.",
};

export default function TermsPage() {
  return (
    <ContentPage
      eyebrow="Terms"
      title="Terms for using Varsten."
      description="Last updated June 13, 2026. These terms describe the baseline rules for the Varsten website, app, proxy, and related services."
    >
      <ContentSection title="The service">
        <p>
          Varsten provides AI spend monitoring, proxy routing, response reuse, evals, quality guardrails, and savings
          proof tools. Customer configuration determines which routes are observed, optimized, retained, or billed.
        </p>
      </ContentSection>

      <ContentSection title="Accounts and access">
        <p>
          You are responsible for keeping account credentials and API keys secure, limiting access to authorized users,
          and promptly notifying Varsten if credentials are lost, shared, or compromised.
        </p>
      </ContentSection>

      <ContentSection title="Acceptable use">
        <ul className="lp-content-list">
          <li>Do not use Varsten to violate laws, rights, provider terms, or security controls.</li>
          <li>Do not attempt to bypass rate limits, billing controls, authentication, or route policies.</li>
          <li>Do not send workloads that require special legal terms unless those terms are signed with Varsten.</li>
          <li>Do not interfere with the availability, integrity, or security of the service.</li>
        </ul>
      </ContentSection>

      <ContentSection title="Fees and savings">
        <p>
          Free plans may provide monitoring and proof features without inline optimization. Performance plans may charge
          a percentage of verified savings after any trial period. Estimates, recommendations, and customer-side changes
          are not billable unless accepted in a written agreement.
        </p>
      </ContentSection>

      <ContentSection title="Customer data and providers">
        <p>
          You retain rights to your prompts, responses, configurations, and application data. You authorize Varsten to
          process that data as needed to provide the service and to route traffic to configured model providers.
        </p>
      </ContentSection>

      <ContentSection title="Disclaimers and termination">
        <p>
          Varsten is provided with the warranties, service levels, limitations, and liability terms in the applicable
          order form or written agreement. Either party may end use of the service according to the applicable agreement,
          and Varsten may suspend access for security, abuse, non-payment, or legal risk.
        </p>
      </ContentSection>

      <ContentCallout title="Questions about these terms?">
        <p>
          Email <a href={`mailto:${CONTACT_EMAIL}`}>{CONTACT_EMAIL}</a> for legal, procurement, or contract questions.
        </p>
      </ContentCallout>
    </ContentPage>
  );
}
