"""Refresh the pricing catalog from a maintained public feed.

Run on demand (a cron/CI job is a later follow-up):

    uv run python -m scripts.sync_prices     # or: make sync-prices

Prices live in the database, never in code. This loader maps the LiteLLM dataset
into model_catalog (identity/capabilities) and model_prices (versioned money). A
new model_prices row is inserted only when a price actually changed, so re-runs
are cheap and the effective_at history stays meaningful.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import SessionLocal
from app.models import ModelCatalog, ModelPrice
from app.pricing.catalog_curation import apply_curation

# model_prices stores TOKEN_COST as Numeric(20, 12). Quantize parsed values to the
# same 12-dp scale so a stored price round-trips equal and re-runs stay no-ops; a
# few feed entries carry more precision than the column holds.
_PRICE_SCALE = Decimal("1e-12")

# Fields that define a price. If any differs from the latest stored row we insert
# a new version; otherwise the run is a no-op for that model.
_PRICE_FIELDS = (
    "input_cost_per_token",
    "output_cost_per_token",
    "cache_read_input_token_cost",
    "cache_write_input_token_cost",
    "input_cost_per_token_batch",
    "output_cost_per_token_batch",
)


@dataclass(frozen=True)
class ParsedModel:
    model_key: str
    provider: str
    mode: str | None
    supports_vision: bool
    supports_function_calling: bool
    supports_reasoning: bool
    input_cost_per_token: Decimal
    output_cost_per_token: Decimal
    cache_read_input_token_cost: Decimal | None
    cache_write_input_token_cost: Decimal | None
    input_cost_per_token_batch: Decimal | None
    output_cost_per_token_batch: Decimal | None


def _dec(value: object) -> Decimal | None:
    # str() first: feed values are floats like 5e-7; going through str avoids
    # binary-float artifacts in the Decimal. Then snap to the stored 12-dp scale.
    if value is None:
        return None
    return Decimal(str(value)).quantize(_PRICE_SCALE, rounding=ROUND_HALF_UP)


def parse_feed(raw: dict) -> list[ParsedModel]:
    """Map the feed JSON to ParsedModel rows. Skips the meta entry and any model
    that carries no token pricing."""
    parsed: list[ParsedModel] = []
    for model_key, spec in raw.items():
        if model_key == "sample_spec" or not isinstance(spec, dict):
            continue
        in_cost = _dec(spec.get("input_cost_per_token"))
        out_cost = _dec(spec.get("output_cost_per_token"))
        if in_cost is None and out_cost is None:
            continue
        provider = spec.get("litellm_provider") or "unknown"
        parsed.append(
            ParsedModel(
                model_key=model_key,
                provider=provider,
                mode=spec.get("mode"),
                supports_vision=bool(spec.get("supports_vision", False)),
                supports_function_calling=bool(
                    spec.get("supports_function_calling", False)
                ),
                supports_reasoning=bool(spec.get("supports_reasoning", False)),
                input_cost_per_token=in_cost or Decimal(0),
                output_cost_per_token=out_cost or Decimal(0),
                cache_read_input_token_cost=_dec(spec.get("cache_read_input_token_cost")),
                cache_write_input_token_cost=_dec(
                    spec.get("cache_creation_input_token_cost")
                ),
                input_cost_per_token_batch=_dec(spec.get("input_cost_per_token_batches")),
                output_cost_per_token_batch=_dec(
                    spec.get("output_cost_per_token_batches")
                ),
            )
        )
    return parsed


def _price_changed(latest: ModelPrice | None, p: ParsedModel) -> bool:
    if latest is None:
        return True
    return any(getattr(latest, f) != getattr(p, f) for f in _PRICE_FIELDS)


def sync(db: Session, raw: dict) -> dict[str, int]:
    """Upsert catalog and append changed prices. Returns run counts."""
    parsed = parse_feed(raw)
    catalog_upserts = 0
    price_inserts = 0

    for p in parsed:
        catalog = db.scalar(
            select(ModelCatalog).where(
                ModelCatalog.model_key == p.model_key,
                ModelCatalog.provider == p.provider,
            )
        )
        if catalog is None:
            db.add(
                ModelCatalog(
                    model_key=p.model_key,
                    provider=p.provider,
                    mode=p.mode,
                    supports_vision=p.supports_vision,
                    supports_function_calling=p.supports_function_calling,
                    supports_reasoning=p.supports_reasoning,
                    source="litellm",
                )
            )
        else:
            catalog.mode = p.mode
            catalog.supports_vision = p.supports_vision
            catalog.supports_function_calling = p.supports_function_calling
            catalog.supports_reasoning = p.supports_reasoning
        catalog_upserts += 1

        latest = db.scalar(
            select(ModelPrice)
            .where(
                ModelPrice.model_key == p.model_key,
                ModelPrice.provider == p.provider,
            )
            .order_by(ModelPrice.effective_at.desc())
            .limit(1)
        )
        if _price_changed(latest, p):
            db.add(
                ModelPrice(
                    model_key=p.model_key,
                    provider=p.provider,
                    currency="USD",
                    input_cost_per_token=p.input_cost_per_token,
                    output_cost_per_token=p.output_cost_per_token,
                    cache_read_input_token_cost=p.cache_read_input_token_cost,
                    cache_write_input_token_cost=p.cache_write_input_token_cost,
                    input_cost_per_token_batch=p.input_cost_per_token_batch,
                    output_cost_per_token_batch=p.output_cost_per_token_batch,
                    source="litellm",
                )
            )
            price_inserts += 1

    # Layer curated tier + cheaper-substitute judgment onto the freshly synced
    # catalog so the cheaper-model lever has candidates in production, not just
    # in the demo seed.
    curation_updates = apply_curation(db)

    db.commit()
    return {
        "models": len(parsed),
        "catalog_upserts": catalog_upserts,
        "price_inserts": price_inserts,
        "curation_updates": curation_updates,
    }


def fetch_feed(url: str) -> dict:
    resp = httpx.get(url, timeout=30.0, follow_redirects=True)
    resp.raise_for_status()
    return resp.json()


def main() -> int:
    raw = fetch_feed(settings.pricing_feed_url)
    db = SessionLocal()
    try:
        counts = sync(db, raw)
    finally:
        db.close()
    print(
        f"synced {counts['models']} models | "
        f"catalog upserts: {counts['catalog_upserts']} | "
        f"new price versions: {counts['price_inserts']} | "
        f"curation updates: {counts['curation_updates']}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
