# Palantir Foundry/AIP — Minimum-Loop Ontology & Action Design

Scope: the §11 "smallest credible" build from the Varsten + Palantir Build Readiness Dossier.
This document specifies the Foundry Ontology objects, their properties, links, the user
Actions, and the AIP brief for one governed decision loop:

> A platform/FinOps lead reviews a proposed model-routing change, sees the eval
> evidence, takes an approve/reject Action that writes back state, and the system
> records who decided what and why in an immutable audit trail.

It maps every field to Varsten's real schema and classifies each as **EXISTS**,
**DERIVED**, **DEMO-ONLY**, or **SYNTHETIC**. The next deliverable (synthetic dataset
spec) is generated to satisfy this ontology, not the reverse.

---

## 0. The key conceptual gap this build fills

> **Update:** the gap this section describes has since been closed natively. `ChangeRequest`
> now exists as a real Varsten object (`app/models/governance.py`, migration `f8a9b0c1d2e3`),
> with exactly the state machine and evidence-bundle shape sketched below, proposed
> automatically off a completed eval and enforced via a global/per-org flag. This document's
> premise shifts accordingly: a Foundry integration would now **sync an existing native
> object** into the Foundry ontology, not introduce governance where none existed. The
> object inventory, property mappings, and Action design below are still a reasonable spec
> for that sync — re-classify `ChangeRequest`'s own fields as **EXISTS** rather than
> **DEMO-ONLY** before treating this as a build plan. See `app/engine/governance.py` for the
> native lifecycle implementation.

Varsten today has **no governance object**. The "approval" of a routing change is
implicit and spread across four tables:

- `Recommendation.status` flips `open` → `applied` via one PATCH
  (`backend/app/api/v1/product_sections.py:943`).
- An `EvalRun` gates it with a `verdict` (`backend/app/models/eval.py:152`).
- A `ProxyPolicy` row is activated to execute it (`backend/app/proxy/routing.py:138`).
- A `RecommendationAction` row logs that something happened
  (`backend/app/models/engine.py:49`).

There is no single object that says *"this specific change is awaiting a named human's
decision, here is the evidence bundle, here is who approved it and the rationale they
signed."* That object is **`ChangeRequest`**, and it is the spine of the Palantir build.
It is net-new governance state that wraps Varsten's existing execution + evidence rows.

This is also why the build is honest about the Foundry↔Varsten boundary: Foundry owns
the **governance/decision** layer (ChangeRequest + AuditEvent + Actions). Varsten keeps
the **data plane and evidence generation** (proxy, eval runner, holdback math). We are
not duplicating Varsten's dashboard.

---

## 1. Object inventory (minimum loop)

| Ontology object | Role in the loop | Backing Varsten table(s) |
|---|---|---|
| **ChangeRequest** | The thing being decided. Net-new governance wrapper. | none (new) — composed from `recommendations`, `eval_runs`, `proxy_policies`, `recommendation_actions` |
| **EvalRun** | The safety evidence the decision rests on. | `eval_runs` (`models/eval.py:107`) |
| **AuditEvent** | The immutable record each Action writes. | `audit_events` (`models/audit.py:32`) |
| **RoutingPolicy** *(context)* | What actually changes when approved. | `proxy_policies` (`models/proxy_policy.py:50`) |
| **Recommendation** *(context)* | Where the proposed change originates. | `recommendations` (`models/recommendation.py:12`) |
| **Workload / Route** *(context, lightweight)* | Blast-radius target (model + feature + customers affected). | derived from `usage_events` + `recommendation.related_*` |

Only the first three are modeled deeply with Actions. RoutingPolicy, Recommendation, and
Workload are linked context so the reviewer can see provenance and blast radius. Canary,
Incident, and Rollback are explicitly **out of the minimum loop** (they belong to the §12
stretch).

---

## 2. `ChangeRequest` (primary object)

