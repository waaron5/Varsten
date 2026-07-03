"""Parse client-supplied Varsten request metadata off the proxy entry path.

A customer passes optional business/task context with each proxied request so
Varsten can attribute cost and quality to the workload that generated it. This is
the seed of the moat: without it, every production request loses the context that
later lets Varsten learn task economics.

Two ways to pass it, both optional and additive:

- ``X-Varsten-Metadata``: a JSON object (preferred), e.g.
  {"feature": "support_reply", "task_type": "support_reply.billing",
   "customer_id": "cust_123", "risk_level": "medium"}
- individual ``X-Varsten-*`` headers (fallback for clients that cannot set a JSON
  header), e.g. ``X-Varsten-Feature: support_reply``. These override the JSON
  object when both are present, since they are the more explicit signal.

Parsing is total and fail-open: malformed JSON, oversized payloads, or junk
values never raise into the request. The worst case is an empty context and a
request that still succeeds. Nothing here touches the upstream provider request,
so these headers are never forwarded (the adapters build fresh upstream headers).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger("varsten.proxy.request_context")

# String values are capped to keep one malformed header from bloating a row or an
# index. Generous enough for real workflow/customer identifiers.
_MAX_VALUE_LEN = 256
# Bound the number of free-form extra keys carried into metadata JSONB.
_MAX_EXTRA_KEYS = 32

# Known fields mapped to first-class meaning. Anything else a client sends in the
# JSON object is preserved under ``extra`` (bounded), never dropped silently.
_STRING_FIELDS = (
    "feature",
    "workflow",
    "customer_id",
    "external_user_id",
    "user_id",
    "team",
    "department",
    "environment",
    "task_type",
    "risk_level",
    "quality_threshold",
    "trace_id",
)

# Individual fallback headers -> field name. Lower-cased lookup; FastAPI/Starlette
# header access is case-insensitive but we normalize anyway.
_HEADER_FIELDS = {
    "x-varsten-feature": "feature",
    "x-varsten-workflow": "workflow",
    "x-varsten-customer-id": "customer_id",
    "x-varsten-external-user-id": "external_user_id",
    "x-varsten-user-id": "user_id",
    "x-varsten-team": "team",
    "x-varsten-department": "department",
    "x-varsten-environment": "environment",
    "x-varsten-task-type": "task_type",
    "x-varsten-risk-level": "risk_level",
    "x-varsten-quality-threshold": "quality_threshold",
    "x-varsten-trace-id": "trace_id",
}

# The fail-open SDKs stamp this on their optimized (primary) calls so Varsten can
# tell that traffic for a provider is running through a Varsten SDK -- the signal
# behind the dashboard's per-provider "Fallback coverage" status. Recorded into the
# usage-event metadata; never forwarded upstream.
SDK_CLIENT_HEADER = "x-varsten-client"

# Every Varsten control header. Used by callers that want to assert these are not
# forwarded upstream.
VARSTEN_REQUEST_HEADERS = (
    "x-varsten-metadata",
    *_HEADER_FIELDS.keys(),
    "x-varsten-task-confidence",
    SDK_CLIENT_HEADER,
)


@dataclass(frozen=True)
class RequestContext:
    """Validated, sanitized client-supplied context for one proxied request."""

    feature: str | None = None
    workflow: str | None = None
    customer_id: str | None = None
    external_user_id: str | None = None
    user_id: str | None = None
    team: str | None = None
    department: str | None = None
    environment: str | None = None
    task_type: str | None = None
    task_confidence: float | None = None
    risk_level: str | None = None
    quality_threshold: str | None = None
    # Client-supplied trace/session id grouping the calls of one agent workflow,
    # so redundant calls within a trace can be detected (D3 agent-loop analysis).
    trace_id: str | None = None
    # The Varsten SDK that issued this optimized call, e.g. "varsten-anthropic/0.1.0".
    sdk_client: str | None = None
    # Any additional client-supplied JSON keys, sanitized and bounded.
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def is_empty(self) -> bool:
        return (
            not any(getattr(self, f) is not None for f in (*_STRING_FIELDS, "task_confidence"))
            and self.sdk_client is None
            and not self.extra
        )

    def task_metadata(self) -> dict[str, Any]:
        """Task/quality context to merge into the ledger's metadata JSONB. Business
        dimensions go to first-class usage_events columns; these do not have
        columns yet, so they ride in metadata for Phase 1."""
        meta: dict[str, Any] = {}
        if self.task_type is not None:
            meta["task_type"] = self.task_type
        if self.task_confidence is not None:
            meta["task_confidence"] = self.task_confidence
        if self.risk_level is not None:
            meta["risk_level"] = self.risk_level
        if self.quality_threshold is not None:
            meta["quality_threshold"] = self.quality_threshold
        if self.sdk_client is not None:
            meta["sdk_client"] = self.sdk_client
        if self.extra:
            meta["context"] = dict(self.extra)
        return meta


EMPTY_CONTEXT = RequestContext()


def _sanitize_str(value: Any) -> str | None:
    """Coerce a scalar to a bounded, stripped string. Non-scalars are dropped."""
    if value is None or isinstance(value, dict | list):
        return None
    # A bool is a valid scalar but ambiguous as an identifier; stringify it.
    text = ("true" if value else "false") if isinstance(value, bool) else str(value)
    text = text.strip()
    if not text:
        return None
    return text[:_MAX_VALUE_LEN]


def _sanitize_confidence(value: Any) -> float | None:
    try:
        conf = float(value)
    except (TypeError, ValueError):
        return None
    if conf != conf:  # NaN
        return None
    return max(0.0, min(1.0, conf))


def _parse_metadata_json(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    if len(raw.encode("utf-8", errors="ignore")) > settings.proxy_metadata_max_bytes:
        logger.warning("X-Varsten-Metadata exceeds size limit; ignoring")
        return {}
    try:
        parsed = json.loads(raw)
    except (ValueError, TypeError):
        logger.warning("X-Varsten-Metadata is not valid json; ignoring")
        return {}
    if not isinstance(parsed, dict):
        return {}
    return parsed


def parse_request_context(headers: dict[str, str]) -> RequestContext:
    """Build a RequestContext from request headers. Total and fail-open: any
    problem yields an empty-or-partial context, never an exception."""
    lower = {k.lower(): v for k, v in headers.items()}

    blob = _parse_metadata_json(lower.get("x-varsten-metadata"))

    values: dict[str, str | None] = {}
    for fieldname in _STRING_FIELDS:
        values[fieldname] = _sanitize_str(blob.get(fieldname))
    confidence = _sanitize_confidence(blob.get("task_confidence"))

    # Individual headers override the JSON object: they are the more explicit
    # per-request signal and survive clients that cannot build a JSON header.
    for header_name, fieldname in _HEADER_FIELDS.items():
        if header_name in lower:
            sanitized = _sanitize_str(lower[header_name])
            if sanitized is not None:
                values[fieldname] = sanitized
    if "x-varsten-task-confidence" in lower:
        header_conf = _sanitize_confidence(lower["x-varsten-task-confidence"])
        if header_conf is not None:
            confidence = header_conf

    # Preserve unknown JSON keys (bounded) so a customer's custom dimensions are
    # not lost, without giving them first-class columns.
    known = set(_STRING_FIELDS) | {"task_confidence"}
    extra: dict[str, Any] = {}
    for key, val in blob.items():
        if key in known or not isinstance(key, str):
            continue
        sanitized = _sanitize_str(val)
        if sanitized is not None:
            extra[key[:_MAX_VALUE_LEN]] = sanitized
        if len(extra) >= _MAX_EXTRA_KEYS:
            break

    return RequestContext(
        feature=values["feature"],
        workflow=values["workflow"],
        customer_id=values["customer_id"],
        external_user_id=values["external_user_id"],
        user_id=values["user_id"],
        team=values["team"],
        department=values["department"],
        environment=values["environment"],
        task_type=values["task_type"],
        task_confidence=confidence,
        risk_level=values["risk_level"],
        quality_threshold=values["quality_threshold"],
        trace_id=values["trace_id"],
        sdk_client=_sanitize_str(lower.get(SDK_CLIENT_HEADER)),
        extra=extra,
    )
