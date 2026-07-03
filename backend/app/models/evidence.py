"""Moat evidence tables: per-request decision records and outcome feedback.

These are the durable, append-only evidence trail behind the long-term moat:
"for task type X, under conditions Y, at quality threshold Z, this execution path
is the cheapest reliable one." Each proxied request that Varsten meters produces
one ``RequestDecisionEvent`` capturing what was requested, what was chosen, why,
what it cost, what it saved, and whether quality looked acceptable.
``RequestFeedback`` captures the implicit production signal that arrives later
(the customer accepted/rejected/edited/escalated the output).

Both are metadata only. No prompt or completion text lives here; content storage
remains governed by the semantic cache and replay corpus and their consent
settings. Writes are best-effort and off the request hot path.
"""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base

# RequestFeedback.outcome vocabulary. Open set kept small and explicit; unknown
# values are rejected at the API boundary so the column stays analyzable.
FEEDBACK_OUTCOMES = (
    "accepted",
    "rejected",
    "edited",
    "regenerated",
    "escalated",
    "overridden",
)


class RequestDecisionEvent(Base):
    """One per metered proxied request: the optimization decision and its measured
    economics/quality. Append-only; links to the usage_events ledger row when one
    was written. The analytical grain the moat aggregates over is
    (task_type, model_requested, model_chosen, lever)."""

    __tablename__ = "request_decision_events"
    __table_args__ = (
        Index("ix_request_decision_project_created", "project_id", "created_at"),
        Index("ix_request_decision_project_task_type", "project_id", "task_type"),
        Index("ix_request_decision_project_lever", "project_id", "lever"),
        Index("ix_request_decision_project_model_chosen", "project_id", "model_chosen"),
        Index("ix_request_decision_project_request", "project_id", "request_id"),
        Index("ix_request_decision_project_route_key", "project_id", "route_key"),
        Index("ix_request_decision_project_trace", "project_id", "trace_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    # The ledger row this decision produced (NULL when no event was metered, e.g.
    # a provider error before any usage).
    usage_event_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("usage_events.id", ondelete="SET NULL"), nullable=True
    )
    api_key_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("api_keys.id", ondelete="SET NULL"), nullable=True
    )
    # Correlation id returned to the client as X-Varsten-Request-Id, so later
    # feedback can be tied back to this exact decision.
    request_id: Mapped[str] = mapped_column(String(128), nullable=False)

    # --- request context (what the client asked for + business/task context) ---
    provider_requested: Mapped[str] = mapped_column(String(64), nullable=False)
    model_requested: Mapped[str] = mapped_column(String(128), nullable=False)
    client_dialect: Mapped[str | None] = mapped_column(String(32), nullable=True)
    request_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    feature: Mapped[str | None] = mapped_column(String(255), nullable=True)
    workflow: Mapped[str | None] = mapped_column(String(255), nullable=True)
    customer_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    external_user_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    team: Mapped[str | None] = mapped_column(String(255), nullable=True)
    department: Mapped[str | None] = mapped_column(String(255), nullable=True)
    environment: Mapped[str | None] = mapped_column(String(64), nullable=True)
    task_type: Mapped[str | None] = mapped_column(String(128), nullable=True)
    task_confidence: Mapped[Decimal | None] = mapped_column(Numeric(4, 3), nullable=True)
    risk_level: Mapped[str | None] = mapped_column(String(32), nullable=True)
    quality_threshold: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Canonical route identity (feature|workflow|request_type|task_type|default),
    # so learning segments, eval runs, and guardrails attach to one route object.
    route_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    # Content-free fingerprint of the request's cacheable prefix (system messages
    # + tools). Powers measured prompt-cache prefix-stability analysis. Hash only.
    prefix_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Client-supplied trace/session id (X-Varsten-Trace-Id) grouping one agent
    # workflow's calls, and a content-free whole-request fingerprint. Together they
    # detect redundant calls within a trace (agent loops). Hashes/ids only.
    trace_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    request_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # --- decision context ---
    decision_type: Mapped[str] = mapped_column(String(32), nullable=False)
    lever: Mapped[str | None] = mapped_column(String(32), nullable=True)
    policy_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("proxy_policies.id", ondelete="SET NULL"), nullable=True
    )
    source_recommendation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("recommendations.id", ondelete="SET NULL"), nullable=True
    )
    arm: Mapped[str | None] = mapped_column(String(16), nullable=True)
    optimization_applied: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    bypassed: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    bypass_reason: Mapped[str | None] = mapped_column(String(64), nullable=True)
    cache_status: Mapped[str | None] = mapped_column(String(16), nullable=True)
    fallback_used: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    fallback_reason: Mapped[str | None] = mapped_column(String(128), nullable=True)
    route_eligible: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    route_ineligible_reason: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # --- chosen path / counterfactual ---
    provider_chosen: Mapped[str | None] = mapped_column(String(64), nullable=True)
    model_chosen: Mapped[str | None] = mapped_column(String(128), nullable=True)
    execution_path: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    # The incumbent path that would have run absent the optimization (NULL when no
    # swap applied).
    provider_counterfactual: Mapped[str | None] = mapped_column(String(64), nullable=True)
    model_counterfactual: Mapped[str | None] = mapped_column(String(128), nullable=True)
    counterfactual_path: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )

    # --- economics (measured; predicted is deferred to the learning phase) ---
    realized_naive_cost_usd: Mapped[Decimal | None] = mapped_column(Numeric(18, 8), nullable=True)
    realized_actual_cost_usd: Mapped[Decimal | None] = mapped_column(Numeric(18, 8), nullable=True)
    realized_savings_usd: Mapped[Decimal | None] = mapped_column(Numeric(18, 8), nullable=True)
    price_version_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("model_prices.id", ondelete="SET NULL"), nullable=True
    )
    pricing_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    cost_source: Mapped[str | None] = mapped_column(String(16), nullable=True)

    # --- quality / health ---
    quality_ok: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    quality_score: Mapped[Decimal | None] = mapped_column(Numeric(6, 4), nullable=True)
    eval_run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("eval_runs.id", ondelete="SET NULL"), nullable=True
    )
    failure_mode: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # --- audit ---
    reason_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    reason_detail: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    event_metadata: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("now()"))


class RequestFeedback(Base):
    """An outcome signal for a prior request: the implicit quality evidence the
    eval harness cannot capture (accepted/rejected/edited/escalated/...). Linked to
    the decision event and/or the usage_events ledger row. Content-free."""

    __tablename__ = "request_feedback"
    __table_args__ = (
        Index("ix_request_feedback_project_created", "project_id", "created_at"),
        Index("ix_request_feedback_project_outcome", "project_id", "outcome"),
        Index("ix_request_feedback_usage_event", "usage_event_id"),
        Index("ix_request_feedback_project_request", "project_id", "request_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    usage_event_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("usage_events.id", ondelete="SET NULL"), nullable=True
    )
    decision_event_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("request_decision_events.id", ondelete="SET NULL"), nullable=True
    )
    request_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    outcome: Mapped[str] = mapped_column(String(32), nullable=False)
    quality_score: Mapped[Decimal | None] = mapped_column(Numeric(6, 4), nullable=True)
    failure_mode: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source: Mapped[str] = mapped_column(String(16), nullable=False, server_default=text("'customer'"))
    event_metadata: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
