# @varsten/anthropic

A fail-open wrapper around the Anthropic SDK.

When Varsten is healthy, your traffic is optimized through it. When Varsten is
unreachable, slow to connect, or returns an error of its own, the **same request
goes directly to Anthropic** with your local key. A Varsten outage costs you
savings and analytics for a few minutes, not your app's uptime.

This is the production integration. The base-URL-only setup (pointing the stock
Anthropic SDK at the Varsten host) is great for evaluation, but it keeps Varsten in
your request path with no way around it if Varsten is down. Use this SDK for
anything production-critical.

> Status: v0.1.0. Messages (streaming and non-streaming) have direct-to-provider
> fallback. Streaming falls back only *before the first token*; once a stream has
> started, a mid-stream error surfaces to you and is never restarted. Every request
> carries an idempotency key so a fallback retry can't double-bill at the provider.
> Shares the `@varsten/core` fail-open engine with `@varsten/openai` and
> `@varsten/gemini`.

## Install

```bash
npm install @varsten/anthropic @anthropic-ai/sdk
```

`@anthropic-ai/sdk` is a peer dependency; the wrapper delegates to it for both the
optimized and the direct path.

## Quickstart

```ts
import { VarstenAnthropic } from "@varsten/anthropic";

const client = new VarstenAnthropic({
  varstenApiKey: process.env.VARSTEN_API_KEY,     // vk_...    (sent to Varsten only)
  anthropicApiKey: process.env.ANTHROPIC_API_KEY, // sk-ant-.. (stays local; used only on fallback)
  onFallback: (e) => console.warn("varsten fallback", e.reasonCode),
});

const res = await client.messages.create({
  model: "claude-3-5-sonnet-20241022",
  max_tokens: 256,
  messages: [{ role: "user", content: "Say hello in five words." }],
});
```

The optimized client targets Varsten's host root and authenticates with the `vk_`
key via `x-api-key`, which the proxy accepts for the Anthropic dialect. Your
Anthropic key is only ever used for the direct fallback and is never sent to
Varsten.

## How fallback decides (shared contract)

Identical to the other Varsten wrappers, because they share `@varsten/core`:

- **Transport failure** (DNS, refused, TLS, connect) → fall back.
- **Varsten-origin error** (`circuit_open`, `rate_limited`, `upstream_unreachable`,
  `no_provider_key`, internal 5xx) → fall back. Identified by the `X-Varsten-Origin`
  header the Anthropic SDK exposes on the error.
- **Relayed provider error** (`origin: provider`, any 4xx/5xx, safety block) →
  **never** fall back; returned verbatim so you are never double-billed.
- **`budget_exceeded` (402)** → surfaced, not bypassed; it is a deliberate cap.
- **Read timeout** → surfaced by default (opt in with `fallbackOnReadTimeout`).

See `docs/design/SDK_FAILOPEN_DESIGN_FREEZE.md` for the full frozen contract.
