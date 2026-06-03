# CLAUDE.md

This file gives Claude persistent context for working on **Varsten**. Read it at the start of every session before suggesting anything.

This file reflects the current product direction, decided in design work that came after the original product guide was written. The direction changed: Varsten is no longer a measurement-first analytics product with optimization deferred to a distant phase. Varsten is a savings engine that cuts AI spend and proves it. Measurement is the foundation the engine stands on, not the product.

`docs/product/VARSTEN_PRODUCT_GUIDE.md` is the detailed reference for the measurement layer: ingestion fields, the pricing catalog, cost derivation, pricing trust, and schema mechanics.

`docs/product/varsten-ui-mockup.html` is the canonical reference for the UI and information architecture. It is a clickable, self-contained mockup of the engine-first layout. When in doubt about screens, tabs, or flow, open it. It supersedes any older mockup.

## What Varsten is

Varsten cuts a company's AI bill and proves how much it cut. A customer connects their AI providers and traffic, Varsten finds specific cuts worth real money, applies the safe ones, holds quality with guardrails, and reports a verified savings number a CFO can trust.

The thing that makes Varsten worth paying for is the engine that executes the savings, not the dashboard that reports on them. Spend visibility is increasingly commoditized. Cloud providers and observability tools already show you where your money went. A buyer does not pay a recurring fee to be told they are bleeding money. They pay to have the bleeding stopped and to have the savings proven. So the engine is the product. Analysis is demoted to a supporting input.

Measurement still matters, more than ever, because the Proof page is only as credible as the spend numbers underneath it. You cannot attribute a saved dollar you cannot measure. So Varsten is excellent at authoritative cost measurement precisely because that is what makes the savings claims defensible. Measurement is the foundation. The engine and the proof are the building.

### The one principle

Every screen answers a money question and produces a decision. If a screen only informs, it does not belong in the daily path.

### The money loop

Spend comes in. The engine cuts it. Guardrails keep the cuts safe. The savings get proven. A human approves what is not yet trusted. Approved cuts feed back into the engine. The product is built around this loop, not around reporting.

## Why this project exists

I am a CS student at BYU relocating to NYC. Varsten started as my portfolio piece and still demonstrates that I can architect and ship real multi-tenant SaaS. But the goal has changed: I am taking Varsten to market and onboarding my first paying client as soon as possible. The product has to be solid and production-ready, not a demo that only survives a happy-path click-through.

This raises the bar on execution, not on surface area. "Done over complete" still holds: ship a focused, coherent slice rather than a sprawling half-built one. But "done" now means production-done for the slice in scope. A real client pushes real traffic, trusts real numbers, and expects the thing to stay up, stay secure, and never leak across tenants. The engine-first vision below is the destination; the near-term job is to make the control plane and decision loop genuinely deployable, secure, and reliable for one real customer.

### Current phase: Phase 1 inline proxy (Build 1)

Direction decided: Varsten is an inline Smart Proxy Gateway that intercepts, optimizes, and forwards live LLM traffic under a gain-share model. It is not a passive post-hoc dashboard. The metadata control plane, measurement, pricing ledger, recommendation engine, and decision-loop UI that already exist are the foundation the proxy stands on, not the product. We are not onboarding anyone onto a metadata-only logging setup; that would be throwaway integration work for the client. We build the proxy foundation now.

This supersedes the older framing in this file and elsewhere that treated the inline data plane as a deferred north-star. The proxy is the current build. Phase 1 is scoped deliberately lean to de-risk the production path and avoid a multi-quarter timeline:

