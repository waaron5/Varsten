"""request decision evidence and outcome feedback

Revision ID: e1f2a3b4c5d6
Revises: d1e2f3a4b5c6
Create Date: 2026-06-15 16:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "e1f2a3b4c5d6"
down_revision: str | Sequence[str] | None = "d1e2f3a4b5c6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "request_decision_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("usage_event_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("api_key_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("request_id", sa.String(length=128), nullable=False),
        # request context
        sa.Column("provider_requested", sa.String(length=64), nullable=False),
        sa.Column("model_requested", sa.String(length=128), nullable=False),
        sa.Column("client_dialect", sa.String(length=32), nullable=True),
        sa.Column("request_type", sa.String(length=64), nullable=True),
        sa.Column("feature", sa.String(length=255), nullable=True),
        sa.Column("workflow", sa.String(length=255), nullable=True),
        sa.Column("customer_id", sa.String(length=255), nullable=True),
        sa.Column("external_user_id", sa.String(length=255), nullable=True),
        sa.Column("team", sa.String(length=255), nullable=True),
        sa.Column("department", sa.String(length=255), nullable=True),
        sa.Column("environment", sa.String(length=64), nullable=True),
        sa.Column("task_type", sa.String(length=128), nullable=True),
        sa.Column("task_confidence", sa.Numeric(4, 3), nullable=True),
        sa.Column("risk_level", sa.String(length=32), nullable=True),
        sa.Column("quality_threshold", sa.String(length=64), nullable=True),
        # decision context
        sa.Column("decision_type", sa.String(length=32), nullable=False),
        sa.Column("lever", sa.String(length=32), nullable=True),
        sa.Column("policy_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("source_recommendation_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("arm", sa.String(length=16), nullable=True),
        sa.Column("optimization_applied", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("bypassed", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("bypass_reason", sa.String(length=64), nullable=True),
        sa.Column("cache_status", sa.String(length=16), nullable=True),
        sa.Column("fallback_used", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("fallback_reason", sa.String(length=128), nullable=True),
        sa.Column("route_eligible", sa.Boolean(), nullable=True),
        sa.Column("route_ineligible_reason", sa.String(length=64), nullable=True),
        # chosen path / counterfactual
        sa.Column("provider_chosen", sa.String(length=64), nullable=True),
        sa.Column("model_chosen", sa.String(length=128), nullable=True),
        sa.Column(
            "execution_path", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("provider_counterfactual", sa.String(length=64), nullable=True),
        sa.Column("model_counterfactual", sa.String(length=128), nullable=True),
        sa.Column(
            "counterfactual_path", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        # economics
        sa.Column("realized_naive_cost_usd", sa.Numeric(18, 8), nullable=True),
        sa.Column("realized_actual_cost_usd", sa.Numeric(18, 8), nullable=True),
        sa.Column("realized_savings_usd", sa.Numeric(18, 8), nullable=True),
        sa.Column("price_version_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("pricing_status", sa.String(length=32), nullable=True),
        sa.Column("cost_source", sa.String(length=16), nullable=True),
        # quality
        sa.Column("quality_ok", sa.Boolean(), nullable=True),
        sa.Column("quality_score", sa.Numeric(6, 4), nullable=True),
        sa.Column("eval_run_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("failure_mode", sa.String(length=64), nullable=True),
        sa.Column("error_code", sa.String(length=128), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        # audit
        sa.Column("reason_code", sa.String(length=64), nullable=True),
        sa.Column(
            "reason_detail", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "metadata", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["usage_event_id"], ["usage_events.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["api_key_id"], ["api_keys.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["policy_id"], ["proxy_policies.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["source_recommendation_id"], ["recommendations.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["price_version_id"], ["model_prices.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["eval_run_id"], ["eval_runs.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_request_decision_project_created", "request_decision_events", ["project_id", "created_at"], unique=False
    )
    op.create_index(
        "ix_request_decision_project_task_type", "request_decision_events", ["project_id", "task_type"], unique=False
    )
    op.create_index(
        "ix_request_decision_project_lever", "request_decision_events", ["project_id", "lever"], unique=False
    )
    op.create_index(
        "ix_request_decision_project_model_chosen",
        "request_decision_events",
        ["project_id", "model_chosen"],
        unique=False,
    )
    op.create_index(
        "ix_request_decision_project_request", "request_decision_events", ["project_id", "request_id"], unique=False
    )

    op.create_table(
        "request_feedback",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("usage_event_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("decision_event_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("request_id", sa.String(length=128), nullable=True),
        sa.Column("outcome", sa.String(length=32), nullable=False),
        sa.Column("quality_score", sa.Numeric(6, 4), nullable=True),
        sa.Column("failure_mode", sa.String(length=64), nullable=True),
        sa.Column("source", sa.String(length=16), server_default=sa.text("'customer'"), nullable=False),
        sa.Column(
            "metadata", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["usage_event_id"], ["usage_events.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["decision_event_id"], ["request_decision_events.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_request_feedback_project_created", "request_feedback", ["project_id", "created_at"], unique=False)
    op.create_index("ix_request_feedback_project_outcome", "request_feedback", ["project_id", "outcome"], unique=False)
    op.create_index("ix_request_feedback_usage_event", "request_feedback", ["usage_event_id"], unique=False)
    op.create_index(
        "ix_request_feedback_project_request", "request_feedback", ["project_id", "request_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_request_feedback_project_request", table_name="request_feedback")
    op.drop_index("ix_request_feedback_usage_event", table_name="request_feedback")
    op.drop_index("ix_request_feedback_project_outcome", table_name="request_feedback")
    op.drop_index("ix_request_feedback_project_created", table_name="request_feedback")
    op.drop_table("request_feedback")
    op.drop_index("ix_request_decision_project_request", table_name="request_decision_events")
    op.drop_index("ix_request_decision_project_model_chosen", table_name="request_decision_events")
    op.drop_index("ix_request_decision_project_lever", table_name="request_decision_events")
    op.drop_index("ix_request_decision_project_task_type", table_name="request_decision_events")
    op.drop_index("ix_request_decision_project_created", table_name="request_decision_events")
    op.drop_table("request_decision_events")
