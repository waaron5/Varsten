"""Minimal in-memory fixed-window rate limiter.

Single-process only: state lives in this process's memory, so with more than one
app instance each instance limits independently (move to a shared store like Redis
when that matters). It is deliberately cheap — a dict lookup and an int compare —
so it is safe to call on the proxy hot path, and it fails open: if anything goes
wrong the request is allowed, never blocked by a limiter bug.
"""

import threading
import time

from app.core.logging import get_logger

logger = get_logger("varsten.ratelimit")


class _FixedWindow:
    def __init__(self) -> None:
        # key -> (window_start_epoch_second_bucket, count)
        self._counts: dict[str, tuple[int, int]] = {}
        self._lock = threading.Lock()

    def allow(self, key: str, limit: int, window_seconds: int = 60) -> bool:
        if limit <= 0:
            return True
        now = time.monotonic()
        bucket = int(now // window_seconds)
        with self._lock:
            current = self._counts.get(key)
            if current is None or current[0] != bucket:
                self._counts[key] = (bucket, 1)
                return True
            window_bucket, count = current
            if count >= limit:
                return False
            self._counts[key] = (window_bucket, count + 1)
            return True

    def reset(self) -> None:
        with self._lock:
            self._counts.clear()


_limiter = _FixedWindow()


def allow(key: str, limit: int, window_seconds: int = 60) -> bool:
    """Return True if this call is within the limit for ``key``. Fail-open."""
    try:
        return _limiter.allow(key, limit, window_seconds)
    except Exception:  # pragma: no cover - defensive; a limiter bug must not block traffic
        logger.exception("rate limiter error; allowing request")
        return True


def reset_all() -> None:
    """Clear all windows. For test isolation and operational reset."""
    _limiter.reset()
