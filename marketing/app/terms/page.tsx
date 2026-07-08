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
      title="The terms for using Varsten"
      description="Last updated June 13, 2026. These terms set the basic rules for the Varsten website, app, proxy, and related services."
    >
      <ContentSection title="The service">
        <p>
          Varsten provides AI spend monitoring, proxy routing, response reuse, evals, quality guardrails, and savings
          proof tools. Your configuration decides which routes are watched, optimized, retained, or billed.
        </p>
      </ContentSection>

      <ContentSection title="Accounts and access">
        <p>
          You are responsible for keeping your account credentials and API keys safe, limiting access to authorized
          users, and telling Varsten right away if credentials are lost, shared, or stolen.
        </p>
      </ContentSection>

      <ContentSection title="Acceptable use">
        <ul className="lp-content-list">
          <li>Do not use Varsten to break laws, rights, provider terms, or security controls.</li>
          <li>Do not try to get around rate limits, billing controls, authentication, or route policies.</li>
          <li>Do not send workloads that need special legal terms unless you have signed those terms with Varsten.</li>
          <li>Do not harm the availability, integrity, or security of the service.</li>
        </ul>
      </ContentSection>

      <ContentSection title="Fees and savings">
        <p>
          Free plans may give you monitoring and proof features without inline optimization. Optimize plans may charge
          a percentage of confirmed savings after any trial period. Estimates, recommendations, and changes you make on
          your own side are not billable unless you accept them in a written agreement.
        </p>
      </ContentSection>

      <ContentSection title="Customer data and providers">
        <p>
          You keep the rights to your prompts, responses, configurations, and application data. You allow Varsten to
          process that data as needed to run the service and to route traffic to the model providers you set up.
        </p>
      </ContentSection>

      <ContentSection title="Disclaimers and termination">
        <p>
          Varsten comes with the warranties, service levels, limits, and liability terms in your order form or written
          agreement. Either party may stop using the service under that agreement, and Varsten may suspend access for
          security, abuse, non-payment, or legal risk.
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
