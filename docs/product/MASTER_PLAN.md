# Varsten Production-Readiness Implementation Plan

## Goal

Make Varsten safe and credible for its first enterprise customer, with:

- A tested release running in production
- A completely functional customer onboarding funnel
- Accurate model pricing and cost attribution
- Installable production SDKs
- Patched dependencies
- Proven backup and recovery
- Actionable monitoring and incident response
- Production-grade identity, billing, and secrets handling
- Accurate operational, security, legal, and marketing claims

The launch gate is not “the deployment succeeded.” It is a real, fresh customer account generating correctly priced production traffic while monitoring, recovery, billing, and fallback controls are proven.

## Operating rules

- Work in small, categorized commits.
- Do not combine application fixes, infrastructure changes, documentation, or dependency upgrades unnecessarily.
- Promote one immutable commit SHA through testing, migration, and deployment.
- Never expose production credentials in terminal output, commits, messages, or screenshots.
- Use expand-only database migrations before deploying dependent code.
- Back up or confirm recovery capability before changing production data.
- Test every material production change immediately after deployment.
- Keep a written evidence record for every launch gate.
- Do not route a customer’s meaningful production traffic until all P0 gates pass.

---

# Phase 0 — Establish the release baseline (Done. See PRODUCTION_READINESS_EVIDENCE.md)

**Owner:** Me
**Production changes:** None
**Purpose:** Create a stable, auditable starting point.

### Tasks

1. Record the current state:

   - Current `main` SHA
   - Current production backend image SHA
   - Current Vercel dashboard and marketing deployments
   - Production database migration revision
   - App Runner configuration
   - Production domains and DNS
   - Auth0 tenant and application identifiers
   - Stripe mode and webhook endpoint
   - Current production data counts

2. Create a production-readiness checklist/evidence document containing:

   - Gate
   - Owner
   - Status
   - Verification command or procedure
   - Result
   - Timestamp
   - Relevant release SHA
   - Rollback procedure

3. Reconcile the intended production architecture:

   - App Runner
   - Neon Postgres
   - AWS Secrets Manager
   - Vercel
   - Auth0
   - Stripe
   - Sentry
   - External uptime monitoring

4. Establish the release candidate branch or exact `main` commit that will receive remediation work.

### Exit criteria

- Clean working tree
- `main` synchronized with the remote
- Current production state documented
- Every later gate has an explicit test and owner

---

# Phase 1 — Patch dependency vulnerabilities

**Owner:** Me
**Risk:** Medium
**Must precede:** Final release build

## 1.1 Backend security updates

Update the affected packages to fixed versions:

- `cryptography` ≥ 48.0.1
- `msgpack` ≥ 1.2.1
- `pydantic-settings` ≥ 2.14.2
- `starlette` ≥ 1.3.1

### Implementation procedure

1. Review dependency constraints and the FastAPI/Starlette compatibility range.
2. Upgrade the smallest safe dependency set.
3. Regenerate the lockfile.
4. Review transitive dependency changes.
5. Run:

   - Dependency consistency check
   - Ruff
   - Formatting check
   - Mypy
   - Bandit
   - Complexity gate
   - Alembic migration test
   - Full backend suite
   - Coverage gate
   - `pip-audit`
   - Docker image build

6. Pay special attention to:

   - Middleware behavior
   - Request parsing
   - Authentication errors
   - CORS handling
   - Stripe webhook body/signature processing
   - Exception handling
   - Streaming responses
   - WebSocket behavior, if applicable

## 1.2 Frontend and marketing dependency findings

The PostCSS finding is transitive through Next.js. Do not run a blind forced downgrade or breaking `npm audit fix --force`.

### Implementation procedure

1. Identify the first patched stable Next.js/PostCSS combination.
2. Review Next.js and Auth0 compatibility.
3. Upgrade frontend and marketing independently if appropriate.
4. Regenerate each lockfile.
5. Run lint, TypeScript, build, browser tests, and production dependency audits.
6. Verify Auth0 middleware, redirects, cookies, callback handling, CSP, and proxy routes.

### Commit structure

- `security: patch backend dependency vulnerabilities`
- `security: update frontend production dependencies`
- `security: update marketing production dependencies`

### Exit criteria

