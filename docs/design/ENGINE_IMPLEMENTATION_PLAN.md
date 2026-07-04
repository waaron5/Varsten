# Engine Implementation Plan — Handoff

Status: active. Written 2026-07-02 as the working spec for completing the engine
roadmap (phases A–F in CLAUDE.md, "Current phase" section). The architectural
decisions here are settled; the job is execution. If something in this document
contradicts observed code, the code moved — reconcile and update this document,
do not silently deviate.

Companion documents:
- `CLAUDE.md` — invariants, working style, roadmap summary. Read first, every session.
- `docs/VARSTEN_ENGINE_AUDIT.md` — independent audit; its Section 14 table and
  the 2026-06-30 addendum are folded into this plan (slice B0).
- `docs/design/PALANTIR_ONTOLOGY_DESIGN.md` — the `ChangeRequest` governance
  object spec (phase F).

---

## 0. Before writing any code

1. Run `git status`. This repo has had two agents working in parallel. Expect
   modified files you did not touch. Never revert or overwrite uncommitted work
   you don't understand; read it, reconcile, and if a conflict is real, stop and
   ask the user.
2. Run the full suite from `backend/`: `uv run pytest -q`. It must be green
   before you start (584 passed / 3 skipped as of handoff). If it isn't, fix or
   report before proceeding.
3. Read the current state of `app/engine/` end to end (~1,900 lines). The
   planner/types/classification files are actively evolving; do not trust this
   document's line references over the code.

## 1. Invariants — violating any of these is a stop-the-line bug

- **Metadata only.** No prompt, completion, or tool-argument text in
  `usage_events`, `request_decision_events`, planner metadata, or logs. The
  semantic cache and replay corpus are the only documented exceptions. The
  runtime-trace sanitizer denylist (`engine/runtime_trace.py`) exists for this.
- **Fail open.** Every lever lookup returns None/unchanged on any error. A bug
  in optimization may stop a saving; it must never fail a request.
- **Nothing expensive on the hot path.** No model calls, no LLM judges, no
  embeddings inline with request forwarding (the semantic-cache embedding on
  miss is the one existing, deliberate exception). Policy and cache lookups only.
- **Never buffer a stream.** SSE passes through as it arrives; token/billing
  capture is async.
- **Judge-scored (subjective) verdicts never auto-apply.** `VERDICT_NEEDS_HUMAN`
  is a ceiling, not a suggestion (`eval/gate.py`).
- **Measured vs. estimated never blur.** Only `MEASURED_METHODS` roll into
  `verified_savings_usd`; the fee is charged on verified only
  (`savings_measurement.py`). New savings numbers must declare a method.
- **Tenancy.** Every new query filters by `project_id` (and `organization_id`
  where the model carries it). Every new endpoint resolves the project through
  the existing deps. No cross-tenant reads, ever.
- **Tests are not optional.** Each slice lands with its own test file plus a
  green full suite plus `uv run ruff check` / `uv run ruff format`.

## 2. Where the loop stands

Closed so far:

- **A1 (done).** `app/engine/promotion.py` + `tests/test_engine_promotion.py` +
  scheduler job `learning-promotion` + settings
  `learning_promotion_interval_seconds` / `learning_promotion_window_days`.
  Measured outcome evidence with readiness `recommendable` /
  `auto_apply_candidate` on policy-backed levers (routing/downshift/trim) is
  promoted into open `Recommendation` rows when no enabled `ProxyPolicy` covers
  that lever+model. Promotion never applies; the eval-gated apply path stays the
  sole authorization point.
- **B1 (done, taken out of order).** `app/proxy/sequential.py` (AsympCS,
  Waudby-Smith et al. 2023) + `tests/test_sequential_inference.py` (the
  behavioural spec: time-uniform coverage ≤ 6%, power ≥ 95% by n≈2000, monotone
  shrinkage) + settings `sequential_cs_alpha` / `sequential_cs_target_n`.
  `proxy/experiment.py` and `proxy/drift.py` now use a time-uniform confidence
  sequence instead of a fixed 1.96·SE interval. **Two consequences the next
  agent must know:**
  - *Drift rollback is now stricter.* It fires only when the CS for the quality
    drop lies entirely above `drift_tolerance` (confident, not point-estimate).
    A 5-vs-5 arm split no longer rolls back; ~12+ per arm at a maximal split
    does. Drift tests were reseeded to 15/arm to reflect this — that is the
    intended new semantics, not a workaround.
    Rate CS uses Laplace (Beta(1,1)) smoothing so an all-pass/all-fail arm still
    yields a bounded interval instead of degenerate zero variance.
  - *`sequential.py` is stdlib-only (no numpy)* so it stays cheap to import on
    request-adjacent paths. The numpy in the test is vectorisation for the
    simulation only, tied to production by a consistency test.

  *Why out of order:* A4 (the strict next Opus slice) depends on A3 (Sonnet-safe,
  not yet done) and rewrites `router.py`, which the other workstream has
  uncommitted changes in. B1 had no unfinished prerequisites, touched only
  `experiment.py`/`drift.py` (untouched by the other agent), and unblocks C4 and
  phase E. Starting A4 before A3 while contending for the hot file was the wrong
  risk.
