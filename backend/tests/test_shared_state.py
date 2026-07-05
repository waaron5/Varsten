"""Cross-instance shared state (slice C2).

The circuit breaker and budget-cap cache keep per-process state by default; with a
shared store configured (Redis in prod) a trip or a computed cap propagates across
instances. These tests inject an in-process store to exercise the coordination
path, and a raising Redis client to prove every shared-store touch fails open.
"""

import time
import uuid

import anyio
import pytest

from app.core.config import settings
from app.proxy import budget_enforcement, circuit
from app.proxy import shared_state as ss


@pytest.fixture
def memory_store():
    store = ss.InProcessStore()
    ss.set_store(store)
    circuit.reset_all()
    try:
        yield store
    finally:
        ss.set_store(None)
        circuit.reset_all()


# --- InProcessStore ------------------------------------------------------------


def test_in_process_store_set_get_delete():
    store = ss.InProcessStore()
    store.set("a", "1")
    assert store.get("a") == "1"
    store.delete("a")
    assert store.get("a") is None


def test_in_process_store_ttl_expiry():
    store = ss.InProcessStore()
    store.set("a", "1", ttl_seconds=0.05)
    assert store.get("a") == "1"
    time.sleep(0.06)
    assert store.get("a") is None


def test_in_process_store_non_positive_ttl_is_immediately_expired():
    store = ss.InProcessStore()
    store.set("a", "1", ttl_seconds=0)
    assert store.get("a") is None


def test_in_process_store_clear_prefix():
    store = ss.InProcessStore()
    store.set("circuit:open:x", "1")
    store.set("circuit:open:y", "1")
    store.set("other", "1")
    store.clear_prefix("circuit:open:")
    assert store.get("circuit:open:x") is None
    assert store.get("other") == "1"


# --- circuit breaker coordination ----------------------------------------------


def test_circuit_trip_propagates_across_instances(memory_store, monkeypatch):
    monkeypatch.setattr(settings, "circuit_breaker_fail_threshold", 1)
    monkeypatch.setattr(settings, "circuit_breaker_reset_seconds", 60.0)
    # Two breaker objects with the same key stand in for two app instances sharing
    # one Redis.
    instance_a = circuit.CircuitBreaker("proj-1")
    instance_b = circuit.CircuitBreaker("proj-1")

    assert instance_b.allow() is True
    instance_a.record_failure()  # trips and publishes the open flag
    # Instance B never saw a failure itself, but respects the shared trip.
    assert instance_b.allow() is False

    instance_a.record_success()  # a probe elsewhere recovered
    assert instance_b.allow() is True


def test_circuit_reset_clears_shared_open_flag(memory_store, monkeypatch):
    monkeypatch.setattr(settings, "circuit_breaker_fail_threshold", 1)
    monkeypatch.setattr(settings, "circuit_breaker_reset_seconds", 60.0)
    instance_a = circuit.CircuitBreaker("proj-reset")
    instance_b = circuit.CircuitBreaker("proj-reset")

    instance_a.record_failure()
    assert instance_b.allow() is False

    circuit.reset_all()
    assert instance_b.allow() is True


def test_circuit_is_local_without_shared_store(monkeypatch):
    ss.set_store(None)
    circuit.reset_all()
    monkeypatch.setattr(settings, "circuit_breaker_fail_threshold", 1)
    monkeypatch.setattr(settings, "circuit_breaker_reset_seconds", 60.0)
    a = circuit.CircuitBreaker("proj-2")
    b = circuit.CircuitBreaker("proj-2")
    a.record_failure()
    # No shared store: B has no idea A tripped (per-process behaviour, unchanged).
    assert b.allow() is True


# --- budget cap cache coordination ---------------------------------------------


def test_budget_cache_uses_shared_store(memory_store):
    project_id = uuid.uuid4()
    budget_enforcement._cache.clear()
    # Prime the shared store as if another instance computed the exhausted set.
    memory_store.set(
        budget_enforcement._BUDGET_PREFIX + str(project_id),
        budget_enforcement._serialize_caps(frozenset({("team", "growth")})),
    )

    # A broken db would blow up if the value were recomputed; the shared hit avoids it.
    async def _run():
        return await budget_enforcement.exhausted_hard_caps(db=None, project_id=project_id)

    result = anyio.run(_run)
    assert result == frozenset({("team", "growth")})


def test_budget_computation_publishes_for_next_instance(memory_store, monkeypatch):
    project_id = uuid.uuid4()
    computed = frozenset({("feature", "chat")})
    calls = 0

    async def compute_once(db, pid):
        nonlocal calls
        assert pid == project_id
        calls += 1
        return computed

    monkeypatch.setattr(budget_enforcement, "_compute_and_report", compute_once)

    async def _run():
        first = await budget_enforcement.exhausted_hard_caps(db=object(), project_id=project_id)
        second = await budget_enforcement.exhausted_hard_caps(db=object(), project_id=project_id)
        return first, second

    first, second = anyio.run(_run)
    assert first == computed
    assert second == computed
    assert calls == 1
    assert memory_store.get(budget_enforcement._BUDGET_PREFIX + str(project_id)) == budget_enforcement._serialize_caps(
        computed
    )


def test_budget_shared_store_failure_still_returns_local_computation(monkeypatch):
    project_id = uuid.uuid4()
    computed = frozenset({("customer", "acme")})

    async def compute(db, pid):
        assert pid == project_id
        return computed

    monkeypatch.setattr(budget_enforcement, "_compute_and_report", compute)

    async def _run():
        return await budget_enforcement.exhausted_hard_caps(db=object(), project_id=project_id)

    ss.set_store(ss.RedisStore("redis://unused", client=_RaisingClient()))
    try:
        assert anyio.run(_run) == computed
    finally:
        ss.set_store(None)


def test_clear_budget_cache_clears_shared_store(memory_store):
    project_id = uuid.uuid4()
    key = budget_enforcement._BUDGET_PREFIX + str(project_id)
    memory_store.set(key, budget_enforcement._serialize_caps(frozenset({("feature", "chat")})))
    budget_enforcement.clear_budget_cache(project_id)
    assert memory_store.get(key) is None


# --- fail open -----------------------------------------------------------------


class _RaisingClient:
    def get(self, key):
        raise RuntimeError("redis down")

    def set(self, *a, **k):
        raise RuntimeError("redis down")

    def delete(self, key):
        raise RuntimeError("redis down")

    def scan_iter(self, match=None):
        raise RuntimeError("redis down")


def test_redis_store_fails_open():
    store = ss.RedisStore("redis://unused", client=_RaisingClient())
    # Every operation swallows the backend error and behaves as miss / no-op.
    assert store.get("k") is None
    store.set("k", "v", ttl_seconds=1)  # no raise
    store.delete("k")  # no raise
    store.clear_prefix("p")  # no raise
