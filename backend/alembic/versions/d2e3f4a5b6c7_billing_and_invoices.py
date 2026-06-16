"""subscription fields, gain-share config, and invoices

Revision ID: d2e3f4a5b6c7
Revises: c1d2e3f4a5b6
Create Date: 2026-06-16 16:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "d2e3f4a5b6c7"
down_revision: str | Sequence[str] | None = "c1d2e3f4a5b6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "organizations",
        sa.Column("subscription_status", sa.String(length=24), server_default=sa.text("'active'"), nullable=False),
    )
    op.add_column("organizations", sa.Column("plan_effective_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("organizations", sa.Column("trial_ends_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "organizations",
        sa.Column("gain_share_percent", sa.Numeric(precision=5, scale=4), server_default=sa.text("0.2000"), nullable=False),
    )
    op.add_column(
        "organizations",
        sa.Column("monthly_fee_floor_usd", sa.Numeric(precision=18, scale=2), server_default=sa.text("0"), nullable=False),
    )

    op.create_table(
        "invoices",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("period_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("period_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("verified_savings_usd", sa.Numeric(precision=18, scale=2), server_default=sa.text("0"), nullable=False),
        sa.Column("gain_share_percent", sa.Numeric(precision=5, scale=4), nullable=False),
        sa.Column("monthly_fee_floor_usd", sa.Numeric(precision=18, scale=2), server_default=sa.text("0"), nullable=False),
        sa.Column("fee_usd", sa.Numeric(precision=18, scale=2), server_default=sa.text("0"), nullable=False),
        sa.Column("net_savings_usd", sa.Numeric(precision=18, scale=2), server_default=sa.text("0"), nullable=False),
        sa.Column("currency", sa.String(length=8), server_default=sa.text("'USD'"), nullable=False),
        sa.Column("status", sa.String(length=16), server_default=sa.text("'draft'"), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("finalized_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "period_start", "period_end", name="uq_invoices_org_period"),
    )


def downgrade() -> None:
    op.drop_table("invoices")
    op.drop_column("organizations", "monthly_fee_floor_usd")
    op.drop_column("organizations", "gain_share_percent")
    op.drop_column("organizations", "trial_ends_at")
    op.drop_column("organizations", "plan_effective_at")
    op.drop_column("organizations", "subscription_status")
