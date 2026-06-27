# @varsten/gemini

A fail-open wrapper around the Google Gen AI SDK.

When Varsten is healthy, your traffic is optimized through it. When Varsten is
unreachable, slow to connect, or returns an error of its own, the **same request
goes directly to Gemini** with your local key. A Varsten outage costs you savings
and analytics for a few minutes, not your app's uptime.

This is the production integration. The base-URL-only setup (pointing the stock Gen
AI SDK at the Varsten host) is great for evaluation, but it keeps Varsten in your
request path with no way around it if Varsten is down. Use this SDK for anything
production-critical.

> Status: v0.1.0. `generateContent` and `generateContentStream` have
> direct-to-provider fallback. Streaming falls back only *before the first token*;
> once a stream has started, a mid-stream error surfaces to you and is never
> restarted. Shares the `@varsten/core` fail-open engine with `@varsten/openai` and
> `@varsten/anthropic`.

## Install

```bash
npm install @varsten/gemini @google/genai
```

`@google/genai` is a peer dependency; the wrapper delegates to it for both the
optimized and the direct path.

## Quickstart

```ts
import { VarstenGemini } from "@varsten/gemini";

const client = new VarstenGemini({
  varstenApiKey: process.env.VARSTEN_API_KEY, // vk_...  (sent to Varsten only)
  geminiApiKey: process.env.GEMINI_API_KEY,   // AIza... (stays local; used only on fallback)
  onFallback: (e) => console.warn("varsten fallback", e.reasonCode),
});

const res = await client.models.generateContent({
  model: "gemini-2.5-flash",
  contents: "Say hello in five words.",
});
```

The optimized client targets Varsten's host root and authenticates with the `vk_`
key via `x-goog-api-key`, which the proxy accepts for the Gemini dialect. Your
Gemini key is only ever used for the direct fallback and is never sent to Varsten.

## A note on the fallback contract for Gemini

The fallback policy is the shared `@varsten/core` contract, with one provider
nuance. Google's `ApiError` does not expose response headers, so the
`X-Varsten-Origin` header cannot be read off a thrown error the way it can for
OpenAI and Anthropic. Instead:

- **Varsten-origin errors** carry `origin: "varsten"` in the response *body*
  (`circuit_open`, `rate_limited`, `upstream_unreachable`, `no_provider_key`,
  internal errors), and the Gen AI SDK puts that body on `ApiError.message`, so they
  are still positively identified and **do** fall back.
- **Transport failures** (fetch `TypeError`, `AbortError`) **do** fall back.
- An **unattributed 5xx** — one that could be a faithfully relayed provider error —
  is **surfaced, not retried**, so a Gemini fallback never risks a double-bill. This
  is deliberately more conservative than the header-readable providers, trading the
  rare bare-crash fallback for a guarantee of no duplicate billing.

See `docs/design/SDK_FAILOPEN_DESIGN_FREEZE.md` for the full frozen contract.