- **B2 (done).** Adaptive holdback management now runs in the learning-promotion
  sweep. Enabled routing/trim policies shrink measurement holdback stepwise
  `5% -> 2% -> 1%` when the sequential savings confidence sequence sits above
  zero, and restore to 5% when the sequence includes zero again. Every change is
  persisted as a system `RecommendationAction`. Outcome scoring now supports
  exponential recency decay (`learning_prior_half_life_days`, default 14) over
  both counts and sums, while retaining raw counts for display/audit.

- **A3 (done, by the other agent).** Persisted outcome priors: `EngineOutcomePrior`
  table (migration `c3d4e5f6a7b9`), `app/engine/priors.py` (sweep upsert +
  TTL-cached hot-path lookup `outcome_priors_for_request`, fail-open), wired into
  `_attach_observe_plan` in `router.py`. The planner now runs with learned priors.

- **A4 (done).** The planner selects a real primary action and the proxy shadows
  parity. `planner.py::select_action` replaces the hardcoded `observe` selection
  (priority `exact_cache → semantic_cache → model_routing → token_trim`; modes
  `enforce` / `shadow` / `observe_only`); `build_observe_only_plan` is kept as an
  alias of the new `build_optimization_plan`. `evidence.py::add_planner_parity_trace`
  records, at the single `record_request_decision` choke point (covers cache hit
  and miss), whether the lever the proxy actually applied was authorized (not
  rejected) by the planner — `stage="planner_parity"`, action `match`/`mismatch`.
  Passthrough is always a match (advisory planner forces nothing); a mismatch means
  the proxy applied a lever the planner would have blocked (e.g. a cache hit while
  cache enforcement is still shadow). `/engine/planner-summary` aggregates parity.
  **Note on "enforcement":** the planner was *already* the authorization layer
  (cache/routing/trim consult `draft.optimization_plan`, and a `None` plan fails
  open), so A4's staged 4b/4c "inversion" was largely already in place; the real
  remaining work — a genuine selected action + parity instrumentation + a
  fault-injection proof (`test_planner_parity.py::test_request_succeeds_when_planner_raises`)
  — is done. Killing the planner changes nothing but the trace.

- **A5 (done).** Canonical route identity. `app/engine/route_identity.py`
  (`canonical_route_key` = feature|workflow|request_type|task_type|default,
  normalized, length-capped; `route_key_from_context`, `model_scoped_route_key`).
  Persisted on `RequestDecisionEvent.route_key` (migration `d4e5f6a7b8c1`, nullable
  + index, populated in `record_request_decision`). Threaded into the learning
  segment: `outcomes._SegmentKey` gained `route_key` (uses the persisted value,
  falls back to deriving it for pre-column rows), surfaced in the
  `LearningCandidateSegment` API schema, and the two decision queries
  (promotion + planner-summary) now select it. `EvalRun.route_key` already existed
  and aligns semantically. **Left for later** (documented in §"Open follow-ups"):
  `QualityGuardrail`/latency-SLO matching still keys on model, not route_key —
  the model-centric drift sweep has no request route context, so converging it
  needs a policy↔route_key linkage.

