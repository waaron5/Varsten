# Production readiness evidence register

This document is the auditable launch register for Varsten. It records the
production baseline, the owner and test for every launch gate, and the evidence
required before meaningful customer traffic is accepted.

Do not place credentials, secret values, access tokens, customer payloads, or
provider keys in this file. Record identifiers, modes, aggregate counts, and
links to separately access-controlled evidence only.

## Release baseline

Baseline captured at `2026-07-16T21:11:12Z` using read-only repository, public
endpoint, AWS control-plane, Stripe account-metadata, and production database
checks.

| Item | Observed state | Status | Verification procedure | Relevant SHA |
| --- | --- | --- | --- | --- |
| Repository branch | `main` | Verified | `git branch --show-current` | `024f56559f9265e1130bbec3e46a2dbeec87a9d3` |
| Local and remote revision | `HEAD` equals `origin/main` | Verified | Compare `git rev-parse HEAD` and `git rev-parse origin/main` | `024f56559f9265e1130bbec3e46a2dbeec87a9d3` |
| Release candidate | Remediation will continue from current `main`; no production release candidate is frozen yet | Established | Freeze the final candidate only after Phases 1–11 pass | `024f56559f9265e1130bbec3e46a2dbeec87a9d3` |
| Production API image | ECR `varsten-api:cf334bdbcac5fd6c7ea730616c1c3712947a45f0` | Verified; behind `main` | Read App Runner image identifier | `cf334bdbcac5fd6c7ea730616c1c3712947a45f0` |
| Production API service | App Runner `varsten-production`, status `RUNNING` | Verified | `aws apprunner describe-service` in `us-east-1` | Production image SHA above |
| Production API domain | `api.varsten.ai`, App Runner custom-domain status `active` | Verified | App Runner custom-domain query, DNS lookup, and readiness request | Production image SHA above |
| API readiness | `https://api.varsten.ai/health/ready` returns `200` | Verified | Public HTTPS request | Production image SHA above |
| Dashboard deployment | `https://app.varsten.ai/dashboard` returns `200` from Vercel | Public deployment verified; immutable Vercel deployment ID unverified | Public HTTPS headers; retrieve immutable ID after human Vercel login | Unknown |
| Marketing deployment | `https://www.varsten.ai` returns `200` from Vercel | Public deployment verified; immutable Vercel deployment ID unverified | Public HTTPS headers; retrieve immutable ID after human Vercel login | Unknown |
| Database provider | Neon Postgres in AWS `us-east-1` | Verified | Parse only the hostname of the Secrets Manager database URL | N/A |
| Database migration | Alembic `b0c1d2e3f4a5 (head)` | Verified | Run `alembic current` with the production database URL without printing it | Production image SHA above |
| Auth0 tenant | `dev-tnqse1hznivo6img.us.auth0.com` | Verified; production designation unresolved | Inspect public authorization redirect and confirm tenant purpose in Auth0 | Dashboard deployment ID pending |
| Auth0 client | `bcBLfGeiEF1ra9LDdkm0xP11MtXBu6NF` | Verified | Inspect public authorization redirect | Dashboard deployment ID pending |
| Auth0 audience | `https://api.varsten.ai` | Verified | Inspect public authorization redirect and App Runner environment | Dashboard/API SHAs above |
| Auth0 callback | `https://app.varsten.ai/auth/callback` | Verified | Inspect public authorization redirect | Dashboard deployment ID pending |
| Stripe account | `acct_1TtEkBHHtpxdRQjQ`, US, details submitted | Verified | Stripe Account API using the secret from Secrets Manager; output metadata only | N/A |
| Stripe mode | Secret and publishable keys are both live mode | Verified | Test only the key prefixes without printing values | N/A |
| Stripe readiness | Charges and payouts enabled | Verified | Stripe Account API metadata | N/A |
| Stripe webhook | `POST https://api.varsten.ai/webhooks/stripe`; unsigned payload rejected with `400 invalid signature` | Verified | Safe unsigned webhook probe | Production image SHA above |
| Sentry | Production DSN is wired through Secrets Manager | Configuration present; alerting unverified | App Runner secret-name and environment inspection | Production image SHA above |
| External uptime monitoring | No evidence available | Not verified | Human supplies monitor configuration and successful notification evidence | N/A |
| CloudWatch alarms | Zero metric alarms found | Not ready | `aws cloudwatch describe-alarms` | N/A |

