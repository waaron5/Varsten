# Integration modes: base-URL vs the fail-open SDK

Varsten sits inline in your request path. That buys the savings, and it raises one
question above all others: what happens to your app when Varsten itself is having a
bad day? This page answers that and explains why the **SDK is the safe production
path**.

There are two ways to send traffic *through* Varsten (inline). There is also a third,
non-inline option: **Direct Monitoring** (`POST /v1/usage-events`) sends token
counts and labels asynchronously after each call — never prompt or completion content,
no provider key, nothing in your request path. It carries zero availability risk and
powers spend/savings analysis, but cannot optimize (optimization requires an inline
path). It is the lowest-risk way to start; the two inline modes below are what unlock
the engine.

## 1. Base-URL mode (good for evaluation)

Point the stock provider SDK at Varsten by overriding its base URL.

```ts
import OpenAI from "openai";

const openai = new OpenAI({
  apiKey: process.env.VARSTEN_API_KEY,        // vk_...
  baseURL: "https://api.varsten.ai/v1",
});
```

This is the fastest way to try Varsten. It is also honest about its limit: **Varsten
is now in your path with no way around it.** If Varsten is unreachable, your call
fails. You get savings while Varsten is healthy and an outage while it is not.

### Base-URL mode is not blind, though — every error is typed

Even in base-URL mode, Varsten never hands you an ambiguous failure. Every response
carries an `X-Varsten-Origin` header, and every Varsten-generated error has a stable
machine `code` and an `origin` in its body:

```jsonc
// HTTP 503, header: X-Varsten-Origin: varsten
{
  "error": {
    "message": "upstream temporarily unavailable (circuit open)",
    "type": "varsten_circuit_open",
    "code": "circuit_open",
    "origin": "varsten"
  }
}
```

- `origin: "varsten"` — Varsten generated this; **no provider call succeeded**. Safe
  to retry directly against your provider.
- `origin: "provider"` — Varsten reached the provider and is relaying its result
  (success or error) verbatim. Retrying direct would double-bill or hit the same sick
  provider. **Do not retry.**

Stable codes you can switch on (a versioned contract — codes never change meaning):

| `code` | HTTP | `origin` | Safe to retry direct? |
|---|---|---|---|
| `circuit_open` | 503 | varsten | yes |
| `rate_limited` | 429 | varsten | yes |
| `upstream_unreachable` | 502 | varsten | yes |
| `no_provider_key` | 502 | varsten | yes |
| `internal_error` | 5xx | varsten | yes |
| `budget_exceeded` | 402 | varsten | **no** (a deliberate cap you set) |
| `bad_request` | 400 | varsten | **no** (your request) |
| `unauthorized` | 401 | varsten | **no** (bad `vk_` key) |
| (relayed) | any | provider | **no** (already answered) |

In base-URL mode **you** are responsible for reading these and deciding whether to
fall back. That is exactly the logic the SDK does for you.

## 2. The fail-open SDK (the production path)

The SDK is a thin wrapper around the official provider client. When Varsten is
healthy your traffic is optimized through it; when Varsten is unreachable, slow to
connect, or returns a Varsten-origin error, **the same request goes directly to your
provider with your local key — automatically, with no code change on your side.** An
outage costs you savings for a few minutes, not your uptime.

```ts
import { VarstenOpenAI } from "@varsten/openai";

const client = new VarstenOpenAI({
  varstenApiKey: process.env.VARSTEN_API_KEY, // vk_...  (sent to Varsten only)
  openaiApiKey: process.env.OPENAI_API_KEY,   // sk-...  (stays local; used only on fallback)
});

// Identical to the OpenAI SDK. Fallback is invisible to this call site.
const res = await client.chat.completions.create({
  model: "gpt-4o-mini",
  messages: [{ role: "user", content: "hi" }],
});
```

What the SDK does that base-URL mode cannot:

- Reads `X-Varsten-Origin` / `code` for you and falls back **only** on Varsten-origin
  failures — never on a relayed provider error, so it never double-bills.
- Treats a transport failure (DNS, connection refused, TLS, connect timeout) as
  Varsten-origin and falls back.
- Sends one idempotency key on both attempts so even a retried call is deduped at the
  provider.
- Runs a local circuit breaker so a sustained outage doesn't pay the Varsten timeout
  on every request — after a few failures it bypasses straight to the provider, then
  probes for recovery.
- Surfaces `budget_exceeded` (your cap) and your own `bad_request` / `unauthorized`
  rather than silently bypassing them.
- Emits a local `onFallback(event)` and a best-effort, content-free telemetry marker
  so fallback windows show up on your dashboard.

### One package per provider, one shared contract

| Provider | Package | Surface |
|---|---|---|
| OpenAI | `@varsten/openai` | `client.chat.completions.create(...)` |
| Anthropic | `@varsten/anthropic` | `client.messages.create(...)` |
| Gemini | `@varsten/gemini` | `client.models.generateContent(...)` / `generateContentStream(...)` |

All three share one fail-open engine (`@varsten/core`), so the decision to fall back
is implemented and audited exactly once. The full frozen contract is in
[`docs/design/SDK_FAILOPEN_DESIGN_FREEZE.md`](../design/SDK_FAILOPEN_DESIGN_FREEZE.md).

> Gemini nuance: Google's `ApiError` does not expose response headers, so the
> Gemini wrapper reads Varsten's origin from the error *body* and is deliberately
> conservative — it surfaces an unattributed 5xx rather than risk a double-bill,
> while still falling back on every positively Varsten-attributed error and all
> transport failures. See the `@varsten/gemini` README.

## Seeing your coverage

The dashboard's **Fallback Coverage** panel shows, per provider, whether your traffic
is running through a Varsten SDK (`SDK enabled`), through base-URL mode with a key but
no SDK (`Key set, no SDK`), or not integrated yet (`Not enabled`). It is derived from
real traffic — the SDK stamps an `X-Varsten-Client` marker the proxy records — so it
reflects what you actually run, not a setting. If a provider shows `Key set, no SDK`,
that traffic has no automatic fallback; move it to the SDK before it is
production-critical.
