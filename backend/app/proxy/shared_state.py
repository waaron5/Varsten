"""Optional cross-instance coordination for the proxy's local safety state.

Two pieces of proxy state are process-local today: the circuit breaker (is the
upstream failing?) and the budget-cap cache (which hard caps are exhausted?).
For a single instance that is exactly right -- each process protects itself. Run
more than one instance, though, and each one has to re-learn that the provider is
down or that a cap is blown, and a breaker one instance tripped does not protect
the others.

This module is the optional shared layer that fixes that when a deploy scales
out. It is a **complete no-op unless a backend is configured**: with no backend,
``get_store()`` returns ``None`` and the circuit/budget code runs its existing
local logic byte-for-byte, so single-instance and dev behaviour is unchanged and
no Redis connection is opened. Set ``REDIS_URL`` and a Redis-backed store is used
so a trip or a cap propagates fleet-wide.

Everything here fails open. Every store operation swallows backend errors and
behaves as a miss / no-op, so callers fall back to their local path: if Redis is
unreachable the worst case is "we stop coordinating," never "we broke a request."
The interface is deliberately tiny (get / set-with-ttl / delete / clear_prefix)
-- just enough for a boolean open-flag and a small cached blob.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Iterable
from typing import Protocol, cast

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger("varsten.proxy.shared_state")


class SharedStore(Protocol):
    """A minimal TTL key-value store shared across app instances."""

    def get(self, key: str) -> str | None: ...
    def set(self, key: str, value: str, ttl_seconds: float | None = None) -> None: ...
    def delete(self, key: str) -> None: ...
    def clear_prefix(self, prefix: str) -> None: ...


class _RedisClient(Protocol):
    def get(self, key: str) -> str | bytes | None: ...
    def set(self, key: str, value: str, px: int | None = None) -> object: ...
    def delete(self, key: str | bytes) -> object: ...
    def scan_iter(self, match: str) -> Iterable[str | bytes]: ...


class InProcessStore:
    """A thread-safe TTL dict. The default for tests and the fallback shape; in a
    single process it is exactly the local state the callers kept themselves, but
    behind the shared interface so the Redis path can be exercised without Redis."""

    def __init__(self) -> None:
        self._data: dict[str, tuple[str, float | None]] = {}
        self._lock = threading.Lock()

    def get(self, key: str) -> str | None:
        with self._lock:
            item = self._data.get(key)
            if item is None:
                return None
            value, expires_at = item
            if expires_at is not None and expires_at <= time.monotonic():
                self._data.pop(key, None)
                return None
            return value

    def set(self, key: str, value: str, ttl_seconds: float | None = None) -> None:
        # A non-positive TTL means "already expired": store nothing, drop any prior
        # value. This mirrors a reset window of zero (immediate half-open probe).
        if ttl_seconds is not None and ttl_seconds <= 0:
            self.delete(key)
            return
        expires_at = time.monotonic() + ttl_seconds if ttl_seconds is not None else None
        with self._lock:
            self._data[key] = (value, expires_at)

    def delete(self, key: str) -> None:
        with self._lock:
            self._data.pop(key, None)

    def clear_prefix(self, prefix: str) -> None:
        with self._lock:
            for key in [k for k in self._data if k.startswith(prefix)]:
                self._data.pop(key, None)


class RedisStore:
    """A Redis-backed store for multi-instance deploys. The redis client is
    imported lazily so the dependency is only needed when REDIS_URL is set. Every
    operation fails open: a backend error is logged and treated as a miss/no-op so
    the caller falls back to local behaviour."""

    def __init__(self, url: str, client: object | None = None) -> None:
        self._client: _RedisClient
        if client is not None:
            self._client = cast(_RedisClient, client)
            return
        import redis  # lazy: only required when a shared store is actually configured

        self._client = redis.Redis.from_url(url, socket_timeout=0.25, socket_connect_timeout=0.25)

    def get(self, key: str) -> str | None:
        try:
            value = self._client.get(key)
        except Exception:
            logger.warning("shared store get failed; treating as miss", extra={"key": key})
            return None
        return value.decode() if isinstance(value, bytes) else value

    def set(self, key: str, value: str, ttl_seconds: float | None = None) -> None:
        if ttl_seconds is not None and ttl_seconds <= 0:
            self.delete(key)
            return
        try:
            px = int(ttl_seconds * 1000) if ttl_seconds is not None else None
            self._client.set(key, value, px=px)
        except Exception:
            logger.warning("shared store set failed; ignoring", extra={"key": key})

    def delete(self, key: str) -> None:
        try:
            self._client.delete(key)
        except Exception:
            logger.warning("shared store delete failed; ignoring", extra={"key": key})

    def clear_prefix(self, prefix: str) -> None:
        try:
            for key in self._client.scan_iter(match=f"{prefix}*"):
                self._client.delete(key)
        except Exception:
            logger.warning("shared store clear_prefix failed; ignoring", extra={"prefix": prefix})


_store: SharedStore | None = None
_configured = False
_lock = threading.Lock()


def _build_default() -> SharedStore | None:
    if not settings.redis_url:
        return None
    try:
        store = RedisStore(settings.redis_url)
        logger.info("shared state using Redis backend")
        return store
    except Exception:
        logger.exception("Redis shared store unavailable; falling back to local (per-instance) state")
        return None


def get_store() -> SharedStore | None:
    """The configured shared store, or ``None`` for purely local behaviour.

    ``None`` is the default and means the caller keeps its own process-local
    state; only a configured backend (Redis in prod, or one injected in tests)
    turns on cross-instance coordination."""
    global _store, _configured
    if not _configured:
        with _lock:
            if not _configured:
                _store = _build_default()
                _configured = True
    return _store


def set_store(store: SharedStore | None) -> None:
    """Inject a store (tests) or force local behaviour with ``None``."""
    global _store, _configured
    with _lock:
        _store = store
        _configured = True


def reset() -> None:
    """Forget the configured store so it is rebuilt from settings (tests)."""
    global _store, _configured
    with _lock:
        _store = None
        _configured = False
