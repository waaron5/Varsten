# Engine Validation Plan — proving the engine is real

Status: active spec, written 2026-07-04, immediately after the last roadmap
slice (D2) landed. The engine now implements the full lifecycle — observe →
classify → generate candidates → score risk/reward → apply/shadow/recommend/
no-op → execute safely → measure cost/quality → persist decision trace → learn
from outcomes — with 719 passing tests. Those tests prove each part works as
designed. **This plan proves the design itself holds up**: that the engine is
robust, fail-open, saving money honestly, verifying savings correctly, and
preserving quality when a realistic, adversarial, unlucky world hits it — and
that nothing about it would look fake or untrustworthy to a skeptical CTO or
CFO.

Companion: `ENGINE_IMPLEMENTATION_PLAN.md` (what was built and where),
`VARSTEN_ENGINE_AUDIT.md` (the independent audit whose standards this plan
adopts as acceptance gates).

## Philosophy

- **Unit tests prove parts; this plan proves the loop.** Every workstream runs
  traffic through the real proxy (ASGI), the real ledger, the real sweeps, and
  the real learning path — mocking only the provider boundary.
- **Adversarial by default.** Each scenario is designed to *catch the engine
  lying*: fake savings, silent quality loss, phantom learning, a request that
  dies because an optimization broke. A scenario that cannot fail is not a
  validation.
- **Ground truth or reconciliation, never trust.** Every claimed number is
  checked against either planted ground truth (synthetic tapes with known
  optimal savings) or an independent recomputation from raw ledger rows
  (never through the same code that produced the claim).
- **The output is a proof pack.** Machine-readable reports a buyer's engineer
  could audit, not green checkmarks.

## Known gaps to probe explicitly (do not paper over)

Carried from the implementation plan's follow-ups; the validation must
*quantify* these, not hide them:

1. Trim/compression same-model experiment-pair collision (guard exists only on
   the compression side; verify trim-after-compression is also impossible or
   measure the contamination).
2. Guardrail/latency-SLO matching is model-scoped, not route_key-scoped.
3. Decision-evidence writes are best-effort: quantify the metered-request-
   without-decision-row rate under fault injection (learning blind spots).
4. Streaming fallback absent; cross-provider fallback absent.
5. Bandit exploit uses mean savings without variance (no Thompson over
   magnitude) — quantify regret vs an oracle in simulation.
6. `redis` dependency not in pyproject (C2 is dormant until added).

---

## Status (updated 2026-07-04)

**ALL WORKSTREAMS (V0–V8) ARE DONE** — `backend/tests/validation/` holds 38
scenarios (182 invariant checks), all green, with the 719-test unit suite
unaffected. `scripts/validate_engine.py` runs the suites, aggregates the
scenario reports, evaluates the seven acceptance gates, and writes
`validation_reports/PROOF_PACK.md` + `validation_report.json` (gitignored
artifacts). Current result: **all gates met, 0 failed checks**.
`--suite fast` is the PR subset (V0 + V1 + reconciliation + chaos matrix).

As-built notes and findings:

- **V3 quality battery.** Injected mid-run degradation through the live proxy:
  rollback confirmed with exposure measured and reported (requests exposed +
  sweeps-to-rollback); a ~3% sub-tolerance dip survived **50 deliberate
  peeking sweeps** with zero rollbacks (time-uniform guarantee on the real SQL
  path); a slow-but-correct candidate rolled back on the latency trigger alone
  (real handler sleeps, wide margins); the judge ceiling proven behaviorally on
  three paths (gate refuses automated=True, HTTP apply 409s without approval,
  the learning sweep proposes but never applies). *Scenario-design finding:*
  incumbent texts ≤ 40 chars trip the objective exact-match scoring tier —
  "judge-only" fixtures must use long freeform text.
