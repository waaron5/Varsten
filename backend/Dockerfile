# Production image for the Varsten API.
# Build context is ./backend. The app runs from source on PYTHONPATH (it is an
# application, not a published package), so uv installs only the dependencies.
FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PATH=/app/.venv/bin:$PATH

# uv binary from its official image.
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

# Dependency layer first, cached until the lockfile changes.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# Application source.
COPY . .
RUN chmod +x /app/docker-entrypoint.sh

EXPOSE 8000
# The entrypoint does NOT run migrations (those are a decoupled release step, so
# replicas never race on boot). It is a thin pass-through, so the same image runs
# either the API (the default CMD) or, as a one-off release command, the migration:
#   docker run --rm -e DATABASE_URL=... <image> alembic upgrade head
ENTRYPOINT ["/app/docker-entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