- **C1–C4 (all done).** Phase C reliability parity, in one pass:
  - *C3 latency guardrail* — `evaluate_latency_drift` in `proxy/drift.py` rolls a
    route back when the treatment arm is confidently slower than control beyond
    `latency_drift_tolerance_ms`, or confidently above a route's
    `QualityGuardrail.max_latency_ms` SLO (one-sample `mean_confidence_sequence`
    added to `sequential.py`). Same peeking-safe CS as B1. Rollbacks now carry a
    `trigger` field (`quality` / `latency` / `latency_slo`).
  - *C4 canary ramp* — `ProxyPolicy.rollout_percent` (migration
    `c2d3e4f5a6b7`, default 100 so existing policies are unaffected) +
    `proxy/canary.py`. `resolve_route`/`resolve_trim` gate on a rollout draw
    *independent of* holdback arm assignment; out-of-rollout traffic is plain
    passthrough, never an experiment arm. Activation starts at
    `canary_initial_percent` only when `canary_enabled` (default off →
    activates fully live, unchanged). The drift sweep promotes `10→50→100` when a
    stage shows enough signal and no quality/latency regression, recording a
    `canary_promoted` system action.
  - *C2 shared state* — `proxy/shared_state.py`: an **optional** cross-instance
    store (get/set-ttl/delete/clear_prefix) that is a **complete no-op unless
    `REDIS_URL` is set**, so default/single-instance behaviour is byte-identical.
    The circuit breaker publishes its open flag (TTL = reset window) and the
    budget-cap cache stores its computed set, so a trip/cap propagates fleet-wide.
    Every store op fails open to local behaviour. **`redis` is a lazy import, NOT
    added to pyproject** — must be flagged/added before a Redis deploy (see §7.5).
  - *C1 retries + fallback* — `proxy/resilience.py` (retryability, jittered
    capped backoff, Retry-After, fallback resolution) + integration in
    `_forward_once` and `_stream_through`. Connect errors / 429 / 5xx are retried
    before the first byte (never mid-stream, never for batches), honouring a
    latency budget; the breaker still records one outcome per request. On
    exhaustion a same-provider degradation model (`proxy_fallback_models`, project
    → model) is tried, recorded as `fallback_used` with zero savings and an
    `X-Varsten-Fallback` response header.
    **Two deliberate scope cuts** for the next agent: (1) *fallback is
    non-streaming only* — streaming retries land, but re-opening an SSE stream on
    the fallback model mid-generator was judged too risky for this pass; (2)
    *fallback is same-provider only* — cross-provider/alt-deployment fallback needs
    the fallback provider's key resolved in the hot path (the vault work) and is
    deferred. `resilience.fallback_model` is structured to extend to both.

- **D1 (done).** Prompt-cache orchestration, detection + recommendation.
  `proxy/prompt_prefix.py::stable_prefix_hash` fingerprints each request's
  cacheable prefix (system/developer messages + tools; sha256[:16], hash only,
  all three dialect shapes) at the `_attach_observe_plan` choke point; persisted
  on `RequestDecisionEvent.prefix_hash` (migration `e5f6a7b8c9d2`). The
  prompt-cache recommendation now uses the route's *measured* dominant-hash share
  (`_prefix_stability` in recommendations.py): stable (≥70%) → enable-caching with
  measured evidence and high confidence; unstable (≤40%) → a new
  `prompt_prefix_restructure` recommendation; no data → the old 0.5 assumption,
  now honestly labeled medium confidence. No transform — detection only, per plan.
- **D3 (done).** Trace/session model + agent-loop detector. `X-Varsten-Trace-Id`
  parsed into `RequestContext.trace_id` (header or metadata JSON); persisted with
  a content-free whole-request fingerprint (`full_request_fingerprint`) on the
  decision ledger (migration `e6f7a8b9c0d3`). `engine/agent_loops.py` groups
  decisions by (trace, fingerprint), treats the first ask as necessary and every
  repeat's cost as measured waste, and requires ≥3 affected traces before
  surfacing an `agent_loop` recommendation (lever=None — a workflow fix, never
  executed) in the standard refresh.