The object a reviewer opens, reads, and acts on. One ChangeRequest = one proposed routing
change (incumbent model → candidate model on a route) awaiting disposition.

### 2.1 State machine

```
proposed ──approveChange──▶ approved ──(Varsten activates ProxyPolicy)──▶ active
   │
   └────────rejectChange──▶ rejected
```

`proposed` is created by the system when a `Recommendation` of a routing lever
(`model_downshift` | `smart_routing`) has a completed `EvalRun`. `approved`/`rejected` are
terminal for the minimum loop. (Stretch adds `active → rolled_back` via Incident.)

### 2.2 Properties

Provenance legend: **EXISTS** = already a Varsten column, copy/sync it. **DERIVED** =
computed from existing Varsten data at sync time. **DEMO-ONLY** = governance field that
does not exist in Varsten yet; this build introduces it (a real future Varsten migration
would add it). **SYNTHETIC** = fabricated/anonymized for the demo dataset.

| Property | Type | Provenance | Source / derivation |
|---|---|---|---|
| `change_request_id` | String (PK) | DEMO-ONLY | Foundry-generated; 1:1 with a `(recommendation_id, eval_run_id)` pair |
| `title` | String | EXISTS | `recommendations.title` |
| `lever` | String | EXISTS | `recommendations.lever` (`model_downshift`/`smart_routing`; `levers.py`) |
| `incumbent_model` | String | EXISTS | `recommendations.related_model` = `eval_runs.incumbent_model` |
| `candidate_model` | String | EXISTS | `eval_runs.candidate_model` (also `proxy_policies.params.candidate_model`) |
| `route_key` | String | EXISTS | `eval_runs.route_key` (Phase-1 = the model; generalizes to feature/route) |
| `feature` | String | EXISTS | `recommendations.related_feature` |
| `environment` | String | EXISTS | `recommendations.related_environment` |
| `estimated_monthly_savings_usd` | Decimal | EXISTS | `recommendations.estimated_monthly_savings_usd` |
| `measured_cost_delta_usd` | Decimal | EXISTS | `eval_runs.cost_delta_usd` (replay-measured, stronger than the estimate) |
| `monthly_request_volume` | Integer | EXISTS | `recommendations.monthly_request_volume` |
| `risk_level` | String | EXISTS | `recommendations.risk_level` (`low`/`medium`/`high`) |
| `eval_verdict` | String | EXISTS | `eval_runs.verdict` (`safe`/`needs_human`/`unsafe`/`insufficient_data`) |
| `quality_score_delta` | Decimal | EXISTS | `eval_runs.score_delta` (normalized [-1,1]) |
| `quality_ci_low` / `quality_ci_high` | Decimal | EXISTS | `eval_runs.score_delta_ci_low` / `_ci_high` |
| `scorer_type` | String | EXISTS | `eval_runs.scorer_type` (`objective`/`judge`/`golden`/`mixed`) |
| `affected_customer_count` | Integer | DERIVED | `COUNT(DISTINCT customer_id)` over `usage_events` matching the route this period |
| `affected_customer_names` | String[] | SYNTHETIC | anonymized customer labels (e.g. "Customer A"); never real names |
| `blast_radius_request_share` | Decimal | DERIVED | route's requests ÷ project requests this period (from `usage_events`) |
| `status` | String | DEMO-ONLY | the state machine above; not a Varsten column (Varsten uses `recommendations.status` for a coarser lifecycle) |
| `auto_eligible` | Boolean | DERIVED | `eval_verdict == 'safe'` AND scorer is objective-family (mirrors `eval/runner.py:261`) |
| `requires_human` | Boolean | DERIVED | `eval_verdict == 'needs_human'` OR scorer involves judge (mirrors `runner.py:249`) |
| `requested_at` | Timestamp | EXISTS | `eval_runs.completed_at` (proposal exists once the eval finishes) |
| `approver_email` | String | DEMO-ONLY | set by `approveChange`/`rejectChange`; analogous to `recommendation_actions.actor_user_id` but governance-grade |
| `decision` | String | DEMO-ONLY | `approved` / `rejected`; written by the Action |
| `decision_rationale` | String | DEMO-ONLY | the human's edited rationale (seeded by the AIP brief) |
| `rollout_mode` | String | DEMO-ONLY | minimum loop: `full`. (Stretch: `canary_10pct`.) |
| `decided_at` | Timestamp | DEMO-ONLY | written by the Action |
| `ai_brief_markdown` | String | DERIVED | output of the AIP brief (see §6); editable before sign |

