.PHONY: sync-prices demo-seed migrate test

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
