"""Gain-share invoices.

One invoice per organization per billing period, computed from VERIFIED (measured)
savings only -- never estimates. The fee is the org's gain-share percent of those
savings, with a floor, and the floor is capped at the savings so the customer's
net is always >= 0. Invoices are generated manually (operator) today; an automated
Stripe path comes later. The row is the durable, CFO-defensible billing record.
"""

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Numeric, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin

INVOICE_DRAFT = "draft"
INVOICE_FINALIZED = "finalized"
INVOICE_SENT = "sent"
INVOICE_PAID = "paid"
INVOICE_VOID = "void"
INVOICE_STATUSES = (INVOICE_DRAFT, INVOICE_FINALIZED, INVOICE_SENT, INVOICE_PAID, INVOICE_VOID)


class Invoice(Base, TimestampMixin):
    __tablename__ = "invoices"
    __table_args__ = (UniqueConstraint("organization_id", "period_start", "period_end", name="uq_invoices_org_period"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    period_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    period_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # The billable base: verified, measured savings for the period. Never estimates.
    verified_savings_usd: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, server_default=text("0"))
    # Snapshots of the rate/floor used, so a later config change never rewrites a
    # historical invoice.
    gain_share_percent: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False)
    monthly_fee_floor_usd: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, server_default=text("0"))
    fee_usd: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, server_default=text("0"))
    net_savings_usd: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, server_default=text("0"))
    currency: Mapped[str] = mapped_column(String(8), nullable=False, server_default=text("'USD'"))
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default=text(f"'{INVOICE_DRAFT}'"))
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    finalized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
