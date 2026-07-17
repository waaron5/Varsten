// Single source of truth for the onboarding integration paths and the generated
// setup recipes. Keeping the strings here (not inline in the view) stops the
// in-app funnel from drifting away from the marketing docs the way it did
// before, when onboarding shipped a base-URL snippet as "production" while the
// docs correctly pushed the fail-open SDK.
//
// Base-URL correctness matters per provider and is verified by the live smoke
// suite (backend/tests/test_sdk_smoke.py) and docs/PROVIDER_COMPATIBILITY.md:
//   - OpenAI SDKs take `{host}/v1` (paths like /chat/completions are appended).
//   - Anthropic SDKs take `{host}` — the SDK itself appends /v1/messages.
//   - google-genai takes `{host}` plus api_version "v1beta".

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

// Host root without /v1 — what the Anthropic and Gemini SDKs need, because they
// append their own version segment (/v1/messages, /v1beta/models/...).
const PROXY_HOST = PROXY_BASE.replace(/\/v1$/, "");

export const DOCS_HREF = "https://varsten.ai/docs";

export type IntegrationPathId = "metadata" | "base_url" | "sdk";
export type IntegrationProviderId = "openai" | "anthropic" | "gemini";
export type IntegrationLanguageId = "node" | "python" | "curl";

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
    name: "Gateway URL",
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

// The in-VPC sidecar data plane is a designed deployment pattern, not a shipped
// one. It is shown on the chooser as planned — never selectable — so the funnel
// stays honest about what the backend supports today.
export const SIDECAR_PLANNED = {
  id: "sidecar" as const,
  name: "Sidecar / in-VPC",
  tagline:
    "Run the Varsten data plane inside your own cloud boundary. Prompt and completion content never leaves your VPC; only token counts and scores reach the control plane.",
  bestFor: "In-VPC deployments",
  contactHref: "mailto:mail@varsten.ai?subject=Varsten%20in-VPC%20sidecar",
};

export const INTEGRATION_LANGUAGES: { id: IntegrationLanguageId; label: string }[] = [
  { id: "node", label: "TypeScript" },
  { id: "python", label: "Python" },
  { id: "curl", label: "HTTP / other" },
];

// The fail-open SDK ships for TypeScript/Node today. Other stacks use the
// gateway URL or metadata ingestion, which are language-agnostic HTTP.
export function sdkSupportsLanguage(language: IntegrationLanguageId): boolean {
  return language === "node";
}

export const PROVIDER_LABELS: Record<IntegrationProviderId, string> = {
  openai: "OpenAI",
  anthropic: "Anthropic",
  gemini: "Gemini",
};

export const EXAMPLE_MODELS: Record<IntegrationProviderId, string> = {
  openai: "gpt-4o-mini",
  anthropic: "claude-haiku-4-5-20251001",
  gemini: "gemini-2.5-flash",
};

const PROVIDER_ENV_KEYS: Record<IntegrationProviderId, { name: string; placeholder: string }> = {
  openai: { name: "OPENAI_API_KEY", placeholder: "sk-..." },
  anthropic: { name: "ANTHROPIC_API_KEY", placeholder: "sk-ant-..." },
  gemini: { name: "GEMINI_API_KEY", placeholder: "AIza..." },
};

// --- recipe model -------------------------------------------------------------

export interface RecipeBlock {
  id: "install" | "env" | "code" | "self-test";
  // Mono header label, e.g. "TERMINAL", ".ENV", "APP / TYPESCRIPT".
  label: string;
  code: string;
  copyLabel: string;
  // Copying this block counts as "snippet viewed" for the funnel checklist.
  countsAsSnippetViewed?: boolean;
}

export interface RecipeInput {
  path: IntegrationPathId;
  provider: IntegrationProviderId;
  language: IntegrationLanguageId;
  // Plaintext vk_ key when it was created in this session; injected into the env
  // block so the recipe is copy-paste complete. Never persisted anywhere.
  varstenKey?: string | null;
}

function languageBlockLabel(language: IntegrationLanguageId): string {
  switch (language) {
    case "node":
      return "APP / TYPESCRIPT";
    case "python":
      return "APP / PYTHON";
    case "curl":
      return "TERMINAL / CURL";
  }
}

