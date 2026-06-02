"""monthly reports

Revision ID: f7a8b9c0d1e2
Revises: d6e7f8a9b0c1
Create Date: 2026-06-02 20:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f7a8b9c0d1e2"
down_revision: Union[str, Sequence[str], None] = "d6e7f8a9b0c1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "monthly_reports",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("period_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("period_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("executive_summary", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=32), server_default=sa.text("'draft'"), nullable=False),
        sa.Column("share_token", sa.String(length=96), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("counterfactual_spend_usd", sa.Numeric(precision=18, scale=8), server_default=sa.text("0"), nullable=False),
        sa.Column("actual_spend_usd", sa.Numeric(precision=18, scale=8), server_default=sa.text("0"), nullable=False),
        sa.Column("gross_savings_usd", sa.Numeric(precision=18, scale=8), server_default=sa.text("0"), nullable=False),
        sa.Column("varsten_fee_usd", sa.Numeric(precision=18, scale=8), server_default=sa.text("0"), nullable=False),
        sa.Column("net_savings_usd", sa.Numeric(precision=18, scale=8), server_default=sa.text("0"), nullable=False),
        sa.Column("trust_score", sa.Numeric(precision=8, scale=4), nullable=True),
        sa.Column("priced_event_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("unpriced_event_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("requests_month", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("metadata_quality", sa.JSON(), server_default=sa.text("'{}'"), nullable=False),
        sa.Column("attribution_rows", sa.JSON(), server_default=sa.text("'[]'"), nullable=False),
        sa.Column("top_recommendations", sa.JSON(), server_default=sa.text("'[]'"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", "period_start", "period_end", name="uq_monthly_reports_project_period"),
        sa.UniqueConstraint("share_token", name="uq_monthly_reports_share_token"),
    )
    op.create_index(
        "ix_monthly_reports_project_period",
        "monthly_reports",
        ["project_id", "period_start", "period_end"],
        unique=False,
    )
    op.create_index(
        "ix_monthly_reports_share_token",
        "monthly_reports",
        ["share_token"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_monthly_reports_share_token", table_name="monthly_reports")
    op.drop_index("ix_monthly_reports_project_period", table_name="monthly_reports")
    op.drop_table("monthly_reports")
