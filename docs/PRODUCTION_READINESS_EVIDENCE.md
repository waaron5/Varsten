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
checks. The application-code baseline was `024f565`; Phase 0 subsequently added
documentation only and did not change the application release candidate.

| Item | Observed state | Status | Verification procedure | Relevant SHA |
| --- | --- | --- | --- | --- |
| Repository branch | `main` | Verified | `git branch --show-current` | Application baseline `024f56559f9265e1130bbec3e46a2dbeec87a9d3` |
| Local and remote revision | `HEAD` equaled `origin/main` at capture and was rechecked after the Phase 0 push | Verified | Compare `git rev-parse HEAD` and `git rev-parse origin/main` | Phase 0 documentation begins at `da8f7aa` |
| Release candidate | Remediation will continue from `main`; no production release candidate is frozen yet | Established | Freeze the final candidate only after Phases 1–11 pass | Application baseline `024f56559f9265e1130bbec3e46a2dbeec87a9d3` |
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
| Backend dependency security | Engineering | Passed | `pip-audit`, backend static gates, 814 tests, 84.70% coverage, and image build passed at `2026-07-16T21:26:53Z` | Revert `cba4b0e`; retain prior image |
| Dashboard dependency security | Engineering | Passed | Zero-vulnerability production audit, lint, typecheck/build, and 26 browser tests passed at `2026-07-16T21:36:45Z` | Revert `4d377ab`; no deployment was made |
| Marketing dependency security | Engineering | Passed | Zero-vulnerability production audit, lint, typecheck, and build passed at `2026-07-16T21:36:45Z` | Revert `32d5296`; no deployment was made |
| Production pricing initialization | Engineering | Passed | Hardened sync at `47aa031`; checkpoint `br-icy-scene-aimmtj6f`; 2,506 catalog and price identities verified at `2026-07-17T15:38:52Z` | Restore the checkpoint if necessary, or append corrected versioned price rows and reconcile affected events |
| Real cost derivation | Engineering | Passed | Six production SDK requests across OpenAI, Anthropic, and Gemini reconciled exactly at `aef5515` on `2026-07-17T18:54:31Z` | Disable affected model/route; mark events unpriced rather than inventing cost |
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

## Phase 1 evidence

### Backend dependency security

- Timestamp: `2026-07-16T21:26:53Z`
- Commit: `cba4b0ec6f191c857c84f0a0d1359cb06d6523b9`
- Package changes:
  - `cryptography` 48.0.0 to 48.0.1
  - `msgpack` 1.1.2 to 1.2.1
  - `pydantic-settings` 2.14.1 to 2.14.2
  - `starlette` 1.2.0 to 1.3.1
- Resolution policy: direct dependency minimums were raised for direct
  dependencies; uv constraints enforce security floors for transitive
  dependencies without misclassifying them as direct application dependencies.
- Dependency consistency: passed (`deptry`, 160 files).
- Vulnerability audit: passed (`pip-audit`: no known vulnerabilities).
- Database migration check: passed at Alembic head.
- Static gates: Ruff check and format, compilation, mypy, complexity budget, and
  Bandit passed.
- Regression suite: 814 passed, 4 opt-in tests skipped, 7 deprecation warnings.
- Coverage: 84.70%, above the required 80% threshold.
- Image gate: local production Docker image built successfully as
  `varsten-api:phase1-backend-audit`; resolved production dependencies contain
  the four patched versions above.
- Production impact: none. The image was not pushed or deployed.
- Remaining Phase 1 work: none.

### Dashboard dependency security

- Timestamp: `2026-07-16T21:36:45Z`
- Commit: `4d377ab168537e14530c502a4980ad64af8ee18e`
- Next.js and its matching ESLint configuration were upgraded from 16.2.7 to
  16.2.10, the latest stable patch available at verification time.
- The current stable Next.js package still pins PostCSS 8.4.31. A narrowly scoped
  npm override replaces only Next.js's internal PostCSS with 8.5.19, above the
  advisory's fixed threshold of 8.5.10. No forced npm fix or framework downgrade
  was used.
- Resolved tree: Next.js 16.2.10, Auth0 Next.js SDK 4.22.0, PostCSS 8.5.19.
- Production dependency audit: zero vulnerabilities.
- ESLint: passed.
- Production build and TypeScript compilation: passed for all 33 app routes.
- Browser regression suite: 26 passed, covering onboarding, Auth0-facing session
  behavior, dashboard integrity, billing states, resilience, ledger math, and
  automation.
- Production impact: none. The dashboard was not deployed.

### Marketing dependency security

