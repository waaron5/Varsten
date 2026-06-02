"""metadata trust recommendations

Revision ID: c4d5e6f7a8b9
Revises: b2f7a1c9d3e4
Create Date: 2026-06-02 14:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c4d5e6f7a8b9"
down_revision: Union[str, Sequence[str], None] = "b2f7a1c9d3e4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("usage_events", sa.Column("organization_id", sa.UUID(), nullable=True))
    op.add_column("usage_events", sa.Column("api_key_id", sa.UUID(), nullable=True))
    op.add_column("usage_events", sa.Column("request_type", sa.String(length=64), nullable=True))
    op.add_column("usage_events", sa.Column("feature", sa.String(length=255), nullable=True))
    op.add_column("usage_events", sa.Column("customer_id", sa.String(length=255), nullable=True))
    op.add_column("usage_events", sa.Column("user_id", sa.String(length=255), nullable=True))
    op.add_column("usage_events", sa.Column("team", sa.String(length=255), nullable=True))
    op.add_column("usage_events", sa.Column("department", sa.String(length=255), nullable=True))
    op.add_column(
        "usage_events",
        sa.Column("environment", sa.String(length=64), server_default=sa.text("'unknown'"), nullable=False),
    )
    op.add_column("usage_events", sa.Column("latency_ms", sa.Integer(), nullable=True))
    op.add_column(
        "usage_events",
        sa.Column("success", sa.Boolean(), server_default=sa.text("true"), nullable=False),
    )
    op.add_column("usage_events", sa.Column("error_code", sa.String(length=128), nullable=True))
    op.add_column("usage_events", sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "usage_events",
        sa.Column("pricing_status", sa.String(length=32), server_default=sa.text("'priced'"), nullable=False),
    )

    op.execute(
        """
        UPDATE usage_events ue
        SET
            organization_id = p.organization_id,
            request_type = ue.operation,
            feature = ue.workflow,
            user_id = ue.external_user_id,
            occurred_at = COALESCE(ue.event_timestamp, ue.received_at),
            environment = COALESCE(NULLIF(ue.metadata->>'environment', ''), 'unknown'),
            team = NULLIF(ue.metadata->>'team', ''),
            department = NULLIF(ue.metadata->>'department', ''),
            customer_id = NULLIF(ue.metadata->>'customer_id', ''),
            pricing_status = 'priced',
            cost_source = CASE WHEN ue.cost_source = 'derived' THEN 'catalog' ELSE ue.cost_source END
        FROM projects p
        WHERE ue.project_id = p.id
        """
    )
    op.execute(
        """
        UPDATE usage_events
        SET success = CASE WHEN status = 'error' THEN false ELSE true END
        """
    )

    op.alter_column("usage_events", "organization_id", nullable=False)
    op.alter_column("usage_events", "cost_usd", nullable=True)
    op.create_foreign_key(
        "fk_usage_events_organization",
        "usage_events",
        "organizations",
        ["organization_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_usage_events_api_key",
        "usage_events",
        "api_keys",
        ["api_key_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_usage_events_project_feature_received_at",
        "usage_events",
        ["project_id", "feature", sa.literal_column("received_at DESC")],
        unique=False,
    )
    op.create_index(
        "ix_usage_events_project_customer_received_at",
        "usage_events",
        ["project_id", "customer_id", sa.literal_column("received_at DESC")],
        unique=False,
    )
    op.create_index(
        "ix_usage_events_project_environment_received_at",
        "usage_events",
        ["project_id", "environment", sa.literal_column("received_at DESC")],
        unique=False,
    )
    op.create_index(
        "ix_usage_events_project_request_type_received_at",
        "usage_events",
        ["project_id", "request_type", sa.literal_column("received_at DESC")],
        unique=False,
    )
    op.create_index(
        "ix_usage_events_project_pricing_status_received_at",
        "usage_events",
        ["project_id", "pricing_status", sa.literal_column("received_at DESC")],
        unique=False,
    )

    op.create_table(
        "recommendations",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("dedupe_key", sa.String(length=255), nullable=False),
        sa.Column("type", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("estimated_monthly_savings_usd", sa.Numeric(precision=18, scale=8), nullable=True),
        sa.Column("risk_level", sa.String(length=16), nullable=False),
        sa.Column("confidence", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=16), server_default=sa.text("'open'"), nullable=False),
        sa.Column("related_provider", sa.String(length=64), nullable=True),
        sa.Column("related_model", sa.String(length=128), nullable=True),
        sa.Column("related_feature", sa.String(length=255), nullable=True),
        sa.Column("related_customer_id", sa.String(length=255), nullable=True),
        sa.Column("related_environment", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", "dedupe_key", name="uq_recommendations_project_dedupe"),
    )
    op.create_index("ix_recommendations_project_status", "recommendations", ["project_id", "status"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_recommendations_project_status", table_name="recommendations")
    op.drop_table("recommendations")

    op.drop_index("ix_usage_events_project_pricing_status_received_at", table_name="usage_events")
    op.drop_index("ix_usage_events_project_request_type_received_at", table_name="usage_events")
    op.drop_index("ix_usage_events_project_environment_received_at", table_name="usage_events")
    op.drop_index("ix_usage_events_project_customer_received_at", table_name="usage_events")
    op.drop_index("ix_usage_events_project_feature_received_at", table_name="usage_events")
    op.drop_constraint("fk_usage_events_api_key", "usage_events", type_="foreignkey")
    op.drop_constraint("fk_usage_events_organization", "usage_events", type_="foreignkey")
    op.alter_column("usage_events", "cost_usd", nullable=False)

    op.drop_column("usage_events", "pricing_status")
    op.drop_column("usage_events", "occurred_at")
    op.drop_column("usage_events", "error_code")
    op.drop_column("usage_events", "success")
    op.drop_column("usage_events", "latency_ms")
    op.drop_column("usage_events", "environment")
    op.drop_column("usage_events", "department")
    op.drop_column("usage_events", "team")
    op.drop_column("usage_events", "user_id")
    op.drop_column("usage_events", "customer_id")
    op.drop_column("usage_events", "feature")
    op.drop_column("usage_events", "request_type")
    op.drop_column("usage_events", "api_key_id")
    op.drop_column("usage_events", "organization_id")
