> **Stale past §7.** Sections 1–7 (auth, tenancy, ledger, spend queries) describe foundations that still hold. Sections 8–11 describe the pre-engine build, before the inline proxy existed: "levers do not execute anything," "savings_attributions only seeded," "levers actually executing, any in-path proxy → not built." None of that is true anymore — the proxy is live, all six levers execute inline, and savings are measured from a live randomized holdback, not seeded demo data. For current engine truth read `CLAUDE.md` and `docs/ENGINE_FINAL_PROOF_STATUS.md`. Left in place below as a historical snapshot of the pre-engine architecture, not current documentation.

1. Account creation and identity

  The login flow is Auth0, not hand-rolled.

  1. User clicks Log in. The Next.js proxy (frontend/proxy.ts) mounts Auth0's /auth/login, /auth/callback, /auth/logout. Auth0
  authenticates and issues an RS256 JWT access token scoped to the API audience.
  2. On first authenticated load, the frontend session provider (session.tsx) calls POST /v1/auth/sync with the token.
  3. The backend (auth.py:sync_user) validates the JWT signature against the Auth0 tenant's JWKS, then reads the token's sub (the
  stable Auth0 subject). Identity is keyed on sub, never on email — the comment in the code is explicit that email-linking would allow
  account takeover.
  4. If no User row has that sub, it creates one and bootstraps a personal Organization plus an OrgMembership with role owner. So a
  brand-new user always lands with one org to put projects in.

  Why it matters: every later authorization check (_assert_member) walks user → org_memberships → organization. The whole multi-tenant
  security model hangs off that sub.

  ---
  2. The tenancy tree
  
  The data hierarchy is Organization → Project → ApiKey → UsageEvent, all UUID primary keys, all cascade-delete down the tree.

  - Project is the unit a dashboard scopes to. The active project lives in the topbar selector and in localStorage.
  - API key is how external apps authenticate ingestion. On POST /projects/{id}/api-keys, the backend (security.py:generate_api_key)
  produces vk_ + secrets.token_urlsafe(24), stores only the SHA-256 hash and a 7-char display prefix, and returns the plaintext exactly
  once. There is no way to retrieve it again; the model only ever holds the hash.

  Two auth modes share one Authorization: Bearer header, discriminated by the vk_ prefix:
  - Token starts with vk_ → API key path → resolves to that key's project directly.
  - Otherwise → Auth0 session JWT → requires an explicit ?project_id= and an org-membership check.

  A performance detail with a reason: last_used_at on the key is only refreshed once per 60 seconds (LAST_USED_REFRESH). The comment
  explains why — updating that row on every ingested event would create write contention that caps ingestion throughput.

  ---
  3. The pricing catalog (built before any usage)
  
  This is the foundation the whole "authoritative cost" claim rests on. Three tables in models/pricing.py:

  - model_catalog — identity only, no money. model_key, provider, mode, tier, capability flags, and cheaper_substitute_key.
  - model_prices — versioned money. Per-token rates stored as Numeric(20,12) (twelve fractional digits, because a rate like 5e-7 would
  lose precision as a float). Each row has an effective_at. Prices are never updated in place — a price change inserts a new row with a
  later effective_at. This is the single most important design decision in the pricing layer: historical events keep the price that
  was live when they happened, so last month's totals never silently change.
  - org_model_price_overrides — per-org negotiated rates, same shape, takes precedence over the public catalog.

  Prices are loaded, not coded. scripts/sync_prices.py (make sync-prices) pulls the LiteLLM public pricing feed (URL is a config value
  in config.py, ~2,292 models) and upserts versioned rows, inserting a new version only when a price actually changed. The "no
  hard-coded prices, ever" principle is enforced three ways: prices are rows not constants, the feed URL is env-overridable, and
  overrides + effective-date versioning mean prices change without a deploy.

  ---
  4. Ingestion: one usage event, step by step
  
  This is the core loop. POST /v1/usage-events with the API key (usage_events.py:create_usage_event).

  What you send (the schema in schemas/usage_event.py):

  {
    "provider": "openai",
    "model": "gpt-4o",
    "request_type": "chat_completion",
    "feature": "support_chatbot",
    "customer_id": "cust_123",
    "user_id": "user_456",
    "team": "support",
    "environment": "production",
    "input_tokens": 2100,
    "cached_input_tokens": 1800,
    "output_tokens": 340,
    "reasoning_tokens": 0,
    "latency_ms": 1200,
    "success": true,
    "occurred_at": "2026-06-01T12:00:00Z",
    "idempotency_key": "req_abc123",
    "cost_usd": null,
    "metadata": { "semantic_cache_key": "...", "batchable": false }
  }

  The schema has a backward-compat layer worth knowing about: request_type also accepts the old name operation, feature accepts
  workflow, user_id accepts external_user_id, occurred_at accepts event_timestamp. A model_validator backfills environment to
  "unknown", derives team/customer_id from metadata if not top-level, and sets success from status. This is so old and new payload
  shapes both ingest cleanly.

  What the endpoint does, in order:

  1. Reject any non-USD currency (422). Blending currencies into one SUM(cost_usd) would corrupt every total, so v1 refuses rather than
  guess an FX rate.
  2. Pick the pricing time: at = occurred_at or now(). This is what selects the price version.
  3. Call price_usage_event(...) to derive cost (Section 5).
  4. Build the UsageEvent row with the derived cost fields plus all the allocation tags.
  5. db.commit(). If it hits the unique constraint on (project_id, idempotency_key), it rolls back, fetches the existing row, and
  returns it with 200 instead of 201 — so a client retry never double-counts spend.
  6. After commit, call refresh_recommendations() and commit again.

  Flag this now for your refactoring decisions: step 6 runs the entire recommendation engine on every single ingested event. That
  engine scans the whole month of events for that project (Section 8). At "non-trivial ingestion volume" — which CLAUDE.md explicitly
  lists as a goal — that is a real bottleneck. It should be moved off the write path to a schedule or a debounce.

  ---
  5. Cost derivation (the actual math)

  pricing/service.py. Two stages.

  Stage 1 — resolve the price (resolve_price), in strict precedence:
  1. Override: newest org_model_price_overrides row for this org + model_key where provider matches or is NULL, with effective_at <= 
  at. Source = override.
  2. Catalog: newest model_prices row for model_key + provider (effective_at <= at); if none, fall back to model_key alone. Source =
  catalog. The fallback exists because a client's provider string ("openai") does not always match the feed's litellm_provider, and
  most model keys are globally unique.
  3. Neither → None.

  Stage 2 — compute the cost (compute_cost):

  cached    = clamp(cached_input_tokens, 0, input_tokens)
  uncached  = input_tokens - cached
  cache_rate = cache_read_input_token_cost  (or input rate if the model has no cache price)

  cost = uncached * input_cost_per_token
       + cached   * cache_rate
       + output_tokens * output_cost_per_token

  Quantized to 8 decimals, ROUND_HALF_UP. Two deliberate choices: cached tokens bill at the discounted cache-read rate (this is what
  makes prompt-cache savings visible), and reasoning_tokens are not added separately because providers already fold them into
  output_tokens for billing.

  The outcome matrix — every event gets a cost_usd, a cost_source, and a pricing_status:

  ┌──────────────────────────────────────────┬────────────────────┬─────────────────────┬──────────────────────┐
  │                Situation                 │      cost_usd      │     cost_source     │    pricing_status    │
  ├──────────────────────────────────────────┼────────────────────┼─────────────────────┼──────────────────────┤
  │ Both token counts 0 and no reported cost │ null               │ unknown             │ missing_token_counts │
  ├──────────────────────────────────────────┼────────────────────┼─────────────────────┼──────────────────────┤
  │ Price resolved                           │ computed           │ catalog or override │ priced               │
  ├──────────────────────────────────────────┼────────────────────┼─────────────────────┼──────────────────────┤
  │ No price, client sent cost_usd           │ the reported value │ reported            │ model_not_in_catalog │
  ├──────────────────────────────────────────┼────────────────────┼─────────────────────┼──────────────────────┤
  │ No price, no reported cost               │ null               │ unknown             │ model_not_in_catalog │
  └──────────────────────────────────────────┴────────────────────┴─────────────────────┴──────────────────────┘

  The "why" here is the trust philosophy: unknown cost is stored as null, never 0, and unpriced events are kept, never dropped. Losing
  usage data is worse than honestly showing incomplete cost. That distinction is what lets the dashboard later say "92% of your spend
  is catalog-priced, 8% is unpriced" instead of quietly understating the bill.

  ---
  6. What gets stored per event
  
  The usage_events row (models/usage_event.py) carries three groups of columns:

  - Allocation tags: provider, model, request_type, feature, customer_id, user_id, team, department, environment. These are the
  dimensions every breakdown groups by, each with a (project_id, dimension, received_at DESC) index.
  - Token + cost facts: input_tokens, output_tokens, cached_input_tokens, reasoning_tokens, total_tokens, cost_usd, reported_cost_usd,
  cost_source, pricing_status, price_version_id (pins the exact catalog row used, for audit).
  - Request health + time: success, error_code, latency_ms, idempotency_key, occurred_at (client time), received_at (server time).

  One nuance that affects every "today/this month" number: all analytics bucket on received_at (server receipt), not occurred_at 
  (client time). occurred_at is captured and used for price-version selection, but the time axis for spend windows is received_at. The
  model comment flags switching the axis as a tracked follow-up needing index changes. For batched or delayed senders, that is a real
  accuracy caveat.

  ---
  7. Reading it back: the dashboard queries

  When the user opens the dashboard at month's end, every number is a live aggregate. No pre-aggregation, no rollup tables.

  GET /metrics/overview (metrics.py) runs one scan bounded by received_at >= month_start with FILTER clauses for the today subset,
  computing:

  - spend_today, spend_month = SUM(cost_usd)
  - authoritative_spend_month = sum where cost_source IN (catalog, override)
  - authoritative_spend_share_month = authoritative / total → the trust score
  - monthly_forecast_usd = spend_month / day_of_month * days_in_month (straight run-rate extrapolation)
  - budget_variance_usd = forecast − budget; budget_burn_percent = spend_month / budget
  - unpriced_event_share_month, and metadata_quality = fraction of events tagged with feature / customer / team / non-unknown
  environment

  GET /metrics/breakdown?dimension=... is SUM(cost_usd) GROUP BY <dimension> over a whitelist of safe columns. GET /metrics/spend-trend
  is date_trunc('day', received_at) with daily sums.

  So "a month of AI cost" is literally: every priced row this month, summed, grouped, and extrapolated to a forecast. It is exact to
  the cent for catalog-priced events because Varsten computed each one from tokens × versioned rate.

  ---
  8. The recommendation engine and the five levers (STALE — see banner at top of file)

  recommendations.py. Critical framing: the levers do not execute anything. Each "lever" is a detector that reads usage rows and writes
  a Recommendation row (deduped by a dedupe_key like token_trim:<route>:2026-06). The text describes a cut; nothing applies it.

  refresh_recommendations() runs on ingestion, on overview load, and on dashboard load. It scans the current month and emits:

  The five product levers:

  - Token trim — top 5 routes by spend; fires when input_tokens / output_tokens >= 8 (bloated context). Estimated savings = run-rate of
  spend × 0.15.
  - Semantic cache — groups by a metadata.semantic_cache_key; fires when one key repeats ≥ 3 times. Savings = run-rate of spend × 0.50.
  (Note: this triggers on a metadata field you supply, not on cached_input_tokens. Real prompt-cache analysis from the token data is
  not built yet.)
  - Batching — events flagged batchable in metadata or whose request_type matches batch/background/export/sync; requires the model to
  have batch pricing in the catalog. Savings = run-rate of (current cost − batch-priced cost), computed from the actual batch rates.
  - Model downshift — requires model_catalog.cheaper_substitute_key to be set and both models priced. Savings = run-rate of (current −
  lower-cost). This is empty in the catalog today, so this lever never fires. It is also the highest-dollar recommendation type.
  - Smart routing — a route already served by ≥ 2 models at different cost-per-request; proposes shifting traffic to the lower-cost one.
  Savings = (expensive_avg − cheap_avg) × expensive_request_count, run-rated.

  Plus four metadata-quality / governance detectors: unpriced usage, budget overrun (forecast > org budget), non-production spend, and
  failed-request spend (success = false events that still burned tokens).

  run_rate(v) = v / day_of_month × days_in_month everywhere, so a partial month projects to a full month.

  The savings percentages (15%, 50%) are heuristics, not measured. The code labels them measurement_method = "estimated" and confidence
  accordingly. That honesty is intentional and correct for this phase.

  ---
  9. Savings and Proof: what's real, what's seeded

  This is the part you most need to understand for business decisions.

  - recommendation_actions records when a human applies or dismisses a recommendation (PATCH /engine/recommendations/{id}). That part
  is real.
  - savings_attributions is what Proof and Dashboard read for "saved this month" / "net after fee" / "annual run-rate." In
  production this would be the measured before/after delta of an applied cut. Today nothing writes measured attribution rows. They are
  populated only by scripts/seed_demo.py, which also hard-codes each lever's savings_to_date. So the Dashboard "Saved this month"
  number is real demo data, but it is seeded, not measured from your traffic.

  Dashboard math: saved_month = SUM(gross_savings) from attribution rows, annual_run_rate = gross × 12, trust_score = the
  priced-share from the same data-quality query as overview.

  So the closed loop the product guide promises — apply a cut, measure the real delta against what you would have spent, write a
  defensible savings number — is scaffolded in the schema but not implemented. Recommendations are estimated; realized savings are
  seeded. The guide's own copy concedes this ("estimated/backtested in v1").

  ---
  10. The honest map: real vs scaffolding

  Fully real and load-bearing:
  - Auth, tenancy, API-key hashing
  - Pricing catalog, versioning, override resolution, cost derivation
  - Ingestion with idempotency and unpriced-but-kept handling
  - All spend allocation: overview, trend, breakdowns by every dimension
  - Forecast (run-rate), budget variance, trust/metadata-quality metrics
  - Rule-based recommendations (estimated savings)
  - The full frontend for every section, wired to live endpoints

  Scaffolded (schema + UI exist, logic does not):
  - Realized savings measurement → savings_attributions only seeded
  - cheaper_substitute_key empty → the top recommendation never fires
  - Prompt-cache analysis from cached_input_tokens → not built (the cache lever keys off a metadata field instead)
  - Latency in recommendation risk → latency_ms stored, ignored by the engine
  - Customer revenue entry → customer_economics has no write endpoint, so margin analysis has no input
  - Budget enforcement → budget_rules stored, nothing throttles
  - Guardrails, alerts delivery, levers actually executing, any in-path proxy → not built, and correctly deferred per the guide

  ---
  11. What this means for your decisions
  
  - Testing priority: the cost-derivation math and the price-resolution precedence are the load-bearing correctness surface. They
  already have unit tests. The thing without coverage that most affects the demo is the seed → overview → recommendations path end to
  end.
  - Refactor priority: move refresh_recommendations off the ingestion write path. Running a full month-scan per event will not survive
  the ingestion volume the project is explicitly meant to showcase. A debounce, a background job, or computing on read only is the fix.
  - Highest-leverage feature gap: populate cheaper_substitute_key for the top 10-15 model pairs (data task, not code) so the
  highest-dollar recommendation fires, and build prompt-cache analysis from cached_input_tokens (the data is already captured per
  event). Those two unlock the most credible savings story with the least new machinery.
  - The structural gap between demo and product: realized-savings measurement. Until an applied recommendation writes a measured
  before/after row into savings_attributions, the Proof section is permanently seeded data. That is the one piece that turns "we
  estimate you could save X" into "we saved you X," which is the entire pitch.