The immutable Vercel deployment identifiers require an authenticated Vercel
session. Phase 0 does not require exposing credentials or initiating a login;
the public production state is recorded above, and immutable identifiers remain
an explicit evidence gap.

## Production data baseline

These are aggregate counts only, captured at `2026-07-16T21:11:12Z`.

| Table | Rows | Interpretation |
| --- | ---: | --- |
| `organizations` | 2 | Existing workspaces are present |
| `projects` | 2 | Existing projects are present |
| `usage_events` | 0 | No production usage funnel has been proven |
| `model_catalog` | 0 | Pricing catalog is not initialized |
| `model_prices` | 0 | Production cost derivation is not ready |
| `provider_connections` | 0 | No production provider connection is recorded |

## App Runner runtime baseline

- Region: `us-east-1`
- Service ARN:
  `arn:aws:apprunner:us-east-1:749534911289:service/varsten-production/57a7c6c67ef74fa69a813254982b0021`
- App Runner URL: `xkmwbvcq2r.us-east-1.awsapprunner.com`
- Automatic deployments: disabled
- CPU/memory: 1 vCPU / 2 GB
- Autoscaling: minimum 1, maximum 1, maximum concurrency 100
- Health check: HTTP `/health/ready`, 10-second interval, 5-second timeout,
  healthy threshold 1, unhealthy threshold 3
- Database pool: size 5, overflow 5
- Scheduler: enabled with advisory locking
- Provider-key backend: AWS Secrets Manager, production prefix
- Billing: self-serve enabled; disabled-billing escape hatch disallowed
- CORS allowlist: `https://app.varsten.ai`
- Secret references present: database URL, Sentry DSN, and three Stripe secrets

## Production DNS baseline

| Host | Destination observed | Role |
| --- | --- | --- |
| `www.varsten.ai` | Vercel DNS | Marketing site |
| `app.varsten.ai` | Vercel DNS | Authenticated dashboard |
| `api.varsten.ai` | App Runner addresses; custom domain active | API and proxy |

DNS addresses are expected to change and are not release identifiers. The
authoritative evidence is the provider/custom-domain status plus successful
HTTPS verification.

## Intended production architecture

| Component | Intended responsibility | Baseline reconciliation |
| --- | --- | --- |
| AWS App Runner | Run the API/proxy image promoted by immutable SHA | Live and healthy; production is behind current `main` |
| Neon Postgres | Production transactional and evidence database | Live and migrated; recovery plan and restore drill unverified |
| AWS Secrets Manager | Database, Sentry, Stripe, and provider-key secrets | Wired; provider-key IAM/persistence is tested in later gates |
| Vercel | Host marketing and dashboard applications | Both public sites live; immutable deployment IDs need human-authenticated verification |
| Auth0 | Customer identity and API token issuer | Live login redirect works; tenant's production designation and hardening unresolved |
| Stripe | Live payment setup, lifecycle, and webhook source | Live account ready; full customer billing lifecycle unproven |
| Sentry | Production exception and release observability | DSN wired; alert rules, scrubbing, releases, and delivery unproven |
| External uptime monitor | Independent website/API availability alerting | No evidence available; required before launch |

This table supersedes any assumption that production uses AWS RDS. The observed
production database is Neon; the operational and security documentation must be
reconciled in Phase 11 after recovery behavior is proven.

## Launch gate register

Statuses are `Not started`, `In progress`, `Blocked`, `Failed`, `Passed`, or
`Accepted risk`. `Passed` requires dated evidence for the exact relevant release
SHA. An accepted risk requires the owner, rationale, scope, expiry date, and
rollback/containment procedure.

