import type { Metadata } from "next";
import {
  CONTACT_EMAIL,
  ContentCallout,
  ContentCard,
  ContentCode,
  ContentGrid,
  ContentPage,
  ContentSection,
} from "../content-page";

export const metadata: Metadata = {
  title: "Docs — Varsten",
  description: "Quickstart documentation for routing AI traffic through the Varsten proxy.",
};

const quickstartCode = `from openai import OpenAI
import os

client = OpenAI(
    base_url="https://proxy.varsten.ai/v1",
    api_key=os.environ["VARSTEN_API_KEY"],
)

stream = client.chat.completions.create(
    model="gpt-4o",
    messages=messages,
    stream=True,
)`;

export default function DocsPage() {
  return (
    <ContentPage
      eyebrow="Docs"
      title="Start sending AI traffic through Varsten."
      description="Varsten sits between your app and model providers so you can reuse safe responses, route to better-priced models, and verify savings without rewriting your product."
    >
      <ContentSection eyebrow="Quickstart" title="Drop in the proxy without changing your provider SDK.">
        <ContentGrid>
          <ContentCard title="1. Create a Varsten key">
            <p>Use a Varsten API key for the route you want to observe or optimize.</p>
          </ContentCard>
          <ContentCard title="2. Change the base URL">
            <p>Point your existing client at https://proxy.varsten.ai/v1.</p>
          </ContentCard>
          <ContentCard title="3. Keep your app behavior">
            <p>Streaming, tool calls, messages, and provider-compatible responses stay in place.</p>
          </ContentCard>
        </ContentGrid>
        <ContentCode>{quickstartCode}</ContentCode>
      </ContentSection>

      <ContentSection eyebrow="Core concepts" title="What Varsten does in the request path.">
        <ContentGrid>
          <ContentCard title="Response reuse">
            <p>
              Exact repeat requests can be served from stored responses where reuse is safe for that route. Near-duplicate
              matching should be enabled only for workloads with clear tolerance rules.
            </p>
          </ContentCard>
          <ContentCard title="Routing and evals">
            <p>
              Candidate model changes are checked against real traffic and quality gates before they become active. Routes
              can roll back when quality falls outside tolerance.
            </p>
          </ContentCard>
          <ContentCard title="Savings proof">
            <p>
              Billable savings should be tied to known avoided model cost, batch price differences, or approved routing
              experiments with an auditable baseline.
            </p>
          </ContentCard>
        </ContentGrid>
      </ContentSection>

      <ContentSection eyebrow="Operational defaults" title="Design routes so safety is explicit.">
        <ul className="lp-content-list">
          <li>Start with read-only monitoring if you want spend visibility before inline optimization.</li>
          <li>Use separate routes for workloads with different quality tolerances or retention needs.</li>
          <li>Keep fail-open behavior enabled for production paths that must continue serving during provider issues.</li>
          <li>Review the Proof dashboard before moving a recommendation into an automated policy.</li>
        </ul>
      </ContentSection>

      <ContentCallout title="Need help with an integration?">
        <p>
          Send your provider, framework, and first route target to{" "}
          <a href={`mailto:${CONTACT_EMAIL}`}>{CONTACT_EMAIL}</a>. We can help map the safest first workload.
        </p>
      </ContentCallout>
    </ContentPage>
  );
}
