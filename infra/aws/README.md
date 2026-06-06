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

`backend/Dockerfile` is already production-shaped: it installs deps with `uv`,
runs `alembic upgrade head` on boot (`docker-entrypoint.sh`), then serves uvicorn
on `:8000`. No changes needed for staging.

> Multi-instance note: the entrypoint runs migrations on every boot, fine for a
> single instance. Before scaling past one task, move `alembic upgrade head` to a
> one-off release step so two booting replicas don't race the migration.

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
- Migrations as a release/one-off task, not on container boot.
- RDS Multi-AZ + automated backups + a read replica if Proof queries grow.
- Put the scheduler on a single leader (or move the two sweep endpoints to
  EventBridge cron) so replicas don't double-run sweeps — see `app/scheduler.py`.
- Promote this runbook to Terraform under `infra/aws/` and validate with
  `terraform plan` against the account.
```