function envBlock(input: RecipeInput): RecipeBlock {
  const vk = input.varstenKey ?? "vk_...";
  const lines = [`VARSTEN_API_KEY=${vk}`];
  if (input.path === "sdk") {
    const env = PROVIDER_ENV_KEYS[input.provider];
    lines.push(`${env.name}=${env.placeholder}  # stays local — used only for direct fallback`);
  }
  return {
    id: "env",
    label: ".ENV",
    code: lines.join("\n"),
    copyLabel: "Copy env vars",
  };
}

// --- SDK recipes (TypeScript only today) ---------------------------------------

const SDK_INSTALL: Record<IntegrationProviderId, string> = {
  openai: "npm install @varsten/openai openai",
  anthropic: "npm install @varsten/anthropic @anthropic-ai/sdk",
  gemini: "npm install @varsten/gemini @google/genai",
};

const SDK_CODE: Record<IntegrationProviderId, string> = {
  openai: `import { VarstenOpenAI } from "@varsten/openai";

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
  anthropic: `import { VarstenAnthropic } from "@varsten/anthropic";

const client = new VarstenAnthropic({
  varstenApiKey: process.env.VARSTEN_API_KEY,     // vk_...
  anthropicApiKey: process.env.ANTHROPIC_API_KEY, // sk-ant-... used only for direct fallback
  onFallback: (event) => console.warn("varsten fallback", event.reasonCode),
});

const res = await client.messages.create({
  model: "claude-haiku-4-5-20251001",
  max_tokens: 256,
  messages: [{ role: "user", content: "Say hello from Varsten" }],
});

console.log(res._varsten?.servedBy); // "varsten" or "provider-fallback"`,
  gemini: `import { VarstenGemini } from "@varsten/gemini";

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
};

export const SDK_FAILOPEN_TEST = `# In a non-production shell only:
VARSTEN_BASE_URL=http://127.0.0.1:1 npm run your-ai-test

# The request should still complete through the provider,
# and your onFallback handler should log the reason code.`;

// --- gateway base-URL recipes ---------------------------------------------------
// The Varsten API key replaces the provider key in the client; the real provider
// key is vaulted server-side. Base URLs differ per provider because each official
// SDK appends its own version segment.

const BASE_URL_CODE: Record<IntegrationProviderId, Record<IntegrationLanguageId, string>> = {
  openai: {
    node: `import OpenAI from "openai";

const client = new OpenAI({
  apiKey: process.env.VARSTEN_API_KEY, // vk_... — your OpenAI key stays vaulted with Varsten
  baseURL: "${PROXY_BASE}",
});`,
    python: `import os
from openai import OpenAI

client = OpenAI(
    api_key=os.environ["VARSTEN_API_KEY"],  # vk_... — your OpenAI key stays vaulted with Varsten
    base_url="${PROXY_BASE}",
)`,
    curl: `curl ${PROXY_BASE}/chat/completions \\
  -H "Authorization: Bearer $VARSTEN_API_KEY" \\
  -H "Content-Type: application/json" \\
  -d '{
    "model": "gpt-4o-mini",
    "messages": [{"role": "user", "content": "Say hello from Varsten"}]
  }'`,
  },
  anthropic: {
    node: `import Anthropic from "@anthropic-ai/sdk";

const client = new Anthropic({
  apiKey: process.env.VARSTEN_API_KEY, // vk_... — your Anthropic key stays vaulted with Varsten
  baseURL: "${PROXY_HOST}", // no /v1 — the SDK appends /v1/messages itself
});`,
    python: `import os
import anthropic

client = anthropic.Anthropic(
    api_key=os.environ["VARSTEN_API_KEY"],  # vk_... — your Anthropic key stays vaulted with Varsten
    base_url="${PROXY_HOST}",  # no /v1 — the SDK appends /v1/messages itself
)`,
    curl: `curl ${PROXY_BASE}/messages \\
  -H "x-api-key: $VARSTEN_API_KEY" \\
  -H "anthropic-version: 2023-06-01" \\
  -H "Content-Type: application/json" \\
  -d '{
    "model": "claude-haiku-4-5-20251001",
    "max_tokens": 256,
    "messages": [{"role": "user", "content": "Say hello from Varsten"}]
  }'`,
  },
  gemini: {
    node: `import { GoogleGenAI } from "@google/genai";

const client = new GoogleGenAI({
  apiKey: process.env.VARSTEN_API_KEY, // vk_... — your Gemini key stays vaulted with Varsten
  httpOptions: { baseUrl: "${PROXY_HOST}", apiVersion: "v1beta" },
});`,
    python: `import os
from google import genai
from google.genai import types

client = genai.Client(
    api_key=os.environ["VARSTEN_API_KEY"],  # vk_... — your Gemini key stays vaulted with Varsten
    http_options=types.HttpOptions(base_url="${PROXY_HOST}", api_version="v1beta"),
)`,
    curl: `curl ${PROXY_HOST}/v1beta/models/gemini-2.5-flash:generateContent \\
  -H "x-goog-api-key: $VARSTEN_API_KEY" \\
  -H "Content-Type: application/json" \\
  -d '{
    "contents": [{"parts": [{"text": "Say hello from Varsten"}]}]
  }'`,
  },
};

// --- metadata ingestion recipes --------------------------------------------------
// Token counts + labels only, never prompt/completion text. No provider key.

function metadataCode(provider: IntegrationProviderId, language: IntegrationLanguageId): string {
  const model = EXAMPLE_MODELS[provider];
  switch (language) {
    case "node":
      return `// After each LLM call, send a usage record. Metadata only — never prompt or
// completion text. No provider key needed; nothing sits in your request path.
await fetch("${PROXY_BASE}/usage-events", {
  method: "POST",
  headers: {
    "Authorization": \`Bearer \${process.env.VARSTEN_API_KEY}\`,
    "Content-Type": "application/json",
  },
  body: JSON.stringify({
    provider: "${provider}",
    model: "${model}",
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
    case "python":
      return `# After each LLM call, send a usage record. Metadata only — never prompt or
# completion text. No provider key needed; nothing sits in your request path.
import os
from datetime import UTC, datetime

import requests

requests.post(
    "${PROXY_BASE}/usage-events",
    headers={"Authorization": f"Bearer {os.environ['VARSTEN_API_KEY']}"},
    json={
        "provider": "${provider}",
        "model": "${model}",
        "request_type": "chat_completion",
        "input_tokens": usage.prompt_tokens,
        "output_tokens": usage.completion_tokens,
        "feature": "support_agent",   # optional labels for workload-level savings
        "customer_id": "cust_123",
        "environment": "production",
        "idempotency_key": request_id,  # retries never double-count
        "occurred_at": datetime.now(UTC).isoformat(),
    },
    timeout=5,
)`;
    case "curl":
      return `curl ${PROXY_BASE}/usage-events \\
  -H "Authorization: Bearer $VARSTEN_API_KEY" \\
  -H "Content-Type: application/json" \\
  -d '{
    "provider": "${provider}",
    "model": "${model}",
    "request_type": "chat_completion",
    "input_tokens": 1200,
    "output_tokens": 340,
    "feature": "support_agent",
    "environment": "production",
    "idempotency_key": "req_abc123",
    "occurred_at": "2026-07-16T12:00:00Z"
  }'`;
  }
}

