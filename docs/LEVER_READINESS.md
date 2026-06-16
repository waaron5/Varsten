# Optimization Lever Readiness

The production state of each savings lever: its default, how it's gated, who has to
approve it, and how far it's cleared for use. This is the canonical posture; the
engine and the entitlements layer enforce it, this doc explains it.

Two rules hold across every lever:

1. **Free is observe-only.** No behaviour-changing lever can activate on the Free
   plan — enforced at the backend chokepoint, not the UI. Levers below are
   Performance-only unless noted.
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
| **Exact cache** (semantic_cache lever, exact-match) | auto | **Direct measured** (avoided model price, from the ledger) | **autonomous** | On the OpenAI dialect path. Content is TTL'd + purged (`PROXY_CACHE_TTL_SECONDS`). The one lever fully ready for hands-off use. |
| **Batching** | auto | **Direct measured** (contractual discount on identical tokens) | **customer self-serve** (non-urgent jobs) | Async `/v1/batches` mirror; staged objects TTL'd + purged. Arithmetic savings, no holdback needed. |
| **Token trim** | auto | Estimated until eval-proven | **founder-approved pilot** | Needs eval proof that output is unchanged before autonomous use. |
| **Smart routing** | approve | **Holdback measured** (concurrent A/B with CI) once it has signal; estimated below threshold | **founder-approved pilot** | Approve-mode by default. Auto requires a passing shadow eval + holdback signal. Cross-provider routing is audited. |
| **Cheaper model** | approve | **Replay measured** (eval cost delta) / holdback | **founder-approved pilot** | Highest quality risk. Eval-gated; human approves. |
| **Semantic (vector) cache** | **off** (`SEMANTIC_CACHE_ENABLED=false`) | n/a | **observe / keep off** | Disabled by default: it adds an embedding round-trip on the miss path and risks false-positive matches on near-identical tool-call JSON. Enable only with an in-process embedding model and a tuned per-route threshold. |

## Why only two levers are autonomous

The exact cache and batching are the only levers whose savings are **arithmetic**
(an avoided price, a contractual discount on identical tokens), so the
counterfactual is measured, not modeled, and there's no quality risk to a stored
exact response or a batch-priced identical call. Everything that swaps a model
changes the output distribution, so it stays human-in-the-loop until the eval
harness and the live holdback prove it safe on the customer's own traffic. This
matches the savings-accounting split in Proof: only measured methods roll into
verified savings (see `FAILURE_MODES.md` and the Proof page).

## Defaults map to risk, by design

`auto` defaults (exact cache, batching, token trim) are the low-risk, objective
levers; `approve` defaults (smart routing, cheaper model) are the medium-risk
ones. Auto is the stronger and scarier sell, so it is earned lever by lever as the
eval and holdback evidence accumulates — never switched on wholesale.

## What it takes to promote a lever

- **trim → autonomous:** an eval gate that proves output equivalence on the route.
- **routing / cheaper model → self-serve or autonomous:** a passing shadow eval on
  the customer's real traffic **and** a live holdback with enough signal to report
  measured savings with a confidence interval, plus auto-rollback on objective
  drift.
- **semantic vector cache → on:** an in-process embedding model (removes the
  miss-path latency) and a per-route distance threshold tuned against false
  positives.
