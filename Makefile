.PHONY: up down logs sync-prices demo-seed seed-demo-tenant migrate test backend-check backend-lint backend-typecheck backend-test backend-security backend-complexity backend-audit backend-dead-code

# Bring up the full local stack (Postgres + API + frontend). The API container
# applies migrations on boot. First run builds the API image.
up:
	docker compose up --build

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

# Apply database migrations.
migrate:
	cd backend && .venv/bin/alembic upgrade head

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
