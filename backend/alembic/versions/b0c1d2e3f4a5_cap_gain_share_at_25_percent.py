"""cap gain-share at 25 percent

Revision ID: b0c1d2e3f4a5
Revises: a0b1c2d3e4f7
Create Date: 2026-07-08 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "b0c1d2e3f4a5"
down_revision: str | Sequence[str] | None = "a0b1c2d3e4f7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        sa.text(
            "UPDATE organizations "
            "SET gain_share_percent = 0.2500 "
            "WHERE gain_share_percent > 0.2500"
        )
    )
    op.execute(
        sa.text(
            "UPDATE organizations "
            "SET gain_share_percent = 0 "
            "WHERE gain_share_percent < 0"
        )
    )
    op.create_check_constraint(
        "ck_organizations_gain_share_percent_0_to_25",
        "organizations",
        "gain_share_percent >= 0 AND gain_share_percent <= 0.2500",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_organizations_gain_share_percent_0_to_25",
        "organizations",
        type_="check",
    )