### 2.3 Links

- `ChangeRequest → EvalRun` (1:1) — the evidence. FK: `eval_runs.recommendation_id` ties
  back; in Foundry, link on `change_request.eval_run_id`.
- `ChangeRequest → RoutingPolicy` (0..1) — what activates on approve. FK in Varsten:
  `proxy_policies.source_recommendation_id`.
- `ChangeRequest → Recommendation` (1:1) — origin. FK: `recommendations.id`.
- `ChangeRequest → AuditEvent` (1:many) — every Action appends one.
- `ChangeRequest → Workload` (1:1) — blast-radius context.

---

## 3. `EvalRun` (evidence object)

A near-direct mirror of `backend/app/models/eval.py:107`. **All properties EXISTS** — this
object is why the build is credible; Varsten already produces rigorous eval verdicts.

| Property | Type | Provenance | Source |
|---|---|---|---|
| `eval_run_id` | String (PK) | EXISTS | `eval_runs.id` |
| `incumbent_model` / `candidate_model` | String | EXISTS | same columns |
| `route_key`, `lever` | String | EXISTS | same |
| `status` | String | EXISTS | `pending`/`running`/`completed`/`failed` |
| `verdict` | String | EXISTS | `safe`/`needs_human`/`unsafe`/`insufficient_data` |
| `scorer_type` | String | EXISTS | `objective`/`judge`/`golden`/`mixed` |
| `sample_count`, `win_count`, `tie_count`, `loss_count` | Integer | EXISTS | same |
| `objective_pass_rate` | Decimal | EXISTS | `eval_runs.objective_pass_rate` |
| `score_delta`, `score_delta_ci_low`, `score_delta_ci_high` | Decimal | EXISTS | same |
| `cost_delta_usd` | Decimal | EXISTS | replay-measured monthly delta |
| `notes` | String | EXISTS | human-readable verdict reason from `runner.py:_finalize` |
| `completed_at` | Timestamp | EXISTS | same |

Linked child (optional in minimum loop, nice for drill-down): **EvalSampleResult**
(`eval_runs` → `eval_sample_results`, `models/eval.py:158`) — per-sample `scorer`,
`objective_pass`, `judge_winner`, `score`, `candidate_cost_usd`, `incumbent_cost_usd`. All
EXISTS. Include only if the demo has time to show "click into the evidence." **Do not
upload `candidate_response` / `incumbent_response` / `request_messages` content** — those
are the documented content exceptions and are not needed for the decision; bring counts
and scores only.

---

## 4. `AuditEvent` (record object)