- **V5 learning integrity — found and fixed two real bandit design flaws.**
  The regret-vs-oracle simulation exposed that the sampled quality floor
  throttled exploration of young candidates twice over: a cold Beta(1,1) draw
  cleared the 0.95 floor only ~5% of the time (cutting the declared budget
  ~20×), and even a *perfect* candidate at n=5 failed the sampled floor ~74%
  of draws (an evidence-accrual catch-22). Fix in `bandit.py::_quality_draw`:
  candidates below `bandit_min_samples` of quality evidence are floor-exempt —
  their real guards are eval clearance at entry, the hard exploration budget,
  and the drift guard; the sampled floor takes over once evidence is
  sufficient. Post-fix regret vs oracle: ~10% at a 10% exploration budget;
  the default 2% budget's slower convergence is reported unasserted as the
  documented cost of no-Thompson-over-savings (variance column remains the
  follow-up). Also proven: priors reconcile exactly to raw decisions (counts,
  quality, savings); a paused proven path is re-proposed with measured
  receipts; a degraded path is marked quality-risk and never re-proposed; no
  phantom evidence.
- **V6 tenancy/concurrency.** Two interleaved tenants: exact per-tenant event
  counts, cross-tenant canary scans clean both directions, control plane
  rejects foreign projects. 30 parallel requests: exactly-once metering and
  decisions. Drift rollback racing live traffic and two sweeps racing on
  separate sessions both converge to consistent state (policy disabled ↔
  recommendation rolled_back); duplicate system-action rows under the
  no-advisory-lock worst case are counted and reported (≤2), not hidden.
  *Harness note:* `create_sim_env(..., sweep_stale=False)` is required for a
  second in-scenario tenant, or the stale sweep deletes the first.
- **V7 replay tapes (capture rate).** Tape 1 (support agent, 40% planted
  duplicates): every duplicate served from cache, **capture rate ≥ 90%** of
  theoretical, stable prefix + downshift both detected. Tape 2 (agent loop, 16
  planted redundant calls in 8 traces): redundancy quantified **exactly**,
  waste within 5% of plant, restructure flagged. Tape 3 (high-variance chat):
  zero savings claimed, zero findings invented. *Interplay finding worth
  knowing:* with the exact cache ON, byte-identical repeats are served at $0
  *before* they can register as agent-loop waste — the detector's niche is
  redundancy the cache can't absorb (tape 2 runs with cache off to plant
  honest ground truth). Detector thresholds (≥1500 avg input tokens) must be
  respected by fixtures.

- **Harness architecture (V0).** The savepoint-isolated unit fixtures wall the
  sync and async DB connections off from each other, so a closed-loop scenario
  can't run under them. The harness (`tests/validation/harness.py`) instead
  runs like production: committed rows namespaced per run (`vsim-<id>` org,
  model keys, canary string), the app's own session factories on both stacks,
  cascade teardown plus a stale-run sweep, SimProvider (stateful scripted mock)
  at the HTTP boundary only, and a content-canary scan over every metadata-only
  store in every scenario. Reports emit as JSON when `VALIDATION_REPORT_DIR` is
  set. Scenarios must seed the global RNG (holdback/canary/bandit draws use it)
  or arm fills flake.
- **V1 golden path** runs the entire lifecycle closed-loop — capture → detect →
  generate → eval (real runner, injected provider boundary) → ChangeRequest
  approval with enforcement ON (apply 409s before approval — proven) → apply →
  canary 50→100 → holdback measurement → priors learned — with the evidence
  chain asserted end to end and planner parity at zero mismatches.
  *Findings:* (1) the published savings fields are quantized independently, so
  `net` vs `gross − costs` can differ by a rounding cent — reconciled within
  ±$0.02 and reported as a metric; the unrounded identity is proven in V2.
  (2) Gap: no operator endpoint tunes a compression policy's holdback (routing
  has one); an ORM surrogate is used and flagged in the report.
- **V2 honest-savings audit**: engine numbers re-derived blind from raw ledger
  rows match to the cent (direct, holdback, measurement cost); holdback
  treatments are never double-counted as direct; control arms never carry
  `saved_usd`; overhead can push net **negative** and is reported as such, not
  clamped; a do-nothing customer gets exact zeros and estimate-labeled
  recommendations only; a mid-experiment 3× price shock cancels across arms.
- **V4 chaos battery — found and fixed two real fail-open gaps.** Injecting a
  *bug* (not an infra failure inside a guard) at the `resolve_route` seam or
  the priors-lookup seam 500'd live requests. Hardened in `router.py`:
  `_safe_outcome_priors` wraps all prior lookups, and the cache probe +
  optimization resolution now degrade to passthrough on any exception (traced
  `resolution_failed_fail_open`). The matrix now proves 10 fault points
  (infra-level and seam-level), poisoned policy params, upstream 500 storms
  (faithful relay, then honestly-labeled breaker 503s), and primary-down →
  fallback-served with zero savings claimed. Evidence-write faults cost
  telemetry only; the loss is measured and reported, never hidden.
  *Note:* trim/compression fault cases run without a routing policy — with one
  active those resolvers never execute and the pass would be vacuous.