- **Single provider: OpenAI only.** Mirror `POST /v1/chat/completions`. Ignore Anthropic and others for now.
- **Streaming is non-negotiable.** Raw SSE pass-through on day one. Never buffer the full completion before streaming to the client; that inflates their latency by seconds. Capture token/billing metadata asynchronously from the stream without blocking delivery.
- **One lever: Semantic Cache.** Cache hit serves from the cache store (Postgres now, Redis later) in well under 20ms at $0, bypassing OpenAI. Cache miss pipes the stream straight through. The other four levers (smart routing, cheaper model, token trim, batching) stay completely bypassed behind a hard kill switch.
- **Key vaulting is temporary.** The client's OpenAI key is supplied via an encrypted backend env var mapped to their `project_id`. No frontend vault UI in Phase 1.
- **The ledger is the proof.** The proxy populates the same authoritative `usage_events` ledger (metadata only) and the dashboard shows Naive Retail Cost vs Varsten Optimized Cost. That delta is the gain-share number.

The production-hardening work already done (tenant-isolated auth, containerized deploy, CI, recompute off the read path) is the foundation under all of this and still holds.

#### Zero-retention, honestly

The ledger stores metadata facts only: token counts, latencies, derived costs, allocation tags. Prompt and completion text are never written to the ledger. The one deliberate exception is the semantic cache, which by definition must store responses to serve them. Treat the cache as the documented, opt-in exception with its own retention controls (TTL, later customer-managed encryption), not a license to log content elsewhere.

## The product, top to bottom

The UI is a left side nav with six sections. The vertical order is the flow: you land at the top, you work in the Engine, you drop into Analysis only when investigating. Each side nav item is a page (a top-level route). The pills inside a page are tabs that swap the main content. A page with tabs defaults to its first tab on load. Command Center is the only multi-panel dashboard and has no tabs.

Routes:

```
/command-center          dashboard, no tabs
                         panels: live savings, decision queue, recent auto-actions, top waste now

/engine                  redirects to /engine/recommendations
  /recommendations       ranked cuts with $ impact, risk, one-click apply
  /levers                the five mechanisms, each with on/off, savings to date, quality impact
  /automation            auto vs approve, per lever

/guardrails              redirects to /guardrails/quality
  /quality               min model tier per route, eval gates, auto-rollback
  /budgets               hard caps per team / feature / customer
  /alerts                thresholds, Slack / email routing

/proof                   redirects to /proof/savings
  /savings               realized vs run-rate, net-to-you after fee, board-ready
  /attribution           counterfactual baseline, savings by lever, methodology
  /data-quality          coverage, trust score, missing metadata

/analysis                redirects to /analysis/spend   (demoted, supporting)
  /spend                 drivers by team / feature / provider
  /customers             per-customer margin, negative-margin flags
  /models                cost per model, switch opportunities

/admin                   redirects to /admin/connections
  /connections           providers, SDK ingestion, mappings
  /team                  users, roles, API keys
  /billing-security      plan, SOC 2, data controls
```

Command Center and Engine should cover ninety percent of daily use. If a user has to leave those two to get value, the IA has drifted back toward a reporting tool and something is wrong. If a tab inside a page starts wanting its own sub-tabs, that page is doing too much and the tab should probably be promoted to its own nav item.

Proof is the load-bearing page. The net-to-you-after-fee row and the counterfactual baseline are the difference between a number finance trusts and a number finance argues with. Build it like the renewal depends on it, because it does.

## The five levers

These are the mechanisms the engine uses to cut spend. Everything in the Engine maps to one of them.

- **Smart routing**: send each request to the cheapest model that clears the quality bar for that route.
- **Semantic cache**: reuse an answer when a new request is semantically close to one already served.
- **Token trim**: compress prompts and context before the call without changing the output.
- **Cheaper model**: systematically move whole workloads to a cheaper tier where evals allow it.
- **Batching**: route non-urgent jobs through batch endpoints to capture bulk pricing.

## The two load-bearing architecture decisions

Most of the hard buyer objections collapse onto two decisions. These are the spine of the technical vision.

### 1. Concurrent randomized holdback

This single mechanism does the two jobs a buyer trusts least: it measures quality against a live baseline, and it measures savings rigorously.

For each optimizable route, hold back a small random percentage of traffic on the unoptimized incumbent (original model and prompt) and optimize the rest. Because assignment is random and concurrent:

