"""per-org governance enforcement flag

Revision ID: b2c3d4e5f6a8
Revises: a9b0c1d2e3f5
Create Date: 2026-07-04 10:00:00.000000

The enterprise "default-on approvals" option: when an organization sets
governance_enforced, gated levers require an approved ChangeRequest before
apply regardless of the global governance_change_requests_enabled default.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b2c3d4e5f6a8"
down_revision: Union[str, Sequence[str], None] = "a9b0c1d2e3f5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "organizations",
        sa.Column("governance_enforced", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )


def downgrade() -> None:
    op.drop_column("organizations", "governance_enforced")