## Workstreams (each is one focused session, in this order)

### V0 — Validation harness foundation

The shared machinery everything else uses. No scenario logic yet.

- **Traffic factory** (`tests/validation/factory.py`): seeded-RNG generator of
  realistic workload mixes — routes/features, task metadata headers,
  stable/unstable system prompts, tools/JSON shares, trace IDs with planted
  duplicate calls, per-model token count distributions. Every tape is
  reproducible from its seed.
- **Stateful mock provider**: one MockTransport-backed provider with per-model
  programmable behavior — latency distribution, error rate, token usage,
  response quality profile, and *scheduled behavior changes* ("model B starts
  returning garbage after request 500"). Aligned with seeded `ModelPrice` rows
  so every cost in the run is priceable.
- **Lifecycle driver**: runs N requests through the live ASGI proxy
  interleaved with deterministic sweep invocations (drift, learning-promotion,
  priors refresh, canary promotion) — the scheduler's jobs called explicitly so
  simulated time is controlled.
- **Report emitter**: every scenario produces `validation/reports/<name>.json`
  (invariants checked, reconciliation tables, timings, counts) plus a markdown
  summary. Define the report schema here once.
- **Content canary**: a unique sentinel string planted in every generated
  prompt; a sweep helper that greps all persisted rows (usage_events,
  request_decision_events metadata, prompt_compressions only excepted where
  documented, logs captured via caplog) and fails on any leak. Used by every
  scenario, not just V4.

### V1 — Golden-path closed loop (the engine's story, end to end)

One scripted scenario: fresh project → consented traffic capture → corpus
builds → detection produces recommendations (prompt-cache stability, downshift,
compression) → compression generated (injected generator) + downshift eval
replayed (mock) → verdicts → ChangeRequest approved by a named user → apply →
canary ramps 10→50→100 under healthy signal → holdback accrues → drift sweep
stays quiet → priors sweep learns → bandit (shadow) agrees with the winner →
promotion proposes nothing new (loop is stable).

**Asserts:** every stage's persisted evidence exists and links — artifact →
recommendation → eval run → change request → policy → decision events →
savings attributions — with zero manual state surgery between stages. If any
stage needs the test to fake a transition, that is a product gap; record it.

### V2 — Honest-savings adversarial audit (highest priority with V4)

Scenarios built to manufacture fake money, asserting the engine refuses it:

- **Independent reconciliation**: recompute verified savings from raw
  `usage_events` arithmetic inside the test (not via `savings_measurement`)
  and require exact-to-the-cent agreement with
  `verified = direct + holdback − measurement_cost − overhead`.
- **Double-count traps**: holdback treatment events must not also count as
  direct-measured; cache hits on routed models; a bandit-chosen candidate's
  events counted once, in one experiment pair.
- **Overhead dominance**: a scenario where eval replays + embeddings +
  compression generation cost *more* than gross savings → net reported
  negative, never clamped to zero.
- **Mid-experiment price change**: shift `ModelPrice` during the run → the
  holdback difference cancels it; nothing "strips out" anything.
- **Do-nothing customer**: all levers off → every savings figure is exactly
  0/None; estimates labeled estimated; nothing painted.
- **Control-arm purity**: no control event ever carries `saved_usd`; retries
  (C1) never double-meter.

### V3 — Quality-preservation battery

- **Injected degradation**: candidate goes bad at t=T → measure requests
  exposed and time-to-rollback; report both. Repeat for latency regression and
  SLO breach.
- **Tolerance respected**: a 3% quality dip (below `drift_tolerance`) must NOT
  roll back; a clear breach must. No flappiness across repeated sweeps.
- **Integrated A/A false-positive rate**: healthy identical arms, many
  simulated months of sweeps → rollback rate ≤ the CS alpha (extends the B1
  simulation into the real drift path with real SQL aggregation).
- **Compression mismatch storm**: traffic that edits the prompt → lever no-ops
  100%, zero quality exposure, prefix-restructure recommendation fires.
- **Judge ceiling**: prove behaviorally (not just by code reading) that a
  `needs_human` verdict can never reach auto-apply through any path —
  automation sweep, bandit candidate add, apply endpoint with automated=True.

### V4 — Fail-open / chaos battery

A chaos matrix through the live proxy; the single invariant: **the client
request succeeds (or receives the provider's own faithful error), never hangs,
never 500s from Varsten's optimization machinery.**

Fault injection points: each lever's policy lookup, priors lookup, planner,
artifact load, shared-state store, budget lookup, evidence write, cache
read/write, embedding call; upstream 429/5xx storms and mid-stream cuts;
poisoned policy params (wrong JSON shapes, dangling artifact/recommendation
ids); breaker + retry + fallback interplay. Every scenario also runs the
content-canary sweep and reports the decision-evidence loss rate (gap #3).

### V5 — Learning-loop integrity (no fake learning)

- **Convergence**: candidate A genuinely cheaper-and-good → priors converge on
  measured reality, promotion proposes it, bandit (active, in-sim) shifts share
  within the exploration budget; reconcile every stat the sampler saw to raw
  decision rows — any phantom count fails.
- **Adaptation**: A degrades → drift removes it, decayed priors reflect it,
  bandit abandons it; report time-to-adapt.
- **Bandit regret**: against the mock provider's known ground truth, report
  realized cost vs oracle-best candidate (quantifies gap #5 honestly).
- **Parity audit**: aggregate planner-parity across all scenarios; classify
  every mismatch as expected-shadow-class or bug; bugs fail.

### V6 — Multi-tenant and concurrency hardening

- Two tenants, same models, interleaved: strict scoping of every row type;
  tenant A's canary string and prompt hashes never appear anywhere in tenant
  B's data.
- Races: parallel requests drawing canary/bandit/holdback on one policy; drift
  rollback racing an apply; two sweeps racing (advisory-lock path). Invariants:
  no double activation, no lost rollback, no crossed experiment tags.

### V7 — Replay tapes with ground truth (the capture-rate number)

Three realistic JSONL workload tapes committed as fixtures, each with planted,
known-optimal savings:

1. *Support agent*: stable big system prompt (compressible, cacheable),
   downshiftable classification traffic.
2. *Agentic research loop*: trace IDs, ~12% planted duplicate calls, unstable
   prefixes.
3. *High-variance chat*: little to save; the engine should mostly no-op.

Replay each through the proxy; validate detection findings against the planted
truth (duplicate-call % within tolerance; prefix stability classification
correct; downshift candidate identified) and report **capture rate** =
measured savings achieved / theoretically available — the honest "how good is
it" metric, kept separate from "is it honest."

### V8 — Proof pack and gates

- `scripts/validate_engine.py`: runs the suites, emits
  `validation_report.json` + a markdown proof pack (per scenario: invariants,
  reconciliation tables, rollback timings, parity stats, canary-leak scan,
  capture rates, known-gap quantifications).
- CI: a fast subset (V1 + V2 reconciliation + V4 core faults) on every PR; the
  full battery on demand / nightly.
- **Acceptance gates** (enterprise-ready = all green):
  1. Savings reconciliation exact to the cent in every scenario.
  2. Zero content-canary leaks anywhere, ever.
  3. 100% request success under the entire chaos matrix.
  4. Integrated A/A rollback rate ≤ 6%.
  5. Every applied optimization traceable to gate + (where required) approval.
  6. Injected clear degradation always rolls back; sub-tolerance dips never do.
  7. Every learning statistic reconciles to persisted decisions.
  8. Tape capture-rate and time-to-rollback/adapt reported (no threshold —
     these are the honest performance numbers the proof pack exists to show).

## Sequencing and sizing

V0 first (everything depends on it), then V1, then V2 and V4 (money and
safety — the two ways to lose a customer), then V3, V5, V6, V7, V8. Each
workstream is one focused session with its own tests landing green before the
next; V8 rolls up continuously as scenarios land. Where a scenario finds a
real defect, fix it in the same slice only if small; otherwise file it in the
implementation plan's follow-ups with the failing scenario kept red-listed in
the report (an honest proof pack shows known reds).
