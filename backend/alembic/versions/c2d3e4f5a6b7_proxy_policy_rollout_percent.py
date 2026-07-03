"""proxy policy canary rollout percent

Revision ID: c2d3e4f5a6b7
Revises: b3c4d5e6f7a8
Create Date: 2026-07-02 22:05:00.000000

Adds the per-policy canary rollout percent: the share of a policy's eligible
traffic it is actually applied to. Defaults to 100 so every existing policy stays
fully live; a canary activation starts low and the drift sweep ramps it up stage
by stage once each stage shows no quality or latency regression.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c2d3e4f5a6b7"
down_revision: Union[str, Sequence[str], None] = "b3c4d5e6f7a8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "proxy_policies",
        sa.Column(
            "rollout_percent",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("100"),
        ),
    )


def downgrade() -> None:
    op.drop_column("proxy_policies", "rollout_percent")