- **F (done).** ChangeRequest governance, natively (per
  PALANTIR_ONTOLOGY_DESIGN.md §2). `models/governance.py` (migration
  `f8a9b0c1d2e3`): one row per proposed model swap with the frozen content-free
  evidence bundle; state machine proposed → approved/rejected → active →
  rolled_back. Proposed automatically when a routing-lever eval completes with
  safe/needs_human (`engine/governance.py::ensure_change_request`, hooked in the
  eval runner's `_finalize`); decided via
  `POST /v1/engine/change-requests/{id}/decision` (named user + rationale +
  immutable audit event); listed via `GET /v1/engine/change-requests`. The apply
  path syncs the lifecycle (active on apply, rolled_back on dismiss/rollback and
  on drift rollback) always, and **enforces** an approved request only when
  `governance_change_requests_enabled` is on (default off — zero behavior change).
- **B0 + A2 (done, by the other agent; verified).** Gain-share accounting
  (measurement cost netted, eval/embedding overhead metered via `record_overhead_usage`,
  fabricated ±15% band removed, reconciliation test in test_savings_measurement)
  and automation-upgrade proposals (`propose_automation_upgrade_candidates`).

- **E (done).** Bandit routing over eval-cleared candidates.
  `app/engine/bandit.py` (selection policy) + `candidate_stats_for_request` in
  `priors.py` (TTL-cached per-candidate ledger aggregates, merged across
  segments) + `_maybe_bandit_select` in `routing.py::resolve_route` +
  `routing.add_bandit_candidate` / `remove_bandit_candidate` (control plane) +
  per-candidate drift removal in `drift.py::_check_bandit_candidates` +
  add/list/remove endpoints under `/engine/routes/{id}/bandit-candidates`.
  Design facts the next agent must know:
  - **Modes** (`bandit_routing_mode`, default `off`): `off` = pure no-op;
    `shadow` = sampler runs, choice recorded in the `bandit_routing` runtime
    trace, traffic still goes to the primary; `active` = sampled candidate
    routed. Fail-open on its own inner try: a bandit error routes to the
    primary — it can only change *which cleared candidate* serves, never
    whether the request is served.
  - **Selection is deliberately NOT Thompson over savings magnitude**: the
    persisted priors carry mean savings but no variance, and inventing one
    would be fake learning. It is a quality-gated exploit/explore split:
    Thompson (Beta) draw on measured quality must clear `bandit_quality_floor`
    (hard constraint); exploit = highest measured mean savings among candidates
    with ≥ `bandit_min_samples`; explore = uniform over under-sampled cleared
    candidates under the hard `bandit_exploration_budget` (2%). A
    savings-variance column on `EngineOutcomePrior` upgrades exploit to full
    Thompson later.
  - **Eligibility is off-path**: `add_bandit_candidate` requires a completed
    eval with verdict `safe`, or `needs_human` + approved/active ChangeRequest
    — the same bar as a single-candidate apply. The drift sweep removes a
    regressed candidate surgically (policy + primary stay live), logging a
    `bandit_candidate_removed` system action.
  - **Savings/learning honesty**: the holdback control arm is assigned *after*
    selection and stays on the incumbent, so per-pair A/B math is untouched;
    chosen models land in the decision ledger (`model_chosen`) and flow back
    into the priors sweep — the learning loop uses only persisted evidence.

- **D2 (done).** Learned prompt compression as a real pipeline.
  `models/compression.py` (`PromptCompression` artifact, migration
  `a9b0c1d2e3f5`; the compressed text is a documented content-store exception,
  the original stored as hash only) + `engine/compression.py` (pure
  extract/hash/substitute helpers; off-path generation from the replay corpus
  with an injectable `compress_fn` — default `openai_ops.compress_system_prompt`
  on the customer's key, metered as `overhead: "compression"` on the caller's
  session; validation rejects empty/identical/insufficient-shrink rewrites via
  `compression_min_prompt_chars` / `compression_max_ratio`; creates the
  Recommendation + pending EvalRun) + `proxy/compression.py` (hot path:
  policy resolve → canary gate → holdback arm → TTL-cached artifact →
  **exact-hash substitution only** — a request whose system prompt is not
  byte-identical to the evaluated original passes through untouched, traced
  `compression_prompt_mismatch`; `TransformConflictError` blocks activation
  while a trim policy is live on the same model, closing the same-model
  experiment-pair collision from the compression side). Integration facts:
  - Lever `prompt_compression` added to the vocabulary (approve-mode default),
    `GATED_LEVERS` (apply requires a completed eval) and `GOVERNED_LEVERS`
    (needs_human proposes a ChangeRequest).
  - Eval = the standard runner with a substituting `replay_fn`
    (`run_compression_eval`); samples not carrying the exact original are
    skipped, so the verdict covers only traffic the lever would touch; the
    same-model cost delta measures the input-token saving for free. The
    evaluate endpoint reuses the generation-created pending run; the background
    executor dispatches by lever.
  - Planner gained a `prompt_compression` candidate (trim's blockers) +
    `SELECTION_PRIORITY` entry, so A4 parity covers compressed requests;
    evidence gained `compression_applied` (decision_type `compression`,
    savings method `compression_holdback_observation`); the client
    Idempotency-Key is not forwarded upstream when compression changed the
    body. Drift sweep covers the lever (same-model pair) for auto-rollback.
  - Endpoints: `POST /v1/engine/compressions` (background generation; audit
    event; Performance-gated) and `GET /v1/engine/compressions` (artifact list
    — sizes and hashes, deliberately not the compressed text).
  - Also: `LEVER_DEFAULT_AUTOMATION` now drives the demo seed's lever configs
    (was a drifted hard-coded copy), and lever-set test assertions moved to 6.

**The roadmap (A–F) is complete.** The next phase of work is
`ENGINE_VALIDATION_PLAN.md` — proving the whole loop end to end with
adversarial simulations, chaos, reconciliation audits, and replay tapes.

**Reuse the B1 confidence sequence**
(`ConfidenceSequence`, `difference_confidence_sequence`, `mean_confidence_sequence`)
and the A5 route key (`canonical_route_key`) everywhere — do not re-derive.
Model guidance: **[Sonnet-safe]** means Sonnet 5 can execute it reliably as a
single focused session; unmarked slices want Opus.

---

## 3. Phase A — close the learning loop

### Slice A2 — automation-mode upgrade proposals [Sonnet-safe]

**Goal.** When a segment's readiness hits `auto_apply_candidate` and its lever's
`LeverConfig.automation_mode` is `approve` *and* an enabled policy is already
running it, the engine should propose flipping that lever to auto — as a
recommendation a human approves, not as a silent flip.

**Where.** Extend `app/engine/promotion.py` (new function, called from
`promote_learning_candidates`). Do not create a new scheduler job.

**Behavior.**
- Trigger condition: candidate readiness == `auto_apply_candidate`, lever in
  `PROMOTABLE_LEVERS`, an enabled `ProxyPolicy` exists for (lever, model), and
  `LeverConfig.automation_mode == "approve"` for that project+lever.
- Emit a `RecommendationSeed` with `type="automation_upgrade"`, `lever` set,
  dedupe key `engine_learning:automation:{lever}:{digest}:{YYYY-MM}`,
  `measurement_method="estimated"`, confidence `high`, and a rationale citing
  the auto-readiness evidence (sample count, savings coverage, quality pass
  rate, acceptance rate).
- Applying this recommendation type is out of scope for A2 — the UI/apply path
  for it can reuse the existing recommendation actions later. A2 only proposes.

**Tests** (`tests/test_engine_promotion.py`, extend): proposal created when all
conditions hold; not created when automation is already `auto`; not created
without an enabled policy; not created at `recommendable` readiness; idempotent.

**Done when:** tests green, full suite green, no new endpoints.

### Slice A3 — persisted outcome priors, wired into the live planner [Sonnet-safe]

**Goal.** The planner accepts `outcome_priors` but the proxy passes none,
because scoring evidence rows at request time is too expensive for the hot
path. Persist the priors and give the proxy a cheap indexed lookup.

**Where.** New model in `app/models/engine.py` (or a new `models/priors.py`),
Alembic migration, refresh logic in `app/engine/promotion.py`'s sweep (same
tick, same advisory lock), read helper in `app/engine/outcomes.py` or a new
`app/engine/priors.py`, wiring where the proxy builds `PlannerInput`
(currently in `proxy/router.py` — find `_attach_observe_plan` or its successor).

**Schema** (`engine_outcome_priors`):
- `id`, `organization_id`, `project_id` (FK, CASCADE), timestamps
- segment identity: `lever`, `task_type`, `risk_level`, `provider_requested`,
  `model_requested`, `provider_chosen`, `model_chosen`
- evidence: `readiness_status`, `sample_count`, `measured_savings_count`,
  `total_gross_savings_usd` Numeric(18,8), `average_gross_savings_usd`,
  `quality_pass_rate` Numeric(6,4), `feedback_acceptance_rate` Numeric(6,4),
  `reason_codes` JSONB, `window_days`, `computed_at`
- Unique on (project_id, lever, task_type, risk_level, provider_requested,
  model_requested, provider_chosen, model_chosen). Index on
  (project_id, model_requested, lever).

**Behavior.**
- The sweep upserts the full current candidate list per project (delete-then-
  insert inside the transaction is acceptable at this scale) every tick.
- Hot-path read: one indexed query by (project_id, model_requested), returning
  rows converted through `outcome_prior_from_learning_candidate`-equivalent
  logic into `OutcomePrior` tuples. Must fail open: any exception returns `()`.
- Cache the lookup in-process with a short TTL (60s) keyed by
  (project_id, model) — follow the pattern in `proxy/budget_enforcement.py`.

**Tests:** new `tests/test_engine_priors.py` — sweep persists and refreshes
rows; hot-path read returns priors and fails open on a broken session; planner
receives priors end-to-end (a proxied request records a plan whose candidate
carries `outcome_prior` metadata — follow existing planner-trace tests).

**Done when:** a request through the proxy on a project with persisted priors
produces planner metadata showing the prior, with zero evidence-scoring queries
on the request path.

### Slice A4 — the planner becomes the single decision point (staged) — DONE (see §2)

**This is the highest-risk slice in the plan. Do not attempt it as one change.**
`proxy/router.py` is ~2,500 lines of streaming hot path serving three client
dialects, and it is actively being modified by another workstream. Each stage
below lands, tests green, before the next starts. If mid-flight planner changes
conflict, reconcile with the code as it exists, not with this document.

**Stage 4a — parity shadow.** The planner already runs observe-only. Add a
parity check: after the proxy makes its real decision (cache serve / route /
trim / passthrough), record both the planner's would-be selection and the
actual decision in the runtime trace, with a `parity` field (`match` /
`mismatch:{reason}`). No behavior change. Add a summary of parity to the
`/engine/planner-summary` endpoint. Run this in real traffic (or the full test
suite + seeded demo) until mismatches are understood and either fixed in the
planner or documented as intentional.

**Stage 4b — enforce for exact cache.** The safest lever: flip the exact-cache
serve decision to consult the plan (`CandidateStatus.ELIGIBLE` + gate allowed)
instead of the inline policy check, keeping the inline check as a fail-open
fallback if the planner errors. Trace `enforced=true`. The proxy behavior must
be byte-identical for every existing test.

**Stage 4c — enforce routing and trim.** Same inversion for
`resolve_route`/`resolve_trim` outcomes: the planner consumes the resolved
policy and emits the selected action (including arm assignment as an input,
not a planner responsibility — randomization stays where it is). The existing
modules keep doing the DB lookups; what changes is that the *decision* — apply
or don't, and why — is the planner's output, recorded once.

**Invariant for all stages:** planner failure of any kind degrades to the
pre-A4 inline path. The planner can never be the reason a request fails or
slows measurably (its work is in-memory classification + prior lookup, both
already off the network path).

**Tests:** parity assertions in existing proxy tests; a fault-injection test
that breaks the planner and asserts the request still succeeds via fallback;
trace-shape tests for `enforced`.

**Done when:** every optimization decision in a proxied request is traceable to
one planner output with reason codes, and killing the planner in a test changes
nothing but the trace.

### Slice A5 — canonical route identity — DONE (see §2; guardrail convergence deferred)

**Goal.** Segments, policies, evals, and guardrails key on different things
(model, task_type, feature, route strings). Define one route key so learning
evidence, eval verdicts, and guardrails all attach to the same object.

**Definition.** `route_key = feature or workflow or request_type, else
task_type, else "default"`, normalized (lowercase, trimmed, length-capped),
combined with the incumbent model where the consumer needs a model-scoped key.
Implement as one function in `app/engine/route_identity.py` with exhaustive
unit tests; then thread it through: `RequestDecisionEvent` (new nullable
`route_key` column + backfill migration), `_SegmentKey` in
`engine/outcomes.py` (additive — keep existing fields), `EvalRun.route_key`
(already exists — converge its semantics), `QualityGuardrail.route`.

Do this after A4, not before: A4's parity work reveals which identity the
decisions actually need.

---

## 4. Phase B — statistical and accounting rigor

### Slice B0 — gain-share accounting integrity [Sonnet-safe] — DONE

Three defects from the audit addendum (2026-06-30). All are in read-side savings
math — no hot-path risk. Fix before quoting net savings to a finance buyer.

1. **Net out the holdback's cost.** In `savings_measurement.py`, compute the
   savings forgone on control-arm traffic (`control_request_count ×
   savings_per_request`) per experiment and surface it as
   `measurement_cost_usd`, with `verified_savings_usd` reported both gross and
   net of it. The Proof surface shows the line item, labeled as the cost of
   rigorous measurement.
2. **Meter eval/replay and embedding overhead.** Replay calls
   (`eval/openai_ops.py`) and cache-miss embeddings (`proxy/embedding.py`) run
   on the customer's key. Record their token usage into `usage_events` with a
   distinguishing metadata tag (`overhead: "eval_replay" | "embedding"`), and
   subtract the period's overhead cost in `compute_verified_savings` as
   `optimization_overhead_cost_usd`. (The engine reporting module already has a
   field by that name — converge on it.)
3. **Kill the fabricated ±15% band.** `savings.py` hard-codes
   `confidence_low = gross × 0.80`, `high = × 1.15` on *estimated* savings.
   Remove the numeric band; label estimates "estimated, not measured" with no
   interval. Never render a fudge factor beside the real holdback CI.

**Tests:** arithmetic tests for each; a reconciliation test asserting
`net = direct + holdback − measurement_cost − overhead` over a seeded period.

Implemented in `app/savings_measurement.py`, `app/savings.py`,
`app/proxy/embedding.py`, `app/eval/runner.py`, and `app/proxy/ledger.py`.
Proof now exposes `verified_gross_savings_usd`, `measurement_cost_usd`,
`optimization_overhead_cost_usd`, and net `verified_savings_usd`; billing clamps
negative net verified savings to a zero billable basis.

### Slice B1 — always-valid sequential inference — DONE

Implemented in `app/proxy/sequential.py`; see "Where the loop stands" above for
the as-built notes (stricter drift, Laplace-smoothed rates, stdlib-only,
field-name-stable so `savings_measurement.py` needed no change). Original spec
retained below for reference.

**Goal.** `compute_experiment` computes a fixed 95% CI that is consulted
continuously (drift sweeps every 5 minutes, dashboards on every load). That is
the textbook peeking problem: the effective false-positive rate is far above
5%, and both auto-rollback and the billed savings number inherit it.

**Approach.** Replace the fixed CI with a time-uniform confidence sequence for
the difference in arm means. Recommended: empirical-Bernstein confidence
sequences (Howard, Ramdas, McAuliffe, Sekhon 2021; Waudby-Smith & Ramdas 2023),
which need only running count/mean/variance per arm — the data already stored.
Keep the point estimate; replace `ci_low/ci_high` with the CS bounds; keep the
API/field names so consumers don't churn.

**The spec is the property, not the formula.** Whatever implementation is
chosen must pass these simulation tests (new
`tests/test_sequential_inference.py`, seeded RNG, marked slow if needed):

1. *Time-uniform coverage:* 10,000 simulated experiments with equal-cost arms
   (lognormal costs, realistic scale), checked at every n from 30 to 5,000; the
   fraction of experiments where the CS ever excludes 0 must be ≤ 5% (with
   slack for simulation noise, assert ≤ 6%).
2. *Power:* with a true 30% cost difference, the CS must exclude 0 by
   n ≈ 2,000 in ≥ 95% of runs.
3. *Monotone shrinkage:* CS width is non-increasing in n on average.

If an implementation can't pass test 1, it is wrong — do not weaken the test.

**Consumers to update:** `proxy/experiment.py` (bounds), `proxy/drift.py`
(rollback trigger becomes "CS for the quality-rate difference excludes the
tolerance", same evidence, honest error control), `savings_measurement.py`
(holdback bounds), and the audit doc's claims once true.

### Slice B2 — adaptive holdback and prior freshness — DONE

Implemented in `app/engine/promotion.py` and `app/engine/outcomes.py`.

- Holdback sizing: once an experiment's CS excludes 0 with positive lower bound,
  the learning-promotion sweep shrinks `holdback_percent` stepwise (5% → 2% →
  1%, floor 1%). If a reduced policy's CS includes zero again, it restores to
  5%. Changes are written as `RecommendationAction` rows with `source="system"`.
- Prior recency: `score_optimization_outcomes` accepts `now` and
  `half_life_days`; promotion passes `settings.learning_prior_half_life_days`
  (default 14). The scorer decays effective sample/measurement/quality/feedback
  counts and savings sums, and returns raw counts beside the weighted/effective
  fields for display.

---

## 5. Phase C — reliability parity (enterprise table stakes)

### Slice C1 — retries and fallback chains — DONE (non-streaming fallback; see §2 scope cuts)

**Goal.** Today an upstream 5xx fails fast to the client. "Fail open" must mean
"keep the request alive," not "pass the error through."

- Retry idempotent-safe failures (connect errors, 429 with Retry-After, 5xx
  before any bytes streamed) with capped exponential backoff + jitter, max 2
  retries, total added latency budget ~3s, all configurable.
- Fallback chain per project+model, stored in `ProxyPolicy` params or a new
  `fallback_chains` config: same model on an alternate provider/deployment
  first, then a configured degradation model. **Fallback is a reliability
  action, not an optimization: it records `fallback_used=true` +
  `fallback_reason` on the decision event (columns exist) and claims zero
  savings.**
- Never retry after streaming has started. Never retry non-idempotent
  operations (batches).
- Tests: httpx-mock upstream failures for each class; assert retry counts,
  fallback order, no-retry-after-first-byte, and decision-event evidence.

### Slice C2 — shared state for multi-instance deploys — DONE (Redis optional, lazy; not in pyproject)

Move circuit-breaker state (`proxy/circuit.py`) and budget-cap cache
(`proxy/budget_enforcement.py`) behind a small interface with two
implementations: current in-process (default, dev) and Redis
(`REDIS_URL` setting; add dependency only when this lands). Fail open to the
in-process implementation if Redis is unreachable. This is the first paid
infra addition — flag it to the user before adding the dependency, per
CLAUDE.md.

### Slice C3 — latency as a real guardrail [Sonnet-safe] — DONE

`QualityGuardrail.max_latency_ms` exists but nothing reads it. In the drift
sweep, compare treatment-arm vs control-arm latency (`latency_ms` is on the
decision events / ledger) with the same sequential machinery as B1; a
treatment arm violating the route's SLO (or degrading beyond tolerance vs
control) rolls back exactly like quality drift, with its own reason string.

### Slice C4 — canary ramp for policy activation — DONE

Replace binary `enabled` with a ramp: `ProxyPolicy` gains
`rollout_percent` (default 100 for backward compatibility). Activation of a
routing/trim policy starts at a configured canary (10%), and the sweep promotes
10 → 50 → 100 when the CS shows no quality/latency regression at each stage,
or rolls back. Requests outside the rollout percent behave as if the policy
did not exist (and are not experiment arms). Randomization must be independent
of arm assignment.

---

## 6. Phases D–F

- **D1. Provider prompt-cache orchestration — DONE (detection; see §2).** The
  opt-in *transform* (restructuring prompts to stabilize prefixes) remains
  later work: it touches content — treat like trim: deterministic, eval-gated,
  holdback-measured.
- **D2. Learned prompt compression — DONE (see §2).** Off-path generation,
  eval-gated, governed, canary+holdback, exact-hash substitution only.
- **D3. Trace/session model — DONE (see §2).** The audit's "agent loop detector."
- **E. Bandit policy — DONE (see §2).** Default off; shadow mode for zero-risk
  telemetry; candidates enter only via the eval/ChangeRequest clearance gate.
- **F. `ChangeRequest` governance object — DONE (see §2).** Enforcement is
  opt-in via `governance_change_requests_enabled` (default off).

---

## 7. Working protocol for every slice

1. Re-read the touched modules first; this codebase moves under you.
2. One slice per session/PR. Land it fully: code + tests + full suite + ruff.
3. New settings get documented defaults that keep current behavior (features
   off or no-op until enabled) so deploys are never surprised.
4. Migrations: additive and backward-compatible; no destructive column changes.
5. Do not commit or push unless the user asks. Do not touch `marketing/` or
   frontend claims — savings-claim language changes are the user's call.
6. If a slice reveals the plan is wrong, say so and propose the correction —
   do not silently improvise architecture.

## Open follow-ups left by Phase C (not blocking, but track them)

- **Redis dependency (C2).** `redis` is used via lazy import and is deliberately
  NOT in `pyproject.toml`. Before any multi-instance/Redis deploy, add it (an
  optional dependency group is cleanest) and set `REDIS_URL`. Flag the cost/
  lock-in to the user first, per CLAUDE.md.
- **Streaming fallback (C1).** Retries cover streaming; falling back to a
  different model mid-SSE does not. Add it when the streaming path is next
  touched (re-open the stream on the fallback model in the pre-first-byte failure
  branch, before yielding the SSE error).
- **Cross-provider fallback (C1).** Only same-provider degradation-model fallback
  ships. Cross-provider needs the fallback provider's key resolved on the hot
  path — do it alongside the provider-key vault work.
- **Guardrail/SLO convergence onto route_key (A5 leftover).** A5 landed the
  canonical route key and persists it on every decision, but `QualityGuardrail`
  and the C3 latency-SLO lookup (`drift._latency_slo_ms`) still key on model. The
  drift sweep is model-centric and has no per-request route context, so real
  convergence needs a `ProxyPolicy → route_key` linkage (store the route key a
  policy serves at activation). Do that when guardrails are next reworked; until
  then guardrails match by model, which is correct but coarser than route-level.
- **Persisted priors + route_key (A5/A3).** `EngineOutcomePrior` (the hot-path
  prior table) is model-keyed and does NOT store route_key; the in-memory learning
  segment does. If per-route priors are ever needed at request time, add route_key
  to that table and the `outcome_priors_for_request` lookup.
