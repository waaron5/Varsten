# Varsten on AWS — staging deployment runbook

This brings up a live **staging** environment for the inline proxy + control plane.
It is a runbook, not an applied state: run the commands against your own AWS
account (`! aws ...` from the Claude Code prompt, or your shell). Nothing here is
provisioned automatically.

## Architecture

```
            client traffic (vk_ key)
                     │
                     ▼
        ┌──────────────────────────┐        ┌───────────────┐
        │  App Runner (or ECS)      │  TLS   │  OpenAI API   │
        │  varsten-api container    │───────▶│               │
        │  FastAPI + inline proxy   │        └───────────────┘
        │  scheduler (in-process)   │
        └─────────┬─────────┬──────┘
                  │         │
         VPC conn │         │ S3 SDK
                  ▼         ▼
        ┌──────────────┐  ┌──────────────────┐
        │ RDS Postgres │  │ S3 batch staging │
        │ + pgvector   │  │ varsten-batches  │
        └──────────────┘  └──────────────────┘
```

- **Compute: App Runner** for staging (managed, fast to stand up). Set
  **min size = 1** so the container never scales to zero — the proxy is inline
  and cannot tolerate a cold start. Swap to **ECS Fargate** (always-on service,
  finer VPC control) when you want production networking; the container image is
  identical.
- **DB: RDS for PostgreSQL** (15.4+), with the `vector` extension for the
  semantic cache.
- **Storage: S3** for batch `.jsonl` staging. The app already speaks S3 via the
  `batch_storage_backend=s3` setting and pre-signed URLs (`app/storage`).
- **Secrets: AWS Secrets Manager** for the DB URL and provider keys. Never bake
  secrets into the image or task definition env literals.

## The container

`backend/Dockerfile` is already production-shaped: it installs deps with `uv` and
serves uvicorn on `:8000`. It does **not** migrate on boot — `docker-entrypoint.sh`
is a thin pass-through, so replicas start in parallel without racing
`alembic upgrade head`. Migrations are a decoupled release step (see the deployment
lifecycle below). The same image runs them as a one-off command:
`docker run --rm -e DATABASE_URL=... <image> alembic upgrade head`.

## Horizontal scaling (`app_max_instances > 1`)

The single-instance constraints are handled in code; the Terraform default
(`app_max_instances = 4`) is now safe. What each instance needs:

- **Scheduler (drift / batch / cache-purge / alert sweeps).** Each job takes a
  per-job Postgres advisory lock for the duration of a tick, so only one instance
  runs a given sweep at a time. Enabled by `SCHEDULER_ADVISORY_LOCK_ENABLED=true`
  (set automatically in `app.tf`). Leadership fails over automatically when an
  instance dies — the lock drops with its connection. No external coordinator.
- **Rate limiter.** Set `RATE_LIMIT_REDIS_URL` (via the `rate_limit_redis_url`
  Terraform var) to enforce one shared window across instances. Provision a small
  managed Redis (ElastiCache / Upstash) yourself — it is the one new recurring cost
  of scaling out. Without it the limiter degrades to per-instance counting, which is
  fail-open (never blocks traffic), just less precise. The limiter call also fails
  open if Redis is unreachable.
- **Database connections.** Each instance holds up to
  `(DB_POOL_SIZE + DB_MAX_OVERFLOW) * 2` connections (sync + async engines).
  At the defaults (5 + 5) × 2 = 20 per instance, ×4 instances = 80. Point
  `DATABASE_URL` at the **pooled endpoint** (Neon pooler / PgBouncer / RDS Proxy) so
  these multiplex onto far fewer server connections, and keep the per-instance pool
  bounded with the `DB_POOL_SIZE` / `DB_MAX_OVERFLOW` vars.
- **Intentionally per-instance (no coordination needed):** the provider-key TTL
  cache (`app/proxy/keys.py`) and the per-project circuit breaker
  (`app/proxy/circuit.py`). These are hot-path performance optimisations, not shared
  state — each instance warms its own key cache, and a breaker that trips on the
  failures that instance actually observes is correct. Leaving them in-memory avoids
  a shared-store round-trip on every request.
- **Schema migrations:** decoupled from boot (see the deployment lifecycle below),
  so parallel replica starts never race the migration.

