import type { Metadata } from "next";
import { ContentCallout, ContentCode, ContentPage, ContentSection } from "../content-page";

export const metadata: Metadata = {
  title: "Status — Varsten",
  description: "Varsten service status and status wiring details.",
};

const statusConfig = `STATUS_ENDPOINT_URL=https://status.example.com/api/v2/status.json
STATUS_PAGE_URL=https://status.example.com`;

export default function StatusPage() {
  return (
    <ContentPage
      eyebrow="Status"
      title="Service Status"
      description="The landing page footer reads a live status endpoint before it says systems are nominal."
    >
      <ContentSection title="Current wiring">
        <p>
          The footer calls Varsten&apos;s marketing status API at <code>/api/status</code>. That API
          normalizes a configured upstream status or health endpoint into operational, degraded,
          outage, maintenance, or unknown.
        </p>
        <p>
          If no upstream endpoint is configured, the public footer shows “Status unavailable” instead
          of claiming that all systems are nominal.
        </p>
      </ContentSection>

      <ContentSection title="Configuration">
        <p>
          Configure these environment variables in production after choosing a status provider such as
          Statuspage, incident.io, Better Stack, or a Varsten-owned health endpoint.
        </p>
        <ContentCode>{statusConfig}</ContentCode>
      </ContentSection>

      <ContentCallout title="Incident contact">
        <p>
          For urgent production incidents, contact the Varsten team through your support channel or
          email <a href="mailto:support@varsten.ai">support@varsten.ai</a>.
        </p>
      </ContentCallout>
    </ContentPage>
  );
}
