#!/bin/sh
set -e

# Apply migrations before serving. Safe for a single instance. For multi-instance
# deploys, move this to a one-off release/job step so two booting replicas don't
# race on the same migration.
alembic upgrade head

exec "$@"
