import uuid
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base

if TYPE_CHECKING:
    from app.models.project import Project


class UsageEvent(Base):
    __tablename__ = "usage_events"
    __table_args__ = (
        Index(
            "ix_usage_events_project_received_at",
            "project_id",
            text("received_at DESC"),
        ),
        Index(
            "ix_usage_events_project_provider_received_at",
            "project_id",
            "provider",
            text("received_at DESC"),
        ),
        Index(
            "ix_usage_events_project_model_received_at",
            "project_id",
            "model",
            text("received_at DESC"),
        ),
        Index(
            "ix_usage_events_project_workflow_received_at",
            "project_id",
            "workflow",
            text("received_at DESC"),
        ),
        Index(
            "ix_usage_events_project_external_user_received_at",
            "project_id",
            "external_user_id",
            text("received_at DESC"),
        ),
        # Retries / at-least-once delivery must not double-count spend. A client
        # may scope idempotency per key; uniqueness is per project. NULL keys are
        # exempt (Postgres treats NULLs as distinct), so unkeyed sends still work.
        UniqueConstraint(
            "project_id", "idempotency_key", name="uq_usage_events_project_idempotency"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    model: Mapped[str] = mapped_column(String(128), nullable=False)
    operation: Mapped[str] = mapped_column(String(64), nullable=False)
    external_user_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    workflow: Mapped[str | None] = mapped_column(String(255), nullable=True)
    input_tokens: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    output_tokens: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    # Subset of input_tokens served from a provider prompt cache (billed cheaper).
    cached_input_tokens: Mapped[int] = mapped_column(
        BigInteger, nullable=False, server_default=text("0")
    )
    # Reasoning/thinking tokens. Stored for analytics; providers already fold these
    # into output_tokens for billing, so cost derivation does not add them again.
    reasoning_tokens: Mapped[int] = mapped_column(
        BigInteger, nullable=False, server_default=text("0")
    )
    total_tokens: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    # Authoritative cost, from whichever source cost_source names.
    cost_usd: Mapped[Decimal] = mapped_column(Numeric(18, 8), nullable=False)
    # The client-supplied cost, retained even when we derived our own, so drift
    # between reported and derived is auditable.
    reported_cost_usd: Mapped[Decimal | None] = mapped_column(
        Numeric(18, 8), nullable=True
    )
    # How cost_usd was determined: override | derived | reported.
    cost_source: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=text("'reported'")
    )
    # The model_prices row that produced a derived cost (NULL for override/reported).
    price_version_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("model_prices.id", ondelete="SET NULL"),
        nullable=True,
    )
    currency: Mapped[str] = mapped_column(String(8), nullable=False, default="USD")
    # Caller-scoped key for idempotent retries; see the unique constraint above.
    idempotency_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # success | error. Lets the optimizer avoid recommending changes that raise
    # failure rates; defaults to success for existing/unspecified events.
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=text("'success'")
    )
    event_metadata: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
        index=False,
    )
    # When the call actually happened on the client, distinct from server receipt.
    # Batched/delayed sends otherwise land in the wrong day. Analytics still bucket
    # on received_at this round; switching the axis to event_timestamp is a tracked
    # follow-up that needs index changes.
    event_timestamp: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    project: Mapped["Project"] = relationship(back_populates="usage_events")
