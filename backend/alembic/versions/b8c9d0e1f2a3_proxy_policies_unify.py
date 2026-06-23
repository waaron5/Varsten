"""unify proxy execution rules into proxy_policies

Revision ID: b8c9d0e1f2a3
Revises: a7b8c9d0e1f2
Create Date: 2026-06-05 10:00:00.000000

One generic execution-policy table backs every lever the data plane runs on the
hot path, replacing the model-downshift-only proxy_routing_rules. Existing routing
rules are migrated in: target_key = incumbent model, params = {candidate_model},
lever taken from the sourcing recommendation (default model_downshift).
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "b8c9d0e1f2a3"
down_revision: Union[str, Sequence[str], None] = "a7b8c9d0e1f2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "proxy_policies",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("lever", sa.String(length=32), nullable=False),
        sa.Column("target_type", sa.String(length=32), nullable=False, server_default=sa.text("'model'")),
        sa.Column("target_key", sa.String(length=255), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("holdback_percent", sa.Numeric(5, 4), nullable=False, server_default=sa.text("0.05")),
        sa.Column("params", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("source_recommendation_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_recommendation_id"], ["recommendations.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("project_id", "lever", "target_key", name="uq_policies_project_lever_target"),
    )
    op.create_index("ix_policies_project_lever_enabled", "proxy_policies", ["project_id", "lever", "enabled"])
    op.create_index("ix_policies_project_enabled", "proxy_policies", ["project_id", "enabled"])

    # Migrate existing model-downshift / smart-routing rules into the unified table.
    op.execute(
        """
        INSERT INTO proxy_policies (
            id, organization_id, project_id, lever, target_type, target_key,
            enabled, holdback_percent, params, source_recommendation_id,
            activated_at, created_at, updated_at
        )
        SELECT
            r.id, r.organization_id, r.project_id,
            COALESCE(rec.lever, 'model_downshift'),
            'model', r.incumbent_model,
            r.enabled, r.holdback_percent,
            jsonb_build_object('candidate_model', r.candidate_model),
            r.source_recommendation_id, r.activated_at, r.created_at, r.updated_at
        FROM proxy_routing_rules r
        LEFT JOIN recommendations rec ON rec.id = r.source_recommendation_id
        """
    )

    op.drop_index("ix_routing_project_enabled", table_name="proxy_routing_rules")
    op.drop_table("proxy_routing_rules")


def downgrade() -> None:
    op.create_table(
        "proxy_routing_rules",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("incumbent_model", sa.String(length=128), nullable=False),
        sa.Column("candidate_model", sa.String(length=128), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("holdback_percent", sa.Numeric(5, 4), nullable=False, server_default=sa.text("0.05")),
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
    op.execute(
        """
        INSERT INTO proxy_routing_rules (
            id, organization_id, project_id, incumbent_model, candidate_model,
            enabled, holdback_percent, source_recommendation_id, activated_at,
            created_at, updated_at
        )
        SELECT
            id, organization_id, project_id, target_key,
            COALESCE(params->>'candidate_model', ''),
            enabled, holdback_percent, source_recommendation_id, activated_at,
            created_at, updated_at
        FROM proxy_policies
        WHERE lever IN ('model_downshift', 'smart_routing')
        """
    )
    op.drop_index("ix_policies_project_enabled", table_name="proxy_policies")
    op.drop_index("ix_policies_project_lever_enabled", table_name="proxy_policies")
    op.drop_table("proxy_policies")