- Savings are the measured difference in cost per request between the two arms, times optimized volume. This is an A/B experiment, not a model of a counterfactual. It is what survives a CFO.
- It defeats "we would have saved anyway." Any app-level change the customer ships lands on both arms and cancels. Varsten only claims the delta that is purely its own.
- It handles mid-month provider price changes for free. Both arms are priced at the same rate at the same time, so price moves hit both and cancel. No "stripping out" required.
- The same held-back traffic is the live baseline for quality drift. If the optimized arm degrades past tolerance against the holdback, auto-rollback.

Report savings with confidence intervals, never a suspiciously exact point estimate. Expose the raw assignment and per-request costs so the customer can audit. The holdback costs money because some traffic stays unoptimized, so keep it small on high-volume routes, widen it on low-volume ones, shrink it over time with sequential testing, and show it to the customer as an explicit line item. Where a holdback is awkward, use the direct method: a cache hit saves exactly the avoided model price, which is measured, not modeled.

### 2. Thin in-VPC data plane, split from the control plane

Separate the data plane (the thin proxy or SDK wrap in the request hot path) from the control plane (policies, learning, dashboards, the holdback math). The data plane caches its current routing policy locally and has near-zero dependencies.

- **Fail open, always, and say so loudly.** If the control plane, the cache, or anything else is unreachable, the data plane passes the request straight through to the original provider with the original model. Savings stop. Traffic does not. The worst case is "we stop saving and add about a millisecond," never "we took down prod."
- **In-VPC keeps content in the customer's boundary.** Run the data plane and the cache inside the customer's own cloud account. Content never leaves their perimeter. Only hashes, token counts, and eval scores flow to the control plane. This converts the truthful answer to "do my prompts leave my boundary" into "no, only counts and scores do," which turns security from a blocker into a selling point.
- **Latency is a first-class guardrail.** The only work allowed in the hot path is a policy lookup and a cache lookup, both sub-millisecond to low single-digit ms. Anything expensive (judging, eval, baseline math, learning) runs async, off-path. Never put a model call or an LLM judge inline. An in-VPC sidecar deploy makes the network hop localhost, roughly 1ms, instead of a cross-internet 50ms. Because a cheaper model can be slower, treat a latency regression like a quality regression and respect a per-route latency SLO.
- Give the customer a kill switch that bypasses everything in one toggle. Ship the proxy with canary deploys and circuit breakers, because the one real inline risk is a bug in the proxy itself.

## Quality is a measurement loop, not a promise

The hardest claim in the product is that you can route and downgrade without degrading output. Never promise it with a generic benchmark. Prove it per route, per customer, continuously.

Before a change goes live on a route, replay a sample of that customer's real recent traffic through both the incumbent and the candidate, and compare on that route's actual distribution. The comparison metric depends on the task: objective signals where they exist (classification accuracy, JSON schema validity, business-rule checks), pairwise LLM-as-judge with position-swapping and a customer-labeled seed set for subjective generation, and customer-supplied golden sets as the strongest signal. Capture implicit signal too: retries, thumbs-down, escalation to a human, edited outputs.

Auto-apply only where the signal is objective and cheap. For open-ended generation, judge-based quality is too noisy to bet auto-rollback on, so default those to approve-mode with a human in the loop. The eval and replay harness is the real IP of this product. Routing is a config change. Knowing it is safe on traffic you have never seen is the entire game.

## Autonomy: auto vs approve

For each lever, the customer decides whether the engine acts on its own or waits for a human. Defaults:

- **Auto** for low-risk, objective levers: semantic cache, batching, token trim.
- **Approve** for medium-risk levers: smart routing, cheaper model.

Auto-applied cuts still pass every guardrail before going live, and any cut that fails an eval gate is rolled back automatically and surfaced in the decision queue. Ship both modes with a per-lever toggle. Auto is the stronger sell and the scarier one, so earn it lever by lever as trust builds.

## Deployment and security posture

