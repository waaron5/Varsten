"""Shared upstream HTTP client for the proxy hot path.

A single pooled httpx.AsyncClient serves every upstream call (completions,
embeddings), so a cache miss reuses a warm keep-alive connection to the provider
instead of paying a fresh TCP + TLS handshake per request. That handshake is
50-200ms against api.openai.com, which would dwarf the proxy's own overhead.

Timeouts stay per-request: the client is built with the non-streaming default
and each call site passes its own budget (stream read/connect, embedding bound).

Lifecycle: the FastAPI lifespan warms the pool on startup and closes it on
shutdown. get_client() also builds lazily so one-off processes (scripts, the
benchmark runner) work without a lifespan. Tests monkeypatch `_client` with an
httpx.MockTransport-backed instance to fake the upstream for both the router
and the embedding path through this one seam.
"""

import httpx

from app.core.config import settings

_client: httpx.AsyncClient | None = None


def get_client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(
            timeout=httpx.Timeout(settings.proxy_upstream_timeout_seconds),
            limits=httpx.Limits(
                max_connections=settings.proxy_pool_max_connections,
                max_keepalive_connections=settings.proxy_pool_max_keepalive_connections,
            ),
        )
    return _client


async def aclose() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None