- Timestamp: `2026-07-16T21:36:45Z`
- Commit: `32d5296170eed3190737301b10b41a9f1cf6a0bb`
- Next.js and its matching ESLint configuration were upgraded from 16.2.7 to
  16.2.10.
- The same narrowly scoped Next.js PostCSS override resolves to PostCSS 8.5.19;
  the direct Tailwind/PostCSS path also deduplicates to that fixed version.
- Production dependency audit: zero vulnerabilities.
- ESLint: passed.
- Production build and TypeScript compilation: passed for all 27 generated and
  dynamic marketing routes.
- Production impact: none. The marketing site was not deployed.

## Phase 2 evidence

### Pricing synchronization preflight

- Timestamp: `2026-07-17T02:04:57Z`
- Commit: `47aa031383953a435be1a0fcae5dfd8e669e1f6c`
- Production impact: none. No production database connection or write was made;
  production catalog and price counts remain at the Phase 0 baseline of zero.
- Source inspected: the configured LiteLLM public model-pricing feed. The current
  feed plus one confirmed direct-provider alias parsed into 2,506 priced model
  identities across 91 providers.
- The loader remains append-only for prices: a changed price creates a new
  effective version, an unchanged rerun creates none, and a later feed that omits
  a model does not delete its catalog or price history.
- Invalid non-finite or negative token prices now fail closed before database
  synchronization. The feed root and the exact launch-onboarding price coverage
  are also validated before a database session is opened.
- Launch coverage verified for OpenAI `gpt-4o-mini`, Anthropic
  `claude-haiku-4-5-20251001`, and Gemini `gemini-2.5-flash`. The onboarding and
  opt-in smoke examples were aligned to those current direct-provider identifiers;
  Gemini's namespaced feed entry is copied to its confirmed unprefixed API alias
  without overwriting an explicit direct entry.
- Full-feed local proof used an outer transaction with savepoints and rolled back
  the entire exercise. The first run parsed 2,506 models and appended 36 price
  versions relative to existing local data; the identical second run appended
  zero. Catalog/price counts returned exactly from `(2474, 2572)` to
  `(2474, 2572)` after rollback, and zero negative price rows were observed.
- Targeted pricing suite: 11 passed. Three live-provider SDK smoke tests skipped
  because their opt-in credentials were intentionally absent. Ruff, formatting,
  and mypy passed for the changed backend files.
- Exact release regression evidence: the full backend gate passed with 822 tests,
  4 opt-in skips, 84.69% coverage, and all migration/static/security gates green.
  The dashboard production build passed all 33 routes and its browser regression
  suite passed 26 tests.
- Correction/rollback procedure: the sync itself does not delete historical rows,
  so corrected prices are appended as a new effective version. A materially bad
  production sync still requires a pre-sync Neon checkpoint/branch for whole-state
  recovery; events priced during a bad interval require explicit reconciliation.
- Phase 2.2 subsequently confirmed a recoverable Neon branch and completed the
  controlled production synchronization below.

### Production pricing synchronization

- Verification completed: `2026-07-17T15:38:52Z`
- Sync implementation: `47aa031383953a435be1a0fcae5dfd8e669e1f6c`
- Human-created pre-sync Neon branch: `br-icy-scene-aimmtj6f`
  (`pre-pricing-sync-20260717`). No credential or connection string was recorded.
- Pre-sync state: Alembic `b0c1d2e3f4a5`; 2 organizations, 2 projects, and zero
  usage events, provider connections, catalog rows, or price rows.
- Post-sync state: 2,506 catalog identities and 2,506 price identities across 91
  providers. Every catalog identity has a price and every price has a catalog
  identity. No duplicate catalog identities, duplicate effective versions,
  negative prices, missing required fields, non-USD rows, or unexpected sources
  were found.
- All rows use source `litellm`; the initial effective timestamp is
  `2026-07-17 15:33:55.043755+00:00`.
- The 130 zero-input/zero-output entries were explicitly counted. Launch-provider
  examples are free moderation or experimental Gemini models; none of the three
  required onboarding models has a zero price. The broader set remains feed data,
  not an invented Varsten fallback.
- Launch prices verified exactly:
  - OpenAI `gpt-4o-mini`: input `0.000000150000`, output `0.000000600000` USD/token.
  - Anthropic `claude-haiku-4-5-20251001`: input `0.000001000000`, output
    `0.000005000000` USD/token.
  - Gemini `gemini-2.5-flash`: input `0.000000300000`, output `0.000002500000`
    USD/token.
- Phase 2.3 superseded the Gemini launch default after Google rejected 2.5 Flash
  for this newly provisioned API key. This row remains the accurate Phase 2.2
  catalog observation, not the current onboarding recommendation.