Offer two modes and let the answer be honest in both:

- **Metadata mode**: ingest only token counts, model, route, and latency from billing APIs and instrumentation. Never content. Powers Analysis, Proof, and recommendations, but not inline caching or content-based routing. Lowest security burden.
- **Inline gateway mode**: sees content because caching and routing require it. Must be in-VPC to keep content in the boundary. If Varsten-hosted: no content persistence by default, in-memory processing, PII redaction before any logging, tenant isolation, customer-managed encryption keys for the cache.

Bring real security artifacts, not a badge: SOC 2 Type II report under NDA, a DPA, a subprocessor list, a pen test summary, and a data flow diagram. A serious CTO asks for all five.

## Pricing model

Percentage of verified savings, with a floor that guarantees the fee stays below the savings. This is what makes the purchase a no-brainer instead of a line item to defend. The Proof page shows realized savings, the Varsten fee, and the net to the customer after the fee. A flat fee independent of outcome makes the buyer do the ROI math themselves and is a weaker sell.

## ICP

The sharpest wedge is AI-native companies where token spend is cost of goods sold and gross margin depends on it. For them Varsten is not a cost-saver, it is a margin-and-survival tool. The Analysis > Customers margin view (per-customer revenue vs AI cost, negative-margin flags) is the page that lands with this buyer. Aim the product at this user, not at a CEO. The CEO is a wedge for the deal. The technical buyer and daily user is a CTO, VP Eng, or platform / FinOps lead, and the stickiness lives with them.

## Measurement foundation

This is the layer the engine and Proof depend on. The rigor here is what makes the savings credible. Most of this carries over from the existing build and is still correct.

A customer creates a project, generates an API key, and sends AI usage records to an ingestion API. Varsten derives cost itself rather than trusting the client when pricing data is available.

### Example usage payload

```json
{
  "provider": "openai",
  "model": "gpt-4o-mini",
  "request_type": "chat_completion",
  "user_id": "user_123",
  "feature": "support_agent",
  "customer_id": "cust_123",
  "environment": "production",
  "input_tokens": 1200,
  "cached_input_tokens": 800,
  "output_tokens": 340,
  "occurred_at": "2026-06-01T12:00:00Z",
  "idempotency_key": "req_abc123",
  "metadata": {
    "team": "support"
  }
}
```

Ingestion takes authoritative token counts and computes `cost_usd` from a versioned pricing catalog Varsten owns: a per-org override first, then the synced public catalog, pinned to the price version that was live at the event's time. Client `cost_usd` is optional. When sent it is stored as `reported_cost_usd` and used only as the fallback when the model is not in the catalog. A `cost_source` field (`override` | `catalog` | `reported` | `unknown`) records which path produced the number, and a separate `pricing_status` field records pricing trust issues such as `model_not_in_catalog`, `missing_token_counts`, `missing_reported_cost`, or `suspected_model_alias`. Unknown cost is `null`, never `0`, and unpriced events are accepted and surfaced rather than dropped. Prices are never hard-coded: they live in data, refreshed by a loader (`make sync-prices`) from a maintained feed, overridable per org, and versioned by effective date so history never mutates. This authoritative cost is exactly what lets the Proof page attribute savings instead of mirroring the customer's math.

## Stack

Backend:
- FastAPI
- Pydantic (v2)
- PostgreSQL (Aurora later in AWS phase)
- Alembic for migrations
- uv for Python dependency management
- OAuth for sign-in (likely Auth0 or Clerk, not rolling my own)

Infra (production posture, now that a real client is coming):
- Docker + Docker Compose for local dev. A backend Dockerfile and a compose that actually runs API + frontend + Postgres is a near-term requirement, not a someday.
- Managed Postgres for production (Neon, Supabase, RDS, or Cloud SQL). Add connection pooling (PgBouncer or the platform pooler) once there is more than one app instance.
- A managed container host for the API (Cloud Run, Fly.io, or Railway) over hand-rolled ECS at this stage. Revisit heavier AWS / Terraform when scale or compliance (SOC 2) actually demands it, not before.
- Frontend on Vercel (Next.js), CORS locked to the known frontend origin.
- CI on GitHub Actions: run the test suite on every PR, because the cost and pricing math is the thing a client stakes money on.
- Secrets in the platform's secret store, never committed. The repo currently has live values in `.env` files; those must not reach a public remote.

