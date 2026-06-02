"""engine control plane schema

Revision ID: d6e7f8a9b0c1
Revises: c4d5e6f7a8b9
Create Date: 2026-06-02 16:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d6e7f8a9b0c1"
down_revision: Union[str, Sequence[str], None] = "c4d5e6f7a8b9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")

    op.add_column("recommendations", sa.Column("lever", sa.String(length=32), nullable=True))
    op.add_column("recommendations", sa.Column("target_type", sa.String(length=32), nullable=True))
    op.add_column("recommendations", sa.Column("target_key", sa.String(length=255), nullable=True))
    op.add_column("recommendations", sa.Column("rationale", sa.Text(), nullable=True))
    op.add_column(
        "recommendations", sa.Column("monthly_request_volume", sa.BigInteger(), nullable=True)
    )
    op.add_column(
        "recommendations", sa.Column("quality_delta_percent", sa.Numeric(precision=8, scale=4), nullable=True)
    )
    op.add_column(
        "recommendations",
        sa.Column(
            "measurement_method",
            sa.String(length=32),
            server_default=sa.text("'estimated'"),
            nullable=False,
        ),
    )
    op.execute(
        """
        UPDATE recommendations
        SET status = 'applied'
        WHERE status IN ('accepted', 'implemented', 'verified')
        """
    )
    op.create_index(
        "ix_recommendations_project_lever",
        "recommendations",
        ["project_id", "lever"],
        unique=False,
    )
    op.create_index(
        "ix_recommendations_project_target",
        "recommendations",
        ["project_id", "target_type", "target_key"],
        unique=False,
    )

    op.create_table(
        "lever_configs",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("lever", sa.String(length=32), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("automation_mode", sa.String(length=16), server_default=sa.text("'approve'"), nullable=False),
        sa.Column("savings_to_date_usd", sa.Numeric(precision=18, scale=8), server_default=sa.text("0"), nullable=False),
        sa.Column("quality_delta_percent", sa.Numeric(precision=8, scale=4), nullable=True),
        sa.Column("paused_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", "lever", name="uq_lever_configs_project_lever"),
    )
    op.create_index(
        "ix_lever_configs_project_enabled",
        "lever_configs",
        ["project_id", "enabled"],
        unique=False,
    )
    op.execute(
        """
        INSERT INTO lever_configs (
            id,
            organization_id,
            project_id,
            lever,
            enabled,
            automation_mode,
            savings_to_date_usd,
            created_at,
            updated_at
        )
        SELECT
            gen_random_uuid(),
            p.organization_id,
            p.id,
            levers.lever,
            true,
            levers.automation_mode,
            0,
            now(),
            now()
        FROM projects p
        CROSS JOIN (
            VALUES
                ('smart_routing', 'approve'),
                ('semantic_cache', 'auto'),
                ('token_trim', 'auto'),
                ('cheaper_model', 'approve'),
                ('batching', 'auto')
        ) AS levers(lever, automation_mode)
        ON CONFLICT ON CONSTRAINT uq_lever_configs_project_lever DO NOTHING
        """
    )

    op.create_table(
        "recommendation_actions",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("recommendation_id", sa.UUID(), nullable=True),
        sa.Column("actor_user_id", sa.UUID(), nullable=True),
        sa.Column("lever", sa.String(length=32), nullable=True),
        sa.Column("action_type", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("source", sa.String(length=16), server_default=sa.text("'system'"), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.Column("estimated_savings_usd", sa.Numeric(precision=18, scale=8), nullable=True),
        sa.Column("realized_savings_usd", sa.Numeric(precision=18, scale=8), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["recommendation_id"], ["recommendations.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_recommendation_actions_project_occurred_at",
        "recommendation_actions",
        ["project_id", "occurred_at"],
        unique=False,
    )
    op.create_index(
        "ix_recommendation_actions_project_lever",
        "recommendation_actions",
        ["project_id", "lever"],
        unique=False,
    )

    op.create_table(
        "savings_attributions",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("recommendation_id", sa.UUID(), nullable=True),
        sa.Column("action_id", sa.UUID(), nullable=True),
        sa.Column("lever", sa.String(length=32), nullable=True),
        sa.Column("measurement_method", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), server_default=sa.text("'estimated'"), nullable=False),
        sa.Column("period_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("period_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("counterfactual_spend_usd", sa.Numeric(precision=18, scale=8), nullable=True),
        sa.Column("actual_spend_usd", sa.Numeric(precision=18, scale=8), nullable=True),
        sa.Column("gross_savings_usd", sa.Numeric(precision=18, scale=8), server_default=sa.text("0"), nullable=False),
        sa.Column("varsten_fee_usd", sa.Numeric(precision=18, scale=8), server_default=sa.text("0"), nullable=False),
        sa.Column("net_savings_usd", sa.Numeric(precision=18, scale=8), server_default=sa.text("0"), nullable=False),
        sa.Column("confidence_low_usd", sa.Numeric(precision=18, scale=8), nullable=True),
        sa.Column("confidence_high_usd", sa.Numeric(precision=18, scale=8), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["action_id"], ["recommendation_actions.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["recommendation_id"], ["recommendations.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_savings_attributions_project_period",
        "savings_attributions",
        ["project_id", "period_start", "period_end"],
        unique=False,
    )
    op.create_index(
        "ix_savings_attributions_project_lever",
        "savings_attributions",
        ["project_id", "lever"],
        unique=False,
    )

    op.create_table(
        "quality_guardrails",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("route", sa.String(length=255), nullable=False),
        sa.Column("min_model_tier", sa.String(length=64), nullable=True),
        sa.Column("eval_gate", sa.String(length=128), nullable=True),
        sa.Column("min_eval_score", sa.Numeric(precision=8, scale=4), nullable=True),
        sa.Column("max_latency_ms", sa.Integer(), nullable=True),
        sa.Column("auto_rollback_enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", "route", name="uq_quality_guardrails_project_route"),
    )

    op.create_table(
        "budget_rules",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("owner_type", sa.String(length=32), nullable=False),
        sa.Column("owner_key", sa.String(length=255), nullable=False),
        sa.Column("monthly_budget_usd", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("hard_cap_enabled", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", "owner_type", "owner_key", name="uq_budget_rules_project_owner"),
    )
    op.create_index(
        "ix_budget_rules_project_owner_type",
        "budget_rules",
        ["project_id", "owner_type"],
        unique=False,
    )

    op.create_table(
        "alert_rules",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("alert_type", sa.String(length=64), nullable=False),
        sa.Column("threshold_usd", sa.Numeric(precision=18, scale=2), nullable=True),
        sa.Column("threshold_percent", sa.Numeric(precision=8, scale=4), nullable=True),
        sa.Column("destination_type", sa.String(length=32), nullable=False),
        sa.Column("destination", sa.String(length=255), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_alert_rules_project_enabled",
        "alert_rules",
        ["project_id", "enabled"],
        unique=False,
    )

    op.create_table(
        "customer_economics",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("customer_id", sa.String(length=255), nullable=False),
        sa.Column("customer_name", sa.String(length=255), nullable=True),
        sa.Column("revenue_usd", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("period_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("period_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "project_id",
            "customer_id",
            "period_start",
            "period_end",
            name="uq_customer_economics_project_customer_period",
        ),
    )
    op.create_index(
        "ix_customer_economics_project_customer",
        "customer_economics",
        ["project_id", "customer_id"],
        unique=False,
    )

    op.create_table(
        "provider_connections",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("connection_method", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), server_default=sa.text("'not_connected'"), nullable=False),
        sa.Column("last_sync_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", "provider", name="uq_provider_connections_project_provider"),
    )


def downgrade() -> None:
    op.drop_table("provider_connections")

    op.drop_index("ix_customer_economics_project_customer", table_name="customer_economics")
    op.drop_table("customer_economics")

    op.drop_index("ix_alert_rules_project_enabled", table_name="alert_rules")
    op.drop_table("alert_rules")

    op.drop_index("ix_budget_rules_project_owner_type", table_name="budget_rules")
    op.drop_table("budget_rules")

    op.drop_table("quality_guardrails")

    op.drop_index("ix_savings_attributions_project_lever", table_name="savings_attributions")
    op.drop_index("ix_savings_attributions_project_period", table_name="savings_attributions")
    op.drop_table("savings_attributions")

    op.drop_index("ix_recommendation_actions_project_lever", table_name="recommendation_actions")
    op.drop_index("ix_recommendation_actions_project_occurred_at", table_name="recommendation_actions")
    op.drop_table("recommendation_actions")

    op.drop_index("ix_lever_configs_project_enabled", table_name="lever_configs")
    op.drop_table("lever_configs")

    op.drop_index("ix_recommendations_project_target", table_name="recommendations")
    op.drop_index("ix_recommendations_project_lever", table_name="recommendations")
    op.drop_column("recommendations", "measurement_method")
    op.drop_column("recommendations", "quality_delta_percent")
    op.drop_column("recommendations", "monthly_request_volume")
    op.drop_column("recommendations", "rationale")
    op.drop_column("recommendations", "target_key")
    op.drop_column("recommendations", "target_type")
    op.drop_column("recommendations", "lever")
