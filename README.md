# Varsten

Varsten is a SaaS platform for AI spend visibility. It helps engineering teams track LLM usage, understand where AI costs are coming from, and build toward explainable optimization.

The first version is intentionally small: multi-tenant projects, API keys, a usage ingestion endpoint, raw usage records, and dashboards for spend, tokens, providers, models, and workflows.

## MVP Scope

In:

- FastAPI backend
- PostgreSQL via Docker Compose
- API-key authenticated usage ingestion
- Pydantic validation
- SQL-backed analytics APIs
- Dashboard and usage explorer

Out for v1:

- automatic model routing
- budget enforcement
- alerts
- provider integrations
- SDKs
- billing

## Local Development

Start Postgres:

```bash
docker compose up db
```

Run the API from `backend/`:

```bash
uv run uvicorn app.main:app --reload
```

Health check:

```bash
curl http://localhost:8000/health
```

## Product Direction

Phase 1 is visibility: track usage, costs, providers, models, tokens, and trends. Recommendations, controls, and automation come later after the data foundation is trustworthy.

The mockups in `references/` show the broader product vision, including some post-MVP concepts. They are useful for design direction, but `CLAUDE.md` and the MVP scope above are the source of truth for the step-by-step build.