Frontend:
- Next.js or React with TypeScript
- I work professionally in Angular + tRPC + Prisma, so React is intentional learning here

The inline proxy is now part of this backend (Phase 1), an OpenAI-only reverse proxy with streaming pass-through and a semantic cache. A future in-VPC data-plane deployment may split it into a separate thin service in the customer's environment, but for Phase 1 it runs in this backend.

## What we build first

The inline proxy is the product, and Phase 1 (Build 1) is the lean first slice of it. The goal is a real, low-latency OpenAI proxy that streams, caches, and bills, that a first client routes real production traffic through.

**Already built (the foundation the proxy reuses):**
- OAuth sign-in, organizations, multi-tenancy, the `vk_` API key scheme and tenancy resolution
- Authoritative cost measurement (versioned `Numeric(20,12)` pricing catalog, cost derivation, `cost_source`, `pricing_status`)
- The `usage_events` ledger and metadata model the proxy writes into
- Recommendation engine (the lever *detection* logic that becomes the policy layer), decision-loop UI, Proof
- Tenant-isolated auth, containerized deploy + CI, recompute off the read path

**Phase 1 proxy (current build):**
- `POST /v1/chat/completions` mirror route, OpenAI only, authenticated by the `vk_` key
- Client OpenAI key resolved from an encrypted backend env var mapped to `project_id`
- Raw SSE streaming pass-through on a cache miss; never buffer before streaming
- Semantic Cache lever only: hit serves from the cache store at $0, well under 20ms; the other four levers are bypassed behind a hard kill switch
- Async capture of token/billing metadata from the stream into the `usage_events` ledger (metadata only)
- Dashboard shows Naive Retail Cost vs Varsten Optimized Cost

**Later phases of the proxy, not Phase 1:**
- Additional providers (Anthropic, Gemini, Bedrock)
- The remaining four levers as live execution modules (smart routing, cheaper model, token trim, batching)
- Real semantic (vector) similarity matching beyond Phase 1's exact-match cache
- Provider-key vault UI + KMS, Redis cache, fail-open hardening, circuit breakers, kill switch UX
- The eval / replay harness and the live randomized holdback that measure quality and savings as a concurrent A/B
- In-VPC deployment

In v1 the data plane behavior can be stubbed or simulated so the full loop demonstrates end to end. Do not pretend the production gateway, eval harness, or live holdback exist in the codebase when they do not.

**Not in scope at all for now:**
- Billing-grade invoice reconciliation
- Department-wide SaaS subscription spend
- Full enterprise permissions and approval workflows
- Advanced ML forecasting
- Multi-cloud infrastructure optimization
- Published SDKs (curl is the SDK for v1)
- API key rotation flow (one key per project is fine for v1)

## Build order

1. Foundation: schema, organizations, users, API keys, usage ingestion, basic auth
2. Measurement: `model_prices`, `model_price_overrides`, `scripts/sync_prices.py`, cost calculation, `pricing_status`, `cost_source`
3. Spend breakdowns: by model, provider, project, feature, customer, environment, plus top spend drivers (this feeds the recommendation engine and Analysis)
4. Recommendation engine: rule-based detection of candidate cuts per lever, estimated savings, risk level, rationale, recommendation status
5. Decision loop UI: Command Center and Engine (Recommendations, Levers, Automation), apply / dismiss / status
6. Proof: savings attribution view, by-lever breakdown, net-after-fee, confidence intervals, data quality
7. Guardrails: budgets, threshold alerts, anomaly alerts, forecast over-budget alerts, quality floors as config
8. Analysis (demoted) and Admin
9. Reports and shareable executive view

