#!/bin/sh
set -e

# NO migrations on boot. The schema is migrated by an explicit release step that
# runs BEFORE new instances are promoted (see .github/workflows/deploy.yml and the
# "Horizontal scaling" runbook in infra/aws/README.md). API containers boot
# assuming the schema is already current, so multiple replicas can start in
# parallel without racing `alembic upgrade head` against each other.
#
# This entrypoint is a thin pass-through, which lets the SAME image run the
# migration as a one-off command in the release step:
#   docker run --rm -e DATABASE_URL=... <image> alembic upgrade head
exec "$@"
