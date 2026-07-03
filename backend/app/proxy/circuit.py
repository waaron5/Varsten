"""Per-project circuit breaker for the upstream provider.

When OpenAI starts failing or timing out, the breaker opens so the proxy fails
fast (a quick 503) instead of making every request wait the full timeout and
piling load onto a sick upstream. After a cooldown it half-opens to probe; one
success closes it, one failure reopens it.

State is in-memory per process. Failure counting toward the trip threshold stays
per-instance -- each process learns the upstream is sick on its own. When a
shared store is configured (REDIS_URL, for multi-instance deploys), the *open*
flag is published to it with the reset window as its TTL, so the moment one
instance trips, every instance fails fast without having to re-learn the outage;
a probe success on any instance clears it. With no shared store (the default)
this layer is inert and the breaker is exactly the per-process one it always was.
Every shared-store touch fails open, so Redis being down only costs coordination.

Cache hits never consult the breaker, so cached responses keep serving even while
the circuit is open.
"""

import time

from app.core.config import settings
from app.core.logging import get_logger
from app.proxy import shared_state

logger = get_logger("varsten.circuit")

_OPEN_PREFIX = "circuit:open:"


def _shared_open(key: str) -> bool:
    """Whether any instance has published this circuit as open. False (never
    blocking) when there is no shared store or the store errors."""
    store = shared_state.get_store()
    if store is None:
        return False
    return store.get(_OPEN_PREFIX + key) is not None


def _shared_set_open(key: str) -> None:
    store = shared_state.get_store()
    if store is not None:
        store.set(_OPEN_PREFIX + key, "1", ttl_seconds=settings.circuit_breaker_reset_seconds)


def _shared_clear_open(key: str) -> None:
    store = shared_state.get_store()
    if store is not None:
        store.delete(_OPEN_PREFIX + key)


CLOSED = "closed"
OPEN = "open"
HALF_OPEN = "half_open"

# Upstream statuses that count as the provider failing (vs a client mistake).
UPSTREAM_FAILURE_STATUSES = frozenset({429, 500, 502, 503, 504})


def is_upstream_failure(status_code: int) -> bool:
    return status_code in UPSTREAM_FAILURE_STATUSES or status_code >= 500


class CircuitBreaker:
    def __init__(self, key: str):
        self.key = key
        self.state = CLOSED
        self.failures = 0
        self.opened_at = 0.0

    def allow(self) -> bool:
        """Whether a request may hit the upstream now."""
        if not settings.circuit_breaker_enabled:
            return True
        # Respect a trip published by any instance (shared store); inert by default.
        if _shared_open(self.key):
            return False
        if self.state == OPEN:
            if time.monotonic() - self.opened_at >= settings.circuit_breaker_reset_seconds:
                self.state = HALF_OPEN
                logger.info("circuit half-open", extra={"circuit": self.key})
                return True
            return False
        return True  # closed or half-open

    def record_success(self) -> None:
        if self.state != CLOSED:
            logger.info("circuit closed", extra={"circuit": self.key})
        self.state = CLOSED
        self.failures = 0
        _shared_clear_open(self.key)

    def record_failure(self) -> None:
        self.failures += 1
        tripped = self.state == HALF_OPEN or self.failures >= settings.circuit_breaker_fail_threshold
        if tripped:
            if self.state != OPEN:
                logger.warning("circuit opened", extra={"circuit": self.key, "failures": self.failures})
            self.state = OPEN
            self.opened_at = time.monotonic()
            _shared_set_open(self.key)


_breakers: dict[str, CircuitBreaker] = {}


def get_breaker(key) -> CircuitBreaker:
    k = str(key)
    breaker = _breakers.get(k)
    if breaker is None:
        breaker = CircuitBreaker(k)
        _breakers[k] = breaker
    return breaker


def reset_all() -> None:
    """Clear all breaker state (used by tests)."""
    _breakers.clear()
    store = shared_state.get_store()
    if store is not None:
        store.clear_prefix(_OPEN_PREFIX)
