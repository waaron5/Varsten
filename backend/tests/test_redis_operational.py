"""Opt-in live Redis smoke for multi-instance coordination.

The deterministic unit tests inject in-process/fake clients so CI can prove the
coordination logic without external infrastructure. This smoke is for staging or
local Docker Redis: set VARSTEN_TEST_REDIS_URL and run it explicitly before
scaling the API horizontally.
"""

import importlib
import os
import uuid

import pytest

from app.core import ratelimit
from app.core.config import settings
from app.proxy import circuit
from app.proxy import shared_state as ss

pytestmark = pytest.mark.redis_live


def _redis_client():
    url = os.getenv("VARSTEN_TEST_REDIS_URL")
    if not url:
        pytest.skip("set VARSTEN_TEST_REDIS_URL to run live Redis operational smoke")
    redis = importlib.import_module("redis")
    client = redis.Redis.from_url(url, socket_timeout=0.25, socket_connect_timeout=0.25)
    client.ping()
    return url, client


def test_live_redis_coordinates_circuit_and_rate_limit(monkeypatch):
    monkeypatch.setattr(settings, "circuit_breaker_fail_threshold", 1)
    monkeypatch.setattr(settings, "circuit_breaker_reset_seconds", 60.0)
    url, client = _redis_client()
    store = ss.RedisStore(url, client=client)
    key = f"live-{uuid.uuid4().hex}"
    ss.set_store(store)
    try:
        instance_a = circuit.CircuitBreaker(key)
        instance_b = circuit.CircuitBreaker(key)
        instance_a.record_failure()
        assert instance_b.allow() is False
        instance_a.record_success()
        assert instance_b.allow() is True

        limiter_a = ratelimit.RedisFixedWindow(client)
        limiter_b = ratelimit.RedisFixedWindow(client)
        assert limiter_a.allow(key, 2) is True
        assert limiter_b.allow(key, 2) is True
        assert limiter_a.allow(key, 2) is False
    finally:
        store.delete(f"circuit:open:{key}")
        for redis_key in client.scan_iter(f"{ratelimit.RedisFixedWindow._KEY_PREFIX}{key}:*"):
            client.delete(redis_key)
        ss.set_store(None)
        circuit.reset_all()
