import type { Metadata } from "next";
import {
  CONTACT_EMAIL,
  ContentCallout,
  ContentCard,
  ContentGrid,
  ContentPage,
  ContentSection,
} from "../content-page";

export const metadata: Metadata = {
  title: "Security — Varsten",
  description: "Varsten security, data handling, access control, and reliability posture.",
};

export default function SecurityPage() {
  return (
    <ContentPage
      eyebrow="Security"
      title="Built for AI traffic that has to keep serving."
      description="Varsten is designed as an inline proxy with conservative controls around data handling, access, provider routing, and fail-open reliability."
    >
      <ContentSection eyebrow="Data handling" title="Keep request data scoped to the route purpose.">
        <ContentGrid>
          <ContentCard title="Route-level policy">
            <p>
              Reuse, retention, routing, and eval behavior should be configured per route so sensitive workloads can use
              stricter controls than low-risk workloads.
            </p>
          </ContentCard>
          <ContentCard title="Provider-compatible traffic">
            <p>
              Varsten forwards provider-compatible requests and responses so teams can preserve existing SDKs while
              adding savings and quality guardrails.
            </p>
          </ContentCard>
          <ContentCard title="Proof records">
            <p>
              Savings records should include enough attribution to explain the avoided cost, route, model, and quality
              decision behind a billable optimization.
            </p>
          </ContentCard>
        </ContentGrid>
      </ContentSection>

      <ContentSection eyebrow="Controls" title="Access and reliability controls stay explicit.">
        <ul className="lp-content-list">
          <li>Production traffic should use scoped API keys instead of shared personal credentials.</li>
          <li>Inline routes should fail open to the original provider when Varsten or an upstream dependency is unavailable.</li>
          <li>Strict read and total timeouts should prevent a hung upstream from pinning production connections.</li>
          <li>Administrative access should be limited to people who need billing, routing, eval, or security review access.</li>
        </ul>
      </ContentSection>

      <ContentSection eyebrow="Compliance" title="Clear posture, no inflated claims.">
        <p>
          Varsten should not claim SOC 2, ISO 27001, HIPAA, or other formal certifications on this page until signed
          reports or agreements are available. Enterprise security reviews, DPA requests, and deployment requirements can
          be handled directly with the Varsten team.
        </p>
      </ContentSection>

      <ContentCallout title="Report a vulnerability or request a security review">
        <p>
          Email <a href={`mailto:${CONTACT_EMAIL}`}>{CONTACT_EMAIL}</a> with a clear description, affected route or
          endpoint, reproduction steps, and the best way to contact you.
        </p>
      </ContentCallout>
    </ContentPage>
  );
}