- Backend `pip-audit` passes or every remaining finding has a documented, accepted mitigation
- Frontend and marketing audits contain no actionable high/critical findings
- Full test and build gates remain green
- Dependency changes are independently reviewable

---

# Phase 2 — Repair and verify production pricing

**Owner:** Me
**Risk:** High to product correctness
**Current blocker:** Production has zero catalog and price records

## 2.1 Inspect the pricing sync path

1. Review the price-sync script and its data sources.
2. Confirm it is idempotent.
3. Confirm it does not delete valid historical prices unexpectedly.
4. Verify effective-date/version behavior.
5. Confirm rollback or correction procedure.
6. Run against a local or staging database first.
7. Verify representative models from every supported provider.

## 2.2 Production synchronization

1. Take or confirm a recoverable production database checkpoint.
2. Record pre-sync counts.
3. Run the price sync against production.
4. Record post-sync counts.
5. Check for duplicate, missing, zero, negative, or overlapping price records.
6. Verify currently marketed models have catalog coverage.
7. Confirm unknown models fail honestly instead of receiving invented pricing.

## 2.3 Real cost derivation test

Send controlled real requests through each launch-supported integration and verify:

- Provider
- Model
- Input tokens
- Output tokens
- Provider-reported usage
- Calculated gross cost
- Pricing source/version
- Currency
- Project and organization attribution
- Dashboard aggregation

### Exit criteria

- `model_catalog` and `model_prices` are populated
- All launch-supported models are covered
- A real request produces a correctly priced usage event
- Unknown-model behavior is explicit and safe
- Dashboard totals reconcile with event-level calculations

---

# Phase 3 — Make the SDK onboarding path real

**Owners:** Me and You
**Risk:** High to onboarding
**Current blocker:** Public package installation returns `E404`

## 3.1 Package preparation

**Owner: Me**

For all packages:

- `@varsten/core`
- `@varsten/openai`
- `@varsten/anthropic`
- `@varsten/gemini`

I will verify:

1. Package names and dependencies
2. Public access configuration
3. License
4. Repository and homepage metadata
5. Correct exports
6. ESM/CommonJS compatibility where intended
7. Included package files
8. Source maps and type declarations
9. No secrets, fixtures, or internal files in package tarballs
10. README installation and integration examples
11. Version consistency
12. Fail-open and timeout behavior
13. Telemetry behavior
14. Local build, typecheck, and tests
15. `npm pack` contents

## 3.2 npm organization and publication

**Owner: You — manual**

You must:

1. Create or confirm ownership of the `varsten` npm organization.
2. Enable MFA on your npm account.
3. Configure publication permissions.
4. Log into npm locally.
5. Supply OTP/passkey authorization when publication requires it.
6. Approve publication of the prepared versions.

Secrets or OTP values should never be sent to me.

## 3.3 Publication and clean-install verification

**Owner: Me, with your npm authorization where required**

1. Publish packages in dependency order.
2. Confirm public registry visibility.
3. Create clean temporary projects.
4. Install each package directly from npm.
5. Run every onboarding snippet exactly as displayed.
6. Test compatible provider SDK versions.
7. Test missing/invalid Varsten configuration.
8. Verify provider fallback when Varsten is unreachable.
9. Confirm no package requires unpublished workspace dependencies.

## 3.4 Onboarding honesty gate

If publication cannot be completed immediately:

- Temporarily hide or disable the SDK path.
- Make Gateway or metadata-only the default.
- Explain that the SDK path is unavailable.
- Never show a command that returns `E404`.

### Commit structure

- `sdk: prepare packages for verified public publication`
- `onboarding: expose only available production integrations`

### Exit criteria

- Every displayed installation command works in a clean project
- All packages are publicly available at the documented versions
- Production onboarding links and snippets match published artifacts
- Fail-open behavior is demonstrated against the production API

---

# Phase 4 — Verify and harden production identity

**Owners:** Me and You
**Risk:** Critical
**Current concern:** Live configuration uses a tenant whose name differs from the documented production tenant

## 4.1 Decide the Auth0 production tenant

**Owner: You — manual decision**

Confirm whether `dev-tnqse1hznivo6img.us.auth0.com` is intentionally the permanent production tenant.

