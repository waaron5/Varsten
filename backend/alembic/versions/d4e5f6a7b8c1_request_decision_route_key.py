"""request decision canonical route key

Revision ID: d4e5f6a7b8c1
Revises: c3d4e5f6a7b9
Create Date: 2026-07-03 12:00:00.000000

Adds the canonical route key to the per-request decision ledger so learning
segments, eval runs, and guardrails can attach to one route identity
(feature|workflow|request_type|task_type|default). Nullable and backfill-free:
existing rows keep NULL and new decisions populate it.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "d4e5f6a7b8c1"
down_revision: Union[str, Sequence[str], None] = "c3d4e5f6a7b9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("request_decision_events", sa.Column("route_key", sa.String(length=128), nullable=True))
    op.create_index(
        "ix_request_decision_project_route_key",
        "request_decision_events",
        ["project_id", "route_key"],
    )


def downgrade() -> None:
    op.drop_index("ix_request_decision_project_route_key", table_name="request_decision_events")
    op.drop_column("request_decision_events", "route_key")
