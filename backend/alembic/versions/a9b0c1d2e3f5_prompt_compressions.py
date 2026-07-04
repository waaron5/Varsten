"""prompt compression artifacts

Revision ID: a9b0c1d2e3f5
Revises: f8a9b0c1d2e3
Create Date: 2026-07-03 20:00:00.000000

The learned prompt-compression lever's artifact store: the compressed rewrite
(a documented content-store exception, like the semantic cache) plus the exact
hash of the original it may replace. See app/models/compression.py.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "a9b0c1d2e3f5"
down_revision: Union[str, Sequence[str], None] = "f8a9b0c1d2e3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "prompt_compressions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "organization_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "recommendation_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("recommendations.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("route_key", sa.String(128), nullable=False),
        sa.Column("model", sa.String(128), nullable=False),
        sa.Column("original_system_hash", sa.String(64), nullable=False),
        sa.Column("original_chars", sa.Integer(), nullable=False),
        sa.Column("compressed_system_prompt", sa.Text(), nullable=False),
        sa.Column("compressed_chars", sa.Integer(), nullable=False),
        sa.Column("generator", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_prompt_compressions_project_route", "prompt_compressions", ["project_id", "route_key"])
    op.create_index("ix_prompt_compressions_recommendation", "prompt_compressions", ["recommendation_id"])


def downgrade() -> None:
    op.drop_index("ix_prompt_compressions_recommendation", table_name="prompt_compressions")
    op.drop_index("ix_prompt_compressions_project_route", table_name="prompt_compressions")
    op.drop_table("prompt_compressions")
