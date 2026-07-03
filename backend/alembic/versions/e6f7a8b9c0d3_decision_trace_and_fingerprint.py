"""request decision trace id and whole-request fingerprint

Revision ID: e6f7a8b9c0d3
Revises: e5f6a7b8c9d2
Create Date: 2026-07-03 16:00:00.000000

Adds the client trace/session id (X-Varsten-Trace-Id) and a content-free
whole-request fingerprint to the decision ledger, so redundant LLM calls within
one agent workflow (agent loops) can be detected and recommended away. Ids and
hashes only, never content. Nullable and backfill-free.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e6f7a8b9c0d3"
down_revision: Union[str, Sequence[str], None] = "e5f6a7b8c9d2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("request_decision_events", sa.Column("trace_id", sa.String(length=128), nullable=True))
    op.add_column("request_decision_events", sa.Column("request_fingerprint", sa.String(length=64), nullable=True))
    op.create_index(
        "ix_request_decision_project_trace",
        "request_decision_events",
        ["project_id", "trace_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_request_decision_project_trace", table_name="request_decision_events")
    op.drop_column("request_decision_events", "request_fingerprint")
    op.drop_column("request_decision_events", "trace_id")
