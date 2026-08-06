# Proxy Failure-Mode Matrix

Exactly what the proxy does, and what the client sees, for every failure on the
request path. This is the behavior a customer's reliability review will ask about.
Each row is backed by a test in `backend/tests/test_proxy.py`; the guiding
principle is **fail open**: when in doubt, the customer's request still completes.

## Non-streaming requests

| Condition | Client sees | Circuit breaker | Notes |
|---|---|---|---|
| Healthy | `200` + completion | success recorded | Metered; cached when optimization is on. |
| No provider key configured | `502`, `detail: no provider key configured` | unaffected | Fails before any upstream call. |
| Upstream **4xx** (client mistake) | the provider's status + body, verbatim | **not** tripped | A 400/401/404 is the caller's error, not a provider outage. |
| Upstream **5xx / 429** | Usually hidden by retry; otherwise the provider's status + body, verbatim, or a configured fallback completion | one outcome recorded | Retries are capped/budgeted and happen only before bytes stream. Fallback is same-provider, reliability-only, and claims zero savings. |
| Upstream unreachable (connect/transport error) | Usually hidden by retry; otherwise `502`, `type: varsten_upstream_error`, or a configured fallback completion | failure recorded | Clean typed error, never a stack trace. |
| Circuit open | `503`, `type: varsten_circuit_open`, header `X-Varsten-Circuit: open` | n/a (short-circuits) | Fails fast instead of waiting the full timeout. Cache hits still served. |
| Over Varsten rate limit | `429`, `type: varsten_rate_limited`, `Retry-After: 60` | n/a | Per-API-key fixed window on the public proxy. |
| Over hard budget cap | `402`, `type: varsten_budget_exceeded` | n/a | Only the over-cap workload owner; cache hits ($0) exempt; fail-open. |
| Kill switch / project bypass | `200`, forwarded straight through, `X-Varsten-Mode: bypass` | n/a | Optimization off, still metered. The emergency lever. |

## Streaming requests

The HTTP envelope is `200` as soon as the stream starts, so streaming failures are
surfaced **inside the stream body**, not as a status code.

| Condition | Client sees in the stream |
|---|---|
| Healthy | the provider's SSE chunks, passed through; bookkeeping happens after `[DONE]`. |
| Upstream non-200 (4xx/5xx/429) | Retry can happen only before the first byte; after streaming starts, the provider's error body is delivered in the stream and breaker state updates as above. |
| Upstream unreachable / transport error | If it occurs before the first byte, retry can hide it; otherwise a clean SSE error event (`type: varsten_upstream_error`) then `data: [DONE]`. |
| Upstream hang (no chunks) | cut by the read/total stream timeout, then the same SSE error + `[DONE]`. Never pins the event loop. |
| Post-stream bookkeeping error | nothing — the client already has every byte; the capture failure is logged only. |

Streaming fallback to another model is intentionally absent today. Once bytes
have reached the client, Varsten never replays the request or swaps the model
mid-stream.

## Degradations that never reach the client (fail-open)

| Internal failure | Behavior |
|---|---|
| Cache lookup error | Treated as a miss; the request forwards normally. |
| Embedding call slow/failed (semantic cache) | Semantic matching skipped; forwards (exact-match cache still works). |
| Plan-tier lookup error | Treated as **Base** (never silently grants paid optimization). |
| Budget-state lookup error | Treated as no cap (never blocks traffic on a bug). |
| Metadata header malformed/oversized | Ignored; request succeeds with empty context. |
| Control plane / scheduler down | Data plane keeps forwarding; only background optimization pauses. |

## The one-line guarantee

If anything Varsten does on the path fails, the customer's request still reaches
their provider. The worst case is "we stop saving and add about a millisecond,"
never "we took down prod." The two ways to force that worst case deliberately are
the global kill switch (`PROXY_KILL_SWITCH`) and a project's bypass toggle.

For the broader set of reliability/product boundaries, including base-URL vs SDK
fail-open behavior and multi-instance gates, see `ENGINE_RELIABILITY_BOUNDARIES.md`.

## Headers a client can key on

- `X-Varsten-Mode`: `optimize` | `observe` | `bypass`
- `X-Varsten-Cache`: `hit` | `miss` | `off` | `bypass`
- `X-Varsten-Circuit`: `open` (only when the breaker short-circuits)
- `X-Varsten-Budget`: `exceeded` (only on a hard-cap block)
- `X-Varsten-Request-Id`: correlation id for feedback and support
