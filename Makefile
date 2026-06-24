.PHONY: up down logs sync-prices demo-seed seed-demo-tenant migrate release-migrate test backend-check backend-lint backend-typecheck backend-test backend-security backend-complexity backend-audit backend-dead-code backend-sdk-smoke

# Bring up the full local stack (Postgres + API + frontend). The API container
# applies migrations on boot. First run builds the API image.
up:
	docker compose up --build -d

# Stop the stack. Add ARGS=-v to also drop the database volume.
down:
	docker compose down $(ARGS)

# Tail logs for all services.
logs:
	docker compose logs -f

# Refresh the pricing catalog from the public feed (manual for now; cron later).
sync-prices:
	cd backend && .venv/bin/python -m scripts.sync_prices

# Seed a deterministic local demo workspace with engine, proof, guardrail, and
# analysis data. Safe to rerun.
demo-seed:
	cd backend && .venv/bin/python -m scripts.seed_demo

# Seed the isolated demo TENANT with a fresh 30-day proxy narrative (Command
# Center). Destructive + idempotent: wipes and regenerates the is_demo org only.
# Pristine before every sales call. ARGS=--base 1000 to scale volume.
seed-demo-tenant:
	cd backend && .venv/bin/python -m scripts.seed_demo_tenant --yes $(ARGS)

# Apply database migrations (local dev DB).
migrate:
	cd backend && .venv/bin/alembic upgrade head

# Release migration: run `alembic upgrade head` inside a built image against a
# target database, the manual / pure-AWS equivalent of the deploy workflow's
# migrate job. Run this BEFORE promoting the matching image. Usage:
#   make release-migrate IMAGE=<ecr-repo>:<sha> DATABASE_URL=postgresql+psycopg://...
release-migrate:
	@test -n "$(IMAGE)" || (echo "set IMAGE=<repo>:<tag>" && exit 1)
	@test -n "$(DATABASE_URL)" || (echo "set DATABASE_URL=..." && exit 1)
	docker run --rm -e DATABASE_URL="$(DATABASE_URL)" "$(IMAGE)" alembic upgrade head

# Run the backend test suite.
test:
	cd backend && .venv/bin/python -m pytest

# Run the backend quality gate used before merging code changes.
backend-check: backend-lint backend-typecheck backend-complexity backend-security backend-test

# Lint, import-sort, format-check, and Python syntax sanity.
backend-lint:
	cd backend && .venv/bin/ruff check .
	cd backend && .venv/bin/ruff format --check .
	cd backend && .venv/bin/python -m compileall -q app scripts tests

# Gradual static typing pass. Configured to check function bodies without
# requiring every legacy function to be fully annotated up front.
backend-typecheck:
	cd backend && .venv/bin/mypy app scripts tests

# Run tests with branch coverage and the configured minimum threshold.
backend-test:
	cd backend && .venv/bin/python -m pytest --cov=app --cov=scripts

# Opt-in live SDK smoke tests. Requires a running Varsten API, a vk_ API key,
# installed official SDKs, and configured upstream provider keys for the project.
backend-sdk-smoke:
	cd backend && .venv/bin/python -m pytest -m sdk_smoke tests/test_sdk_smoke.py

# End-to-end fail-open smoke test: real @varsten/openai SDK -> real backend ->
# mock provider, exercising optimized, provider-error relay, telemetry, and the
# backend-down + circuit-open fallback paths. Self-contained: seeds and tears down
# its own project, stands up the backend and a mock upstream, builds the SDK.
# Needs the dev Postgres (docker compose up db) and Node installed.
failopen-smoke:
	cd backend && .venv/bin/python scripts/smoke_failopen.py

# Static security scan for application code. Dependency vulnerability auditing
# lives in backend-audit because it may need network access.
backend-security:
	cd backend && .venv/bin/bandit -q -c pyproject.toml -r app scripts

# Flag high-complexity functions that should be split before they become hard
# to test. Grade B allows moderate branching in API handlers and orchestrators.
backend-complexity:
	cd backend && .venv/bin/radon cc app scripts -s -nb
	cd backend && .venv/bin/python -m scripts.check_complexity

# Slower or noisier audits that are useful before releases and in CI.
backend-audit:
	cd backend && .venv/bin/deptry app scripts --config pyproject.toml
	cd backend && .venv/bin/pip-audit --cache-dir .cache/pip-audit

# Dead-code candidate scan. Review findings before deleting; FastAPI routes and
# framework entry points can look unused to static analyzers.
backend-dead-code:
	cd backend && .venv/bin/vulture
