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
  description: "Production installation steps for routing AI traffic through Varsten with fail-open SDK fallback.",
};

const proxyBase = "https://api.varsten.ai/v1";

const installCode = `# OpenAI
npm install @varsten/openai openai

# Anthropic
npm install @varsten/anthropic @anthropic-ai/sdk

# Gemini
npm install @varsten/gemini @google/genai`;

const envCode = `VARSTEN_API_KEY=vk_...
OPENAI_API_KEY=sk-...
ANTHROPIC_API_KEY=sk-ant-...
GEMINI_API_KEY=AIza...

# Optional. Defaults to https://api.varsten.ai/v1
VARSTEN_BASE_URL=${proxyBase}`;

const openaiCode = `import { VarstenOpenAI } from "@varsten/openai";

const client = new VarstenOpenAI({
  varstenApiKey: process.env.VARSTEN_API_KEY,
  openaiApiKey: process.env.OPENAI_API_KEY,
  onFallback: (event) => {
    console.warn("varsten fallback", event.reasonCode);
  },
});

const response = await client.chat.completions.create({
  model: "gpt-4o-mini",
  messages,
});`;

const providerCode = `// Anthropic
import { VarstenAnthropic } from "@varsten/anthropic";

const anthropic = new VarstenAnthropic({
  varstenApiKey: process.env.VARSTEN_API_KEY,
  anthropicApiKey: process.env.ANTHROPIC_API_KEY,
});

await anthropic.messages.create({
  model: "claude-3-5-sonnet-20241022",
  max_tokens: 256,
  messages,
});

// Gemini
import { VarstenGemini } from "@varsten/gemini";

const gemini = new VarstenGemini({
  varstenApiKey: process.env.VARSTEN_API_KEY,
  geminiApiKey: process.env.GEMINI_API_KEY,
});

await gemini.models.generateContent({
  model: "gemini-2.5-flash",
  contents,
});`;

const verifyCode = `const result = await client.chat.completions.create({
  model: "gpt-4o-mini",
  messages: [{ role: "user", content: "Say hello in five words." }],
});

console.log(result._varsten?.servedBy);
// "varsten" or "provider-fallback"`;

const fallbackTestCode = `# In a non-production shell only:
VARSTEN_BASE_URL=http://127.0.0.1:1 npm run your-ai-test

# The request should still complete through the provider.
# Your fallback log should print the reason code.`;

const evaluationCode = `import OpenAI from "openai";

const client = new OpenAI({
  apiKey: process.env.VARSTEN_API_KEY,
  baseURL: "${proxyBase}",
});`;

const metadataCode = `// Metadata only — token counts and labels, never prompt or completion text.
// No provider key, nothing in your request path, zero availability risk.
await fetch("${proxyBase}/usage-events", {
  method: "POST",
  headers: {
    "Authorization": \`Bearer \${process.env.VARSTEN_API_KEY}\`,
    "Content-Type": "application/json",
  },
  body: JSON.stringify({
    provider: "openai",
    model: "gpt-4o-mini",
    request_type: "chat_completion",
    input_tokens: usage.prompt_tokens,
    output_tokens: usage.completion_tokens,
    feature: "support_agent",       // optional labels for workload-level savings
    environment: "production",
    idempotency_key: requestId,     // retries never double-count
    occurred_at: new Date().toISOString(),
  }),
});`;

