# Varsten

Varsten is an AI cost-control platform for production LLM traffic. It proxies
requests to model providers, measures their cost, identifies savings
opportunities, applies approved optimizations, and records evidence behind the
savings.

> Varsten is under active development. The repository supports local development
> and demos; it is not presented as a finished production service.

## What's included

- `backend/` — FastAPI API, LLM proxy, optimization engine, and PostgreSQL data
  layer.
- `frontend/` — authenticated Next.js dashboard.
- `marketing/` — public Next.js website.
- `sdk/` — fail-open TypeScript wrappers for OpenAI, Anthropic, and Gemini.
- `infra/aws/` — Terraform and deployment tooling for AWS.
- `docs/` — architecture, operations, security, and product documentation.

The proxy supports OpenAI-compatible chat completions, Anthropic Messages, and
Gemini content generation. Current optimization work includes routing, semantic
caching, token trimming, model downshifting, and batching. The SDK wrappers can
bypass Varsten and call the provider directly when Varsten is unavailable.

## Run locally

Prerequisites: Docker, Python 3.13, [`uv`](https://docs.astral.sh/uv/), Node.js
22, and npm.

Start PostgreSQL, Redis, the API, and the dashboard:

```bash
docker compose up --build -d
```

- Dashboard: <http://localhost:3000>
- API: <http://localhost:8000>
- API health: <http://localhost:8000/health>

Stop the stack with `docker compose down`.

For the guided local demo:

```bash
make walkthrough
```

See [the walkthrough](docs/SELF_SERVE_WALKTHROUGH.md) for details and
[frontend/README.md](frontend/README.md) for Auth0 setup.

## Develop and verify

```bash
# Backend
cd backend
uv sync --dev
cd ..
make backend-check

# Dashboard
cd frontend
npm ci
npm run lint
npm run build

# SDKs
cd ../sdk
npm ci
npm test
npm run typecheck
```

The marketing site has the same `npm ci`, `npm run lint`, and `npm run build`
workflow from `marketing/`.

## Important limitations

- The AWS infrastructure still requires a reviewed first production deployment
  and recovery drill.
- Production integrations should use a fail-open SDK wrapper; changing only an
  SDK base URL cannot bypass Varsten during an outage.
- Billing is not yet a complete self-service subscription system.
- Inline proxy traffic passes request content through Varsten. Some features,
  such as evaluations and semantic caching, may store bounded content.

See [engine reliability boundaries](docs/ENGINE_RELIABILITY_BOUNDARIES.md),
[architecture](docs/ARCHITECTURE.md), and [security](docs/security/SECURITY.md)
for the current technical details.

## License

The SDK packages are licensed under Apache-2.0. No repository-wide license is
currently declared.
