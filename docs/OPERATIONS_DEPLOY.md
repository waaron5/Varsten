# Production Deploy, Backup, and Rollback Runbook

This is the operational counterpart to `infra/aws/terraform/`. It covers how the
Varsten API is deployed, how the database is backed up and restored, how to roll
back, and the migration-safety rules. Read it before the first production deploy.

> Status: the Terraform under `infra/aws/terraform/` has not yet been applied
> against a live AWS account. The first run must be a reviewed `terraform plan`.
> Until that plan succeeds end to end (including an App Runner deploy that passes
> `/health/ready` and a tested restore), production is not proven. Do not route a
> customer's traffic before then.

## Architecture

```
Vercel (Next.js dashboard + marketing)
   │ HTTPS, CORS-locked to the app origin
   ▼
AWS App Runner  ── varsten-api image from ECR ──┐  (single instance in Phase 1)
   │  instance role: read varsten/<env>/* secrets, kms:Decrypt
   │  health check: GET /health/ready
   ├── VPC connector ──► RDS Postgres 16 (private, encrypted, PITR on)
   ├──────────────────► AWS Secrets Manager (DATABASE_URL, provider keys, Sentry DSN)
   └──────────────────► OpenAI / Anthropic / Gemini upstreams
Sentry  ◄── errors        JSON logs ◄── App Runner / CloudWatch
```

Single instance is deliberate: the in-process scheduler (`app/scheduler.py`) and
the in-memory rate limiter (`app/core/ratelimit.py`) assume one runner. Keep
`app_max_instances = 1` until those move to an external job runner and a shared
store (Redis). Scale up (CPU/memory), not out.

## Environments

`staging` and `production` are the same Terraform, separated by the `environment`
variable and, critically, by **separate state** (distinct Terraform workspaces or
backend keys). They get distinct RDS instances, distinct secret prefixes
(`varsten/staging/*` vs `varsten/production/*`), and distinct App Runner services.
Never point staging at the production database.

## First-time setup

1. Create the remote-state bucket + lock table once, fill in the `backend "s3"`
   block in `versions.tf`, and `terraform init` per environment.
2. `terraform apply` with a `terraform.tfvars` (see the example). This creates the
   ECR repo, RDS, secrets, IAM, the VPC connector, and the App Runner service.
3. Build and push the API image, then set `image_tag` and apply again:
   ```bash
   aws ecr get-login-password --region "$REGION" | docker login --username AWS --password-stdin "$ECR_URL"
   docker build -t "$ECR_URL:$GIT_SHA" ./backend
   docker push "$ECR_URL:$GIT_SHA"
   terraform apply -var "image_tag=$GIT_SHA"
   ```
4. Run migrations against the new database (see below).
5. Verify: `curl https://<api_url>/health/ready` returns `{"ok": true, ...}`.
6. Connect a provider key through the dashboard Connections flow and confirm the
   secret lands at `varsten/<env>/provider-keys/<project_id>/<provider>`.

## Routine deploy

1. Merge to `main` with green CI (lint, type, security, complexity, tests, builds).
2. Build + push the image tagged with the git SHA.
3. Run migrations **before** shifting traffic (expand/contract; see below).
4. `terraform apply -var "image_tag=$GIT_SHA"`. App Runner does a zero-downtime
   rolling deploy and only cuts over once `/health/ready` passes.

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

Backups are automatic: `db_backup_retention_period = 14` enables daily snapshots
**and** point-in-time recovery (PITR) to any second in the window. There is
nothing to schedule.

**A backup you have never restored is not a backup.** Run this drill on staging
before the first customer and quarterly after:

1. Restore to a new instance at a chosen timestamp:
   ```bash
   aws rds restore-db-instance-to-point-in-time \
     --source-db-instance-identifier varsten-production \
     --target-db-instance-identifier varsten-restore-test \
     --restore-time "2026-06-15T12:00:00Z" \
     --no-publicly-accessible --db-subnet-group-name varsten-production
   ```
2. Point a staging API (or a psql session) at the restored endpoint and verify row
   counts and a recent `usage_events` record are present.
3. Record the wall-clock restore time (this is your real RTO) and the timestamp
   gap (RPO). Tear the restore instance down.

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
- App Runner request/error/latency metrics + CloudWatch logs (JSON). Set a CPU and
  a 5xx-rate CloudWatch alarm to an on-call email/Slack.
- `/health/ready` is the orchestration health check; `/health` is liveness.
- Application-level budget/alert delivery is a separate workstream (Phase 5); this
  section is infrastructure health only.

## Secrets

- All secrets live in Secrets Manager under `varsten/<env>/*`. Nothing sensitive is
  committed; `DATABASE_URL` and `SENTRY_DSN` are injected by App Runner from
  secrets, and provider keys are written at runtime by the Connections flow.
- The instance role can read only `varsten/<env>/*` and write only under
  `provider-keys/*`. It cannot read another environment's secrets.
- Rotating the DB password: rotate in RDS, update the `database-url` secret, then
  force a new App Runner deploy so the running task re-reads it.