Build simple before complex. Do not jump to the production data plane, real eval harness, or live holdback before the control plane and the decision loop are coherent end to end.

## Database design notes (current thinking)

Suggested core tables: `organizations`, `users`, `organization_memberships`, `api_keys`, `usage_events`, `model_prices`, `model_price_overrides`, `model_price_sync_runs`, `budgets`, `alerts`, `recommendations`, `monthly_reports`. A model catalog table is acceptable if it supports normalization, aliases, capabilities, tiers, or cheaper-substitute mappings without hard-coding pricing.

New tables the engine direction implies (design when you reach them, not before):
- `recommendations` carries lever type, target (route / endpoint / workload), estimated monthly savings, risk level, rationale, and status (`open` | `applied` | `dismissed` | `rolled_back`).
- A savings-attribution concept (call it `savings_attributions` or fold into reports) ties a realized saved amount to a recommendation, a lever, and a measurement method, with a confidence interval. This is what Proof reads from.
- A holdback / experiment table is a later, production-phase concern. Do not build it for v1.

The `usage_events` table is the hot one. Columns:

- `organization_id`
- `project_id`
- `api_key_id`
- `provider`
- `model`
- `normalized_model`
- `operation` or `request_type`
- `external_user_id` or `user_id`
- `workflow` or `feature`
- `team`
- `department`
- `customer_id`
- `environment`
- `input_tokens`
- `cached_input_tokens` (subset of input served from a provider prompt cache, billed cheaper)
- `reasoning_tokens` (stored for analytics; already inside output_tokens for billing)
- `output_tokens`
- `total_tokens`
- `cost_usd` (authoritative, from whichever source `cost_source` names)
- `reported_cost_usd` (the client-sent number, kept for drift cross-check)
- `cost_source` (`override` | `catalog` | `reported` | `unknown`)
- `pricing_status` (`priced` | `model_not_in_catalog` | `missing_token_counts` | `missing_reported_cost` | `suspected_model_alias`)
- `price_version_id` (the `model_prices` row that produced catalog or override cost, if applicable)
- `currency` (USD only in v1; non-USD is rejected at ingestion)
- `idempotency_key` (unique per project; retries do not double-count)
- `status` or `success` plus `error_code`
- `latency_ms`
- `metadata` JSONB
- `occurred_at` or `event_timestamp` (when the call happened on the client; distinct from receipt)
- `ingested_at` or `received_at`

Cost is derived in `app/pricing/` using the resolution order: org override, global catalog, client-reported cost, then unknown. Accept unpriced events and flag them. Do not use `0` for unknown cost. Use `null`.

Indexes on `usage_events`:

- `(project_id, received_at DESC)` for recent usage and time-windowed counts
- `(project_id, provider, received_at DESC)` for provider breakdowns
- `(project_id, model, received_at DESC)` for model breakdowns
- `(project_id, workflow, received_at DESC)` for workflow or agent breakdowns
- `(project_id, external_user_id, received_at DESC)` for per-user queries
- `(project_id, customer_id, received_at DESC)` for per-customer margin

`metadata` is JSONB. No GIN index in v1 unless query patterns justify it.

API keys are stored as hashes, not plaintext. Plaintext is shown once at generation and never retrievable again.

Raw usage records are the source of truth. Do not denormalize or pre-aggregate until query pressure makes it necessary.

If I propose a schema change, evaluate it against these access patterns and the allocation, recommendation, attribution, governance, and reporting workflows before agreeing.

## How I want Claude to work with me

**This is the most important section. Read it carefully.**

I am shipping this to a real client, so default to execution. When a task is clear, build it end to end: write the code, run it, test it, verify it against the real app, and report what you did and what you found. Do not stop between every step to ask permission. I will redirect if you go the wrong way.

Specifically:

