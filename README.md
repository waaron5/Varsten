# Varsten

Varsten is an AI cost-control and savings-proof system for production LLM traffic.
It sits in front of model providers, records trusted cost metadata, identifies
safe savings opportunities, applies approved optimizations, and shows the ledger
behind the savings number.

The current repository contains four main surfaces:

- `backend/` - FastAPI control plane and inline proxy.
- `frontend/` - authenticated dashboard/control-plane UI.
- `marketing/` - public marketing site.
- `sdk/openai/` - fail-open OpenAI SDK wrapper.

This README describes what is built in this repo today. Longer product and
operations notes live under `docs/`, including the current engine reliability
boundaries in `docs/ENGINE_RELIABILITY_BOUNDARIES.md`.

## What Is Built

### Backend

The backend is a FastAPI app with PostgreSQL/pgvector storage. It includes:

- API-key authenticated usage ingestion.
- Pricing catalog and cost resolution with pricing/data-quality status.
- Provider connection state and provider-key handling.
- Dashboard snapshot APIs.
- Recommendations mapped to savings levers.
- Engine apply/dismiss flows.
- Guardrails for quality floors, budgets, and alerts.
- Proof views for savings, attribution, data quality, and reports.
- Eval/replay harness for gated model-swap recommendations.
- Inline proxy routes for OpenAI-compatible chat completions, Anthropic Messages,
  Gemini native generation, Gemini OpenAI-compatible chat, streaming, tool-call
  preservation, semantic cache, token trim, routing, batching, holdback evidence,
  drift sweep, and optimization decision records.

Proxy routes include:

- `POST /v1/chat/completions`
- `POST /v1/messages`
- `POST /v1/messages/count_tokens`
- `POST /v1/messages/batches`
- `POST /v1beta/models/{model}:generateContent`
- `POST /v1beta/models/{model}:streamGenerateContent?alt=sse`
- `POST /v1beta/models/{model}:countTokens`
- `POST /v1beta/batches`
- `POST /v1beta/openai/chat/completions`

The backend exposes:

- `GET /health` for process liveness.
- `GET /health/ready` for database-backed readiness.

### Dashboard App

The dashboard is a Next.js app in `frontend/`. It includes:

- Auth0-backed app shell.
- Server-seeded session/project bootstrap for the dashboard path.
- Onboarding and provider connection flows.
- Dashboard, Engine, Analysis, Guardrails, Proof, Reports, Admin, Settings, and
  Upgrade surfaces.
- Shared design tokens in `frontend/app/tokens.css`.
- Playwright E2E specs for onboarding, proxy resilience, and savings math using
  a mock API harness.

### Marketing App

The marketing site is a separate Next.js app in `marketing/`. It includes:

- Landing page for Varsten.
- Docs, security, privacy, and terms pages.
- Lead capture endpoint using Resend when configured.
- Shared design tokens in `marketing/app/tokens.css`.

The marketing app is intentionally separate from the authenticated dashboard.

### OpenAI SDK

The OpenAI SDK wrapper in `sdk/openai/` is the production-oriented fail-open
integration for OpenAI chat completions.

When Varsten is healthy, requests go through Varsten. When Varsten is
unreachable, slow to connect, or returns a Varsten-originated failure before
provider output is produced, the SDK can send the same request directly to
OpenAI with the customer's provider key.

See `sdk/openai/README.md` for the exact fallback rules and limitations.

## What Is Not Finished

The repo is usable for local demos, frontend verification, and continued product
development, but a few things are intentionally not represented as complete:

- The AWS Terraform under `infra/aws/terraform/` still needs a reviewed first
  production apply and restore drill before routing customer traffic.
- The base-URL-only proxy integration is useful for evaluation, but production
  apps that require fail-open behavior should use the SDK wrapper path.
- The OpenAI SDK exists; Anthropic and Gemini SDK wrappers are not present in
  this repo yet.
- Manual invoicing is the current commercial path. There is no full Stripe
  subscription system here.
- Some product claims depend on deployment mode. Inline proxy traffic necessarily
  passes request content through the proxy; ledger/proof storage is based on
  metadata and measured costs unless a feature such as eval capture or cache
  explicitly stores bounded content.
- Engine optimization is advanced but still bounded: streaming fallback,
  cross-provider fallback, savings-variance bandit rewards, and live staging
  Redis proof before horizontal scale are not finished product claims yet. See
  `docs/ENGINE_RELIABILITY_BOUNDARIES.md`.

## Repository Layout

```text
backend/        FastAPI app, Alembic migrations, proxy, pricing, evals, tests
frontend/       Authenticated Next.js dashboard and Playwright E2E tests
marketing/      Public Next.js marketing site
sdk/openai/     Fail-open OpenAI SDK wrapper package
infra/aws/      AWS App Runner/RDS/ECR/Secrets Manager Terraform and runbooks
docs/           Product, security, operations, and design notes
```

## Prerequisites

