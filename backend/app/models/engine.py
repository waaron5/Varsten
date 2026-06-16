import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class LeverConfig(Base, TimestampMixin):
    __tablename__ = "lever_configs"
    __table_args__ = (
        UniqueConstraint("project_id", "lever", name="uq_lever_configs_project_lever"),
        Index("ix_lever_configs_project_enabled", "project_id", "enabled"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    lever: Mapped[str] = mapped_column(String(32), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    automation_mode: Mapped[str] = mapped_column(String(16), nullable=False, server_default=text("'approve'"))
    savings_to_date_usd: Mapped[Decimal] = mapped_column(Numeric(18, 8), nullable=False, server_default=text("0"))
    quality_delta_percent: Mapped[Decimal | None] = mapped_column(Numeric(8, 4), nullable=True)
    paused_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class RecommendationAction(Base):
    __tablename__ = "recommendation_actions"
    __table_args__ = (
        Index("ix_recommendation_actions_project_occurred_at", "project_id", "occurred_at"),
        Index("ix_recommendation_actions_project_lever", "project_id", "lever"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    recommendation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("recommendations.id", ondelete="SET NULL"),
        nullable=True,
    )
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    lever: Mapped[str | None] = mapped_column(String(32), nullable=True)
    action_type: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    source: Mapped[str] = mapped_column(String(16), nullable=False, server_default=text("'system'"))
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    estimated_savings_usd: Mapped[Decimal | None] = mapped_column(Numeric(18, 8), nullable=True)
    realized_savings_usd: Mapped[Decimal | None] = mapped_column(Numeric(18, 8), nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("now()"))


class SavingsAttribution(Base, TimestampMixin):
    __tablename__ = "savings_attributions"
    __table_args__ = (
        Index("ix_savings_attributions_project_period", "project_id", "period_start", "period_end"),
        Index("ix_savings_attributions_project_lever", "project_id", "lever"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    recommendation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("recommendations.id", ondelete="SET NULL"),
        nullable=True,
    )
    action_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("recommendation_actions.id", ondelete="SET NULL"),
        nullable=True,
    )
    lever: Mapped[str | None] = mapped_column(String(32), nullable=True)
    measurement_method: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, server_default=text("'estimated'"))
    period_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    period_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    counterfactual_spend_usd: Mapped[Decimal | None] = mapped_column(Numeric(18, 8), nullable=True)
    actual_spend_usd: Mapped[Decimal | None] = mapped_column(Numeric(18, 8), nullable=True)
    gross_savings_usd: Mapped[Decimal] = mapped_column(Numeric(18, 8), nullable=False, server_default=text("0"))
    varsten_fee_usd: Mapped[Decimal] = mapped_column(Numeric(18, 8), nullable=False, server_default=text("0"))
    net_savings_usd: Mapped[Decimal] = mapped_column(Numeric(18, 8), nullable=False, server_default=text("0"))
    confidence_low_usd: Mapped[Decimal | None] = mapped_column(Numeric(18, 8), nullable=True)
    confidence_high_usd: Mapped[Decimal | None] = mapped_column(Numeric(18, 8), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)


class QualityGuardrail(Base, TimestampMixin):
    __tablename__ = "quality_guardrails"
    __table_args__ = (UniqueConstraint("project_id", "route", name="uq_quality_guardrails_project_route"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    route: Mapped[str] = mapped_column(String(255), nullable=False)
    min_model_tier: Mapped[str | None] = mapped_column(String(64), nullable=True)
    eval_gate: Mapped[str | None] = mapped_column(String(128), nullable=True)
    min_eval_score: Mapped[Decimal | None] = mapped_column(Numeric(8, 4), nullable=True)
    max_latency_ms: Mapped[int | None] = mapped_column(nullable=True)
    auto_rollback_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))


class BudgetRule(Base, TimestampMixin):
    __tablename__ = "budget_rules"
    __table_args__ = (
        UniqueConstraint("project_id", "owner_type", "owner_key", name="uq_budget_rules_project_owner"),
        Index("ix_budget_rules_project_owner_type", "project_id", "owner_type"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    owner_type: Mapped[str] = mapped_column(String(32), nullable=False)
    owner_key: Mapped[str] = mapped_column(String(255), nullable=False)
    monthly_budget_usd: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    hard_cap_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))


class AlertRule(Base, TimestampMixin):
    __tablename__ = "alert_rules"
    __table_args__ = (Index("ix_alert_rules_project_enabled", "project_id", "enabled"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    alert_type: Mapped[str] = mapped_column(String(64), nullable=False)
    threshold_usd: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    threshold_percent: Mapped[Decimal | None] = mapped_column(Numeric(8, 4), nullable=True)
    destination_type: Mapped[str] = mapped_column(String(32), nullable=False)
    destination: Mapped[str] = mapped_column(String(255), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))


class CustomerEconomics(Base, TimestampMixin):
    __tablename__ = "customer_economics"
    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "customer_id",
            "period_start",
            "period_end",
            name="uq_customer_economics_project_customer_period",
        ),
        Index("ix_customer_economics_project_customer", "project_id", "customer_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    customer_id: Mapped[str] = mapped_column(String(255), nullable=False)
    customer_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    revenue_usd: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    period_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    period_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ProviderConnection(Base, TimestampMixin):
    __tablename__ = "provider_connections"
    __table_args__ = (UniqueConstraint("project_id", "provider", name="uq_provider_connections_project_provider"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    connection_method: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, server_default=text("'not_connected'"))
    secret_ref: Mapped[str | None] = mapped_column(String(512), nullable=True)
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)


class OptimizationDecision(Base, TimestampMixin):
    __tablename__ = "optimization_decisions"
    __table_args__ = (
        Index("ix_optimization_decisions_project_created_at", "project_id", "created_at"),
        Index("ix_optimization_decisions_project_request", "project_id", "request_id"),
        Index("ix_optimization_decisions_project_reason_code", "project_id", "reason_code"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    request_id: Mapped[str] = mapped_column(String(128), nullable=False)
    client_dialect: Mapped[str] = mapped_column(String(32), nullable=False)
    requested_provider: Mapped[str] = mapped_column(String(64), nullable=False)
    requested_model: Mapped[str] = mapped_column(String(255), nullable=False)
    candidate_provider: Mapped[str] = mapped_column(String(64), nullable=False)
    candidate_model: Mapped[str] = mapped_column(String(255), nullable=False)
    decision: Mapped[str] = mapped_column(String(32), nullable=False)
    reason_code: Mapped[str] = mapped_column(String(64), nullable=False)
    reason_detail: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))


class MonthlyReport(Base, TimestampMixin):
    __tablename__ = "monthly_reports"
    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "period_start",
            "period_end",
            name="uq_monthly_reports_project_period",
        ),
        UniqueConstraint("share_token", name="uq_monthly_reports_share_token"),
        Index("ix_monthly_reports_project_period", "project_id", "period_start", "period_end"),
        Index("ix_monthly_reports_share_token", "share_token"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    period_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    period_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    executive_summary: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, server_default=text("'draft'"))
    share_token: Mapped[str] = mapped_column(String(96), nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    counterfactual_spend_usd: Mapped[Decimal] = mapped_column(Numeric(18, 8), nullable=False, server_default=text("0"))
    actual_spend_usd: Mapped[Decimal] = mapped_column(Numeric(18, 8), nullable=False, server_default=text("0"))
    gross_savings_usd: Mapped[Decimal] = mapped_column(Numeric(18, 8), nullable=False, server_default=text("0"))
    varsten_fee_usd: Mapped[Decimal] = mapped_column(Numeric(18, 8), nullable=False, server_default=text("0"))
    net_savings_usd: Mapped[Decimal] = mapped_column(Numeric(18, 8), nullable=False, server_default=text("0"))
    trust_score: Mapped[Decimal | None] = mapped_column(Numeric(8, 4), nullable=True)
    priced_event_count: Mapped[int] = mapped_column(nullable=False, server_default=text("0"))
    unpriced_event_count: Mapped[int] = mapped_column(nullable=False, server_default=text("0"))
    requests_month: Mapped[int] = mapped_column(nullable=False, server_default=text("0"))
    metadata_quality: Mapped[dict] = mapped_column(JSON, nullable=False, server_default=text("'{}'"))
    attribution_rows: Mapped[list] = mapped_column(JSON, nullable=False, server_default=text("'[]'"))
    top_recommendations: Mapped[list] = mapped_column(JSON, nullable=False, server_default=text("'[]'"))
