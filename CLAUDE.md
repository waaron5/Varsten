# CLAUDE.md

This file gives Claude persistent context for working on **Varsten**. Read it at the start of every session before suggesting anything.

## What Varsten is

Varsten is a SaaS platform that helps engineering teams understand, control, and reduce AI spending. A customer creates a project, generates an API key, sends AI usage records to an ingestion API, and views simple analytics about provider spend, model usage, token volume, workflows, and cost trends.

This is a portfolio / startup-style project. The goal is not to build a full AI optimization platform in v1. The goal is to build a credible, real piece of multi-tenant SaaS backend software that a CTO would look at and think "this person can ship."

The core product philosophy is: if you cannot measure AI spending, you cannot optimize it. Varsten should become excellent at measuring, tracking, analyzing, and explaining AI costs before it tries to automate optimization.

**Current phase: perfecting the base layer of cost calculation and savings estimation.** The visibility MVP (ingestion, multi-tenancy, dashboards) and the authoritative cost ledger (an owned, versioned pricing catalog that derives cost rather than trusting the client) are built. The work now is to make cost accuracy airtight and to lay the data foundation for savings estimation, before any automatic optimization gets built on top of it. Accuracy of measurement comes first; everything in Phase 2+ is only as trustworthy as this base.

## Why this project exists

I am a CS student at BYU relocating to NYC and actively job hunting for junior / mid full-stack roles, with a backend lean. Varsten is my main portfolio piece for that search. It needs to demonstrate that I can handle:

- Multi-tenancy
- API key authentication
- Event ingestion at non-trivial volume
- Pydantic request validation
- Relational database design and migrations
- Analytics-style SQL queries with reasonable indexes
- Cost calculation and explainable derived metrics
- A clean dashboard UI on top of a real backend
- Observability-minded backend design
- Infrastructure as code (later phase)

The product itself is a vehicle for showing those skills. Keep that framing in mind when weighing tradeoffs.

## The core product loop

This is the demo path. Everything else is secondary.

1. User signs in
2. User creates a project
3. User generates an API key
4. User copies a code snippet into their own app, agent, or backend service
5. Their app POSTs an AI usage record to the Varsten ingestion API
6. Varsten confirms usage records are arriving
7. The user can view spend dashboards and inspect raw usage records

The single most impressive moment is step 5 to 6: an external curl call lands in the database and shows up in the UI within seconds. Protect that experience.

### Example usage payload

```json
{
  "provider": "openai",
  "model": "gpt-4o-mini",
  "operation": "chat_completion",
  "external_user_id": "user_123",
  "workflow": "support_agent",
  "input_tokens": 1200,
  "cached_input_tokens": 800,
  "output_tokens": 340,
  "idempotency_key": "req_abc123",
  "metadata": {
    "team": "support",
    "environment": "production"
  }
}
```

Varsten now derives cost itself rather than trusting the client. Ingestion takes authoritative token counts and computes `cost_usd` from a versioned pricing catalog Varsten owns: a per-org override first, then the synced public catalog, pinned to the price version that was live at the event's time. Client `cost_usd` is optional. When sent it is stored as `reported_cost_usd` and used only as the fallback when the model is not in the catalog. A `cost_source` field (`derived` | `override` | `reported`) records which path produced the number, and the dashboard surfaces the share of spend that was derived vs reported. Prices are never hard-coded: they live in data, refreshed by a loader (`make sync-prices`) from a maintained feed, overridable per org, and versioned by effective date so history never mutates. This is what makes Varsten authoritative on spend instead of a mirror of the customer's math.

### Metrics the dashboard surfaces

- Spend today
- Spend this month
- Total requests today
- Input tokens and output tokens
- Cost trend over time
- Top providers by spend
- Top models by spend
- Top workflows or agents by spend
- Recently received usage records
- Average cost per request
- Most expensive users, teams, or workflows

## Stack

Backend:
- FastAPI
- Pydantic (v2)
- PostgreSQL (Aurora later in AWS phase)
- Alembic for migrations
- uv for Python dependency management
- OAuth for sign-in (likely Auth0 or Clerk, not rolling my own)

