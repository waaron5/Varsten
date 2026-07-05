import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, Numeric, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class Recommendation(Base):
    __tablename__ = "recommendations"
    __table_args__ = (
        UniqueConstraint("project_id", "dedupe_key", name="uq_recommendations_project_dedupe"),
        Index("ix_recommendations_project_status", "project_id", "status"),
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
    dedupe_key: Mapped[str] = mapped_column(String(255), nullable=False)
    type: Mapped[str] = mapped_column(String(64), nullable=False)
    lever: Mapped[str | None] = mapped_column(String(32), nullable=True)
    target_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    target_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    estimated_monthly_savings_usd: Mapped[Decimal | None] = mapped_column(Numeric(18, 8), nullable=True)
    monthly_request_volume: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    quality_delta_percent: Mapped[Decimal | None] = mapped_column(Numeric(8, 4), nullable=True)
    measurement_method: Mapped[str] = mapped_column(String(32), nullable=False, server_default=text("'estimated'"))
    risk_level: Mapped[str] = mapped_column(String(16), nullable=False)
    confidence: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default=text("'open'"))
    # Structured, type-specific evidence for the UI (e.g. the prefix-restructure
    # proposal's offsets/shares). Metrics and structure only — NEVER prompt or
    # completion text; recommendations are a metadata-only store.
    details: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    related_provider: Mapped[str | None] = mapped_column(String(64), nullable=True)
    related_model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    related_feature: Mapped[str | None] = mapped_column(String(255), nullable=True)
    related_customer_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    related_environment: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
