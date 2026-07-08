// Single source of truth for the onboarding integration paths and their code
// snippets. Keeping the strings here (not inline in the view) stops the in-app
// funnel from drifting away from the marketing docs the way it did before, when
// onboarding shipped a base-URL snippet as "production" while the docs correctly
// pushed the fail-open SDK.

import type { IntegrationMethod } from "@/lib/types";

// The public proxy/ingest base customers point their client at. Distinct from the
// dashboard API host when the proxy host differs. In local/e2e environments the
// dashboard API often serves the proxy routes too, so fall back to API_BASE + /v1.
const PRODUCTION_PROXY_BASE = "https://api.varsten.ai/v1";

function normalizeProxyBase(value: string | undefined): string | undefined {
  const trimmed = value?.trim().replace(/\/+$/, "");
  if (!trimmed) return undefined;
  return trimmed.endsWith("/v1") ? trimmed : `${trimmed}/v1`;
}

export const PROXY_BASE =
  normalizeProxyBase(process.env.NEXT_PUBLIC_VARSTEN_PROXY_BASE) ??
  normalizeProxyBase(process.env.NEXT_PUBLIC_API_BASE) ??
  PRODUCTION_PROXY_BASE;
export const DOCS_HREF = "https://varsten.ai/docs";

export type IntegrationPathId = "metadata" | "base_url" | "sdk";
export type IntegrationProviderId = "openai" | "anthropic" | "gemini";

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

export const SDK_PROVIDER_SNIPPETS: Record<IntegrationProviderId, { label: string; install: string; snippet: string }> = {
  openai: {
    label: "OpenAI",
    install: "npm install @varsten/openai openai",
    snippet: `import { VarstenOpenAI } from "@varsten/openai";

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

console.log(res._varsten?.servedBy); // "varsten" or "provider-fallback"`,
  },
  anthropic: {
    label: "Anthropic",
    install: "npm install @varsten/anthropic @anthropic-ai/sdk",
    snippet: `import { VarstenAnthropic } from "@varsten/anthropic";

const client = new VarstenAnthropic({
  varstenApiKey: process.env.VARSTEN_API_KEY,     // vk_...
  anthropicApiKey: process.env.ANTHROPIC_API_KEY, // sk-ant-... used only for direct fallback
  onFallback: (event) => console.warn("varsten fallback", event.reasonCode),
});

const res = await client.messages.create({
  model: "claude-3-5-haiku-20241022",
  max_tokens: 256,
  messages: [{ role: "user", content: "Say hello from Varsten" }],
});

console.log(res._varsten?.servedBy); // "varsten" or "provider-fallback"`,
  },
  gemini: {
    label: "Gemini",
    install: "npm install @varsten/gemini @google/genai",
    snippet: `import { VarstenGemini } from "@varsten/gemini";

const client = new VarstenGemini({
  varstenApiKey: process.env.VARSTEN_API_KEY, // vk_...
  geminiApiKey: process.env.GEMINI_API_KEY,   // AIza... used only for direct fallback
  onFallback: (event) => console.warn("varsten fallback", event.reasonCode),
});

const res = await client.models.generateContent({
  model: "gemini-2.5-flash",
  contents: "Say hello from Varsten",
});

console.log(res._varsten?.servedBy); // "varsten" or "provider-fallback"`,
  },
};

export const SDK_FAILOPEN_TEST = `# In a non-production shell only:
VARSTEN_BASE_URL=http://127.0.0.1:1 npm run your-ai-test

# The request should still complete through the provider,
# and your onFallback handler should log the reason code.`;

export const BASE_URL_PROVIDER_SNIPPETS: Record<IntegrationProviderId, { label: string; endpoint: string; snippet: string }> = {
  openai: {
    label: "OpenAI",
    endpoint: `baseURL: "${PROXY_BASE}"`,
    snippet: `import OpenAI from "openai";

const client = new OpenAI({
  apiKey: process.env.VARSTEN_API_KEY,
  baseURL: "${PROXY_BASE}",
});`,
  },
  anthropic: {
    label: "Anthropic",
    endpoint: `baseURL: "${PROXY_BASE}"`,
    snippet: `import Anthropic from "@anthropic-ai/sdk";

const client = new Anthropic({
  apiKey: process.env.VARSTEN_API_KEY,
  baseURL: "${PROXY_BASE}",
});`,
  },
  gemini: {
    label: "Gemini",
    endpoint: `baseUrl: "${PROXY_BASE}/v1beta"`,
    snippet: `import { GoogleGenAI } from "@google/genai";

const client = new GoogleGenAI({
  apiKey: process.env.VARSTEN_API_KEY,
  httpOptions: { baseUrl: "${PROXY_BASE}/v1beta" },
});`,
  },
};

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
