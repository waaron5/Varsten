"""structured details on recommendations

Revision ID: d5e6f7a8b9c2
Revises: b2c3d4e5f6a8
Create Date: 2026-07-04 12:00:00.000000

Type-specific structured evidence for the UI (first user: the deterministic
prefix-restructure proposal's offsets and shares). Metrics and structure only,
never prompt/completion text — recommendations are a metadata-only store.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "d5e6f7a8b9c2"
down_revision: Union[str, Sequence[str], None] = "b2c3d4e5f6a8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "recommendations",
        sa.Column("details", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("recommendations", "details")
