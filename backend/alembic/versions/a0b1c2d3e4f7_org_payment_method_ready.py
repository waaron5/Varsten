"""track payment method readiness separately from active billing

Revision ID: a0b1c2d3e4f7
Revises: a0b1c2d3e4f6
Create Date: 2026-07-07 15:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a0b1c2d3e4f7"
down_revision: str | Sequence[str] | None = "a0b1c2d3e4f6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("organizations", sa.Column("payment_method_ready_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("organizations", "payment_method_ready_at")
