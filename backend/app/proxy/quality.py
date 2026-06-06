"""Objective response-health signal for live drift detection.

Computed at capture time (off the hot path), this is a cheap, objective boolean
per completion: did the model return a usable answer? No model call, no judge, no
stored content. The boolean is a metadata fact, so the ledger stays metadata-only
while still carrying enough to compare the treatment arm's health against the
concurrent control arm.

This is deliberately the objective floor (empty, truncated, malformed-JSON, or
filtered responses fail). Subtle subjective quality loss is not caught here and is
a judge-based, approve-mode concern, never auto-rollback.
"""

import json


def wants_json(body: dict) -> bool:
    fmt = (body or {}).get("response_format")
    return isinstance(fmt, dict) and fmt.get("type") in {"json_object", "json_schema"}


def response_quality_ok(payload: dict | None, json_expected: bool) -> bool:
    """True when the completion is a usable answer: non-empty, finished cleanly,
    and valid JSON when the route requested JSON."""
    if not payload:
        return False
    try:
        choice = payload["choices"][0]
    except (KeyError, IndexError, TypeError):
        return False

    if choice.get("finish_reason") in {"length", "content_filter"}:
        return False  # truncated or filtered: a degraded answer

    message = choice.get("message") or {}
    if message.get("tool_calls"):
        return True  # a tool call is a valid completion even with null content

    content = message.get("content")
    if isinstance(content, list):
        content = " ".join(b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text")
    if not content or not content.strip():
        return False

    if json_expected:
        try:
            json.loads(content)
        except (json.JSONDecodeError, TypeError):
            return False
    return True