- **Default to doing, not just discussing.** If I describe a problem or a goal, implement the fix and verify it works. Reserve prose-only answers for when I explicitly ask to think through tradeoffs, review an approach, or plan before building.
- **Hold a production bar.** Prefer correct, secure, tested code over the fastest patch. When you build something client-facing, call out its security, tenancy, reliability, and failure-mode implications without being asked.
- **Push back when I'm wrong, harder now.** If I'm about to make a bad architectural or security call, say so directly and explain the cost in concrete terms ("that lets one tenant read another's keys because..."). A real client is on the line, so a wrong call is more expensive than it was at demo stage. Do not soften it.
- **Explain tradeoffs honestly.** If there are two reasonable approaches, say so and tell me when each is right. Don't manufacture certainty where there isn't any.
- **Skip the pep talk.** No "great question," no "you're on the right track." Engage with the substance.

When I want discussion instead of code, I will say so plainly ("help me think through X," "what are the tradeoffs of Y," "review this approach"). Otherwise assume I want it built and verified.

## Communication preferences

- Short direct sentences. No em dashes.
- Confident peer tone, not eager-applicant tone.
- No filler praise. No restating what I said back to me before answering.
- Code blocks use the actual stack: Python with type hints and Pydantic v2 syntax; SQL in plain Postgres dialect; TypeScript not JavaScript on the frontend.

## Repo layout (target)

```text
varsten/
├── CLAUDE.md
├── README.md
├── docker-compose.yml
├── Makefile
├── docs/
│   └── product/
│       ├── VARSTEN_PRODUCT_GUIDE.md
│       └── varsten-ui-mockup.html   # canonical UI / IA reference
├── backend/
│   ├── pyproject.toml           # uv
│   ├── alembic/
│   ├── app/
│   │   ├── main.py
│   │   ├── api/                 # FastAPI routers
│   │   ├── models/              # SQLAlchemy
│   │   ├── schemas/             # Pydantic
│   │   ├── pricing/             # cost derivation
│   │   ├── recommendations/     # rule-based cut detection
│   │   ├── db/
│   │   └── auth/
│   └── tests/
├── frontend/
│   ├── package.json
│   ├── app/                     # Next.js app router, routes mirror the IA above
│   └── components/
└── infra/                       # Terraform, later
```

This is a target, not a contract. Open to changes if there's a real reason.

## Things that should make Claude pause and ask

- If I propose reverting to an analytics or dashboard-first framing where measurement is the product. Measurement is the foundation. The engine and Proof are the product.
- If I propose expanding the Phase 1 proxy beyond its scope (a second provider, a second lever, vector similarity, a vault UI, Redis) before the OpenAI streaming + semantic-cache skeleton is solid. Scope additions honestly first.
- If I propose putting the proxy in a client's path without a kill switch and fail-open behavior once it moves past skeleton. Being inline means if Varsten is down their calls fail; that safety story is required before real traffic.
- If I propose writing prompt or completion text to the ledger. The ledger is metadata only; the semantic cache is the one documented exception.
- If I propose showing a savings number without an attribution method behind it. No painted-on savings. Every dollar ties to a method, and the UI says whether it is estimated or measured.
- If I propose putting anything expensive (a model call, an LLM judge, an eval) in a request hot path, even hypothetically.
- If I propose adding a feature outside the current v1 scope.
- If I propose exposing a client-facing endpoint without authentication and organization scoping, or a query that could read or mutate across tenants. This is a hard stop now that a real client is coming.
- If I propose a third-party service with meaningful recurring cost or vendor lock-in. Paid infrastructure is justified now, but still flag the cost, the lock-in, and whether a simpler or cheaper option covers the need.
- If I propose denormalizing or pre-aggregating before I have a real query problem.
- If I propose skipping tests on the ingestion endpoint.
- If I propose hand-rolling auth instead of using a provider.
- If I propose deploying with secrets in the repo, or pushing `.env` files to a public remote.

In any of these, ask me why before going along with it.

## run npx fallow to install fallow and see maintainability issues

- fix issues presented by fallow only when I explicitly say to do so
