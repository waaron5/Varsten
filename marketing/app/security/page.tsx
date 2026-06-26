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
      description="Varsten is an inline proxy with careful controls around data handling, access, provider routing, and reliability."
    >
      <ContentSection eyebrow="Data handling" title="Keep request data scoped to the route's purpose.">
        <ContentGrid>
          <ContentCard title="Route-level policy">
            <p>
              Set reuse, retention, routing, and eval behavior per route. That way sensitive workloads can use stricter
              controls than low-risk ones.
            </p>
          </ContentCard>
          <ContentCard title="Provider-compatible traffic">
            <p>
              Varsten passes through provider-compatible requests and responses. You keep your current SDKs and add
              savings and quality guardrails on top.
            </p>
          </ContentCard>
          <ContentCard title="Proof records">
            <p>
              Each savings record holds enough detail to explain the avoided cost, the route, the model, and the quality
              decision behind a billable optimization.
            </p>
          </ContentCard>
        </ContentGrid>
      </ContentSection>

      <ContentSection eyebrow="Controls" title="Access and reliability controls stay clear.">
        <ul className="lp-content-list">
          <li>Use scoped API keys for production traffic instead of shared personal credentials.</li>
          <li>Pass requests through to the original provider when an internal optimization step fails, and use a circuit breaker with strict timeouts so a failing upstream cannot stall traffic.</li>
          <li>Base-URL integration keeps Varsten in the request path; service-level fallback that calls your provider directly during a Varsten outage ships with the Varsten SDK, which is in development.</li>
          <li>Use strict read and total timeouts so a hung upstream cannot tie up production connections.</li>
          <li>Limit admin access to people who need billing, routing, eval, or security review.</li>
        </ul>
      </ContentSection>

      <ContentSection eyebrow="Compliance" title="A clear posture, with no inflated claims.">
        <p>
          Varsten does not claim SOC 2, ISO 27001, HIPAA, or other formal certifications on this page until signed
          reports or agreements are in place. You can handle enterprise security reviews, DPA requests, and deployment
          requirements directly with the Varsten team.
        </p>
      </ContentSection>

      <ContentCallout title="Report a vulnerability or request a security review">
        <p>
          Email <a href={`mailto:${CONTACT_EMAIL}`}>{CONTACT_EMAIL}</a> with a clear description, the affected route or
          endpoint, steps to reproduce it, and the best way to reach you.
        </p>
      </ContentCallout>
    </ContentPage>
  );
}
