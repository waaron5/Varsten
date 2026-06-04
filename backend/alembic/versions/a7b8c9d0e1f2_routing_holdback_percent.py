"""routing holdback percent (live A/B arm split)

Revision ID: a7b8c9d0e1f2
Revises: f6a7b8c9d0e1
Create Date: 2026-06-04 14:15:00.000000

Adds the per-route holdback fraction: the share of traffic kept on the incumbent
as the control arm, so savings are measured as a concurrent A/B rather than
modelled.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a7b8c9d0e1f2"
down_revision: Union[str, Sequence[str], None] = "f6a7b8c9d0e1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "proxy_routing_rules",
        sa.Column(
            "holdback_percent",
            sa.Numeric(5, 4),
            nullable=False,
            server_default=sa.text("0.05"),
        ),
    )


def downgrade() -> None:
    op.drop_column("proxy_routing_rules", "holdback_percent")
