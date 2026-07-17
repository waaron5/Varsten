# @varsten/openai

A fail-open wrapper around the OpenAI SDK.

When Varsten is healthy, your traffic is optimized through it. When Varsten is
unreachable, slow to connect, or returns an error of its own, the **same request
goes directly to your provider** with your local key. A Varsten outage costs you
savings and analytics for a few minutes, not your app's uptime.

This is the production integration. The base-URL-only setup (pointing the stock
OpenAI SDK at `https://api.varsten.ai/v1`) is great for evaluation, but it keeps
Varsten in your request path with no way around it if Varsten is down. Use this
SDK for anything production-critical.

> Status: v0.1.0 beta. Chat completions (streaming and non-streaming) have
> direct-to-provider fallback. Streaming falls back only *before the first token*
> (if the optimized request fails before a stream is returned); once a stream has
> started, a mid-stream error surfaces to you and is never restarted. Every request
> carries an idempotency key so a fallback retry can't double-bill at the provider.
> Shares the `@varsten/core` fail-open engine with `@varsten/anthropic` and
> `@varsten/gemini`.

## Install

```bash
npm install @varsten/openai openai
```

`openai` is a peer dependency; the wrapper delegates to it for both the optimized
and the direct path.

Runtime: Node.js 18 or newer. This is an ESM package; CommonJS applications must
use dynamic `import()` or an ESM entry point. JavaScript, TypeScript declarations,
source maps, and declaration maps are included.

## Quickstart

```ts
import { VarstenOpenAI } from "@varsten/openai";

const client = new VarstenOpenAI({
  varstenApiKey: process.env.VARSTEN_API_KEY, // vk_...  (sent to Varsten only)
  openaiApiKey: process.env.OPENAI_API_KEY,   // sk-...  (stays local; used only on fallback)
  onFallback: (e) => console.warn("varsten fallback", e.reasonCode),
});

const res = await client.chat.completions.create({
  model: "gpt-4o-mini",
  messages: [{ role: "user", content: "Hello" }],
});

console.log(res.choices[0].message.content);
```

The surface mirrors the OpenAI SDK, so existing call sites need no other changes.

## Workflow metadata and agent traces

Tell Varsten what a request *is* — which feature, which of your customers,
which agent workflow — and the engine can allocate cost, pick task-aware
optimizations, and detect redundant calls inside agent loops. Pass `varsten`
metadata as a per-request option; it rides the optimized attempt as the
`X-Varsten-Metadata` header and is **never sent to the provider** on a direct
fallback. Labels only, never prompt or completion content.

```ts
import { VarstenTrace } from "@varsten/openai";

// One trace per logical workflow (an agent run, a session):
const trace = new VarstenTrace();

for (const step of steps) {
  await client.chat.completions.create(body, {
    varsten: trace.metadata({
      feature: "research_agent",
      taskType: "research.step",
      customerId: "cust_123",
    }),
  });
}
```

Calls sharing a trace id are analyzed as one workflow: if the agent asks the
same question twice, the engine quantifies the waste and recommends
memoization or an idempotency guard — it will not silently dedupe your calls.

## Environment variables

| Variable           | Purpose                                  | Sent to        |
| ------------------ | ---------------------------------------- | -------------- |
| `VARSTEN_API_KEY`  | your `vk_` key                           | Varsten only   |
| `OPENAI_API_KEY`   | your provider key                        | provider only  |
| `VARSTEN_BASE_URL` | override the proxy URL (optional)        | —              |

Any constructor option overrides the matching environment variable.

## Configuration

```ts
new VarstenOpenAI({
  varstenApiKey,
  openaiApiKey,
  baseURL,                       // default https://api.varsten.ai/v1
  fallback: "auto",              // "auto" (default) | "off"
  fallbackOnReadTimeout: false,  // see "Double billing" below
  onFallback: (event) => {},     // synchronous, in-process notification
  timeouts: { varstenTotalMs: 60000, providerTotalMs: 60000 },
  breakerThreshold: 5,           // consecutive Varsten failures before bypass
  breakerCooldownMs: 30000,
});
```

## When the SDK falls back

It falls back (reissues your request directly to the provider) when the failure is
Varsten's own and no provider output was produced:

- DNS failure, connection refused, or connection reset reaching Varsten
- A Varsten-originated 5xx (`X-Varsten-Origin: varsten`), including `circuit_open`,
  `upstream_unreachable`, and `no_provider_key`
- A Varsten rate limit (`429`) — Varsten's limit never blocks your production
- A header-less 5xx (Varsten crashed mid-response)

It does **not** fall back, because retrying would hit the same problem or double
bill:

- Any response Varsten relayed from the provider (`X-Varsten-Origin: provider`),
  success or error — including a provider 5xx
- A deliberate budget cap (`402 budget_exceeded`)
- A bad request or auth error you caused (`400` / `401`)
- A read timeout, by default (see below)
- Streaming, once the stream has started (a mid-stream error is surfaced, never restarted)

## How a response was served

Each response carries a non-enumerable `_varsten` marker (it never appears in
`JSON.stringify`):

```ts
const res = await client.chat.completions.create(body);
// res._varsten === { servedBy: "varsten" }                              // optimized
// res._varsten === { servedBy: "provider-fallback", reason: "..." }     // fell back
```

You also get a synchronous `onFallback(event)` call and best-effort, non-blocking
telemetry back to Varsten so the dashboard can show outage windows. Telemetry
carries only metadata (reason, status, model, latency) — never prompt or
completion content.

## Double billing

The one place a naive fallback double-charges is a Varsten read timeout: Varsten
may have already reached the provider and billed, but the response was lost. Two
defenses: (1) a read timeout does **not** trigger fallback by default (a hard
connection failure means Varsten never forwarded, so falling back there is safe);
and (2) every request carries an `Idempotency-Key` sent on **both** the Varsten
attempt and the direct fallback, so when Varsten forwards the request verbatim the
provider deduplicates the retry instead of billing/generating twice. If you would
rather have availability than avoid a rare double charge, set
`fallbackOnReadTimeout: true`.

## During a sustained outage

After `breakerThreshold` consecutive Varsten failures the SDK opens a local circuit
breaker and goes straight to the provider for a cooldown, so you do not pay a
Varsten timeout on every request. It then lets a single probe through to detect
recovery.

## License

Apache-2.0.

Issues and support: [Varsten GitHub issues](https://github.com/waaron5/Varsten/issues).
