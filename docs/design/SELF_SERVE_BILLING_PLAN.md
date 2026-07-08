# Self-serve onboarding + billing: implementation plan

Status: IMPLEMENTED (backend + frontend wiring + tests). Scope: make the advertised
14-day Optimize trial real, reliable, and upgradeable end to end. No org invites,
no plan selection UI, no enterprise flows, no gain-share Stripe metering, no sidecar.

What shipped, against the plan below:
- Migration `b3c4d5e6f7a8`: `trial_started_at`, `stripe_customer_id`,
  `stripe_subscription_id`, `integration_snippet_viewed_at`, `dashboard_entered_at`;
  `SUBSCRIPTION_EXPIRED` status. Server defaults left free/active.
- `app/billing_lifecycle.py`: the single home for every billing-state transition
  (start_trial, activate_performance, expire_trial, mark_past_due, cancel,
  maybe_expire, sweep_expired_trials). Used by signup, entitlements, sweep, Stripe.
- `app/provisioning.py`: signup creates an Optimize-trialing org + default
  Production project (wired into `/auth/sync`; `create_organization` gets the project
  but no fresh trial, to avoid trial farming).
- Entitlements patched (not rewritten) for expired/canceled/past_due + lazy read-time
  expiry; the proxy hot path stays read-only and fail-open.
- `trial-sweep` scheduler job (hourly) downgrades unpaid elapsed trials.
- Onboarding `POST /onboarding/event` + 5-item record-driven checklist; OnboardingView
  fires snippet_viewed on copy and dashboard_entered on finish.
- Stripe setup-mode `app/stripe_billing.py`, org-level checkout/portal endpoints,
  signature-verified idempotent `/webhooks/stripe`, behind `SELF_SERVE_BILLING_ENABLED`;
  UpgradeView has the checkout button. Config gated in `validate_production`.
- Tests: `test_trials.py`, `test_stripe_billing.py`, additions to `test_onboarding.py`
  and `test_provider_connections.py`. Full suite 537 passed / 3 skipped.

Deployment note: for self-serve key connect outside AWS set
`PROVIDER_KEY_BACKEND=localdb` + `PROVIDER_KEY_LOCAL_ENCRYPTION_KEY`; for upgrade set
the Stripe keys and `SELF_SERVE_BILLING_ENABLED=true`. See `.env.example`.

Original plan follows.

## 1. Where the codebase already is (so we do not rebuild it)

A lot of this is built. The honest gap list is short.

Already done:
- `Organization` has `plan_tier` (free|performance), `subscription_status`
  (trialing|active|past_due|canceled), `trial_ends_at`, `plan_effective_at`,
  `onboarding_completed_at`, `gain_share_percent`, `monthly_fee_floor_usd`
  (`backend/app/models/tenant.py`).
- Entitlements already derive observe-only from plan + status + trial dates,
  including a trial-expired and a monthly-quota path, with a short-TTL hot-path
  cache and fail-open default (`backend/app/auth/entitlements.py`).
- Provider-key connect already validates OpenAI/Anthropic/Gemini keys, encrypts and
  stores them (Secrets Manager in prod, `localdb` Fernet for self-serve dev, `env`
  legacy), and records a `provider_connections` row with status
  (`backend/app/api/v1/projects.py`, `backend/app/proxy/keys.py`,
  `backend/app/proxy/provider_validation.py`).
- Onboarding status is record-derived: has_api_key, has_provider_connection,
  first_request all computed from real tables (`backend/app/api/v1/onboarding.py`).
- Customer billing reads + operator billing mutations exist
  (`backend/app/api/v1/billing.py`, `backend/app/api/v1/operator.py`).
- Frontend funnel exists: marketing "Start free" -> `app.varsten.ai/start` ->
  `StartRedirect` -> `/onboarding` or `/dashboard`; `OnboardingView` has the 4
  setup steps; `UpgradeView` shows trial/quota.
- Scheduler framework with advisory-lock multi-instance safety
  (`backend/app/scheduler.py`).

The real gaps:
1. New orgs are created Free + active with **no trial and no project**. The trial is
   never started, so the whole "14-day Optimize trial" is inert today.
2. No `trial_started_at`, `stripe_customer_id`, `stripe_subscription_id` columns; no
   `expired` subscription status.
3. No Stripe at all. Upgrade is a `mailto:` link.
4. No durable trial-expiry transition (read-time gating works, but the row never
   flips to Free/expired).
5. Onboarding checklist is missing two non-derivable items (snippet viewed,
   dashboard entered).

## 2. Naming decision

Keep the existing `plan_tier` / `subscription_status` column names. The task lists
them as `plan` / `status`; renaming would churn ~15 call sites and two migrations for
no behavioral gain. We add only the genuinely missing columns. Mapping:

| task field          | actual column          |
|---------------------|------------------------|
| plan                | `plan_tier`            |
| status              | `subscription_status`  |
| trial_started_at    | NEW `trial_started_at` |
| trial_ends_at       | exists                 |
| stripe_customer_id  | NEW                    |
| stripe_subscription_id | NEW                 |