Infra:
- Docker + Docker Compose for local dev
- Terraform + AWS later, not in the initial two-week build

Frontend:
- Next.js or React with TypeScript
- I work professionally in Angular + tRPC + Prisma, so React is intentional learning here

## Scope: what's in the two-week MVP and what isn't

**In:**
- OAuth sign-in
- `organizations -> projects -> api_keys -> usage_events` schema with Alembic migrations
- `POST /v1/usage-events` with Bearer API key auth and Pydantic validation
- Setup screen with curl snippet and live "waiting / received" status
- Overview dashboard (4 stat cards, spend trend chart, top models, recent usage records)
- Usage explorer with filters (provider, model, workflow, date range, user ID) and a JSON detail drawer
- Providers/models/workflows page
- Settings page (org, projects, API keys, monthly AI spend)
- Docker Compose `make up` bringing up Postgres + API + frontend
- A small load test script in the repo with a throughput number in the README

**Out (mention in README roadmap, do not build):**
- Team invites, roles, billing, alerts
- Budget enforcement and spend limits
- Automatic model routing
- Automatic context optimization
- Cost-aware agent execution
- Provider API integrations
- SDKs (curl is the SDK for v1)
- Rate limiting beyond a simple per-key counter
- API key rotation flow (one key per project is fine for v1)

Design mockups may show final-product roadmap concepts such as recommendations, budgets, alerts, teams, and optimization workflows. Treat those as product-direction examples, not MVP implementation scope. The two-week MVP scope above remains the source of truth unless explicitly revised.

If I ask for something in the "out" list, push back and remind me of the scope before helping.

## Roadmap framing

Phase 1: Visibility
- Track usage
- Track costs
- Track models
- Track providers
- Monitor trends
- Provide dashboards and reporting

Phase 2: Intelligence
- Detect waste
- Estimate savings
- Identify inefficient workflows
- Recommend optimizations
- Surface unusual spending patterns

Phase 3: Control
- Budgets
- Alerts
- Guardrails
- Spend limits
- Policy enforcement

Phase 4: Optimization
- Intelligent routing
- Automatic model selection
- Context optimization
- Cost-aware agent execution
- Automated spend reduction

The current build sits at the Phase 1 / Phase 2 boundary: Phase 1 visibility is in place, and the focus now is hardening the cost-measurement base and building the data foundation Phase 2 savings estimation needs (catalog tier metadata, cheaper-substitute mapping, request status, cached/reasoning token capture). Do the measurement and estimation groundwork, but do not jump ahead to the recommendation engine, automatic routing, or any Phase 3/4 control or optimization work unless explicitly discussing roadmap.

## How I want Claude to work with me

**This is the most important section. Read it carefully.**

I am building this to learn, not to ship the fastest possible version. I am preparing for a job where I will need to architect and debug this kind of system myself. If Claude does the thinking for me, the project fails at its actual purpose even if the code works.

Specifically:

- **Do not write code unless I explicitly ask for it.** "Help me think through X," "what are the tradeoffs of Y," "review this approach" are not requests for code. Default to prose explanations.
- **When I do ask for code, prefer the smallest useful snippet.** Not a full file. Not a refactor. The piece I asked about.
- **Explain tradeoffs honestly.** If there are two reasonable approaches, say so and tell me when each is right. Don't pretend there's one obvious answer when there isn't.
- **Push back when I'm wrong.** If I'm about to make a bad architectural choice, say so directly. Don't soften it. I would rather hear "that will hurt you at 100k usage records/day because..." than a polite hedge.
- **Don't take over.** If I'm halfway through reasoning about something, let me finish. Ask what I'm thinking before jumping in with the answer.
- **Skip the pep talk.** No "great question," no "you're on the right track." Just engage with the substance.

When I want code written, I will say so plainly ("write the migration for X," "give me the SQL for daily spend by model"). Otherwise assume I want to discuss, not delegate.

## Communication preferences

- Short direct sentences. No em dashes.
- Confident peer tone, not eager-applicant tone.
- No filler praise. No restating what I said back to me before answering.
- Code blocks use the actual stack: Python with type hints and Pydantic v2 syntax; SQL in plain Postgres dialect; TypeScript not JavaScript on the frontend.

