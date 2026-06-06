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

# Per-token prices are tiny (e.g. 5e-7). Numeric(20, 12) keeps twelve fractional
# digits so sub-microcent rates survive without float drift.
TokenCost = Numeric(20, 12)


class ModelCatalog(Base, TimestampMixin):
    """Stable identity and capabilities for a model. No money lives here; prices
    are versioned separately in model_prices. The optimizer (later) reads tier and
    cheaper_substitute_key from this table."""

    __tablename__ = "model_catalog"
    __table_args__ = (UniqueConstraint("model_key", "provider", name="uq_model_catalog_key_provider"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # Matches usage_events.model as it arrives (e.g. "gpt-4o-mini").
    model_key: Mapped[str] = mapped_column(String(128), nullable=False)
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    mode: Mapped[str | None] = mapped_column(String(32), nullable=True)
    # Curated coarse class for substitution logic: frontier | mid | small.
    tier: Mapped[str | None] = mapped_column(String(16), nullable=True)
    supports_vision: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    supports_function_calling: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    supports_reasoning: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    # Curated cheaper alternative for the optimizer; unused this round.
    cheaper_substitute_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    source: Mapped[str] = mapped_column(String(32), nullable=False, server_default=text("'litellm'"))


class ModelPrice(Base):
    """A versioned list price for a model. A price change inserts a new row with a
    later effective_at; existing rows are never mutated, so historical events keep
    the price that was live when they happened. Resolution picks the greatest
    effective_at that is <= the event's time."""

    __tablename__ = "model_prices"
    __table_args__ = (
        Index(
            "ix_model_prices_key_provider_effective_at",
            "model_key",
            "provider",
            text("effective_at DESC"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    model_key: Mapped[str] = mapped_column(String(128), nullable=False)
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    currency: Mapped[str] = mapped_column(String(8), nullable=False, server_default=text("'USD'"))
    input_cost_per_token: Mapped[Decimal] = mapped_column(TokenCost, nullable=False, server_default=text("0"))
    output_cost_per_token: Mapped[Decimal] = mapped_column(TokenCost, nullable=False, server_default=text("0"))
    cache_read_input_token_cost: Mapped[Decimal | None] = mapped_column(TokenCost, nullable=True)
    cache_write_input_token_cost: Mapped[Decimal | None] = mapped_column(TokenCost, nullable=True)
    input_cost_per_token_batch: Mapped[Decimal | None] = mapped_column(TokenCost, nullable=True)
    output_cost_per_token_batch: Mapped[Decimal | None] = mapped_column(TokenCost, nullable=True)
    source: Mapped[str] = mapped_column(String(32), nullable=False, server_default=text("'litellm'"))
    effective_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("now()"))


class OrgModelPriceOverride(Base):
    """A per-organization negotiated rate. Same price shape as model_prices and
    takes precedence over it, so committed-use / contract pricing is honored.
    provider NULL means the override applies to the model_key regardless of
    provider."""

    __tablename__ = "org_model_price_overrides"
    __table_args__ = (
        Index(
            "ix_org_price_overrides_org_key_effective_at",
            "organization_id",
            "model_key",
            text("effective_at DESC"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    model_key: Mapped[str] = mapped_column(String(128), nullable=False)
    provider: Mapped[str | None] = mapped_column(String(64), nullable=True)
    currency: Mapped[str] = mapped_column(String(8), nullable=False, server_default=text("'USD'"))
    input_cost_per_token: Mapped[Decimal] = mapped_column(TokenCost, nullable=False, server_default=text("0"))
    output_cost_per_token: Mapped[Decimal] = mapped_column(TokenCost, nullable=False, server_default=text("0"))
    cache_read_input_token_cost: Mapped[Decimal | None] = mapped_column(TokenCost, nullable=True)
    cache_write_input_token_cost: Mapped[Decimal | None] = mapped_column(TokenCost, nullable=True)
    effective_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