If it is not, create or select the actual production tenant.

## 4.2 Auth0 configuration

**Owner: You — manual dashboard work, guided by me**

Configure:

- API audience: `https://api.varsten.ai`
- Callback: `https://app.varsten.ai/auth/callback`
- Logout URL: `https://app.varsten.ai`
- Allowed web origin: `https://app.varsten.ai`
- Only necessary grant types
- Appropriate token lifetime
- Refresh-token rotation
- Brute-force protection
- Breached-password protection
- Administrator MFA
- Tenant recovery owners
- Production email provider and templates
- Log retention/export appropriate for incident investigation
- No unintended localhost/preview URLs in production

## 4.3 Application validation

**Owner: Me**

Verify:

- Login and signup
- Logout
- Callback error handling
- State and PKCE behavior
- Session-cookie security attributes
- Audience and issuer validation
- Token expiration
- Invalid-token rejection
- Organization/user synchronization
- Duplicate callback/idempotency behavior
- Unauthorized dashboard behavior
- Cross-organization isolation

### Exit criteria

- The selected tenant is explicitly designated production
- Production allowlists are minimal
- Administrative MFA and recovery are configured
- A fresh signup completes successfully
- Token and tenant isolation tests pass
- Documentation and environment examples match reality

---

# Phase 5 — Prove backup, restore, and data recovery

**Owners:** Me and You
**Risk:** Critical
**Current blocker:** Production uses Neon while recovery documentation describes RDS

## 5.1 Establish the Neon recovery capability

**Owner: You — manual account access if required**

Confirm and provide non-secret evidence of:

- Neon plan
- Backup retention
- Point-in-time recovery window
- Branch/restore capability
- Region
- Account recovery and MFA
- Authorized administrators
- Billing status

## 5.2 Define recovery objectives

**Owner: You, with recommendations from me**

Choose realistic initial objectives:

- RPO: acceptable maximum data loss
- RTO: acceptable maximum service recovery time
- Recovery owner
- Customer notification threshold

These must be promises Varsten can actually meet.

## 5.3 Conduct a restore drill

**Owner: Me, with your approval before any provider-side operation**

1. Record production database revision and safe aggregate counts.
2. Create a recovery point or restore branch.
3. Restore into an isolated destination.
4. Ensure restored data cannot send email, bill customers, call providers, or receive production traffic.
5. Connect a temporary verification process.
6. Validate:

   - Alembic version
   - Organizations/projects
   - API-key metadata
   - Price catalog
   - Usage events
   - Billing state
   - Provider connection metadata
   - Tenant isolation

7. Record elapsed restore time and recovery point gap.
8. Destroy the temporary environment after evidence is captured.

## 5.4 Correct documentation

Replace RDS-specific production claims with the actual Neon procedure. Do not claim a restore is drilled until the drill has passed.

### Exit criteria

- Recovery retention is known
- Restore drill succeeds
- Measured RPO/RTO are recorded
- Recovery documentation matches production
- At least two people/accounts can recover access, if organizationally possible

---

# Phase 6 — Implement production monitoring and alerting

**Owners:** Me and You
**Risk:** Critical operational gap

## 6.1 AWS and application alarms

**Owner: Me**

Implement alerts for:

- App Runner deployment failure
- Unhealthy instance or failed readiness checks
- Elevated 5xx rate
- Abnormal 4xx/authentication rate where useful
- High latency
- Request-volume disappearance
- Database connection failures
- Database pool exhaustion
- Scheduler failures
- Pricing lookup/catalog misses
- Provider-key vault failures
- Stripe webhook failures
- Provider error/circuit-breaker activity
- Excessive unpriced usage events

Alerts should reach a real destination, not merely exist.

## 6.2 Sentry

**Owner: You — manual account access may be required; Me for application verification**

Configure:

- Production project/environment
- New production error alert
- Regression alert
- Error-volume alert
- Release tracking
- Source maps where applicable
- Alert delivery to your email/phone/Slack
- Data-scrubbing rules for tokens, API keys, authorization headers, and prompts

## 6.3 External uptime monitoring

**Owner: You — manual account setup**

Configure an independent monitor for:

- `https://api.varsten.ai/health/ready`
- `https://app.varsten.ai`
- `https://www.varsten.ai`