// --- recipe builder ---------------------------------------------------------------

export function buildRecipe(input: RecipeInput): RecipeBlock[] {
  const providerLabel = PROVIDER_LABELS[input.provider];
  const blocks: RecipeBlock[] = [];

  if (input.path === "sdk") {
    blocks.push({
      id: "install",
      label: "TERMINAL",
      code: SDK_INSTALL[input.provider],
      copyLabel: "Copy install command",
    });
    blocks.push(envBlock(input));
    blocks.push({
      id: "code",
      label: languageBlockLabel("node"),
      code: SDK_CODE[input.provider],
      copyLabel: `Copy ${providerLabel} SDK snippet`,
      countsAsSnippetViewed: true,
    });
    return blocks;
  }

  if (input.path === "base_url") {
    blocks.push(envBlock(input));
    blocks.push({
      id: "code",
      label: languageBlockLabel(input.language),
      code: BASE_URL_CODE[input.provider][input.language],
      copyLabel: `Copy ${providerLabel} snippet`,
      countsAsSnippetViewed: true,
    });
    return blocks;
  }

  blocks.push(envBlock(input));
  blocks.push({
    id: "code",
    label: languageBlockLabel(input.language),
    code: metadataCode(input.provider, input.language),
    copyLabel: "Copy ingest snippet",
    countsAsSnippetViewed: true,
  });
  return blocks;
}