## 3. Backend changes

### 3.1 Schema (priority 1)
`backend/app/models/tenant.py` + new Alembic migration:
- Add `trial_started_at: datetime | None`.
- Add `stripe_customer_id: str | None` (String(64), indexed, unique-nullable).
- Add `stripe_subscription_id: str | None` (String(64)).
- Add `SUBSCRIPTION_EXPIRED = "expired"` to `SUBSCRIPTION_STATUSES`.
- Add onboarding-event timestamps (see 3.6): `integration_snippet_viewed_at`,
  `dashboard_entered_at` (both `datetime | None`).

Do **not** change the server defaults for `plan_tier`/`subscription_status` (leaving
them free/active). The trial is set explicitly in the signup path so demo/seeded and
operator-created orgs are unaffected. Migration is additive only; no backfill.

### 3.2 Signup provisions a trialing Optimize org + default project (priorities 2, 3)
New shared helper, e.g. `app/auth/provisioning.py::provision_new_organization(db, name) -> (Organization, Project)`:
- Create org with `plan_tier=performance`, `subscription_status=trialing`,
  `trial_started_at=now`, `trial_ends_at=now + settings.free_trial_days`.
- Create one `Project(name="Production")` under it.
- Return both.

Wire it into `sync_user` (`backend/app/api/v1/auth.py`) on the brand-new-user branch,
replacing the bare `Organization(name=...)` create. Also use it in
`create_organization` (`organizations.py`) so any new workspace gets a Production
project (keeps the "never ask the user to create a project" invariant). The frontend
`bootstrapAccount` already calls `api.projects` after sync and picks the active
project, so a Production project existing immediately fixes the "activeProjectId is
null -> Create API key disabled" dead end.

Idempotency: `sync_user` already guards on existing user/sub; provisioning only runs
in the new-user branch, so re-sync never creates a second org/project.

### 3.3 Entitlements (priority 4)
`backend/app/auth/entitlements.py`:
- Treat `subscription_status in {expired, canceled, past_due}` as observe-only with a
  clear reason, in addition to the existing free/trial-expired/quota paths.
- Keep the existing rule that `trialing + performance` unlocks until `trial_ends_at`;
  with 3.2 it now actually fires.
- `is_performance` stays correct: performance + not observe_only -> true during trial,
  false after expiry. This is the read-time defense-in-depth that holds even before
  the sweep flips the row.
- Reflect `trial_started_at` in `EntitlementState` if useful for the UI countdown.

### 3.4 Stripe upgrade (priority 6)
Add `stripe` to `backend/pyproject.toml`. New module `app/billing_stripe.py`. New
config in `app/core/config.py`: `stripe_secret_key`, `stripe_webhook_secret`,
`stripe_publishable_key`, `stripe_price_id` (only if subscription mode), and
`billing_success_url` / `billing_cancel_url`. Gate these in `validate_production`
(require secret + webhook secret when `app_env=production`).

Customer-facing, session-auth, org-scoped endpoints (extend `api/v1/billing.py`):
- `POST /admin/billing/checkout-session` -> ensure a `stripe_customer_id` (create on
  first use, persist), create a Checkout Session, return `{ url }`.
- `POST /admin/billing/portal-session` -> Customer Portal `{ url }` for managing the
  payment method / canceling.

Webhook (new tiny router, unauthenticated but **signature-verified** with
`stripe_webhook_secret`, mounted outside the auth-required group):
- `POST /webhooks/stripe`. Verify signature, parse event, look up org by
  `stripe_customer_id`. Idempotent. Handle:
  - checkout completed / `customer.subscription.created|updated` active ->
    `plan_tier=performance`, `subscription_status=active`, store
    `stripe_subscription_id`, `plan_effective_at=now`, `invalidate_plan_tier(org.id)`.
  - `customer.subscription.deleted` / canceled -> downgrade to
    `plan_tier=free`, `subscription_status=canceled`, invalidate.
  - `invoice.payment_failed` -> `subscription_status=past_due` (observe-only), invalidate.

**Open decision (flagged):** what does "activate Optimize" mean in Stripe?
- (A, recommended) Checkout in `mode=setup`: collect a payment method, mark the org
  active Optimize on completion. Matches the gain-share pricing model (you bill
  verified savings via the existing `Invoice` flow, not a fixed monthly Stripe
  charge), and honors "do not add advanced gain-share billing calculations."
- (B) Checkout in `mode=subscription` against a fixed `stripe_price_id`. Simpler
  Stripe lifecycle webhooks, but it commits to a flat price that contradicts the
  product's percentage-of-savings pricing.
Recommend A. Either way the webhook -> entitlement transition is identical.

Stripe is a recurring-cost vendor with lock-in. Flagging per project rules. It is the
simplest professional self-serve payment path and is justified for a real client, but
the secret keys must live in the platform secret store, never the repo.

