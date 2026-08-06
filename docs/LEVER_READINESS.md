# Optimization Lever Readiness

The production state of each savings lever: its default, how it's gated, who has to
approve it, and how far it's cleared for use. This is the canonical posture; the
engine and the entitlements layer enforce it, this doc explains it.

For system-level boundaries that are not specific to one lever, see
`ENGINE_RELIABILITY_BOUNDARIES.md`.

Two rules hold across every lever:

1. **Free is Base.** No behaviour-changing lever can activate on the Free
   plan — enforced at the backend chokepoint, not the UI. Levers below are
   Pro-only unless noted.
2. **Fail-open and kill-switchable.** Any lever can be bypassed in one toggle
   (global `PROXY_KILL_SWITCH` or a project's bypass), and a failure in the
   optimization path forwards the request straight to the provider.

## Readiness levels

- **observe** — measured/recommended only, never acts.
- **founder-approved pilot** — may run on a customer, but a human enables it and
  watches it.
- **customer self-serve** — safe for a customer to turn on themselves.
- **autonomous** — safe to apply automatically without a human in the loop.

## Matrix

| Lever | Default mode | Savings measurement | Cleared for | Notes |
|---|---|---|---|---|
| **Exact cache** (semantic_cache lever, exact-match) | auto | **Direct measured** (avoided model price, from the ledger) | **autonomous** | On the OpenAI dialect path. Content is TTL'd + purged (`PROXY_CACHE_TTL_SECONDS`). This is the always-on cache path; vector semantic matching is separate and remains disabled by default. |
| **Batching** | auto | **Direct measured** (contractual discount on identical tokens) | **customer self-serve** (non-urgent jobs) | Async `/v1/batches` mirror; staged objects TTL'd + purged. Arithmetic savings, no holdback needed. It is functional and self-serve, but not inline automatic batching of normal proxy calls. |
| **Token trim** | auto | Ledger / holdback once active; recommendation savings may start estimated | **autonomous when configured auto** | The sweep can apply open trim recommendations through the shared transition layer when the lever is enabled and auto-mode is set. |
| **Smart routing** | approve | **Holdback measured** (concurrent A/B with CI) once it has signal; estimated below threshold | **approve by default; autonomous when configured auto and gates clear** | Eval-gated for apply. Auto-mode still goes through entitlement, eval, governance, execution, holdback, and rollback machinery. Cross-provider routing is audited. |
| **Model downshift** | approve | **Replay measured** (eval cost delta) / holdback | **approve by default; autonomous when configured auto and gates clear** | Highest quality risk. Auto-mode requires a safe objective eval; needs-human verdicts remain manual. |
| **Prompt compression** | approve | Replay measured / ledger once active | **approve by default; autonomous when configured auto and gates clear** | Generated off-path, eval-gated, and applied only by exact-hash substitution of the evaluated prompt. |
| **Semantic (vector) cache** | **off** (`SEMANTIC_CACHE_ENABLED=false`) | n/a until enabled | **config-gated pilot** | Disabled by default: it adds an embedding round-trip on the miss path and risks false-positive matches on near-identical tool-call JSON. Enable only with an in-process embedding model and a tuned per-route threshold. |

## What can run hands-off

Exact cache is the only fully autonomous hot-path optimization with no customer
policy artifact. The policy-backed levers (token trim, smart routing, model
downshift, prompt compression) can now run without a human apply action when the
project's `LeverConfig` is enabled, `automation_mode="auto"`, and the shared
transition gates pass. Batching is functional and self-serve through its async API,
but it is not automatic inline batching of ordinary proxy requests.

Arithmetic levers still have the cleanest savings proof: exact cache avoids the
provider call, and batching uses the provider's batch price. Model swaps and prompt
rewrites change output distribution, so auto-mode relies on eval gates, holdbacks,
governance, canary/ramp controls, drift rollback, and measured outcome evidence.

## Defaults map to risk, by design

`auto` defaults (exact cache, batching, token trim) are the low-risk, objective
levers; `approve` defaults (smart routing, model downshift, prompt compression)
are the medium-risk ones. Auto is the stronger and scarier sell, so it is earned
lever by lever as eval, holdback, and production evidence accumulate — never
switched on wholesale.

## What it takes to promote a lever

- **trim → autonomous:** enabled lever config, auto-mode, and production evidence
  that stays within quality and latency guardrails.
- **routing / model downshift → self-serve or autonomous:** a passing shadow eval on
  the customer's real traffic, live holdback evidence as traffic accumulates, and
  auto-rollback on objective drift.
- **prompt compression → autonomous:** generated artifact, safe eval, exact-hash
  substitution, and auto-mode.
- **semantic vector cache → on:** an in-process embedding model (removes the
  miss-path latency) and a per-route distance threshold tuned against false
  positives.
