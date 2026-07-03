"""change requests: the governance decision spine

Revision ID: f8a9b0c1d2e3
Revises: e6f7a8b9c0d3
Create Date: 2026-07-03 17:00:00.000000

One ChangeRequest per proposed model-swap change awaiting a named human's
decision, carrying the frozen evidence bundle and the decision record. See
app/models/governance.py and docs/design/PALANTIR_ONTOLOGY_DESIGN.md.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "f8a9b0c1d2e3"
down_revision: Union[str, Sequence[str], None] = "e6f7a8b9c0d3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "change_requests",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "organization_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "recommendation_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("recommendations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "eval_run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("eval_runs.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("lever", sa.String(32), nullable=False),
        sa.Column("route_key", sa.String(128), nullable=True),
        sa.Column("incumbent_model", sa.String(128), nullable=False),
        sa.Column("candidate_model", sa.String(128), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default=sa.text("'proposed'")),
        sa.Column("evidence", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column(
            "decided_by_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decision_rationale", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("project_id", "recommendation_id", name="uq_change_requests_project_recommendation"),
    )
    op.create_index("ix_change_requests_project_status", "change_requests", ["project_id", "status"])


def downgrade() -> None:
    op.drop_index("ix_change_requests_project_status", table_name="change_requests")
    op.drop_table("change_requests")
