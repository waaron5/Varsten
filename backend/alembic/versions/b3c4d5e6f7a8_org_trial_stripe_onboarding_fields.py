"""organization trial, stripe, and onboarding-event fields

Revision ID: b3c4d5e6f7a8
Revises: a2b3c4d5e6f7
Create Date: 2026-06-29 12:00:00.000000

Additive only. Server defaults for plan_tier/subscription_status are left as
free/active; the self-serve trial is set explicitly in the signup path so seeded,
demo, and operator-created orgs are never silently turned into billable trials.
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "b3c4d5e6f7a8"
down_revision: str | Sequence[str] | None = "a2b3c4d5e6f7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("organizations", sa.Column("trial_started_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("organizations", sa.Column("stripe_customer_id", sa.String(length=64), nullable=True))
    op.add_column("organizations", sa.Column("stripe_subscription_id", sa.String(length=64), nullable=True))
    op.add_column(
        "organizations",
        sa.Column("integration_snippet_viewed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column("organizations", sa.Column("dashboard_entered_at", sa.DateTime(timezone=True), nullable=True))
    op.create_unique_constraint(
        "uq_organizations_stripe_customer_id", "organizations", ["stripe_customer_id"]
    )


def downgrade() -> None:
    op.drop_constraint("uq_organizations_stripe_customer_id", "organizations", type_="unique")
    op.drop_column("organizations", "dashboard_entered_at")
    op.drop_column("organizations", "integration_snippet_viewed_at")
    op.drop_column("organizations", "stripe_subscription_id")
    op.drop_column("organizations", "stripe_customer_id")
    op.drop_column("organizations", "trial_started_at")
