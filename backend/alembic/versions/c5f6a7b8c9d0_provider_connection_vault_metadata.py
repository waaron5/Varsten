"""provider connection vault metadata

Revision ID: c5f6a7b8c9d0
Revises: d0e1f2a3b4c5
Create Date: 2026-06-14 18:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c5f6a7b8c9d0"
down_revision: Union[str, Sequence[str], None] = "d0e1f2a3b4c5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("provider_connections", sa.Column("secret_ref", sa.String(length=512), nullable=True))
    op.add_column("provider_connections", sa.Column("last_verified_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("provider_connections", sa.Column("last_error", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("provider_connections", "last_error")
    op.drop_column("provider_connections", "last_verified_at")
    op.drop_column("provider_connections", "secret_ref")
