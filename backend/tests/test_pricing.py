"""Unit tests for price resolution and cost derivation.

resolve_price/price_usage_event run against local Postgres (rolled back per test);
compute_cost is pure.
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from app.models import ModelPrice, Organization, OrgModelPriceOverride
from app.pricing import (
    ResolvedPrice,
    compute_cost,
    price_usage_event,
    resolve_price,
)

NOW = datetime(2026, 6, 1, tzinfo=UTC)


def _price(**rate) -> ResolvedPrice:
    return ResolvedPrice(
        input_cost_per_token=Decimal(rate.get("input", "0.000001")),
        output_cost_per_token=Decimal(rate.get("output", "0.000002")),
        cache_read_input_token_cost=(Decimal(rate["cache"]) if "cache" in rate else None),
        source="catalog",
        price_version_id=None,
    )


def test_compute_cost_basic():
    # 1000 * 1e-6 + 500 * 2e-6 = 0.001 + 0.001
    assert compute_cost(_price(), 1000, 500, 0) == Decimal("0.002")


def test_compute_cost_applies_cache_discount():
    # 800 of 1000 input tokens are cache reads at 1e-7 instead of 1e-6.
    # uncached 200*1e-6 + cached 800*1e-7 + output 200*2e-6
    cost = compute_cost(_price(cache="0.0000001"), 1000, 200, 800)
    assert cost == Decimal("0.00068")


def test_compute_cost_falls_back_to_input_rate_without_cache_price():
    # No cache rate -> cached tokens billed at the input rate, same as no caching.
    with_cache = compute_cost(_price(), 1000, 0, 800)
    without_cache = compute_cost(_price(), 1000, 0, 0)
    assert with_cache == without_cache == Decimal("0.001")


def test_compute_cost_clamps_cached_to_input():
    # cached > input must not produce negative uncached tokens.
    assert compute_cost(_price(), 100, 0, 999) == compute_cost(_price(), 100, 0, 100)


def _org(db) -> Organization:
    org = Organization(name="T")
    db.add(org)
    db.flush()
    return org


def test_resolve_prefers_override_over_catalog(db_session):
    org = _org(db_session)
    db_session.add(
        ModelPrice(
            model_key="gpt-4o-mini",
            provider="openai",
            input_cost_per_token=Decimal("0.000001"),
            output_cost_per_token=Decimal("0.000002"),
            effective_at=NOW - timedelta(days=1),
        )
    )
    db_session.add(
        OrgModelPriceOverride(
            organization_id=org.id,
            model_key="gpt-4o-mini",
            provider=None,
            input_cost_per_token=Decimal("0.0000005"),
            output_cost_per_token=Decimal("0.000001"),
            effective_at=NOW - timedelta(days=1),
        )
    )
    db_session.flush()

    price = resolve_price(db_session, org.id, "gpt-4o-mini", "openai", NOW)
    assert price is not None
    assert price.source == "override"
    assert price.input_cost_per_token == Decimal("0.0000005")


def test_resolve_picks_latest_effective_at_before_event(db_session):
    org = _org(db_session)
    for day, rate in ((10, "0.000001"), (5, "0.000003")):
        db_session.add(
            ModelPrice(
                model_key="m",
                provider="openai",
                input_cost_per_token=Decimal(rate),
                output_cost_per_token=Decimal("0"),
                effective_at=NOW - timedelta(days=day),
            )
        )
    db_session.flush()

    # Between the two prices -> the older one is still in effect.
    older = resolve_price(db_session, org.id, "m", "openai", NOW - timedelta(days=7))
    assert older is not None
    assert older.input_cost_per_token == Decimal("0.000001")
    # After both -> the newer one.
    newer = resolve_price(db_session, org.id, "m", "openai", NOW)
    assert newer is not None
    assert newer.input_cost_per_token == Decimal("0.000003")


def test_resolve_returns_none_on_miss(db_session):
    org = _org(db_session)
    assert resolve_price(db_session, org.id, "nope", "openai", NOW) is None


def test_price_usage_event_falls_back_to_reported(db_session):
    org = _org(db_session)
    cost, source, pricing_status, version = price_usage_event(
        db_session,
        organization_id=org.id,
        model_key="unknown",
        provider="openai",
        input_tokens=10,
        output_tokens=10,
        cached_input_tokens=0,
        reported_cost_usd=Decimal("0.005"),
        at=NOW,
    )
    assert (cost, source, pricing_status, version) == (
        Decimal("0.005"),
        "reported",
        "model_not_in_catalog",
        None,
    )


def test_price_usage_event_unknown_without_reported_returns_null_cost(db_session):
    org = _org(db_session)
    cost, source, pricing_status, version = price_usage_event(
        db_session,
        organization_id=org.id,
        model_key="unknown",
        provider="openai",
        input_tokens=10,
        output_tokens=10,
        cached_input_tokens=0,
        reported_cost_usd=None,
        at=NOW,
    )
    assert (cost, source, pricing_status, version) == (
        None,
        "unknown",
        "model_not_in_catalog",
        None,
    )
