"""persist selected onboarding integration

Revision ID: a0b1c2d3e4f6
Revises: f9a0b1c2d3e4
Create Date: 2026-07-07 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a0b1c2d3e4f6"
down_revision: str | Sequence[str] | None = "f9a0b1c2d3e4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("organizations", sa.Column("onboarding_selected_path", sa.String(length=32), nullable=True))
    op.add_column("organizations", sa.Column("onboarding_selected_provider", sa.String(length=64), nullable=True))


def downgrade() -> None:
    op.drop_column("organizations", "onboarding_selected_provider")
    op.drop_column("organizations", "onboarding_selected_path")
