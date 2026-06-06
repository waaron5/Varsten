"""Cost derivation from the versioned pricing catalog.

No model price is hard-coded here. Prices are resolved from data: a per-org
override first, then the synced public catalog, always choosing the row whose
effective_at is the latest one at or before the event's time. That keeps history
stable when prices change and lets new prices land via a sync, not a deploy.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ModelPrice, OrgModelPriceOverride

# usage_events.cost_usd is Numeric(18, 8); quantize calculated costs to match.
COST_QUANTUM = Decimal("0.00000001")


@dataclass(frozen=True)
class ResolvedPrice:
    input_cost_per_token: Decimal
    output_cost_per_token: Decimal
    cache_read_input_token_cost: Decimal | None
    # "override" (per-org rate) or "catalog" (public catalog).
    source: str
    # Set only when the price came from a model_prices row, for audit pinning.
    price_version_id: uuid.UUID | None


def _override_for(
    db: Session,
    organization_id: uuid.UUID,
    model_key: str,
    provider: str,
    at: datetime,
) -> ResolvedPrice | None:
    # provider IS NULL means the override applies regardless of provider.
    stmt = (
        select(OrgModelPriceOverride)
        .where(
            OrgModelPriceOverride.organization_id == organization_id,
            OrgModelPriceOverride.model_key == model_key,
            (OrgModelPriceOverride.provider == provider) | (OrgModelPriceOverride.provider.is_(None)),
            OrgModelPriceOverride.effective_at <= at,
        )
        .order_by(OrgModelPriceOverride.effective_at.desc())
        .limit(1)
    )
    row = db.scalars(stmt).first()
    if row is None:
        return None
    return ResolvedPrice(
        input_cost_per_token=row.input_cost_per_token,
        output_cost_per_token=row.output_cost_per_token,
        cache_read_input_token_cost=row.cache_read_input_token_cost,
        source="override",
        price_version_id=None,
    )


def _catalog_price_for(db: Session, model_key: str, provider: str, at: datetime) -> ResolvedPrice | None:
    base = select(ModelPrice).where(ModelPrice.model_key == model_key, ModelPrice.effective_at <= at)
    # Prefer an exact (model_key, provider) row. Fall back to the model_key alone,
    # since callers' provider strings ("openai") do not always match the feed's
    # litellm_provider, and most model_keys are globally unique anyway.
    for stmt in (
        base.where(ModelPrice.provider == provider),
        base,
    ):
        row = db.scalars(stmt.order_by(ModelPrice.effective_at.desc()).limit(1)).first()
        if row is not None:
            return ResolvedPrice(
                input_cost_per_token=row.input_cost_per_token,
                output_cost_per_token=row.output_cost_per_token,
                cache_read_input_token_cost=row.cache_read_input_token_cost,
                source="catalog",
                price_version_id=row.id,
            )
    return None


def resolve_price(
    db: Session,
    organization_id: uuid.UUID,
    model_key: str,
    provider: str,
    at: datetime,
) -> ResolvedPrice | None:
    """The price to apply, override taking precedence over the public catalog.
    Returns None when nothing covers the model at that time."""
    return _override_for(db, organization_id, model_key, provider, at) or _catalog_price_for(
        db, model_key, provider, at
    )


def compute_cost(
    price: ResolvedPrice,
    input_tokens: int,
    output_tokens: int,
    cached_input_tokens: int,
) -> Decimal:
    """Cost in USD, quantized to 8 dp. Cached input tokens are a subset of
    input_tokens billed at the cache-read rate (falling back to the input rate
    when the model has no separate cache price). reasoning_tokens are not added:
    providers already fold them into output_tokens for billing."""
    cached = min(max(cached_input_tokens, 0), input_tokens)
    uncached = input_tokens - cached
    cache_rate = (
        price.cache_read_input_token_cost
        if price.cache_read_input_token_cost is not None
        else price.input_cost_per_token
    )
    raw = uncached * price.input_cost_per_token + cached * cache_rate + output_tokens * price.output_cost_per_token
    return raw.quantize(COST_QUANTUM, rounding=ROUND_HALF_UP)


def price_usage_event(
    db: Session,
    organization_id: uuid.UUID,
    model_key: str,
    provider: str,
    input_tokens: int,
    output_tokens: int,
    cached_input_tokens: int,
    reported_cost_usd: Decimal | None,
    at: datetime,
) -> tuple[Decimal | None, str, str, uuid.UUID | None]:
    """Resolve the authoritative cost for an event.

    Returns (cost_usd, cost_source, pricing_status, price_version_id). Derives
    from override/catalog when priced; otherwise keeps the event with reported or
    unknown cost so observability data is not lost.
    """
    if input_tokens == 0 and output_tokens == 0 and reported_cost_usd is None:
        return None, "unknown", "missing_token_counts", None

    price = resolve_price(db, organization_id, model_key, provider, at)
    if price is not None:
        cost = compute_cost(price, input_tokens, output_tokens, cached_input_tokens)
        return cost, price.source, "priced", price.price_version_id
    if reported_cost_usd is not None:
        return reported_cost_usd, "reported", "model_not_in_catalog", None
    return None, "unknown", "model_not_in_catalog", None
