# Engine Reliability Boundaries

This is the current source of truth for what the Varsten engine can honestly
claim after the A-F roadmap, validation pack, and hardening chunks completed on
2026-07-05. The engine is now a real cost-optimization foundation, but not every
delivery mode, provider surface, or autonomous lever is equally mature.

The product promise stays narrow and defensible:

> Varsten reduces AI spend only when it can preserve quality, prove the savings
> from measured evidence, explain the decision, and fail open when Varsten is the
> part that fails.

## Current Standing

The backend is ready for controlled enterprise pilots once packaging/onboarding
and staging deployment gates are complete. It is not yet an unqualified
"install anywhere, fully autonomous across every provider" product.

What is strong today:

- The request path defaults to pass-through/fail-open behavior.
- Optimization decisions are persisted as auditable, content-free traces.
- Savings accounting separates baseline cost, actual cost, overhead, method,
  confidence, and quality status.
- Risky levers are eval-gated, holdback-measured, canary-ramped, drift-guarded,
  and governable through ChangeRequests.
- Learning uses persisted production outcomes and aggregates; it does not invent
  synthetic rewards.
- Provider-specific behavior is isolated behind adapters enough to keep the core
  planner/provider boundary sane.
- The validation pack and backend gate are green in this repo.

What remains bounded:

- Base-URL-only integration cannot fail open if the Varsten service is entirely
  unreachable; use the SDK wrapper or sidecar for fail-open client behavior.
- Streaming fallback does not switch to a fallback model after an SSE stream
  starts.
- Cross-provider fallback is not implemented; fallback is same-provider only.
- Route-key policy/prior/guardrail convergence is implemented, but new customer
  routes still start on default/model-wide evidence until measured route-specific
  data accumulates.
- Bandit exploit ranks measured mean savings, not Thompson sampling over savings
  magnitude, because persisted savings variance is not stored yet.
- Redis-backed multi-instance behavior is unit-proven and has an opt-in live
  smoke, but the live smoke must be run against staging Redis before scaling out.
- OpenAI is the strongest production path; Anthropic and Gemini should be treated
  as founder-supervised beta paths until customer traffic proves them.

## Boundary Matrix

| Area | Current state | Boundary to disclose |
|---|---|---|
| Request forwarding | OpenAI, Anthropic, and Gemini paths forward and meter traffic; OpenAI is the most mature. | Provider-specific fields and less-travelled dialects require customer-traffic smoke before optimization. |
| Fail-open | Internal optimization failures degrade to pass-through; kill switches exist globally and per project. | Base-URL-only clients still depend on the Varsten endpoint being reachable. SDK/sidecar packaging is needed for client-side fail-open. |
| Retries and fallback | Non-streaming transient failures retry with capped jitter; exhausted retries can fall back to a configured same-provider model. | Fallback is reliability-only and claims zero savings. Cross-provider fallback is not present. |
| Streaming | Streaming retries are limited to pre-first-byte failures; after bytes start, Varsten does not replay or swap the stream. | Streaming fallback to another model is a future implementation slice. |
| Savings proof | Direct, holdback, replay, and overhead-aware accounting are validated by the proof pack. | Unknown pricing or insufficient holdback signal must remain unverified/estimated, never promoted as proven savings. |
| Quality protection | Evals, holdbacks, quality feedback, latency guardrails, canary ramp, drift rollback, and governance are implemented. | These protect measured regressions; they do not guarantee every individual answer is semantically identical. |
| Risky automation | Routing, downshift, trim, and compression are gated by eval/governance/holdback/canary machinery. | Keep risky levers shadow/recommend/approved until a customer route has enough evidence. |
| Learned compression | Compression is generated off-path, eval-gated, governed, and applied by exact-hash substitution only. | The generation approach is not a general prompt rewriter; it must not silently rewrite unmatched content. |
| Bandit routing | Default off; shadow mode is zero behavior change; active mode only samples eval-cleared candidates and is quality-gated. | Savings-variance persistence is still needed for full Thompson sampling over reward magnitude. |
| Multi-instance | Circuit, budget-cap, and rate-limit sharing are Redis-backed and deterministic-test proven. | `REDIS_URL`, Redis rate-limit backend, scheduler singleton handling, DB pool sizing, and live Redis smoke are required before horizontal scale. |
| Learning loop | Outcome priors are refreshed from the decision ledger and feed planning/bandit decisions; persisted priors are route-keyed with default fallback. | Cold routes rely on default/model-wide evidence until measured route-specific outcomes accumulate. |
| Governance | ChangeRequests freeze evidence bundles and can enforce approval per organization. | Enforcement must be enabled per org or globally; otherwise governance objects record but do not block applies. |

## Claims To Avoid

Do not claim these until the corresponding boundary is closed:

- "Fully autonomous across every lever and provider."
- "Guaranteed identical output."
- "Verified savings for every recommendation."
- "Horizontal scaling is production-proven without a live Redis run."
- "Streaming fallback and cross-provider fallback are complete."
- "The bandit is full Thompson sampling over cost savings."
- "Base URL integration is fail-open when Varsten is unreachable."

## Enterprise Pilot Gate

Before routing a first enterprise pilot through the engine:

1. Run `make backend-check`.
2. Run the full engine proof pack, not only the fast PR subset.
3. Run live SDK/provider smokes for the customer's provider mix.
4. Run the live Redis smoke if more than one API instance will serve traffic.
5. Run an optimization rollback drill with `PROXY_KILL_SWITCH` or project bypass.
6. Confirm governance mode for that organization: observe/recommend, approved
   applies, or automated applies.
7. Confirm which integration path is being piloted: base URL, SDK wrapper, or
   sidecar.

## Readiness Summary

Engine readiness is high for a controlled OpenAI-centered enterprise pilot with
approved optimization and proof reporting. It is not the final product surface:
packaging, onboarding, SDK/sidecar options, live deployment drills, and the
remaining bandit/fallback convergence work still decides how broadly and
autonomously Varsten can be sold.
