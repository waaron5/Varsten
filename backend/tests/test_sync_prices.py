"""Tests for the price loader: parsing, idempotent re-runs, and versioning on
price change. Runs against local Postgres (rolled back per test).

Model keys are synthetic so the global count assertions stay independent of any
real catalog rows a live `sync_prices` run may have seeded into the dev DB.
"""

from decimal import Decimal
from typing import Any

from app.models import ModelCatalog, ModelPrice
from scripts.sync_prices import parse_feed, sync

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
