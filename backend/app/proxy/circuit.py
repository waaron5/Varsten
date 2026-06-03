"""Per-project circuit breaker for the upstream provider.

When OpenAI starts failing or timing out, the breaker opens so the proxy fails
fast (a quick 503) instead of making every request wait the full timeout and
piling load onto a sick upstream. After a cooldown it half-opens to probe; one
success closes it, one failure reopens it.

State is in-memory per process. In a multi-instance deploy each instance protects
itself independently; a shared (Redis-backed) breaker is a later optimization.
Cache hits never consult the breaker, so cached responses keep serving even while
the circuit is open.
"""
import time

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger("varsten.circuit")

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

    def record_failure(self) -> None:
        self.failures += 1
        tripped = self.state == HALF_OPEN or self.failures >= settings.circuit_breaker_fail_threshold
        if tripped:
            if self.state != OPEN:
                logger.warning(
                    "circuit opened", extra={"circuit": self.key, "failures": self.failures}
                )
            self.state = OPEN
            self.opened_at = time.monotonic()


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
