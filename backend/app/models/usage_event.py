import uuid
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base

if TYPE_CHECKING:
    from app.models.api_key import ApiKey
    from app.models.project import Project
    from app.models.tenant import Organization


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
        UniqueConstraint("project_id", "idempotency_key", name="uq_usage_events_project_idempotency"),
        Index(
            "ix_usage_events_project_feature_received_at",
            "project_id",
            "feature",
            text("received_at DESC"),
        ),
        Index(
            "ix_usage_events_project_customer_received_at",
            "project_id",
            "customer_id",
            text("received_at DESC"),
        ),
        Index(
            "ix_usage_events_project_environment_received_at",
            "project_id",
            "environment",
            text("received_at DESC"),
        ),
        Index(
            "ix_usage_events_project_request_type_received_at",
            "project_id",
            "request_type",
            text("received_at DESC"),
        ),
        Index(
            "ix_usage_events_project_pricing_status_received_at",
            "project_id",
            "pricing_status",
            text("received_at DESC"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    api_key_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("api_keys.id", ondelete="SET NULL"),
        nullable=True,
    )
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    model: Mapped[str] = mapped_column(String(128), nullable=False)
    operation: Mapped[str] = mapped_column(String(64), nullable=False)
    external_user_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    workflow: Mapped[str | None] = mapped_column(String(255), nullable=True)
    request_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    feature: Mapped[str | None] = mapped_column(String(255), nullable=True)
    customer_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    user_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    team: Mapped[str | None] = mapped_column(String(255), nullable=True)
    department: Mapped[str | None] = mapped_column(String(255), nullable=True)
    environment: Mapped[str] = mapped_column(String(64), nullable=False, server_default=text("'unknown'"))
    input_tokens: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    output_tokens: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    # Subset of input_tokens served from a provider prompt cache (billed cheaper).
    cached_input_tokens: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default=text("0"))
    # Reasoning/thinking tokens. Stored for analytics; providers already fold these
    # into output_tokens for billing, so cost derivation does not add them again.
    reasoning_tokens: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default=text("0"))
    total_tokens: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    # Authoritative cost, from whichever source cost_source names.
    cost_usd: Mapped[Decimal | None] = mapped_column(Numeric(18, 8), nullable=True)
    # The client-supplied cost, retained even when Varsten calculates its own, so
    # drift between reported and authoritative cost is auditable.
    reported_cost_usd: Mapped[Decimal | None] = mapped_column(Numeric(18, 8), nullable=True)
    # How cost_usd was determined: override | catalog | reported | unknown.
    cost_source: Mapped[str] = mapped_column(String(16), nullable=False, server_default=text("'reported'"))
    # The pricing trust state: priced | model_not_in_catalog |
    # missing_token_counts | missing_reported_cost | suspected_model_alias.
    pricing_status: Mapped[str] = mapped_column(String(32), nullable=False, server_default=text("'priced'"))
    # The model_prices row that produced a catalog cost (NULL for override/reported/unknown).
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
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default=text("'success'"))
    success: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    error_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
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
    event_timestamp: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    occurred_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    project: Mapped["Project"] = relationship(back_populates="usage_events")
    organization: Mapped["Organization"] = relationship()
    api_key: Mapped["ApiKey | None"] = relationship()