Use multiple regions if available. Alert your phone and email.

## 6.4 Alert drill

**Owner: Me, with your approval**

Trigger safe synthetic failures or test notifications and prove:

- The alert arrives
- The message identifies the affected service
- It contains a useful runbook link
- Recovery/acknowledgment responsibility is clear

### Exit criteria

- Every P0 alert has a verified recipient
- At least one end-to-end alert drill passes
- Sentry scrubbing is verified
- External uptime monitoring is active
- The runbook explains what to do for each alert

---

# Phase 7 — Harden infrastructure and release controls

**Owner:** Me
**Risk:** Medium to high

## 7.1 Container and supply-chain security

1. Enable or run container-image vulnerability scanning.
2. Patch actionable findings.
3. Confirm the runtime image is minimal and non-root where feasible.
4. Verify no secrets are embedded in image layers.
5. Generate or retain dependency inventory/SBOM if supported.
6. Pin critical CI actions and deployment dependencies appropriately.

## 7.2 App Runner review

Verify:

- Minimum and maximum instances
- CPU and memory
- Request concurrency
- Health-check thresholds
- Deployment rollback behavior
- Log retention
- IAM least privilege
- Secret references
- No plaintext credentials
- Rate-limiting behavior at current instance count

The current one-instance configuration avoids distributed-state inconsistencies but creates a capacity ceiling. Before increasing it, Redis/shared-state requirements must be resolved and tested.

## 7.3 Capacity and resilience

1. Re-run supported load benchmarks against a safe environment.
2. Validate target concurrency and request sizes.
3. Test upstream slowness, rate limits, malformed responses, streaming interruption, and connection resets.
4. Confirm circuit breaker and fail-open behavior.
5. Establish initial customer traffic limits.
6. Document what happens when Varsten or the database is unavailable.

## 7.4 CI/CD validation

1. Confirm GitHub Actions runs successfully on `main`.
2. Verify production deployment uses GitHub OIDC, not long-lived deployment credentials.
3. Confirm Terraform plan gating.
4. Confirm migrations precede promotion.
5. Confirm deployment uses an immutable SHA.
6. Test rollback to a prior image without rolling back the database.
7. Add dependency audits to CI with an intentional severity policy.

### Exit criteria

- Release image passes vulnerability scanning
- Current capacity is documented and tested
- CI passes for the exact release SHA
- Deployment and rollback procedures are exercised
- Scaling beyond one instance is either proven safe or explicitly prohibited

---

# Phase 8 — Complete the real production onboarding funnel

**Owners:** Me and You
**Risk:** Critical launch gate

## 8.1 Create a clean customer-like identity

**Owner: You — manual signup**

Use an email account that has never used Varsten. Do not use developer bypasses, seed data, or mocked authentication.

## 8.2 Run the exact funnel

Together, verify:

1. Visit `www.varsten.ai`.
2. Select the intended plan/trial CTA.
3. Complete Auth0 signup.
4. Confirm user and organization synchronization.
5. Enter onboarding.
6. Create or select a project.
7. Generate a `vk_` key.
8. Confirm it is displayed only once.
9. Choose a real, publicly available integration.
10. Connect a real provider key.
11. Confirm it is written to the correct Secrets Manager prefix.
12. Send a real provider request.
13. Confirm onboarding detects verified traffic.
14. Finish onboarding without manual database intervention.
15. Confirm the dashboard displays actual usage.
16. Confirm event-level and aggregate costs reconcile.
17. Confirm pricing provenance is present.
18. Confirm cross-page navigation and refresh persistence.
19. Confirm logout and login restore the correct workspace.

## 8.3 Failure-path tests

Verify graceful handling of:

- Invalid provider key
- Provider rate limit
- Missing model price
- Duplicate project creation
- Repeated callback
- Refresh during every onboarding step
- Back-button navigation
- Mobile viewport
- Network interruption
- Varsten API temporarily unavailable
- Provider unavailable
- Expired Auth0 session
- User abandoning and resuming onboarding

## 8.4 Security checks

Verify:

- Foreign-origin CORS rejection
- Anonymous API rejection
- Cross-tenant resource rejection
- API-key one-time visibility
- Redacted logs
- Provider key never returned through the API
- Stripe webhook signature enforcement
- Rate limits
- Kill switch and project bypass