- Docker
- Python 3.13
- `uv`
- Node.js 22
- npm

## Local Development

### Start the Compose Stack

This starts Postgres, the API, and the dashboard app:

```bash
docker compose up --build -d
```

Services:

- API: `http://localhost:8000`
- Dashboard: `http://localhost:3000`
- Postgres: host port `5434`

Stop the stack:

```bash
docker compose down
```

Drop the local database volume too:

```bash
docker compose down -v
```

### Backend Native Dev

Start only Postgres:

```bash
docker compose up db
```

Install backend dependencies:

```bash
cd backend
uv sync --dev
```

Run migrations:

```bash
cd ..
make migrate
```

Run the API:

```bash
cd backend
uv run uvicorn app.main:app --reload
```

Health checks:

```bash
curl http://localhost:8000/health
curl http://localhost:8000/health/ready
```

### Seed Demo Data

After migrations:

```bash
make demo-seed
```

This creates a deterministic demo organization, project, API key, pricing rows,
usage events, recommendations, guardrails, proof rows, customer economics, and
provider connection state.

The demo project key is:

```text
vk_demo_varsten_local_key
```

For sales/demo tenant resets:

```bash
make seed-demo-tenant
```

### Dashboard App

```bash
cd frontend
npm install
cp .env.example .env.local
npm run dev
```

Open:

```text
http://localhost:3000
```

Auth0 settings are documented in `frontend/README.md`.

### Marketing App

```bash
cd marketing
npm install
cp .env.example .env.local
npm run dev -- -p 3001
```

Open:

```text
http://localhost:3001
```

Lead-email configuration is documented in `docs/OPERATIONS_SETUP.md`.

## Verification

Backend quality gate:

```bash
make backend-check
```

Backend tests only:

```bash
make backend-test
```

Backend security/audit checks:

```bash
make backend-security
make backend-audit
```

Dashboard checks:

```bash
cd frontend
npm run lint
npm run build
npm run test:e2e
```

Marketing checks:

```bash
cd marketing
npm run lint
npm run build
```

OpenAI SDK package checks are run from `sdk/openai/` according to that package's
own README and scripts.

## Live SDK Smoke Tests

Run these only against a running Varsten API with real provider keys configured
for the target project:

```bash
cd backend
uv pip install openai anthropic google-genai
cd ..
VARSTEN_SDK_SMOKE=1 \
VARSTEN_SDK_SMOKE_BASE_URL=http://127.0.0.1:8000 \
VARSTEN_SDK_SMOKE_API_KEY=vk_your_project_key \
make backend-sdk-smoke
```

Optional model overrides:

```bash
VARSTEN_SDK_SMOKE_OPENAI_MODEL=gpt-4o-mini
VARSTEN_SDK_SMOKE_ANTHROPIC_MODEL=claude-3-5-haiku-20241022
VARSTEN_SDK_SMOKE_GEMINI_MODEL=gemini-3.5-flash
```

## Deployment Notes

Frontend and marketing are designed for Vercel deployments. The backend is
designed for AWS App Runner with RDS Postgres, ECR, Secrets Manager, Sentry, and
Terraform-managed infrastructure.

Important docs:

- `infra/aws/README.md` - AWS infrastructure overview and remote-state setup.
- `infra/aws/bootstrap_state.sh` - one-time S3/DynamoDB Terraform state bootstrap.
- `docs/OPERATIONS_DEPLOY.md` - deploy, backup, migration, and rollback runbook.
- `docs/OPERATIONS_SETUP.md` - provider connections, SDK smoke, lead email, and
  operator setup.
- `docs/security/` - security notes and data-handling docs.

Terraform remote state must be bootstrapped before first `terraform init`:

```bash
cd infra/aws
./bootstrap_state.sh
cd terraform
terraform init
```

Production migrations should run as a separate release step before promoting a
new backend image. Do not run production migrations implicitly on container boot.

## Product Model

Varsten's current product loop is:

1. Ingest or proxy production AI usage.
2. Resolve trusted cost from the pricing catalog.
3. Surface savings opportunities by lever.
4. Gate risky changes with evals, guardrails, approvals, and holdbacks.
5. Apply enabled policies in the proxy path.
6. Record evidence and savings attribution.
7. Show the proof ledger for finance and operations.

The savings levers represented in the app are:

- Smart routing
- Semantic cache
- Token trim
- Model downshift
- Batching

Guardrails are split into:

- Quality floors and auto-rollback controls.
- Budget rules.
- Alert rules.

Proof is split into:

- Savings accounting.
- Attribution.
- Data quality.
- Shareable reports.

## Useful References

- `docs/product/VARSTEN_PRODUCT_GUIDE.md` - product direction and buyer-facing
  explanations.
- `CLAUDE.md` - engineering/product constraints and agent guidance.
- `docs/design/SDK_FAILOPEN_DESIGN_FREEZE.md` - fail-open SDK contract.
- `docs/SMOKE_TESTS.md` - manual smoke checks.
