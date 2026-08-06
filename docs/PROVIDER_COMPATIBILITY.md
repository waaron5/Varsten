# Provider Compatibility and Readiness

Which providers Varsten proxies, what surface each exposes, and how ready each is
for customer traffic. Readiness is stated honestly: only OpenAI is recommended for
a first customer's production path today.

## Readiness matrix

| Provider | Status | Dialects accepted | Streaming | Recommended use |
|---|---|---|---|---|
| **OpenAI** | **GA** | OpenAI Chat Completions | Yes (raw SSE pass-through) | Production. The fully-supported path; lead with this for a first customer. |
| **Anthropic** | **Beta** | Anthropic Messages (native) | Yes | Founder-supervised pilots. Functional and smoke-tested, but prove it on the customer's traffic first. |
| **Gemini** | **Beta** | Gemini native (`/v1beta`) + OpenAI-compat | Yes | Founder-supervised pilots. Newest adapter; widest surface, least mileage. |

"Beta" means: the adapter works and is covered by tests and the live SDK smoke
suite, but has less production mileage than OpenAI. Label it beta in any customer
conversation and watch the first real traffic closely.

Provider maturity is one part of the broader reliability posture. See
`ENGINE_RELIABILITY_BOUNDARIES.md` for fail-open, fallback, multi-instance, and
automation boundaries.

## Endpoint surface

Authenticate every call with a Varsten `vk_` key in the provider's usual auth
location (OpenAI/Gemini-OpenAI: `Authorization: Bearer`; Anthropic: `x-api-key`;
Gemini native: `x-goog-api-key` or `?key=`). Varsten resolves the upstream
provider key server-side.

| Provider | Route(s) | Client base URL (official SDK) |
|---|---|---|
| OpenAI | `POST /v1/chat/completions` | `{base}/v1` |
| Anthropic (native) | `POST /v1/messages`, `/v1/messages/count_tokens`, `/v1/messages/batches` | `{base}` |
| Gemini (native) | `POST /v1beta/models/{model}:{action}`, `/v1beta/batches` | `{base}`, api version `v1beta` |
| Gemini (OpenAI-compat) | `POST /v1/openai/chat/completions`, `POST /v1beta/openai/chat/completions` | `{base}/v1` |

The official OpenAI, Anthropic, and `google-genai` SDKs all work unmodified by
pointing their base URL at Varsten — see the live smoke suite
(`tests/test_sdk_smoke.py`) for exact client construction per provider.

## What's optimized vs passed through, per provider

- **Semantic cache (exact-match)** and **metering** apply to the OpenAI-dialect
  path. Anthropic and Gemini native are passthrough-metered today (no cache on the
  native path); cross-provider routing is gated to Pro and audited.
- All other levers (semantic vector cache, trim, batching, smart routing) are
  Pro-gated and covered by the lever readiness matrix in the audit.

## Known limitations (be upfront)

- The native Anthropic and Gemini paths are passthrough: they meter and can route,
  but do not serve from the cache. Cache savings on those providers wait until the
  cache lands on the native paths.
- Cross-provider translation (e.g. serving an OpenAI-dialect request from a Gemini
  upstream) is supported but is the least-travelled code; keep it founder-approved.
- Provider feature parity is not guaranteed across dialects. If a customer relies on
  a provider-specific field, test it on their traffic before enabling optimization.

## Before enabling a provider for a customer

1. Configure the upstream key through the dashboard Connections flow (validated
   before store).
2. Run the live SDK smoke for that provider (see `SMOKE_TESTS.md`).
3. Confirm a real request, a stream, and a cache hit (OpenAI) behave correctly.
4. Keep the kill switch one toggle away.