## Repo layout (target)

```text
varsten/
├── CLAUDE.md
├── README.md
├── docker-compose.yml
├── Makefile
├── backend/
│   ├── pyproject.toml          # uv
│   ├── alembic/
│   ├── app/
│   │   ├── main.py
│   │   ├── api/                # FastAPI routers
│   │   ├── models/             # SQLAlchemy
│   │   ├── schemas/            # Pydantic
│   │   ├── db/
│   │   └── auth/
│   └── tests/
├── frontend/
│   ├── package.json
│   ├── app/                    # Next.js app router
│   └── components/
└── infra/                      # Terraform, later
```

This is a target, not a contract. Open to changes if there's a real reason.

## Preferred build order

1. Backend health check
2. Docker Compose Postgres
3. SQLAlchemy models
4. Alembic migrations
5. Organizations/projects
6. API key generation and hashing
7. `POST /v1/usage-events`
8. Usage explorer API
9. Dashboard metrics API
10. Provider/model/workflow breakdown APIs
11. Minimal frontend
12. Auth polish
13. Tests/load test/README

## Database design notes (current thinking)

Tables: `organizations`, `users`, `org_memberships`, `projects`, `api_keys`, `usage_events`, plus the pricing layer: `model_catalog` (model identity, capabilities, tier, cheaper-substitute mapping), `model_prices` (versioned list prices by `effective_at`), `org_model_price_overrides` (per-org negotiated rates).

The `usage_events` table is the hot one. Columns:

- `project_id`
- `provider`
- `model`
- `operation`
- `external_user_id`
- `workflow`
- `input_tokens`
- `cached_input_tokens` (subset of input served from a provider prompt cache, billed cheaper)
- `reasoning_tokens` (stored for analytics; already inside output_tokens for billing)
- `output_tokens`
- `total_tokens`
- `cost_usd` (authoritative, from whichever source `cost_source` names)
- `reported_cost_usd` (the client-sent number, kept for drift cross-check)
- `cost_source` (`derived` | `override` | `reported`)
- `price_version_id` (the `model_prices` row that produced a derived cost)
- `currency` (USD only in v1; non-USD is rejected at ingestion)
- `idempotency_key` (unique per project; retries do not double-count)
- `status` (`success` | `error`)
- `metadata` JSONB
- `event_timestamp` (when the call happened on the client; distinct from receipt)
- `received_at`

Cost is derived in `app/pricing/` (override then catalog, latest `effective_at <= event time`). Analytics still bucket on `received_at`; moving the axis to `event_timestamp` is a tracked follow-up that needs index changes.

Indexes on `usage_events`:

- `(project_id, received_at DESC)` for recent usage and time-windowed counts
- `(project_id, provider, received_at DESC)` for provider breakdowns
- `(project_id, model, received_at DESC)` for model breakdowns
- `(project_id, workflow, received_at DESC)` for workflow or agent breakdowns
- `(project_id, external_user_id, received_at DESC)` for per-user queries

`metadata` is JSONB. No GIN index in v1 unless query patterns justify it.

API keys are stored as hashes, not plaintext. The plaintext is shown once at generation and never retrievable again.

Raw usage records are the source of truth. Do not denormalize or pre-aggregate until query pressure makes it necessary.

If I propose a schema change, evaluate it against these access patterns before agreeing.

## Things that should make Claude pause and ask

- If I propose adding a feature outside the MVP scope above
- If I propose a third-party service that costs money for a portfolio project
- If I propose denormalizing or pre-aggregating before I have a real query problem
- If I propose skipping tests on the ingestion endpoint
- If I propose hand-rolling auth instead of using a provider
- If I propose optimization or routing before the visibility layer is trustworthy

In any of these, ask me why before going along with it.

## Out-of-band context

- I work professionally in Angular / tRPC / Prisma / Postgres, so I'm comfortable in TypeScript and relational DB land. FastAPI, Pydantic, Alembic, and Next.js are the parts I'm actively learning.
- The NYC move and job hunt are the deadline pressure. I would rather have a smaller, polished, end-to-end-working version of Varsten than a half-built ambitious one. Bias toward "done" over "complete."