Mirror of `backend/app/models/audit.py:32`. The minimum loop's Actions each append one.
**Schema EXISTS**; this build adds new `action` constants (Varsten's existing constants
are plan/provider-key/billing only — see `audit.py:25`, which is exactly the §6 "sparse
coverage" blocker this project demonstrates fixing).

| Property | Type | Provenance | Source |
|---|---|---|---|
| `audit_event_id` | String (PK) | EXISTS | `audit_events.id` |
| `action` | String | DEMO-ONLY (new constants) | e.g. `routing_change.approved`, `routing_change.rejected` — extends `audit.py` constants |
| `actor_email` | String | EXISTS | denormalized actor (survives user deletion, per `audit.py:55`) |
| `target_type` | String | EXISTS | `"change_request"` |
| `target_id` | String | EXISTS | `change_request_id` |
| `before` / `after` | JSON | EXISTS | status + decision snapshot (e.g. `{status: proposed}` → `{status: approved, rollout_mode: full}`) |
| `details` | JSON | EXISTS | `{eval_verdict, measured_cost_delta_usd, rationale_excerpt}` — **never secrets** |
| `source_ip` | String | EXISTS | best-effort, from `core/audit.py:client_ip` |
| `created_at` | Timestamp | EXISTS | append time |

Proposed new action constants for this loop (would be added to `audit.py` in a real
Varsten change):
`routing_change.proposed`, `routing_change.approved`, `routing_change.rejected`.

---

## 5. Actions (the graded core)

Three Actions. Each is a write-back that transitions object state **and** appends an
AuditEvent in the same logical commit (mirrors `core/audit.py`'s "added to the caller's
session; the caller's commit persists it atomically").

### 5.1 `approveChange`
- **Actor:** platform/FinOps lead (or, at sign-off, finance).
- **Precondition:** `ChangeRequest.status == 'proposed'` AND `eval_verdict != 'unsafe'`
  AND `eval_verdict != 'insufficient_data'`. (An `unsafe` verdict is non-approvable —
  mirrors `runner.py` blocking; surface it as a disabled action with the reason.)
- **Inputs:** `decision_rationale` (pre-filled from `ai_brief_markdown`, editable),
  `rollout_mode` (minimum loop fixed to `full`).
- **Writes:**
  - `ChangeRequest.status → 'approved'`, `decision = 'approved'`, `approver_email`,
    `decided_at`, persisted `decision_rationale`.
  - (Represents, in Varsten terms) `recommendations.status → 'applied'`,
    `proxy_policies.enabled → true` + `activated_at` + `source_recommendation_id`
    (the real activation path is `routing.activate_rule`, `routing.py:138`).
  - One `AuditEvent(action='routing_change.approved', before, after, details)`.
- **Maps to real endpoint:** `PATCH /v1/engine/recommendations/{id}` with `status=applied`
  (`product_sections.py:943`) + policy activation. The Foundry Action is the **governed**
  version of that PATCH, adding approver identity, rationale, and the audit row Varsten
  does not currently write for this transition.

### 5.2 `rejectChange`
- **Precondition:** `status == 'proposed'`.
- **Inputs:** `decision_rationale` (required — why rejected).
- **Writes:** `status → 'rejected'`, `decision='rejected'`, `approver_email`, `decided_at`;
  `AuditEvent(action='routing_change.rejected')`. In Varsten terms: `recommendations.status
  → 'dismissed'` and any sourced policy stays disabled (`deactivate_rules_for_recommendation`,
  `routing.py:183`).

### 5.3 `recordRolloutDecision` (audit-only confirmation)
- A lightweight Action the reviewer can invoke to attach a note/disposition to an already
  decided ChangeRequest without changing routing state (e.g. "monitoring for 7 days,"
  "expand later"). Pure governance/audit. Demonstrates that **not every Action mutates the
  data plane** — some only write the record. Writes only an `AuditEvent` (no state change).
  This keeps the audit-trail story rich in the 4-minute demo without building the canary
  machinery.

> Why these three: they show (1) a consequential mutate-the-system action, (2) its
> negative counterpart, and (3) a pure record action — covering the full "decision +
> write-back + audit" surface the assignment grades, with zero canary/incident scope.

---

## 6. AIP brief: the "Change Risk Brief"

One AIP function. Input is the ChangeRequest's evidence; output is `ai_brief_markdown`,
which seeds (does not replace) the human's `decision_rationale`. AIP is doing
**judgment-shaped drafting**, not arithmetic — this is the line to defend on camera.

### 6.1 Inputs (all already on the object, no content)
`title`, `lever`, `incumbent_model`, `candidate_model`, `route_key`, `feature`,
`eval_verdict`, `scorer_type`, `score_delta` + CI, `objective_pass_rate`,
`win/tie/loss_count`, `sample_count`, `estimated_monthly_savings_usd`,
`measured_cost_delta_usd`, `monthly_request_volume`, `affected_customer_count`,
`blast_radius_request_share`, `risk_level`.

### 6.2 Prompt contract (sketch)
System: *"You are drafting a one-screen risk brief for a platform engineer deciding
whether to route production traffic from `{incumbent_model}` to `{candidate_model}` on
route `{route_key}`. You are given measured evidence only; never invent numbers. Be blunt
about residual risk. End with a recommended disposition the human will edit and sign."*

Required output sections (Markdown):
1. **What changes** — one sentence, incumbent → candidate on which route/feature.
2. **Safety evidence** — verdict in plain language, `scorer_type`, win/loss, score delta
   with its CI; explicitly state when the scorer is judge-based and therefore
   approve-only, never auto (mirrors the `runner.py` verdict ladder).
3. **Money** — estimated vs **measured** monthly delta; flag if they diverge.
4. **Blast radius** — `affected_customer_count`, request share, feature.
5. **Residual risk & recommendation** — one paragraph + a suggested
   approve/reject/approve-as-canary disposition.

### 6.3 Guardrail
The brief is advisory text only. It **cannot** call `approveChange`. A human must invoke
the Action. This is the explicit "AI assists, human owns the decision" boundary.

---

## 7. Field provenance summary (what to build where)

- **EXISTS (copy from Varsten / synthetic mirror of the real column):** every EvalRun
  field, every AuditEvent schema field, and the bulk of ChangeRequest's evidence/economics
  fields. These prove the build sits on Varsten's real measurement IP.
- **DERIVED (compute at dataset-build time):** `affected_customer_count`,
  `blast_radius_request_share`, `auto_eligible`, `requires_human` — simple aggregates over
  the synthetic `usage_events`.
- **DEMO-ONLY (governance fields this build introduces):** the entire ChangeRequest
  lifecycle layer — `status`, `approver_email`, `decision`, `decision_rationale`,
  `rollout_mode`, `decided_at`, `ai_brief_markdown` — plus the new `audit_events.action`
  constants. **This is the deliberate product gap the project demonstrates closing**, and
  it should be called out as such in the demo ("Varsten generates the evidence; Foundry
  adds the governed decision and the audit record it's missing today").
- **SYNTHETIC / ANONYMIZED:** all customer identifiers (`affected_customer_names`,
  `related_customer_id`), org/project names, and the underlying usage rows. No real tenant
  data, no prompt/response content, ever.

---

## 8. Out of scope for the minimum loop (do not build yet)

- Canary/Rollout ramp object and `advanceCanary`/`haltAndRollback` Actions (§12 stretch).
- Incident object + AIP root-cause draft (§12 stretch).
- Finance `signOffSavings` on holdback-measured savings (§12 stretch; pulls
  `savings_attributions` + `proxy/experiment.py`).
- EvalSampleResult drill-down (optional; include only if time).
- Any data-plane / proxy / cache / pricing logic — stays in Varsten.

---

## 9. Open items feeding the next deliverable (synthetic dataset spec)

The dataset must produce, at minimum, **three ChangeRequests that exercise the verdict
ladder**: one `safe`/objective (auto-eligible but still shown for approval), one
`needs_human`/judge (the hero of the demo — AIP brief + human approve), and one `unsafe`
(approve disabled, shows the gate has teeth). Each needs a coherent EvalRun (matching
win/loss vs score_delta vs verdict per `runner.py` logic), a believable
`measured_cost_delta_usd` vs `estimated_monthly_savings_usd`, and a blast radius
(distinct synthetic customers on the route). Generate dataset to fit this ontology.
