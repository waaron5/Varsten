from __future__ import annotations

from typing import Any

_MAX_DETAIL_STRING = 256
_MAX_DETAIL_LIST = 32
_DENYLISTED_DETAIL_KEYS = {
    "arguments",
    "body",
    "completion",
    "content",
    "messages",
    "prompt",
    "request",
    "request_body",
    "response",
    "response_payload",
    "tool_arguments",
}


def runtime_trace_event(
    *,
    stage: str,
    lever: str,
    action: str,
    reason_code: str,
    enforced: bool = False,
    policy_id: str | None = None,
    source_recommendation_id: str | None = None,
    detail: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a content-free runtime trace event for request evidence.

    The detail sanitizer deliberately drops fields that commonly contain prompt,
    completion, request body, or tool argument content. Runtime traces are for
    auditability of decisions, not content capture.
    """
    event: dict[str, Any] = {
        "stage": stage,
        "lever": lever,
        "action": action,
        "reason_code": reason_code,
        "enforced": enforced,
    }
    if policy_id:
        event["policy_id"] = str(policy_id)
    if source_recommendation_id:
        event["source_recommendation_id"] = str(source_recommendation_id)
    clean_detail = _clean_detail(detail or {})
    if clean_detail:
        event["detail"] = clean_detail
    return event


def _clean_detail(value: Any) -> Any:
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for key, nested in value.items():
            if not isinstance(key, str):
                continue
            if key.lower() in _DENYLISTED_DETAIL_KEYS:
                continue
            clean = _clean_detail(nested)
            if clean is not None:
                out[key[:_MAX_DETAIL_STRING]] = clean
        return out
    if isinstance(value, list | tuple):
        items = [_clean_detail(item) for item in value[:_MAX_DETAIL_LIST]]
        return [item for item in items if item is not None]
    if isinstance(value, str):
        text = value.strip()
        return text[:_MAX_DETAIL_STRING] if text else None
    if isinstance(value, bool | int | float) or value is None:
        return value
    return str(value)[:_MAX_DETAIL_STRING]
