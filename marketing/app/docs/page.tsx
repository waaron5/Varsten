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
      title="Send your AI traffic through Varsten."
      description="Varsten sits between your app and your model providers. You can reuse safe responses, route to lower-priced models, and confirm your savings. You do not have to rewrite your product to do it."
    >
      <ContentSection eyebrow="Quickstart" title="Add the proxy without changing your provider SDK.">
        <ContentGrid>
          <ContentCard title="1. Create a Varsten key">
            <p>Make a Varsten API key for the route you want to watch or optimize.</p>
          </ContentCard>
          <ContentCard title="2. Change the base URL">
            <p>Point your current client at https://proxy.varsten.ai/v1.</p>
          </ContentCard>
          <ContentCard title="3. Keep your app as it is">
            <p>Streaming, tool calls, messages, and provider-compatible responses all keep working.</p>
          </ContentCard>
        </ContentGrid>
        <ContentCode>{quickstartCode}</ContentCode>
      </ContentSection>

      <ContentCallout title="Evaluation vs production fail-open">
        <p>
          The base-URL change is the fastest way to evaluate Varsten and is a good fit for
          development and low-risk workloads. It keeps Varsten in your request path, so a Varsten
          outage would interrupt requests to it. Service-level fallback that calls your provider
          directly when Varsten is unavailable ships with the Varsten SDK, which is in development.
        </p>
      </ContentCallout>

      <ContentSection eyebrow="Core concepts" title="What Varsten does in the request path.">
        <ContentGrid>
          <ContentCard title="Response reuse">
            <p>
              When the same request comes in again, Varsten can serve a stored response if reuse is safe for that route.
              Turn on near-duplicate matching only for workloads that have clear rules about what counts as close enough.
            </p>
          </ContentCard>
          <ContentCard title="Routing and evals">
            <p>
              Before a new model takes over a route, Varsten checks it against real traffic and your quality gates. If
              quality drops below your limits, the route can roll back.
            </p>
          </ContentCard>
          <ContentCard title="Savings proof">
            <p>
              Billable savings are tied to known avoided model cost, batch price differences, or approved routing tests.
              Each one has a baseline you can audit.
            </p>
          </ContentCard>
        </ContentGrid>
      </ContentSection>

      <ContentSection eyebrow="Operational defaults" title="Set up routes so safety is clear.">
        <ul className="lp-content-list">
          <li>Begin with read-only monitoring if you want to see spend before you optimize anything inline.</li>
          <li>Use separate routes for workloads with different quality needs or retention rules.</li>
          <li>Rely on the circuit breaker and strict timeouts so a struggling provider fails fast instead of tying up your connections.</li>
          <li>Check the Proof dashboard before you turn a recommendation into an automatic policy.</li>
        </ul>
      </ContentSection>

      <ContentCallout title="Need help with an integration?">
        <p>
          Send your provider, framework, and first route target to{" "}
          <a href={`mailto:${CONTACT_EMAIL}`}>{CONTACT_EMAIL}</a>. We can help you pick the safest workload to start
          with.
        </p>
      </ContentCallout>
    </ContentPage>
  );
}
