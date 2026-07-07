// Single source of truth for the onboarding integration paths and their code
// snippets. Keeping the strings here (not inline in the view) stops the in-app
// funnel from drifting away from the marketing docs the way it did before, when
// onboarding shipped a base-URL snippet as "production" while the docs correctly
// pushed the fail-open SDK.

import type { IntegrationMethod } from "@/lib/types";

// The public proxy/ingest base customers point their client at. Distinct from the
// dashboard API host; swap per environment if the proxy host differs.
export const PROXY_BASE = "https://api.varsten.ai/v1";
export const DOCS_HREF = "https://varsten.ai/docs";

export type IntegrationPathId = "metadata" | "base_url" | "sdk";

export interface IntegrationPath {
  id: IntegrationPathId;
  // The traffic method this path produces, so we can match it against the
  // backend-detected integration method on the live first request.
  method: Extract<IntegrationMethod, "metadata" | "base_url" | "sdk">;
  name: string;
  tagline: string;
  // Outcome-led "who this is for" so a non-expert can choose without decoding
  // the trade-off tags below.
  bestFor: string;
  recommended?: boolean;
  // Tradeoff chips shown on the chooser card.
  failOpen: "yes" | "no" | "n/a";
  seesContent: boolean;
  needsProviderKey: boolean;
  unlocksOptimize: boolean;
  // Whether the "connect a provider key" step applies to this path.
  requiresProviderConnection: boolean;
}

export const INTEGRATION_PATHS: IntegrationPath[] = [
  {
    id: "sdk",
    method: "sdk",
    name: "Production SDK",
    tagline: "Fail-open wrapper. Optimize safely; a Varsten outage never takes your app down.",
    bestFor: "Going to production",
    recommended: true,
    failOpen: "yes",
    seesContent: true,
    needsProviderKey: true,
    unlocksOptimize: true,
    requiresProviderConnection: true,
  },
  {
    id: "base_url",
    method: "base_url",
    name: "Quick eval",
    tagline: "One-line base-URL change. Fastest way to see traffic. Evaluation only — not fail-open.",
    bestFor: "A fast first look",
    failOpen: "no",
    seesContent: true,
    needsProviderKey: true,
    unlocksOptimize: true,
    requiresProviderConnection: true,
  },
  {
    id: "metadata",
    method: "metadata",
    name: "Metadata only",
    tagline: "Send usage records async. Nothing inline, no content leaves your boundary, no provider key.",
    bestFor: "The strictest security review",
    failOpen: "n/a",
    seesContent: false,
    needsProviderKey: false,
    unlocksOptimize: false,
    requiresProviderConnection: false,
  },
];

export function integrationPath(id: IntegrationPathId): IntegrationPath {
  return INTEGRATION_PATHS.find((p) => p.id === id) ?? INTEGRATION_PATHS[0];
}

// --- snippets ---------------------------------------------------------------

export const SDK_INSTALL: { label: string; value: string }[] = [
  { label: "OpenAI", value: "npm install @varsten/openai openai" },
  { label: "Anthropic", value: "npm install @varsten/anthropic @anthropic-ai/sdk" },
  { label: "Gemini", value: "npm install @varsten/gemini @google/genai" },
];

export const SDK_SNIPPET = `import { VarstenOpenAI } from "@varsten/openai";

const client = new VarstenOpenAI({
  varstenApiKey: process.env.VARSTEN_API_KEY, // vk_...  (identifies you to Varsten)
  openaiApiKey: process.env.OPENAI_API_KEY,   // sk-...  (used only for direct fallback)
  onFallback: (event) => console.warn("varsten fallback", event.reasonCode),
});

// Identical to the OpenAI SDK. Fallback is invisible to this call site.
const res = await client.chat.completions.create({
  model: "gpt-4o-mini",
  messages: [{ role: "user", content: "Say hello from Varsten" }],
});

console.log(res._varsten?.servedBy); // "varsten" or "provider-fallback"`;

export const SDK_FAILOPEN_TEST = `# In a non-production shell only:
VARSTEN_BASE_URL=http://127.0.0.1:1 npm run your-ai-test

# The request should still complete through the provider,
# and your onFallback handler should log the reason code.`;

export const BASE_URL_SNIPPET = `import OpenAI from "openai";

const client = new OpenAI({
  apiKey: process.env.VARSTEN_API_KEY,
  baseURL: "${PROXY_BASE}",
});`;

export const BASE_URL_PROVIDER_SNIPPETS = [
  { label: "OpenAI", value: `baseURL: "${PROXY_BASE}"` },
  { label: "Anthropic", value: `baseURL: "${PROXY_BASE}"` },
  { label: "Gemini", value: `baseURL: "${PROXY_BASE}/v1beta"` },
];

// Metadata ingestion: token counts + labels only, never prompt/completion text.
export const METADATA_SNIPPET = `// After each LLM call, send a usage record. Metadata only — never prompt or
// completion text. No provider key needed; nothing sits in your request path.
await fetch("${PROXY_BASE}/usage-events", {
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
    feature: "support_agent",     // optional labels for workload-level savings
    customer_id: "cust_123",
    environment: "production",
    idempotency_key: requestId,   // retries never double-count
    occurred_at: new Date().toISOString(),
  }),
});`;
