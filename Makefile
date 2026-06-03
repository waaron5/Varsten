.PHONY: up down logs sync-prices demo-seed migrate test

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

# Apply database migrations.
migrate:
	cd backend && .venv/bin/alembic upgrade head

# Run the backend test suite.
test:
	cd backend && .venv/bin/python -m pytest