## Terraform remote state (bootstrap once, before the first `terraform init`)

Terraform uses an **S3 backend with a DynamoDB lock** (`terraform/versions.tf`) so
CI/CD and operators share one state and concurrent applies can't corrupt it. The
state bucket can't be created by the same Terraform run that uses it, so create it
**once per account, before your first `terraform init`**:

```sh
cd infra/aws
# Defaults match the backend block (bucket varsten-tfstate, table varsten-tflock,
# us-east-1). Override STATE_BUCKET if the global name is taken -- then change it in
# terraform/versions.tf too.
./bootstrap_state.sh

cd terraform
terraform init                              # configures the S3 backend
terraform workspace new staging             # per-env state: env:/staging/...
# terraform workspace new production
terraform apply -var="environment=staging" -var="image_tag=<git-sha>" ...
```

The script is idempotent (safe to re-run) and creates the bucket with versioning,
AES256 encryption, full public-access block, and a TLS-only policy, plus the lock
table keyed on `LockID`. Each environment is a Terraform **workspace**, so staging
and production keep separate state in the same bucket.

If this directory already has **local** state from an earlier solo deploy
(`terraform.tfstate` present), the first `terraform init` after adding the backend
will offer to copy it up: run `terraform init -migrate-state` and confirm. Verify
with `terraform plan` (expect no changes), then delete the local `terraform.tfstate*`
files so they can't drift.

The principal running Terraform (your CLI identity, and the CI `AWS_DEPLOY_ROLE_ARN`)
needs `s3:{Get,Put,List}Object` on the bucket and `dynamodb:{GetItem,PutItem,
DeleteItem}` on the lock table, in addition to the resource permissions in `iam.tf`.

## Deployment lifecycle (migrate before promote)

The API image no longer migrates on boot. The schema is brought to head by a
dedicated release step that runs **before** new instances are promoted, so the
single booting process owns the migration and replicas never race it. Order:

1. **Build & push** the image to ECR, tagged with the immutable git SHA.
2. **Migrate**: run `alembic upgrade head` once, using that exact image
   (`docker run --rm -e DATABASE_URL=... <image> alembic upgrade head`), against the
   target database. One process, no race.
3. **Promote**: point App Runner at the new tag (Terraform `image_tag`); it rolls
   out behind the `/health/ready` check with zero downtime.

`.github/workflows/deploy.yml` wires this as a manual `workflow_dispatch` with
`build-push → migrate → deploy` jobs (job `needs` enforce the order). The migrate
job connects to the database directly with the deploy role / `DATABASE_URL` secret.

Pure-AWS / manual equivalent (no GitHub Actions): after pushing the image, run the
migration as a one-off from CloudShell or any host with the image and DB access —
`make release-migrate IMAGE=<repo>:<sha> DATABASE_URL=...` (or an `aws ecs run-task`
/ CodeBuild step that runs the same `alembic upgrade head` command on the image) —
then bump `image_tag` and `terraform apply`.

**Migration compatibility:** because the old image runs briefly against the new
schema during rollout, migrations must be backward compatible. Additive changes
(new nullable column, table, index) are safe. For a destructive change, use
expand/contract across two releases: release 1 adds the new shape and dual-writes;
release 2 (after backfill) removes the old shape.

**Rollback:** re-run the deploy with a previous SHA. The schema is forward, so a
rolled-back (older) image keeps working against the newer additive schema; never
pair a rollback with a contracting migration.

## Required environment / secrets

Set these on the service (plain env for non-secrets, Secrets Manager refs for the rest):

| Key | Example | Notes |
|---|---|---|
| `DATABASE_URL` | `postgresql+psycopg://varsten:…@<rds-endpoint>:5432/varsten` | **secret** |
| `PROXY_OPENAI_KEYS` | `{"<project-uuid>":"sk-…"}` | **secret**, JSON map |
| `CORS_ORIGINS` | `["https://app.varsten.com"]` | lock to the real frontend origin |
| `AUTH0_DOMAIN` / `AUTH0_AUDIENCE` | … | dashboard auth |
| `BATCH_STORAGE_BACKEND` | `s3` | switches storage off local disk |
| `BATCH_S3_BUCKET` | `varsten-batches-staging` | |
| `BATCH_S3_REGION` | `us-east-1` | |
| `SCHEDULER_ENABLED` | `true` | runs the drift sweep + batch poller |
| `SENTRY_DSN` | … | optional |

