"""persist engine outcome priors

Revision ID: c3d4e5f6a7b9
Revises: c2d3e4f5a6b7
Create Date: 2026-07-02 23:10:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "c3d4e5f6a7b9"
down_revision: str | Sequence[str] | None = "c2d3e4f5a6b7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "engine_outcome_priors",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("lever", sa.String(length=32), nullable=False),
        sa.Column("task_type", sa.String(length=128), nullable=False),
        sa.Column("risk_level", sa.String(length=32), nullable=False),
        sa.Column("provider_requested", sa.String(length=64), nullable=False),
        sa.Column("model_requested", sa.String(length=128), nullable=False),
        sa.Column("provider_chosen", sa.String(length=64), nullable=False),
        sa.Column("model_chosen", sa.String(length=128), nullable=False),
        sa.Column("readiness_status", sa.String(length=32), nullable=False),
        sa.Column("sample_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("measured_savings_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("total_gross_savings_usd", sa.Numeric(precision=18, scale=8), nullable=True),
        sa.Column("average_gross_savings_usd", sa.Numeric(precision=18, scale=8), nullable=True),
        sa.Column("quality_pass_rate", sa.Numeric(precision=6, scale=4), nullable=True),
        sa.Column("feedback_acceptance_rate", sa.Numeric(precision=6, scale=4), nullable=True),
        sa.Column(
            "reason_codes",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("window_days", sa.Integer(), nullable=False),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "project_id",
            "lever",
            "task_type",
            "risk_level",
            "provider_requested",
            "model_requested",
            "provider_chosen",
            "model_chosen",
            name="uq_engine_outcome_priors_segment",
        ),
    )
    op.create_index(
        "ix_engine_outcome_priors_project_model_lever",
        "engine_outcome_priors",
        ["project_id", "model_requested", "lever"],
    )


def downgrade() -> None:
    op.drop_index("ix_engine_outcome_priors_project_model_lever", table_name="engine_outcome_priors")
    op.drop_table("engine_outcome_priors")
