"""Alert delivery history.

One row per alert actually evaluated-and-acted-on: what fired, what the observed
value was, where it was sent, and whether the send succeeded. The dedupe_key makes
a given threshold crossing fire once per period instead of every sweep, and the
row is the audit trail behind "did my alert actually go out?".
"""

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Index, Numeric, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base

# Delivery outcomes.
DELIVERY_SENT = "sent"
DELIVERY_FAILED = "failed"
DELIVERY_SKIPPED = "skipped"  # recorded, but no channel configured to send to


class AlertDelivery(Base):
    __tablename__ = "alert_deliveries"
    __table_args__ = (
        # One delivery per crossing per period; a re-evaluation finds this and skips.
        UniqueConstraint("project_id", "dedupe_key", name="uq_alert_deliveries_project_dedupe"),
        Index("ix_alert_deliveries_project_created_at", "project_id", text("created_at DESC")),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    alert_rule_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("alert_rules.id", ondelete="SET NULL"), nullable=True
    )
    alert_type: Mapped[str] = mapped_column(String(64), nullable=False)
    channel: Mapped[str] = mapped_column(String(32), nullable=False)
    destination: Mapped[str] = mapped_column(String(255), nullable=False)
    subject: Mapped[str] = mapped_column(String(255), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    observed_usd: Mapped[Decimal | None] = mapped_column(Numeric(18, 8), nullable=True)
    threshold_usd: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    threshold_percent: Mapped[Decimal | None] = mapped_column(Numeric(8, 4), nullable=True)
    owner_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    owner_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    dedupe_key: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
