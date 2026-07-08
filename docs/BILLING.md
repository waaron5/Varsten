# Billing and Commercialization

How Varsten charges, and what exists today vs what comes later. The model is
gain-share: Varsten takes at most 25% of **verified** savings. A monthly floor can
exist in the config, but it is always capped by the same 25% maximum, so the fee
is below verified savings whenever verified savings are positive.

## The pricing model

- **Base:** verified (measured) savings only — direct measured (cache/batch/route
  avoided cost) plus holdback-measured A/B. **Estimated savings never bill.** This
  is the same number Proof presents as "verified", and the reason Phase 3's savings
  honesty had to land before billing.
- **Fee:** `gain_share_percent` of verified savings (default 25%, per-org), capped
  at 25%. We never charge more than 25% of verified savings.
- **Floor:** an optional `monthly_fee_floor_usd`. The floor can lift a small fee,
  but is also **capped at 25% of verified savings**, so `fee < verified_savings`
  whenever verified savings are positive.

```
effective_rate = min(gain_share_percent, 0.25)
fee = min( max(verified_savings * effective_rate, monthly_fee_floor_usd),
           verified_savings * 0.25 )
net = verified_savings - fee
```

Per-org `gain_share_percent` and `monthly_fee_floor_usd` live on the organization.
Operator writes reject rates above 25%, billing clamps stale rows defensively, and
each invoice **snapshots** the effective rate and floor it used, so changing the
config never rewrites a historical invoice.

## How to describe measurement publicly

Avoid claiming that every dollar is measured by "counterfactual replay." That is
too broad for the current product. Verified savings come from:

- direct ledger evidence for cache, batch, and routing/downshift avoided cost;
- live randomized holdback A/B where traffic volume supports measurement;
- explicit subtraction of measurement and optimization overhead before billing.

Safer public wording:

> Every billable dollar comes from verified ledger evidence: direct avoided
> provider cost where the counterfactual is explicit, plus live holdback A/B
> where Varsten measures optimized traffic against an unoptimized control.
> Estimates stay separate and never become billable savings.

## What exists today (manual)

- **Subscription state on the org:** `plan_tier` (entitlement: free/performance),
  `subscription_status` (trialing/active/past_due/canceled), `plan_effective_at`,
  `trial_ends_at`. No more hand-editing the database to change a plan or trial.
- **Operator endpoints** (gated to `operator_admin_emails`, audited):
  - `POST /v1/operator/organizations/{id}/plan` — entitlement tier (sets effective date).
  - `POST /v1/operator/organizations/{id}/billing` — gain-share %, floor, subscription status, trial end.
  - `POST /v1/operator/organizations/{id}/invoices` — generate/refresh the draft invoice for a period (default: last full month).
- **Customer read endpoints:** `GET /v1/admin/billing` (plan, subscription, config, a live preview of this month's verified savings + fee), `GET /v1/admin/billing/invoices` (history).
- **Invoices** are a durable record (`invoices` table) computed from verified
  savings: verified amount, effective rate, floor, fee, net, status (draft → finalized →
  sent → paid). Generation is manual; **there is no auto-charge**.

This is deliberately manual: invoice off the verified number, send it, get paid.
It is honest and it works for the first customers without taking a payment
dependency.

## What comes before hands-off self-serve (Stripe)

- Stripe Billing to actually collect payment after the manually reviewed invoice
  flow is proven.
- A Stripe webhook drives `subscription_status` (so it is no longer operator-set).
- Self-serve upgrade/downgrade in the dashboard, calling the same plan-change path
  (which already invalidates the proxy's tier cache).

Plan tier remains the single source of truth for entitlement; Stripe drives the
subscription lifecycle around it.

## What comes before automated gain-share

Do **not** automate gain-share billing until holdback-measured savings have real
production signal. Billing a customer automatically on a number that is still
mostly direct-measured cache savings (true) mixed with thin holdback data (noisy)
is the most dangerous thing the product could do. The sequence is:

1. Manual invoicing off verified savings (today).
2. Verified savings matures: holdback A/B accumulates signal with confidence
   intervals across routes.
3. Automated monthly invoice generation + Stripe charge on the verified number,
   with the 25% cap and net-positive guarantee enforced in code (already is).

## The honest guarantees a buyer can rely on

- We bill on measured savings, never estimates.
- The fee never exceeds 25% of verified savings; when verified savings are
  positive, `fee < savings` is always true.
- Every invoice traces to verified savings you can audit on the Proof page.
- Until automated billing and Stripe land, an invoice is a statement a human
  sends, not a charge that happens to you.
