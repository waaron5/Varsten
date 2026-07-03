"""Upstream retries and fallback: keep the request alive on transient failures.

"Fail open" has to mean "keep the customer's request alive," not just "relay the
error." A provider blip -- a dropped connection, a 429, a 5xx -- should be retried
a couple of times with backoff before the client ever sees a failure, and when
retries are exhausted the request should fall back to a configured degradation
model rather than dying. Savings stop; traffic does not.

Two hard safety rules, enforced by the callers in router.py:

- **Never retry after bytes have streamed.** Once the client has begun receiving
  a completion, re-sending would duplicate or corrupt it. Retries only ever wrap
  the connection attempt, before the first byte.
- **Never retry non-idempotent operations.** Batch submission has its own async
  path and is not routed through here at all.

This module is pure policy: retryability, the backoff schedule, Retry-After
parsing, and fallback-model resolution. The actual HTTP calls and the breaker
accounting stay in router.py so the hot path keeps one place that owns them. A
fallback is a reliability action, not an optimization, so it is recorded as
``fallback_used`` with zero claimed savings.
"""

import asyncio
import random
import time

import httpx

from app.core.config import settings
from app.proxy.circuit import is_upstream_failure


def retries_enabled() -> bool:
    return settings.proxy_retry_enabled and settings.proxy_retry_max_attempts > 0


def is_retryable_status(status_code: int) -> bool:
    """A 429 or 5xx is the provider faltering and is safe to retry before any
    bytes have streamed. A 4xx (other than 429) is the client's request and must
    be relayed unchanged."""
    return is_upstream_failure(status_code)


def backoff_delays() -> list[float]:
    """One delay per retry attempt: capped exponential backoff with full jitter.

    Full jitter (uniform in [0, capped_base]) spreads a fleet's retries so a
    recovering provider is not stampeded. The list length is the retry count, so
    ``len(...) + 1`` total attempts are made."""
    if not retries_enabled():
        return []
    delays: list[float] = []
    for i in range(settings.proxy_retry_max_attempts):
        capped = min(settings.proxy_retry_base_delay_seconds * (2**i), settings.proxy_retry_max_delay_seconds)
        delays.append(random.uniform(0.0, capped))  # nosec B311 - backoff jitter, not security
    return delays


def retry_after_seconds(retry_after_header: str | None, default: float) -> float:
    """Honour a 429/503 ``Retry-After`` (delta-seconds form), capped at the max
    backoff so a hostile or huge value cannot pin a request open. Falls back to the
    scheduled jittered delay when the header is absent or unparseable."""
    if retry_after_header:
        try:
            return min(float(retry_after_header), settings.proxy_retry_max_delay_seconds)
        except (TypeError, ValueError):
            pass
    return default


def fallback_model(project_id, requested_model: str) -> str | None:
    """The configured same-provider degradation model for this project, or None.

    Never returns the model we just failed on (that would be a pointless retry)."""
    if not settings.proxy_fallback_enabled:
        return None
    candidate = settings.proxy_fallback_models.get(str(project_id))
    if candidate and candidate != requested_model:
        return candidate
    return None


async def post_with_retry(
    client: httpx.AsyncClient,
    url: str,
    *,
    headers: dict,
    json: dict,
    timeout,
) -> tuple[httpx.Response | None, Exception | None]:
    """POST with capped, budgeted retries on connect errors and retryable statuses.

    Returns ``(response, last_exc)``. A 200 or a non-retryable status returns
    immediately; a ``None`` response means every attempt raised a connection error.
    Retries stop at the added-latency budget. This does NOT touch the circuit
    breaker: the caller records exactly one breaker outcome per request (a single
    slow request must not count as several failures)."""
    delays = backoff_delays()
    deadline = time.monotonic() + settings.proxy_retry_budget_seconds
    last_exc: Exception | None = None
    resp: httpx.Response | None = None
    for attempt in range(1 + len(delays)):
        try:
            resp = await client.post(url, headers=headers, json=json, timeout=timeout)
        except httpx.RequestError as exc:
            last_exc = exc
            resp = None
            if attempt < len(delays) and time.monotonic() < deadline:
                await asyncio.sleep(delays[attempt])
                continue
            return None, last_exc
        if resp.status_code == 200 or not is_retryable_status(resp.status_code):
            return resp, None
        if attempt < len(delays) and time.monotonic() < deadline:
            await asyncio.sleep(retry_after_seconds(resp.headers.get("retry-after"), delays[attempt]))
            continue
        return resp, None
    return resp, last_exc