- Unknown models remain honest by design and regression evidence: pricing service
  returns `model_not_in_catalog` with no fabricated catalog cost when no version
  resolves. No synthetic production event was inserted for this check.
- Operational note: the first monitored command lost its client output window but
  continued and committed successfully. A concurrently started retry held an
  earlier empty snapshot, encountered the catalog uniqueness constraint at commit,
  and rolled back in full. Final integrity queries prove that only one complete
  2,506-row version exists.
- Post-sync readiness check: `https://api.varsten.ai/health/ready` returned
  `{\"ok\":true,\"database\":\"ok\"}`.
- Rollback remains available through the recorded pre-sync branch. Normal price
  corrections should append a new effective version; any events priced during an
  incorrect interval require explicit reconciliation rather than silent rewriting.

### Real production cost derivation

- Verification completed: `2026-07-17T18:54:31Z`
- Launch-model correction commit: `aef5515`
- Production project `4d1c870c-2302-4e2e-abbb-93b2914036b6` had verified,
  vaulted connections for OpenAI, Anthropic, and Gemini before traffic was sent.
  Provider secret values were never printed or recorded.
- The official OpenAI, Anthropic, and Google Gen AI Python clients sent one normal
  and one streamed request per provider through `https://api.varsten.ai`. Every
  request used a short prompt and a maximum of 24 output tokens.
- The original Gemini onboarding default, `gemini-2.5-flash`, returned Google's
  explicit `404` that the model is unavailable to new users. `gemini-3.5-flash`
  was enabled and priced but returned Google's `503 high demand` twice. Neither
  failed request produced a usage event.
- The stable enabled model `gemini-3.1-flash-lite` was selected instead. Its
  direct-provider feed entry is input `0.000000250000` and output
  `0.000001500000` USD/token. The hardened sync appended its direct Gemini alias,
  and both normal and streamed production requests then passed.
- All six successful events have `status=success`, `pricing_status=priced`,
  `cost_source=catalog`, `currency=USD`, a non-null price-version ID, and matching
  organization, project, and API-key attribution. Each referenced price version
  has source `litellm` and predates its event.
- Event-level recomputation matched exactly:
  - OpenAI normal: 16 input + 21 output tokens, `$0.00001500`.
  - OpenAI repeated stream: intentional cache hit, `$0.00000000`; metadata records
    `$0.00001500` naive cost and avoided cost.
  - Anthropic normal: 17 input + 18 output tokens, `$0.00010700`.
  - Anthropic stream: 17 input + 24 output tokens, `$0.00013700`.
  - Gemini normal: 10 input + 15 output tokens, `$0.00002500`.
  - Gemini stream: 11 input + 9 output tokens, `$0.00001625`.
- Project/dashboard-period reconciliation: 6 requests, 87 input tokens, 108
  output tokens, 195 total tokens, 6 priced events, and `$0.00030025` actual cost.
  The sum of independently recomputed event costs is also `$0.00030025`.
- Unknown-model behavior remains explicit through the pricing regression suite:
  no catalog match yields `model_not_in_catalog` rather than a fabricated cost.
  No synthetic unknown-model production event was created.
- Verification gates for the correction: 822 backend tests passed, 4 opt-in tests
  skipped, coverage was 84.69%, and all backend static/security gates passed.
  Frontend lint and the 33-route production build passed. The targeted live Gemini
  SDK test passed after the stable-model correction.
- Manual credential cleanup: the temporary Varsten `vk_` key shared for this test
  must be revoked in the dashboard because it was exposed in chat. Provider keys
  remain vaulted and were not exposed.

## Evidence update procedure

For each gate:

1. Record the exact UTC timestamp and release SHA.
2. Record the command or human procedure without secret values.
3. Summarize the result and link to access-controlled artifacts when needed.
4. Record any skipped scenario as an unresolved gap, not a pass.
5. Record the rollback or containment action actually tested.
6. Change the status to `Passed` only after the production-relevant check passes.

## Phase 0 exit assessment

- `main` and `origin/main` are synchronized. The captured application baseline is
  `024f56559f9265e1130bbec3e46a2dbeec87a9d3`; Phase 0 adds documentation only.
- Remediation work is established to continue from current `main`; the final
  immutable release candidate will be frozen only after earlier phases pass.
- Current production state and architecture are documented above.
- Every later phase has an owner, explicit evidence requirement, and containment
  or rollback procedure.
- The user's addition of the implementation plan and this evidence register are
  the only intended Phase 0 documentation changes; repository cleanliness is
  verified after they are committed.
