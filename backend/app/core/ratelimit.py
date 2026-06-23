"""Pluggable fixed-window rate limiter.

Two backends sit behind one ``allow(key, limit, window_seconds)`` interface:

- **memory** (default): a per-process dict + lock. Microsecond-cheap and safe to
  call on the proxy hot path, but each app instance limits independently, so it is
  only correct at a single instance. The right default for dev and single-instance
  deploys.
- **redis**: a shared fixed-window counter (atomic INCR + EXPIRE via a Lua script)
  so every app instance enforces one global window. Required once
  app_max_instances > 1. It FAILS OPEN -- an unreachable or slow Redis allows the
  request rather than blocking traffic -- and uses a tight socket timeout so a
  degraded Redis can never stall the hot path.

The limiter is called synchronously from the async proxy handler. For memory that
is free; for redis it costs one round-trip on the event loop, acceptable for a
same-VPC store (sub-millisecond) and bounded by the fail-open timeout. A fully
async path (async client + async allow) is a deliberate follow-up -- it would
change this interface, which callers depend on staying synchronous.
"""

import threading
import time
from typing import Any, Protocol

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger("varsten.ratelimit")


class RateLimiter(Protocol):
    def allow(self, key: str, limit: int, window_seconds: int = 60) -> bool: ...

    def reset(self) -> None: ...


class InMemoryFixedWindow:
    """Per-process fixed-window counter. Correct only at a single app instance."""

    def __init__(self) -> None:
        # key -> (window_start_bucket, count)
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


# Backward-compatible alias for any importer of the old class name.
_FixedWindow = InMemoryFixedWindow


# Atomic fixed window: INCR the bucket key, and only on the first hit (count == 1)
# set its TTL. Doing both in one script means concurrent instances cannot race the
# EXPIRE and leak a key with no TTL (which would wedge a window open forever).
_FIXED_WINDOW_LUA = """
local current = redis.call('INCR', KEYS[1])
if current == 1 then
  redis.call('EXPIRE', KEYS[1], ARGV[1])
end
return current
"""


class RedisFixedWindow:
    """Fixed-window counter shared across instances. Fails open on any Redis error."""

    _KEY_PREFIX = "varsten:rl:"

    def __init__(self, client: Any) -> None:
        self._client = client
        self._script: Any = None

    def allow(self, key: str, limit: int, window_seconds: int = 60) -> bool:
        if limit <= 0:
            return True
        # Wall-clock bucket so every instance agrees on the same window boundary.
        bucket = int(time.time() // window_seconds)
        redis_key = f"{self._KEY_PREFIX}{key}:{bucket}"
        try:
            if self._script is None:
                self._script = self._client.register_script(_FIXED_WINDOW_LUA)
            count = self._script(keys=[redis_key], args=[window_seconds])
            return int(count) <= limit
        except Exception:
            # Fail open: a degraded store must never block production traffic.
            logger.warning("redis rate limiter unavailable; allowing request", exc_info=True)
            return True

    def reset(self) -> None:
        try:
            for redis_key in self._client.scan_iter(f"{self._KEY_PREFIX}*"):
                self._client.delete(redis_key)
        except Exception:
            logger.warning("redis rate limiter reset failed", exc_info=True)


def _build_redis_client() -> Any:
    import redis  # lazy: only imported when the redis backend is actually selected

    return redis.Redis.from_url(
        settings.rate_limit_redis_url,
        socket_timeout=settings.rate_limit_redis_timeout_seconds,
        socket_connect_timeout=settings.rate_limit_redis_timeout_seconds,
    )


def build_limiter() -> RateLimiter:
    """Construct the limiter the settings ask for, with a safe fallback.

    Selecting redis but leaving it unconfigured, or failing to construct the client
    (missing dependency, bad URL), degrades to the in-memory limiter with a loud log
    rather than crashing the app at import time."""
    backend = settings.rate_limit_backend.strip().lower()
    if backend == "redis":
        if not settings.rate_limit_redis_url:
            logger.warning("rate_limit_backend=redis but rate_limit_redis_url is empty; using in-memory limiter")
            return InMemoryFixedWindow()
        try:
            return RedisFixedWindow(_build_redis_client())
        except Exception:
            logger.exception("failed to initialise redis rate limiter; using in-memory limiter")
            return InMemoryFixedWindow()
    return InMemoryFixedWindow()


_limiter: RateLimiter = build_limiter()


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


def set_limiter(limiter: RateLimiter) -> None:
    """Swap the active limiter. For tests and operational reconfiguration."""
    global _limiter
    _limiter = limiter
