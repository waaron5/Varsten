"""Eval / replay harness tables (Track B).

The shadow-evaluation loop that gates a model-downshift swap on a route's real
traffic before it can be applied. Three tables:

- ``ReplaySample``  the replay corpus. Sampled real traffic plus customer golden
  sets. This is the SECOND documented content exception alongside the semantic
  cache: it stores prompts and incumbent responses so they can be replayed.
  Traffic samples are opt-in, sampled, bounded per route, and TTL'd; golden
  samples are customer-supplied and do not expire. The metadata ledger still
  never sees content; this store is separate, opt-in, and retention-controlled.
- ``EvalRun``  one shadow evaluation of (incumbent_model -> candidate_model) on a
  route, with the aggregate verdict, confidence interval, and measured cost delta.
- ``EvalSampleResult``  the per-sample audit trail behind a run, so the customer
  can verify the verdict rather than trust it (same audit principle as the
  randomized holdback).

Everything that writes EvalRun / EvalSampleResult runs in a worker, off the
request hot path. Nothing here is ever touched by a live proxied request.
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
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin

# ReplaySample.source
SOURCE_TRAFFIC = "traffic"
SOURCE_GOLDEN = "golden"

# EvalRun.status
RUN_PENDING = "pending"
RUN_RUNNING = "running"
RUN_COMPLETED = "completed"
RUN_FAILED = "failed"

# EvalRun.verdict
VERDICT_SAFE = "safe"  # objective signal cleared the bar: auto-eligible
VERDICT_NEEDS_HUMAN = "needs_human"  # subjective/borderline: approve-only
VERDICT_UNSAFE = "unsafe"  # candidate degraded the route: blocked
VERDICT_INSUFFICIENT = "insufficient_data"  # not enough samples to judge


class ReplaySample(Base, TimestampMixin):
    """A single (prompt, incumbent response) pair available for replay on a route.

    ``source`` distinguishes sampled real traffic from a customer golden sample.
    Golden samples may carry an ``expected_output`` the customer considers
    correct, the strongest scoring signal. Real-traffic samples carry the actual
    incumbent answer the user received in production, which is replayed against,
    so the incumbent is never re-run (free, and the real answer)."""

    __tablename__ = "replay_samples"
    __table_args__ = (
        Index("ix_replay_samples_project_route", "project_id", "route_key"),
        Index("ix_replay_samples_project_source", "project_id", "source"),
        Index("ix_replay_samples_expires_at", "expires_at"),
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
    # Phase 1 route identity = the requested model. Generalizes to feature/route
    # once the proxy carries per-route metadata.
    route_key: Mapped[str] = mapped_column(String(255), nullable=False)
    source: Mapped[str] = mapped_column(String(16), nullable=False, server_default=text(f"'{SOURCE_TRAFFIC}'"))
    incumbent_model: Mapped[str] = mapped_column(String(128), nullable=False)
    # Content. The chat messages and the sampling params needed to replay
    # faithfully through a candidate model.
    request_messages: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    request_params: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    # The incumbent's assembled completion (real production answer for traffic
    # samples). Replayed against; never re-run.
    incumbent_response: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    # Customer-asserted correct answer for golden samples. Null for traffic.
    expected_output: Mapped[str | None] = mapped_column(Text, nullable=True)
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    # Null for golden samples (no retention limit); set for traffic samples.
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class EvalRun(Base, TimestampMixin):
    """One shadow evaluation of a candidate model against the incumbent on a route."""

    __tablename__ = "eval_runs"
    __table_args__ = (
        Index("ix_eval_runs_project_created", "project_id", "created_at"),
        Index("ix_eval_runs_recommendation", "recommendation_id"),
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
    lever: Mapped[str] = mapped_column(String(32), nullable=False)
    route_key: Mapped[str] = mapped_column(String(255), nullable=False)
    incumbent_model: Mapped[str] = mapped_column(String(128), nullable=False)
    candidate_model: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default=text(f"'{RUN_PENDING}'"))
    # objective | judge | golden | mixed: which scoring tier produced the verdict.
    scorer_type: Mapped[str | None] = mapped_column(String(16), nullable=True)
    sample_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    win_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    tie_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    loss_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    objective_pass_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    objective_pass_rate: Mapped[Decimal | None] = mapped_column(Numeric(5, 4), nullable=True)
    # Aggregate quality delta (candidate vs incumbent), normalized to [-1, 1], with
    # a confidence interval. Never a bare point estimate on the Proof/decision UI.
    score_delta: Mapped[Decimal | None] = mapped_column(Numeric(6, 4), nullable=True)
    score_delta_ci_low: Mapped[Decimal | None] = mapped_column(Numeric(6, 4), nullable=True)
    score_delta_ci_high: Mapped[Decimal | None] = mapped_column(Numeric(6, 4), nullable=True)
    # Replay-measured per-request cost delta extrapolated to the route's volume.
    cost_delta_usd: Mapped[Decimal | None] = mapped_column(Numeric(18, 8), nullable=True)
    verdict: Mapped[str | None] = mapped_column(String(20), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class EvalSampleResult(Base):
    """Per-sample outcome behind an EvalRun. The audit trail the customer can read."""

    __tablename__ = "eval_sample_results"
    __table_args__ = (Index("ix_eval_sample_results_run", "eval_run_id"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    eval_run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("eval_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    replay_sample_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("replay_samples.id", ondelete="SET NULL"),
        nullable=True,
    )
    # The candidate model's answer for this prompt. Content; carries the run's TTL.
    candidate_response: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    scorer: Mapped[str] = mapped_column(String(16), nullable=False)
    objective_pass: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    # incumbent | candidate | tie, for the pairwise judge tier.
    judge_winner: Mapped[str | None] = mapped_column(String(16), nullable=True)
    score: Mapped[Decimal | None] = mapped_column(Numeric(6, 4), nullable=True)
    candidate_cost_usd: Mapped[Decimal | None] = mapped_column(Numeric(18, 8), nullable=True)
    incumbent_cost_usd: Mapped[Decimal | None] = mapped_column(Numeric(18, 8), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
