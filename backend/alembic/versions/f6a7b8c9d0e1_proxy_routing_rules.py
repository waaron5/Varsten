"""proxy routing rules (cheaper-model lever execution)

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-06-04 13:30:00.000000

Active inline model-routing rules. When an eval-passed cheaper-model
recommendation is applied, a rule is activated here and the proxy rewrites the
matching requests to the cheaper candidate model.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "f6a7b8c9d0e1"
down_revision: Union[str, Sequence[str], None] = "e5f6a7b8c9d0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "proxy_routing_rules",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("incumbent_model", sa.String(length=128), nullable=False),
        sa.Column("candidate_model", sa.String(length=128), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("source_recommendation_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_recommendation_id"], ["recommendations.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("project_id", "incumbent_model", name="uq_routing_project_incumbent"),
    )
    op.create_index("ix_routing_project_enabled", "proxy_routing_rules", ["project_id", "enabled"])


def downgrade() -> None:
    op.drop_index("ix_routing_project_enabled", table_name="proxy_routing_rules")
    op.drop_table("proxy_routing_rules")