### Exit criteria

- A fresh user reaches a correctly priced dashboard using real traffic
- No mock, seed, bypass, or direct database correction is used
- Resume and failure behavior are smooth
- Secrets and tenant boundaries are preserved
- Evidence is recorded for the release candidate

---

# Phase 9 — Verify production billing

**Owners:** Me and You
**Risk:** Critical if accepting payment

## 9.1 Stripe configuration

**Owner: You — manual Stripe Dashboard review**

Confirm:

- Correct business identity
- Bank/payout details
- Public business information
- Customer support contact
- Statement descriptor
- Tax configuration decision
- Receipt behavior
- Dispute notifications
- Webhook endpoint
- Required webhook event subscriptions
- Webhook delivery history
- Restricted dashboard access and MFA

## 9.2 Billing lifecycle tests

**Owner: Me, using a controlled production customer and with your approval**

Verify:

- Checkout/setup session opens
- Cancel returns safely
- Successful payment-method setup
- Webhook delivery
- Idempotent duplicate webhook handling
- Subscription/customer association
- Trial-to-paid transition
- Past-due state
- Cancellation/reactivation
- Customer portal
- No charge occurs merely from estimates or recommendations
- Billing calculation reconciles with verified savings rules

Use the smallest safe real transaction only if a true live charge test is required and you explicitly approve it.

### Exit criteria

- Stripe live account and webhook are operational
- Billing state survives duplicate/out-of-order events
- Dashboard entitlement state matches Stripe
- Cancellation and failure behavior are clear
- Financial calculations are auditable

---

# Phase 10 — Legal, privacy, and enterprise readiness

**Owners:** You, qualified counsel, and Me for technical accuracy
**Risk:** Commercial and contractual

## 10.1 Legal package

**Owner: You and counsel — manual**

Prepare/review:

- Binding Terms of Service or MSA
- Privacy Policy
- DPA
- Subprocessor list
- Acceptable Use Policy
- Support terms
- Data-retention/deletion commitments
- Limitation of liability
- Warranty disclaimers
- Security incident notification terms
- Pricing and verified-savings definition
- Trial and cancellation terms

The current public pages should not be treated as a substitute for legal review.

## 10.2 Security package

**Owner: Me for technical content; You for distribution/approval**

Prepare:

- Architecture/data-flow diagram
- Security overview
- Provider-key handling
- Encryption posture
- Access-control model
- Tenant-isolation explanation
- Data inventory
- Retention matrix
- Incident-response procedure
- Backup and recovery evidence
- Pen-test or independent assessment roadmap
- Accurate SOC 2 status
- Security contact process

## 10.3 Claims review

Audit all public copy for claims involving:

- “Enterprise-ready”
- “Production-ready”
- “Finance-grade”
- “Fail-open”
- “Never stores prompts”
- “Guaranteed quality”
- “Real-time”
- “Every dollar priced”
- “Verified savings”
- “Uptime”
- “SOC 2-compatible”
- “Review-ready”

Every claim must be demonstrably true, carefully qualified, or removed.

### Exit criteria

- Counsel-approved commercial documents are available
- DPA and subprocessors are ready
- Security claims match implemented controls
- No public page promises unproven recovery, reliability, or coverage
- Sales language distinguishes current controls from roadmap items

---

# Phase 11 — Documentation and operational handoff

**Owner:** Me

Update:

- Deployment runbook
- Dashboard deployment guide
- AWS infrastructure documentation
- Security documentation
- Incident-response runbook
- Backup/restore procedure
- Auth0 configuration
- Stripe configuration
- Price synchronization
- SDK publication
- Kill-switch procedure
- Customer onboarding procedure
- Customer offboarding and data deletion
- Monitoring/alert response
- Release and rollback process

Remove stale claims that:

- Terraform has never been applied
- Production uses RDS
- Restore drills are complete when they are not
- SDK packages are available when unpublished
- Monitoring exists when it is unverified

### Exit criteria

A competent operator can deploy, observe, bypass, recover, and roll back Varsten using the documentation without relying on undocumented founder knowledge.

---

# Phase 12 — Final release and launch gate

**Owners:** Me and You

