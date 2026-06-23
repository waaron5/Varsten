"""usage_events.source discriminator (proxy | ingest)

Revision ID: a2b3c4d5e6f7
Revises: f0a1b2c3d4e5
Create Date: 2026-06-23 12:00:00.000000

Adds a first-class `source` column so proxy analytics stop overloading the
`feature` business dimension. Historically the proxy ledger wrote
`metadata->>'proxy' = 'true'` on every event it produced, so that flag is the
authoritative backfill signal: every existing proxy row carries it, every
ingested row does not.

Forward path:
  1. Add `source` NOT NULL DEFAULT 'ingest' (existing rows become 'ingest'
     immediately, so the NOT NULL constraint is satisfied without a table rewrite
     gap).
  2. Backfill `source = 'proxy'` for the historical proxy rows via the metadata
     flag.
  3. Add the (project_id, source, received_at DESC) index that the /proxy-traffic
     query now filters on.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a2b3c4d5e6f7"
down_revision: str | Sequence[str] | None = "f0a1b2c3d4e5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "usage_events",
        sa.Column("source", sa.String(length=16), nullable=False, server_default=sa.text("'ingest'")),
    )
    # Backfill historical proxy traffic from the metadata flag the proxy ledger has
    # always written. Ingested rows lack the flag and correctly stay 'ingest'.
    op.execute(
        """
        UPDATE usage_events
        SET source = 'proxy'
        WHERE metadata ->> 'proxy' = 'true'
        """
    )
    op.create_index(
        "ix_usage_events_project_source_received_at",
        "usage_events",
        ["project_id", "source", sa.text("received_at DESC")],
    )


def downgrade() -> None:
    op.drop_index("ix_usage_events_project_source_received_at", table_name="usage_events")
    op.drop_column("usage_events", "source")