## Runbook

Assumes `AWS_REGION=us-east-1` and the AWS CLI authenticated.

### 1. ECR — build and push the image

```sh
aws ecr create-repository --repository-name varsten-api
ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
REPO=$ACCOUNT.dkr.ecr.$AWS_REGION.amazonaws.com/varsten-api
aws ecr get-login-password | docker login --username AWS --password-stdin $ACCOUNT.dkr.ecr.$AWS_REGION.amazonaws.com

# build for the runtime arch (App Runner/Fargate are linux/amd64)
docker build --platform linux/amd64 -t varsten-api ./backend
docker tag varsten-api:latest $REPO:latest
docker push $REPO:latest
```

### 2. RDS — Postgres + pgvector

```sh
aws rds create-db-instance \
  --db-instance-identifier varsten-staging \
  --engine postgres --engine-version 15.4 \
  --db-instance-class db.t4g.micro \
  --allocated-storage 20 \
  --master-username varsten --master-user-password "<generate>" \
  --db-name varsten \
  --no-publicly-accessible \
  --vpc-security-group-ids <sg-id>
```

After it is available, enable pgvector once (migrations create the column; the
extension must exist first):

```sh
psql "$DATABASE_URL" -c "CREATE EXTENSION IF NOT EXISTS vector;"
```

### 3. S3 — batch staging bucket

```sh
aws s3api create-bucket --bucket varsten-batches-staging --region $AWS_REGION
aws s3api put-public-access-block --bucket varsten-batches-staging \
  --public-access-block-configuration BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true
# lifecycle: expire staged objects after the retention window (matches batch_object_ttl_hours)
aws s3api put-bucket-lifecycle-configuration --bucket varsten-batches-staging \
  --lifecycle-configuration '{"Rules":[{"ID":"expire-batches","Status":"Enabled","Filter":{"Prefix":""},"Expiration":{"Days":7}}]}'
```

### 4. Secrets Manager

```sh
aws secretsmanager create-secret --name varsten/staging/database-url --secret-string "$DATABASE_URL"
aws secretsmanager create-secret --name varsten/staging/proxy-openai-keys --secret-string '{"<project-uuid>":"sk-…"}'
```

### 5. App Runner service (image-based)

Create an App Runner service from the ECR image. Key settings:
- Port `8000`, CPU `1 vCPU`, memory `2 GB`.
- **Auto scaling: minimum size = 1** (no scale-to-zero — keeps the proxy warm).
- Instance role granting `s3:*Object` on the batch bucket and
  `secretsmanager:GetSecretValue` on the two secrets.
- A **VPC connector** so the service can reach RDS on the private subnet.
- Env from the table above; `DATABASE_URL` and `PROXY_OPENAI_KEYS` as Secrets
  Manager references, the rest as plain values.
- Health check path: `/health`.

(Console or `aws apprunner create-service` with a JSON input; the config is long
enough that the console is the pragmatic path for the first staging bring-up.
Capture the final JSON into `infra/aws/apprunner-service.json` once it works, so
it is reproducible.)

### 6. Smoke test

```sh
curl https://<service-url>/health           # {"ok": true}
# seed a workspace + key, then send a proxied completion with the vk_ key
```

## When this graduates to production

- Move compute to **ECS Fargate** (always-on service, blue/green deploys, finer
  security groups), keeping the same image.
- Migrations already run as a decoupled release step, not on container boot (see
  "Deployment lifecycle" above), and Terraform state is already remote (S3 + Dynamo
  lock, see "Terraform remote state" above), so the promote job can
  `terraform apply` from CI.
- RDS Multi-AZ + automated backups + a read replica if Proof queries grow.
- Scheduler overlap across replicas is already handled by the per-job Postgres
  advisory lock (`SCHEDULER_ADVISORY_LOCK_ENABLED`, see `app/scheduler.py` and the
  Horizontal scaling section above). Moving the sweeps to EventBridge cron is the
  next step only if you want the API tier fully free of background work.
- This runbook is largely codified in `infra/aws/terraform/` already (App Runner,
  ECR, IAM, secrets, autoscaling, remote state). Validate changes with
  `terraform plan` against the account before applying.
```