## 12.1 Release candidate

**Owner: Me**

1. Confirm all preceding phases pass.
2. Ensure the repository is clean and synchronized.
3. Record the exact release SHA.
4. Run the complete CI-equivalent suite.
5. Build the Linux production image.
6. Scan it.
7. Push the immutable SHA tag.
8. Produce and review the Terraform plan.
9. Confirm no destructive database or infrastructure changes.

## 12.2 Production promotion

**Owner: Me, with your approval**

1. Confirm recovery checkpoint.
2. Apply expand-only migrations.
3. Promote the exact image SHA.
4. Wait for App Runner stabilization.
5. Verify readiness.
6. Check error, latency, database, and deployment telemetry.
7. Run production smoke tests.
8. Verify dashboard and marketing deployments.
9. Repeat the critical customer funnel checks.
10. Observe production for a defined soak period.

## 12.3 Rollback conditions

Immediately roll back or activate bypass if:

- Readiness becomes unstable
- Error rate rises materially
- Authentication fails
- Tenant isolation is questionable
- Provider requests fail or duplicate
- Costs are missing or materially incorrect
- Provider keys cannot be retrieved safely
- Stripe state becomes inconsistent
- Dashboard shows another organization’s data
- Logs expose credentials or prompt content

### Exit criteria

- Exact release SHA is running
- All automated gates are green
- Production smoke tests pass
- Real end-to-end onboarding passes
- Alerts remain quiet except for expected drill events
- Rollback and bypass controls are immediately available

---

# Human-only action checklist

These actions require you or another authorized human:

- Confirm or create the production Auth0 tenant.
- Configure Auth0 administrator MFA, recovery, connections, and allowlists.
- Provide Auth0/Vercel secrets through their secure dashboards.
- Create or confirm the `varsten` npm organization.
- Authenticate npm publication with MFA/OTP/passkey.
- Confirm Neon plan, retention, account security, and recovery access.
- Approve creation of a Neon restore branch or recovery drill.
- Configure or authorize Sentry notification destinations.
- Create external uptime-monitoring accounts and notification contacts.
- Review the Stripe Dashboard, business settings, tax decision, and webhook events.
- Approve any real live-mode Stripe transaction.
- Perform the fresh-user signup where human email verification is required.
- Confirm receipt of enterprise lead emails and operational alerts.
- Engage legal counsel and approve the MSA, Terms, Privacy Policy, and DPA.
- Decide initial RPO, RTO, SLA, support commitments, and customer traffic limits.
- Approve DNS or production infrastructure changes.
- Approve final production promotion.
- Decide when the LinkedIn/commercial announcement goes live.

---

# Recommended commit sequence

1. `security: patch backend dependency vulnerabilities`
2. `security: update frontend dependencies`
3. `security: update marketing dependencies`
4. `pricing: harden and verify catalog synchronization`
5. `sdk: finalize packages for public publication`
6. `onboarding: align integration choices with published SDKs`
7. `observability: add production metrics and alarms`
8. `infrastructure: harden image scanning and runtime controls`
9. `auth: align production tenant configuration`
10. `billing: harden production lifecycle verification`
11. `docs: document Neon backup and tested recovery`
12. `docs: reconcile production deployment and incident runbooks`
13. `legal: align public security and service claims`

Each category should be pushed after its tests pass. Production should be promoted only from the final audited SHA.

# Final definition of “production-ready”

Varsten is ready for its first enterprise customer only when all of these are true:

- No unresolved critical/high security findings
- Production pricing catalog is populated and verified
- Every advertised SDK command installs successfully
- Fresh-account real onboarding succeeds
- Real traffic creates correctly priced dashboard data
- Provider keys are vaulted, retrievable, and never exposed
- Auth0 production posture is explicitly approved
- Stripe lifecycle and webhook handling are verified
- Database restore has been performed successfully
- RPO and RTO are measured
- Operational alerts reach a human
- Kill switch and rollback have been exercised
- Capacity limits are known and enforced
- Commercial and security documentation is accurate
- Legal agreements are ready
- The deployed SHA exactly matches the tested release candidate
- A post-deployment soak period completes without unexplained errors

Until then, Varsten should be positioned as a controlled design-partner pilot rather than generally available enterprise software.
