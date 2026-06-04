"""Active inline routing rules for the proxy.

When a cheaper-model recommendation is applied (which requires a passing shadow
eval), a rule here is activated. The proxy reads it on the hot path and rewrites
matching requests from the incumbent model to the proven cheaper candidate. This
is the execution side of the cheaper-model lever: detection -> eval -> apply ->
this rule -> the proxy actually routes the traffic and the savings are real.

One enabled rule per (project, incumbent_model). Disabling it (or the kill
switch / per-project bypass) returns traffic to the incumbent immediately.
"""
import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class ProxyRoutingRule(Base, TimestampMixin):
    __tablename__ = "proxy_routing_rules"
    __table_args__ = (
        UniqueConstraint("project_id", "incumbent_model", name="uq_routing_project_incumbent"),
        Index("ix_routing_project_enabled", "project_id", "enabled"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
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
    incumbent_model: Mapped[str] = mapped_column(String(128), nullable=False)
    candidate_model: Mapped[str] = mapped_column(String(128), nullable=False)
    enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    # Fraction of this route's traffic held back on the incumbent as the control
    # arm of the live A/B. The rest is routed to the candidate (treatment). Small
    # by default: the holdback costs money (control stays at the dearer price), so
    # it buys a rigorous, concurrently-measured savings number, not a modelled one.
    holdback_percent: Mapped[Decimal] = mapped_column(
        Numeric(5, 4), nullable=False, server_default=text("0.05")
    )
    # The applied recommendation whose eval cleared this swap, for provenance.
    source_recommendation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("recommendations.id", ondelete="SET NULL"),
        nullable=True,
    )
    activated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
