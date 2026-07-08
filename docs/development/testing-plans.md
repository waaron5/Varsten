# Testing Free vs Optimize

This is how to exercise both plan tiers locally without editing the database by
hand or creating product-state confusion.

## The three workspaces you have

| Workspace | How it exists | Tier | Use it to test |
|---|---|---|---|
| Your personal workspace | created on first login (`POST /v1/auth/sync`) | **Free** (default) | Free onboarding, observe-only dashboard, locked actions |
| The seeded demo org | `make seed-demo` (`scripts/seed_demo.py`, org `is_demo=true`) | **Optimize** (intentional, so the demo shows applied savings) | Optimize dashboard with populated, real seeded savings |
| Any org you flip | operator plan switch (below) | Free ⇄ Optimize | switching the *same* workspace between tiers |

`plan_tier` lives on `organizations.plan_tier` (default `free`). `GET /v1/entitlements`
is the canonical source the UI reads (via `useEntitlements`). The proxy caches the
tier for ~60s; the operator switch invalidates that cache immediately.

## Switching a workspace's plan (operator only)

There is **no public plan switcher**. Flipping a tier requires an operator account
(your email must be in `OPERATOR_ADMIN_EMAILS`) and is done via an authenticated
endpoint:

```
POST /v1/operator/organizations/{organization_id}/plan
Authorization: Bearer <your dashboard access token>
Content-Type: application/json

{ "plan_tier": "performance" }   # or "free"
```

Steps:

1. Add your email to `OPERATOR_ADMIN_EMAILS` in `backend/.env`, e.g.
   `OPERATOR_ADMIN_EMAILS='["you@example.com"]'`, and restart the backend.
2. Get your org id: `GET /v1/auth/me` (or read it from the dashboard session) →
   `organizations[].id`.
3. Get a dashboard access token: in the browser dev tools, the app fetches
   `/auth/access-token`; copy the `token`. (Or use the app while signed in.)
4. Flip the tier:

```bash
curl -X POST "http://localhost:8000/v1/operator/organizations/$ORG_ID/plan" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"plan_tier":"performance"}'
```

5. Reload the dashboard. The nav badge flips between `Free · Observe-only` and
   `Optimize`, and locked actions unlock.

A non-operator caller gets `403`; an unknown tier gets `422`.

## What to verify

### Free onboarding
- Sign in as a fresh user → land in `/start` → `/onboarding`. Create the workspace,
  reveal the API key, see the OpenAI snippet, send a request, see "First request
  received" with cost/tokens/model/latency/request id and the observe-only framing.

### Free observe-only dashboard
- Nav shows `Free · Observe-only` + `Upgrade`. Side nav shows the Free plan card.
- Dashboard shows observed spend/requests/tokens/latency/model usage.
- Savings panels are empty / $0 ("No savings recorded yet"). **There must be no
  captured-savings numbers** — observe-only disables caching, so a repeated request
  is *not* served from cache and accrues no `saved_usd`.
- Engine recommendations show estimated opportunities; the upgrade banner explains
  they are estimates, not captured savings.

### Free locked actions
- Apply on a recommendation is disabled with "Enable Optimize to apply…".
- Calling the API directly still fails server-side: a free org gets `403`
  (`feature_requires_performance`) on apply / enable route / enable trim / enable
  lever / lever automation / submit batch. Frontend locks are never the only gate.

### Optimize dashboard + actions
- On the demo org (or your org flipped to Optimize), nav shows `Optimize`.
- Apply a non-gated recommendation (e.g. semantic cache) → it applies; savings
  attribution language is real. Model-swap levers still require a passing shadow
  eval (separate gate).
- A repeated identical proxy request is served from cache (`X-Varsten-Cache: hit`).

### Avoiding demo confusion
- The demo org is **intentionally Optimize** and carries seeded savings. If a
  dashboard looks "Free but with savings," check the nav badge — you are probably on
  the demo (Optimize) org. Use your personal Free org (or flip a tier) to test the
  true Free experience.

## Automated coverage

- `tests/test_entitlements.py` — gates + `/v1/entitlements` shape (free vs performance).
- `tests/test_observe_only.py` — Free does not cache/capture savings; Optimize does;
  operator plan switch (allowed / forbidden / bad tier).
- `tests/test_onboarding.py` — derived setup state + first-request detection.
- `tests/test_provider_validation.py`, `tests/test_ratelimit.py` — self-serve hardening.