export default function DocsPage() {
  return (
    <ContentPage
      eyebrow="Docs"
      title="Setup Instructions"
      description="The production install uses the Varsten SDK wrapper. Your normal provider SDK still does the work, but the wrapper sends healthy traffic through Varsten and falls back directly to your provider when Varsten is unavailable."
    >
      <ContentSection id="quickstart" eyebrow="Production path" title="What you are changing">
        <ContentGrid>
          <ContentCard title="1. Add one Varsten package">
            <p>Install the wrapper for the provider you already use. Keep the official provider SDK installed.</p>
          </ContentCard>
          <ContentCard title="2. Keep both keys in your app">
            <p>Use a Varsten key for the optimized path and your provider key for direct fallback.</p>
          </ContentCard>
          <ContentCard title="3. Replace the client constructor">
            <p>Swap the provider client for the Varsten wrapper. Your request call sites should stay the same.</p>
          </ContentCard>
        </ContentGrid>
      </ContentSection>

      <ContentSection id="architecture" eyebrow="Architecture" title="Request path and fallback">
        <ContentGrid>
          <ContentCard title="Inline SDK path">
            <p>
              The SDK sends healthy traffic through Varsten so configured optimization policies can run.
              The local provider key remains available for direct fail-open fallback.
            </p>
          </ContentCard>
          <ContentCard title="Quick Eval path">
            <p>
              A stock OpenAI-compatible client points at Varsten with a base URL change. It is useful for
              evaluation traffic, but it is not the production fail-open path.
            </p>
          </ContentCard>
          <ContentCard title="Metadata-only path">
            <p>
              Usage events are posted asynchronously after provider calls. Nothing sits inline, so this path
              is analysis-only and cannot apply optimization levers.
            </p>
          </ContentCard>
        </ContentGrid>
      </ContentSection>

      <ContentSection eyebrow="Step 1" title="Install the SDK package">
        <p>Install the package for each provider you want to route through Varsten.</p>
        <ContentCode>{installCode}</ContentCode>
      </ContentSection>

      <ContentSection eyebrow="Step 2" title="Set environment variables">
        <p>
          Set the provider key for the provider you use. The Varsten key is sent to Varsten. The
          provider key stays in your app and is used only when the SDK needs to call the provider directly.
        </p>
        <ContentCode>{envCode}</ContentCode>
      </ContentSection>

      <ContentSection id="sdk-reference" eyebrow="Step 3" title="Replace the provider client">
        <p>
          Start with one route or service. Do not rewrite prompts, request bodies, streaming loops,
          or tool handling as part of the first install.
        </p>
        <ContentCode>{openaiCode}</ContentCode>
      </ContentSection>

      <ContentSection eyebrow="Other providers" title="Use the matching wrapper">
        <p>Anthropic and Gemini use the same pattern: Varsten key plus local provider key.</p>
        <ContentCode>{providerCode}</ContentCode>
      </ContentSection>

      <ContentSection eyebrow="Step 4" title="Verify one normal request">
        <p>
          Run one request in development or staging and log the `_varsten` marker. It is attached to
          the response and does not show up in serialized output.
        </p>
        <ContentCode>{verifyCode}</ContentCode>
      </ContentSection>

      <ContentSection eyebrow="Step 5" title="Test fallback before rollout">
        <p>
          In a non-production environment, point `VARSTEN_BASE_URL` at a dead local port. The same
          request should still complete through the provider if the provider key is configured.
        </p>
        <ContentCode>{fallbackTestCode}</ContentCode>
      </ContentSection>

      <ContentSection eyebrow="Rollout" title="Ship it in one narrow place first">
        <ul className="lp-content-list">
          <li>Start with one route, job, or service that already has stable provider traffic.</li>
          <li>Keep your existing provider key in the same secret store you use today.</li>
          <li>Log `onFallback` events to the same place you log provider errors.</li>
          <li>Watch the Varsten dashboard for request volume, savings proof, and fallback coverage.</li>
          <li>Expand route by route after the first route behaves normally.</li>
        </ul>
      </ContentSection>

      <ContentSection eyebrow="Fallback rules" title="What the SDK does and does not do">
        <ContentGrid>
          <ContentCard title="Falls back on Varsten failures">
            <p>
              DNS, connection failures, Varsten-origin 5xx errors, Varsten rate limits, and local
              circuit-breaker bypass can call the provider directly.
            </p>
          </ContentCard>
          <ContentCard title="Does not hide provider errors">
            <p>
              If the provider returns an error and Varsten relays it, the SDK returns that provider
              error. Retrying direct would usually double bill or hit the same problem.
            </p>
          </ContentCard>
          <ContentCard title="Does not restart mid-stream">
            <p>
              Streaming can fall back before output starts. Once tokens are flowing, a mid-stream
              error is surfaced instead of silently restarting the request.
            </p>
          </ContentCard>
        </ContentGrid>
      </ContentSection>

      <ContentSection eyebrow="Lowest-risk start" title="Metadata-only: nothing in your request path">
        <p>
          The safest way to start. Send usage records asynchronously after each call — token counts
          and labels, never prompt or completion content, and no provider key. Nothing sits inline,
          so there is zero availability risk and no content leaves your boundary. You get full spend
          and savings analysis; turning on optimization later means adding an inline path (the SDK or
          a base URL change).
        </p>
        <ContentCode>{metadataCode}</ContentCode>
      </ContentSection>

      <ContentSection eyebrow="Evaluation only" title="Use base URL changes only for low-risk trials">
        <p>
          A base-URL-only setup is useful when you want to see whether traffic reaches Varsten before
          adding the production wrapper. It does not provide direct-to-provider fallback if Varsten is
          unavailable.
        </p>
        <ContentCode>{evaluationCode}</ContentCode>
      </ContentSection>

      <ContentSection eyebrow="Before you finish" title="Check the boring things">
        <ul className="lp-content-list">
          <li>The app has `VARSTEN_API_KEY` and the provider key in every deployed environment.</li>
          <li>Your fallback log does not include prompts, completions, or customer content.</li>
          <li>Your team knows that a fallback means Varsten savings and analytics may be missing for that request.</li>
          <li>Your first rollout is small enough that you can compare provider behavior before and after.</li>
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
