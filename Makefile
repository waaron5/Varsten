.PHONY: sync-prices migrate test

# Refresh the pricing catalog from the public feed (manual for now; cron later).
sync-prices:
	cd backend && uv run python -m scripts.sync_prices

# Apply database migrations.
migrate:
	cd backend && uv run alembic upgrade head

# Run the backend test suite.
test:
	cd backend && uv run pytest
