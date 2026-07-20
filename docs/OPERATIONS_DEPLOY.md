# Production Deploy, Backup, and Rollback Runbook

This is the operational counterpart to `infra/aws/terraform/`. It covers how the
Varsten API is deployed, how the database is backed up and restored, how to roll
back, and the migration-safety rules. Read it before the first production deploy.
For what the engine can and cannot claim before packaging/onboarding, see
`ENGINE_RELIABILITY_BOUNDARIES.md`.

> Status: Terraform is applied in AWS and the production App Runner service is
> live. The database is Neon Postgres in AWS `us-east-1`; Terraform does not create
> or back it up. A tested isolated Neon restore is still a launch gate.

## Architecture

```
Vercel (Next.js dashboard + marketing)
   │ HTTPS, CORS-locked to the app origin
   ▼
AWS App Runner  ── varsten-api image from ECR ──┐
   │  instance role: read varsten/<env>/* secrets, kms:Decrypt
   │  health check: GET /health/ready
   ├──────────────────► Neon Postgres (AWS us-east-1, TLS)
   ├──────────────────► Redis / ElastiCache (required before horizontal scale)
   ├──────────────────► AWS Secrets Manager (DATABASE_URL, provider keys, Sentry DSN)
   └──────────────────► OpenAI / Anthropic / Gemini upstreams
Sentry  ◄── errors        JSON logs ◄── App Runner / CloudWatch
```

Default to one instance. Horizontal scale is allowed only after shared
coordination is configured and tested: set `REDIS_URL`, `RATE_LIMIT_BACKEND=redis`,
and `RATE_LIMIT_REDIS_URL`, size the database pool for `app_max_instances`, and
run the live Redis smoke against staging:

```bash
VARSTEN_TEST_REDIS_URL=redis://<staging-redis>:6379/0 \
  pytest tests/test_redis_operational.py -m redis_live
```

Without Redis, the circuit breaker, budget-cap cache, and rate limiter are
process-local. Scale up (CPU/memory), not out. The in-process scheduler
(`app/scheduler.py`) is still a deployment boundary: run exactly one scheduler or
move it to an external job runner before scaling the API horizontally.

## Environments

`staging` and `production` are the same Terraform, separated by the `environment`
variable and, critically, by **separate state** (distinct Terraform workspaces or
backend keys). They get distinct secret prefixes (`varsten/staging/*` vs
`varsten/production/*`) and distinct App Runner services. Their Neon databases
must also use isolated projects or branches and credentials. Never point a
staging application at the production branch.

## First-time setup

1. Create the remote-state bucket + lock table once, fill in the `backend "s3"`
   block in `versions.tf`, and `terraform init` per environment.
2. Provision the Neon database separately, require TLS, store its connection URL
   in the environment's AWS Secrets Manager database secret, and record the Neon
   project/branch identifiers without recording credentials.
3. `terraform apply` with a `terraform.tfvars` (see the example). This creates the
   ECR repository, application secrets, IAM, audit infrastructure, and App Runner
   service; it does not create Neon.
4. Build and push the API image, then set `image_tag` and apply again:
   ```bash
   aws ecr get-login-password --region "$REGION" | docker login --username AWS --password-stdin "$ECR_URL"
   docker build -t "$ECR_URL:$GIT_SHA" ./backend
   docker push "$ECR_URL:$GIT_SHA"
   terraform apply -var "image_tag=$GIT_SHA"
   ```
5. Run migrations against the new database (see below).
6. Verify: `curl https://<api_url>/health/ready` returns `{"ok": true, ...}`.
7. Connect a provider key through the dashboard Connections flow and confirm the
   secret lands at `varsten/<env>/provider-keys/<project_id>/<provider>`.

## Routine deploy

1. Merge to `main` with green CI (lint, type, security, complexity, tests, builds).
2. Build + push the image tagged with the git SHA.
3. Run migrations **before** shifting traffic (expand/contract; see below).
4. `terraform apply -var "image_tag=$GIT_SHA"`. App Runner does a zero-downtime
   rolling deploy and only cuts over once `/health/ready` passes.

## Multi-instance Redis checklist

Do not raise `app_max_instances` above `1` until all checks pass:

1. `REDIS_URL` points to the staging/production Redis cluster used for shared
   circuit-breaker and budget-cap state.
2. `RATE_LIMIT_BACKEND=redis` and `RATE_LIMIT_REDIS_URL` point to the same
   low-latency Redis cluster or an explicitly separate one.
3. `RATE_LIMIT_REDIS_TIMEOUT_SECONDS` is tight enough that Redis degradation
   fails open quickly instead of stalling proxy traffic.