| Gate | Owner | Status | Verification / required evidence | Rollback or containment |
| --- | --- | --- | --- | --- |
| Phase 0: baseline and evidence register | Engineering | Passed | This document; live state captured `2026-07-16T21:11:12Z` | Re-run read-only capture if production changes |
| Backend dependency security | Engineering | Not started | `pip-audit`, backend static gates, full tests, coverage, and image build pass for release SHA | Revert dependency commit; retain prior image |
| Dashboard dependency security | Engineering | Not started | Production-only npm audit reviewed; lint, typecheck, build, and browser suite pass | Revert dashboard dependency commit/deployment |
| Marketing dependency security | Engineering | Not started | Production-only npm audit reviewed; lint, typecheck, and build pass | Revert marketing dependency commit/deployment |
| Production pricing initialization | Engineering | Failed at baseline | Idempotent sync; nonzero catalog/price counts; representative models validated | Restore/checkpoint if sync is destructive; otherwise correct with versioned price rows |
| Real cost derivation | Engineering | Not started | Real request reconciles tokens, versioned price, event cost, and dashboard aggregate | Disable affected model/route; mark events unpriced rather than inventing cost |
| Public SDK availability | Engineering + npm owner | Failed at baseline | Clean registry installs and exact onboarding snippets pass for all advertised packages | Hide/disable unavailable SDK paths; retain gateway/metadata paths |
| Auth0 production hardening | Auth0 owner + Engineering | Blocked on human confirmation | Tenant designation, MFA, allowlists, protections, token settings, fresh signup, isolation tests | Revert Auth0/Vercel config together; preserve prior callback until verified |
| Neon backup capability | Neon owner + Engineering | Blocked on human account evidence | Plan, retention, PITR/branch capability, account recovery, and admins recorded | Stop data-changing launch work until recoverability is known |
| Database restore drill | Engineering + Neon owner | Not started | Isolated restore succeeds; revision/counts/tenancy verified; measured RPO/RTO recorded | Destroy isolated restore; production remains untouched |
| AWS/application monitoring | Engineering | Failed at baseline | Alarms exist for availability, errors, latency, database, scheduler, pricing, secrets, and billing | Disable noisy alarm; never disable underlying telemetry |
| Sentry alerting and scrubbing | Sentry owner + Engineering | Not started | Test event reaches human; release linked; sensitive fields demonstrably scrubbed | Disable faulty integration or alert; retain error capture only if data-safe |
| External uptime monitoring | Human operations owner | Blocked on human setup | Three monitors active; test notification reaches phone/email | Use secondary provider/manual checks during repair |
| Container and supply-chain security | Engineering | Not started | Image scan/SBOM reviewed; no actionable critical/high findings; secrets scan clean | Do not promote image; retain last known-good SHA |
| Capacity and fail-open resilience | Engineering | Not started | Load and failure tests meet documented limit; fallback and circuit behavior verified | Cap traffic; set project bypass/global kill switch |
| CI/CD and migration promotion | Engineering | Not started | CI green for exact SHA; plan gate; expand migration before promotion; rollback test | Redeploy prior image SHA; never reverse an incompatible migration |
| Fresh production onboarding funnel | Human test user + Engineering | Not started | New identity reaches priced dashboard through real provider traffic without seeds/bypass | Project bypass; revoke test keys; remove test tenant data safely |
| Production billing lifecycle | Stripe owner + Engineering | Not started | Checkout/cancel/webhook/idempotency/trial/past-due/cancel/reactivate states verified | Disable self-serve billing; preserve existing entitlements for review |
| Legal and privacy package | Founder + counsel | Blocked on human/counsel review | Approved Terms/MSA, Privacy Policy, DPA, subprocessors, retention, support terms | Limit engagement to explicitly contracted design pilot |
| Security and marketing claims | Founder + Engineering + counsel | Not started | Every reliability, data, pricing, savings, and compliance claim maps to evidence | Remove or qualify unsupported claim |
| Operational documentation | Engineering | Not started | Deployment, Neon recovery, incident, monitoring, billing, SDK, and rollback docs match production | Treat observed control-plane state as authoritative during correction |
| Final immutable release | Engineering + Founder approval | Not started | All P0 gates passed; exact SHA deployed; smoke/funnel/soak evidence complete | App Runner rollback plus project/global bypass |

## Evidence update procedure

For each gate:

1. Record the exact UTC timestamp and release SHA.
2. Record the command or human procedure without secret values.
3. Summarize the result and link to access-controlled artifacts when needed.
4. Record any skipped scenario as an unresolved gap, not a pass.
5. Record the rollback or containment action actually tested.
6. Change the status to `Passed` only after the production-relevant check passes.

## Phase 0 exit assessment

- `main` and `origin/main` are synchronized at
  `024f56559f9265e1130bbec3e46a2dbeec87a9d3`.
- Remediation work is established to continue from current `main`; the final
  immutable release candidate will be frozen only after earlier phases pass.
- Current production state and architecture are documented above.
- Every later phase has an owner, explicit evidence requirement, and containment
  or rollback procedure.
- The user's addition of the implementation plan and this evidence register are
  the only intended Phase 0 documentation changes; repository cleanliness is
  verified after they are committed.
