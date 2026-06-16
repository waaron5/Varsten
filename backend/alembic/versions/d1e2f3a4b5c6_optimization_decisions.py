"""optimization decisions

Revision ID: d1e2f3a4b5c6
Revises: c5f6a7b8c9d0
Create Date: 2026-06-15 12:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "d1e2f3a4b5c6"
down_revision: str | Sequence[str] | None = "c5f6a7b8c9d0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "optimization_decisions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("request_id", sa.String(length=128), nullable=False),
        sa.Column("client_dialect", sa.String(length=32), nullable=False),
        sa.Column("requested_provider", sa.String(length=64), nullable=False),
        sa.Column("requested_model", sa.String(length=255), nullable=False),
        sa.Column("candidate_provider", sa.String(length=64), nullable=False),
        sa.Column("candidate_model", sa.String(length=255), nullable=False),
        sa.Column("decision", sa.String(length=32), nullable=False),
        sa.Column("reason_code", sa.String(length=64), nullable=False),
        sa.Column(
            "reason_detail",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_optimization_decisions_project_created_at",
        "optimization_decisions",
        ["project_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_optimization_decisions_project_reason_code",
        "optimization_decisions",
        ["project_id", "reason_code"],
        unique=False,
    )
    op.create_index(
        "ix_optimization_decisions_project_request",
        "optimization_decisions",
        ["project_id", "request_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_optimization_decisions_project_request", table_name="optimization_decisions")
    op.drop_index("ix_optimization_decisions_project_reason_code", table_name="optimization_decisions")
    op.drop_index("ix_optimization_decisions_project_created_at", table_name="optimization_decisions")
    op.drop_table("optimization_decisions")