4. `pytest tests/test_redis_operational.py -m redis_live` passes with
   `VARSTEN_TEST_REDIS_URL` set to the target Redis URL.
5. Exactly one scheduler is active, or scheduled jobs have been moved to an
   external singleton runner.
6. Database pool sizing has been recalculated for the new instance count.

## Migrations

- Alembic is the only way the schema changes. Never edit the database by hand.
- Run migrations as a discrete step, not on container boot, for production. The
  dev `docker-entrypoint.sh` applies them at start; in production run
  `alembic upgrade head` as a one-off task against the same image before applying
  the new `image_tag`, so a failed migration never crash-loops the service.
- **Expand/contract** for zero downtime: add columns/tables (expand) and deploy
  code that tolerates both shapes first; backfill; only later drop/rename
  (contract) in a separate migration after the old code is gone. Do not rename or
  drop a column in the same deploy that stops using it.
- Every migration must be reversible or have a documented forward-fix. Test it on
  staging (a restored copy of production data) before production.

## Backups and restore

Production recovery uses Neon's **Backup & Restore**, instant restore/history,
snapshots, and isolated branches. The configured restore window and snapshot
schedule are plan-dependent; record the actual console values in
`security/neon-production-recovery.md`. Never infer retention from an old Neon
default or from this repository.

**A backup you have never restored is not a backup.** Run this drill on staging
before the first customer and quarterly after:

1. Record the production branch ID, current UTC time, Alembic revision, and safe
   aggregate counts. Do not print a connection string.
2. In Neon **Backup & Restore**, select a timestamp inside the configured restore
   window. Preview the timestamp if the plan supports it.
3. Restore to a **new isolated branch/endpoint**, never in place. Name it
   `restore-drill-YYYYMMDD` and set an expiry where available.
4. Do not point App Runner, Vercel, scheduled jobs, provider-key connections,
   Stripe webhooks, or email delivery at the restored branch. Connect only a
   temporary read-only verification process.
5. Verify Alembic revision, safe table counts, tenant relationships, API-key
   metadata (never plaintext), price coverage, usage, billing state, and provider
   connection metadata. Run no provider or billing requests.
6. Record the selected recovery timestamp, branch-ready time, verification-ready
   time, measured recovery-point gap, and any errors.
7. Delete the temporary endpoint/branch after evidence is captured. Confirm the
   production connection and readiness never changed.

Document the measured RTO/RPO in the customer security package.

## Rollback

- **App rollback** (bad deploy): re-apply the previous image tag.
  `terraform apply -var "image_tag=$PREVIOUS_GIT_SHA"`. Because ECR tags are
  immutable and tags are git SHAs, the previous image is exactly what was running.
- **Optimization rollback** (a lever misbehaving in production, not a deploy bug):
  use the in-product kill switch — set `PROXY_KILL_SWITCH=true` (global) or flip a
  project's bypass — to forward all traffic straight to the upstream, still
  metered, with no optimization. This is independent of a redeploy and is the
  fast lever during an incident.
- **Schema rollback**: prefer a forward-fix migration. A destructive `downgrade`
  after data has been written is the dangerous path; only use it if the migration
  was purely additive and unused.

## Monitoring and alerting (minimum before first customer)

- Sentry captures unhandled errors (required: the app refuses to boot in
  production without `SENTRY_DSN`).
- Terraform manages production App Runner 5xx, latency, CPU, memory, database,
  scheduler, provider-key vault, Stripe, and provider-circuit alarms. Deployment
  failures route through EventBridge. All P0 paths publish to the
  `varsten-production-p0-alerts` SNS topic and link to
  `monitoring/ALERT_RUNBOOK.md`.
- `/health/ready` is the orchestration health check; `/health` is liveness.
- SNS email subscriptions must be confirmed and drilled; an alarm existing in
  CloudWatch is not proof that a human received it.
- Pricing coverage, excessive unpriced usage, authentication-rate, and
  request-disappearance alerts remain Phase 6 work because they require durable
  custom metrics or a stable synthetic/customer traffic baseline.

## Secrets

- All secrets live in Secrets Manager under `varsten/<env>/*`. Nothing sensitive is
  committed; `DATABASE_URL` and `SENTRY_DSN` are injected by App Runner from
  secrets, and provider keys are written at runtime by the Connections flow.
- The instance role can read only `varsten/<env>/*` and write only under
  `provider-keys/*`. It cannot read another environment's secrets.
- Rotating the DB password: rotate the Neon role password, update the
  `database-url` secret, then force a new App Runner deploy so the running task
  re-reads it. Verify readiness before revoking the old credential.
