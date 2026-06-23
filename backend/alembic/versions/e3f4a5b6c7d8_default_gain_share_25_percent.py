"""default gain-share fee to 25 percent

Revision ID: e3f4a5b6c7d8
Revises: d2e3f4a5b6c7
Create Date: 2026-06-21 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "e3f4a5b6c7d8"
down_revision: str | Sequence[str] | None = "d2e3f4a5b6c7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Move orgs still on the former default to Varsten's current standard fee.
    # Non-default custom org overrides are intentionally preserved.
    op.execute(
        sa.text(
            "UPDATE organizations "
            "SET gain_share_percent = 0.2500 "
            "WHERE gain_share_percent = 0.2000"
        )
    )
    op.alter_column(
        "organizations",
        "gain_share_percent",
        existing_type=sa.Numeric(precision=5, scale=4),
        server_default=sa.text("0.2500"),
        existing_nullable=False,
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            "UPDATE organizations "
            "SET gain_share_percent = 0.2000 "
            "WHERE gain_share_percent = 0.2500"
        )
    )
    op.alter_column(
        "organizations",
        "gain_share_percent",
        existing_type=sa.Numeric(precision=5, scale=4),
        server_default=sa.text("0.2000"),
        existing_nullable=False,
    )
