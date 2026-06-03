"""Request-context middleware and optional Sentry error tracking.

The middleware is pure ASGI (not BaseHTTPMiddleware) so the request-id contextvar
it sets propagates into the endpoint and into a streaming response body, which a
BaseHTTPMiddleware would not guarantee.
"""
import time
import uuid

from app.core.config import settings
from app.core.logging import get_logger, request_id_ctx

logger = get_logger("varsten.request")

REQUEST_ID_HEADER = b"x-request-id"


def _incoming_request_id(scope) -> str | None:
    for key, value in scope.get("headers", []):
        if key == REQUEST_ID_HEADER:
            return value.decode("latin-1")
    return None


class RequestContextMiddleware:
    """Assign/echo X-Request-ID, bind it for the request's logs, and access-log
    the outcome with method, path, status, and duration."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id = _incoming_request_id(scope) or uuid.uuid4().hex
        token = request_id_ctx.set(request_id)
        start = time.perf_counter()
        status_code = 500

        async def send_wrapper(message):
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
                headers = message.setdefault("headers", [])
                headers.append((REQUEST_ID_HEADER, request_id.encode("latin-1")))
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            duration_ms = round((time.perf_counter() - start) * 1000, 1)
            logger.info(
                "request",
                extra={
                    "method": scope.get("method"),
                    "path": scope.get("path"),
                    "status": status_code,
                    "duration_ms": duration_ms,
                },
            )
            request_id_ctx.reset(token)


def init_sentry() -> bool:
    """Initialize Sentry if a DSN is configured. Error-level logs (including the
    proxy's fail-open logger.exception calls) become Sentry events automatically
    via the logging integration. Returns True if enabled."""
    if not settings.sentry_dsn:
        return False
    try:
        import sentry_sdk
        from sentry_sdk.integrations.fastapi import FastApiIntegration
        from sentry_sdk.integrations.logging import LoggingIntegration
        from sentry_sdk.integrations.starlette import StarletteIntegration
    except ImportError:
        logger.warning("sentry_dsn set but sentry-sdk is not installed; skipping")
        return False

    sentry_sdk.init(
        dsn=settings.sentry_dsn,
        environment=settings.sentry_environment,
        integrations=[
            StarletteIntegration(),
            FastApiIntegration(),
            LoggingIntegration(level=None, event_level="ERROR"),
        ],
        traces_sample_rate=0.0,
    )
    logger.info("sentry initialized", extra={"environment": settings.sentry_environment})
    return True
