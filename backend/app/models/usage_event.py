import uuid
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, Numeric, String, text
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
    total_tokens: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    cost_usd: Mapped[Decimal] = mapped_column(Numeric(18, 8), nullable=False)
    currency: Mapped[str] = mapped_column(String(8), nullable=False, default="USD")
    event_metadata: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
        index=False,
    )

    project: Mapped["Project"] = relationship(back_populates="usage_events")