### 3.5 Trial expiration sweep (priority 7)
New scheduler job `trial-sweep` (`backend/app/scheduler.py` + a function in
`app/billing.py` or a new `app/trials.py`), interval `settings.trial_sweep_interval_seconds`
(default ~hourly), under the same advisory lock as the other sweeps:
- Find orgs where `subscription_status=trialing AND trial_ends_at <= now AND
  stripe_subscription_id IS NULL`.
- Set `plan_tier=free`, `subscription_status=expired`, `invalidate_plan_tier(org.id)`.
- Required behavior, all already structurally true and re-asserted by tests:
  traffic keeps flowing (proxy is fail-open; observe-only never blocks), optimizations
  lock (observe-only gating), metering + dashboard + recommendations continue (they
  are not Optimize-gated).

### 3.6 Onboarding checklist, fully record-driven (priority 8)
Two of the five items are not derivable, so persist them on the org (3.1 columns):
- `integration_snippet_viewed_at`, `dashboard_entered_at`.
New endpoint `POST /onboarding/event { event: "snippet_viewed" | "dashboard_entered" }`
(project-scoped via `resolve_project`), first-write-wins, idempotent. Extend
`GET /onboarding/status` to return the full 5-item checklist as booleans:
`has_api_key`, `has_provider_connection`, `integration_snippet_viewed`,
`first_request.seen`, `dashboard_entered`. The first three of these already exist or
become trivial; the two new ones read the new columns.

## 4. Frontend changes
- `OnboardingView.tsx`: call `POST /onboarding/event {snippet_viewed}` from the
  snippet `CopyButton`; call `{dashboard_entered}` in `finish()` before routing to
  `/dashboard`. Render the checklist from the status response.
- `UpgradeView.tsx` / `app/admin/billing-security/page.tsx`: replace the `mailto:`
  CTA with an "Add payment method / Activate Optimize" button that POSTs to
  `checkout-session` and redirects to the returned Stripe URL; show "Manage billing"
  (portal) once `subscription_status=active`; show a trial countdown from
  `trial_ends_at`. Keep the existing observe-only / paused messaging for the expired
  state.
- Optional: a slim trial-status banner driven by the entitlements endpoint.

## 5. Provider-key connection (priority 5) — mostly verification
The connect path already validates and vaults all three providers. The only work:
- Ensure self-serve-capable deployments set `provider_key_backend=localdb` (or
  `secretsmanager`) plus `PROVIDER_KEY_LOCAL_ENCRYPTION_KEY`, so connect succeeds
  without the "manual setup required" 409. Document in `.env.example` / README.
- Verify (test) that anthropic and gemini probes succeed end to end and that a
  successful connect flips the onboarding `has_provider_connection`. No new code
  expected beyond config/docs.

## 6. Tests (priority 9)
- `test_session_auth` / new `test_provisioning`: new signup creates an Optimize
  **trialing** org with `trial_started_at`/`trial_ends_at` set and exactly one
  Production project.
- `test_entitlements`: a trialing Optimize org gets Optimize entitlements
  (observe_only=False, features unlocked) until `trial_ends_at`; past `trial_ends_at`
  it is observe-only with reason `trial_expired`.
- new `test_trials`: the sweep flips an unpaid expired trial to Free/`expired`, leaves
  a paid (`stripe_subscription_id` set) trial alone, and an expired org keeps metering
  + recommendations while levers are locked.
- new `test_stripe_billing`: webhook with a valid signature for an active subscription
  moves the org to active Optimize and stores `stripe_subscription_id`; invalid
  signature is rejected; cancel/payment_failed transitions downgrade; handler is
  idempotent. Stripe SDK calls mocked; no network.
- `test_provider_connections`: a successful connect updates onboarding status to
  `has_provider_connection=true`.
- `test_onboarding`: first proxied request flips `first_request.seen`; the new event
  endpoint flips `integration_snippet_viewed` and `dashboard_entered`.

## 7. Build order
1. Migration + model fields (3.1).
2. Provisioning helper + wire into sync/create-org (3.2) + tests.
3. Entitlement status handling for expired/canceled/past_due (3.3) + tests.
4. Trial sweep job (3.5) + tests.
5. Onboarding event endpoint + status checklist (3.6) + frontend wiring + tests.
6. Stripe module, endpoints, webhook, config (3.4) + tests + frontend upgrade button.
7. Provider-key config/docs verification (5).

Steps 1-5 make the trial real and reliable with zero new vendor. Step 6 makes it
self-serve-upgradeable. They can ship in that order; the trial is honest and usable
after step 5 even before Stripe lands.

## 8. Risks / things to watch
- Tenancy: every new endpoint (checkout, portal, onboarding event) must stay
  org-scoped through `resolve_project` / membership. The webhook is the one
  unauthenticated route and must be signature-verified and idempotent or it becomes a
  plan-escalation hole.
- Do not block traffic on expiry. The sweep and entitlement changes only flip
  observe-only; the proxy stays fail-open.
- Server defaults stay free/active; the trial is opt-in per signup path so seeded/demo
  and operator orgs do not silently become billable Optimize trials.
- Stripe keys are secrets: platform secret store only, gated in `validate_production`.
