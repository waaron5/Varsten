"""Tests for the price loader: parsing, idempotent re-runs, and versioning on
price change. Runs against local Postgres (rolled back per test).

Model keys are synthetic so the global count assertions stay independent of any
real catalog rows a live `sync_prices` run may have seeded into the dev DB.
"""

from decimal import Decimal
from typing import Any

import pytest

from app.models import ModelCatalog, ModelPrice
from scripts.sync_prices import REQUIRED_LAUNCH_PRICES, parse_feed, sync, validate_launch_coverage

MODEL = "varsten-test-model"

FEED: dict[str, dict[str, Any]] = {
    "sample_spec": {"note": "meta entry, must be ignored"},
    MODEL: {
        "litellm_provider": "varsten-test",
        "mode": "chat",
        "input_cost_per_token": 1.5e-07,
        "output_cost_per_token": 6e-07,
        "cache_read_input_token_cost": 7.5e-08,
        "supports_vision": True,
        "supports_function_calling": True,
    },
    "varsten-test-unpriced": {"litellm_provider": "varsten-test", "mode": "chat"},
}


def test_parse_skips_meta_and_unpriced():
    parsed = parse_feed(FEED)
    assert {p.model_key for p in parsed} == {MODEL}
    p = parsed[0]
    assert p.provider == "varsten-test"
    assert p.cache_read_input_token_cost == Decimal("7.5e-08")
    assert p.supports_vision is True


def test_sync_inserts_then_is_noop(db_session):
    first = sync(db_session, FEED)
    assert first["price_inserts"] == 1
    assert first["catalog_upserts"] == 1

    second = sync(db_session, FEED)
    assert second["price_inserts"] == 0  # unchanged price -> no new version

    assert db_session.query(ModelCatalog).filter_by(model_key=MODEL).count() == 1
    assert db_session.query(ModelPrice).filter_by(model_key=MODEL).count() == 1


def test_sync_appends_version_on_price_change(db_session):
    sync(db_session, FEED)
    changed = {**FEED, MODEL: {**FEED[MODEL], "input_cost_per_token": 2e-07}}
    result = sync(db_session, changed)
    assert result["price_inserts"] == 1
    assert db_session.query(ModelPrice).filter_by(model_key=MODEL).count() == 2


def test_sync_never_deletes_models_missing_from_a_later_feed(db_session):
    sync(db_session, FEED)
    result = sync(db_session, {})

    assert result["price_inserts"] == 0
    assert db_session.query(ModelCatalog).filter_by(model_key=MODEL).count() == 1
    assert db_session.query(ModelPrice).filter_by(model_key=MODEL).count() == 1


@pytest.mark.parametrize("bad_price", ["NaN", "Infinity", "-0.000001"])
def test_parse_rejects_invalid_token_prices(bad_price):
    feed = {**FEED, MODEL: {**FEED[MODEL], "input_cost_per_token": bad_price}}
    with pytest.raises(ValueError, match="invalid token price"):
        parse_feed(feed)


def test_launch_coverage_requires_every_onboarding_default():
    with pytest.raises(ValueError, match="anthropic/claude-haiku-4-5-20251001"):
        validate_launch_coverage(parse_feed(FEED))


def test_launch_coverage_accepts_all_direct_provider_defaults():
    feed = {
        model: {
            "litellm_provider": provider,
            "mode": "chat",
            "input_cost_per_token": "0.000001",
            "output_cost_per_token": "0.000005",
        }
        for provider, model in REQUIRED_LAUNCH_PRICES
    }
    validate_launch_coverage(parse_feed(feed))


def test_parse_adds_provider_scoped_gemini_alias():
    feed = {
        "gemini/gemini-3.1-flash-lite": {
            "litellm_provider": "gemini",
            "mode": "chat",
            "input_cost_per_token": "0.0000003",
            "output_cost_per_token": "0.0000025",
        }
    }
    identities = {(p.provider, p.model_key) for p in parse_feed(feed)}
    assert ("gemini", "gemini/gemini-3.1-flash-lite") in identities
    assert ("gemini", "gemini-3.1-flash-lite") in identities


def test_parse_does_not_overwrite_an_explicit_direct_model_with_alias():
    feed = {
        "gemini/gemini-3.1-flash-lite": {
            "litellm_provider": "gemini",
            "input_cost_per_token": "0.0000003",
            "output_cost_per_token": "0.0000025",
        },
        "gemini-3.1-flash-lite": {
            "litellm_provider": "gemini",
            "input_cost_per_token": "0.0000004",
            "output_cost_per_token": "0.0000030",
        },
    }
    direct = [p for p in parse_feed(feed) if p.provider == "gemini" and p.model_key == "gemini-3.1-flash-lite"]
    assert len(direct) == 1
    assert direct[0].input_cost_per_token == Decimal("0.0000004")
