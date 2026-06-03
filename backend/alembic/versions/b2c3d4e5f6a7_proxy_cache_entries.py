"""proxy cache entries

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-06-03 19:00:00.000000

The semantic-cache store for the Phase 1 inline proxy.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "b2c3d4e5f6a7"
down_revision: Union[str, Sequence[str], None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "proxy_cache_entries",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("cache_key", sa.String(length=64), nullable=False),
        sa.Column("model", sa.String(length=128), nullable=False),
        sa.Column("response_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("input_tokens", sa.BigInteger(), server_default=sa.text("0"), nullable=False),
        sa.Column("output_tokens", sa.BigInteger(), server_default=sa.text("0"), nullable=False),
        sa.Column("hit_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("last_hit_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", "cache_key", name="uq_proxy_cache_project_key"),
    )


def downgrade() -> None:
    op.drop_table("proxy_cache_entries")
