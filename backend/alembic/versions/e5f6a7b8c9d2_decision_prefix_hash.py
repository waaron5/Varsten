"""request decision cacheable-prefix fingerprint

Revision ID: e5f6a7b8c9d2
Revises: d4e5f6a7b8c1
Create Date: 2026-07-03 15:00:00.000000

Adds the content-free stable-prefix hash to the decision ledger so prompt-cache
recommendations can use a route's *measured* prefix stability instead of a flat
assumption. Hash only (sha256[:16] of system/tools), never content. Nullable and
backfill-free.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e5f6a7b8c9d2"
down_revision: Union[str, Sequence[str], None] = "d4e5f6a7b8c1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("request_decision_events", sa.Column("prefix_hash", sa.String(length=64), nullable=True))


def downgrade() -> None:
    op.drop_column("request_decision_events", "prefix_hash")
