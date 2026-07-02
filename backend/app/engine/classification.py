from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from app.engine.types import OptimizationRisk, RequestClassification
from app.proxy.request_context import EMPTY_CONTEXT, RequestContext

_FRESHNESS_TERMS = (
    "as of ",
    "breaking",
    "current",
    "latest",
    "live",
    "now",
    "recent",
    "right now",
    "stock price",
    "this month",
    "this week",
    "today",
    "weather",
    "yesterday",
)

_PERSONALIZED_TERMS = (
    "account number",
    "billing address",
    "customer id",
    "for my account",
    "my account",
    "patient",
    "policy number",
    "ssn",
    "social security",
)

_HIGH_RISK_TERMS = (
    "diagnose",
    "dosage",
    "financial advice",
    "legal advice",
    "medical advice",
    "prescription",
    "security vulnerability",
    "trade stock",
)

_HIGH_RISK_TASK_FRAGMENTS = (
    "compliance",
    "financial",
    "health",
    "hr",
    "legal",
    "medical",
    "policy",
    "security",
)

_MULTIMODAL_PART_TYPES = (
    "audio",
    "file",
    "image",
    "image_url",
    "input_audio",
    "input_file",
    "input_image",
    "video",
)

_MULTIMODAL_FIELDS = ("audio", "file", "image", "image_url", "input_audio", "input_file", "input_image", "video")


def classify_request(body: dict[str, Any], context: RequestContext | None = None) -> RequestClassification:
    """Classify a provider request into conservative optimization features.

    The classifier intentionally avoids returning request text. Downstream code
    should persist only the derived flags and reason codes returned here.
    """
    ctx = context or EMPTY_CONTEXT
    prompt_fragments = tuple(_iter_text_fragments(body))
    prompt_text = "\n".join(prompt_fragments).lower()
    prompt_chars = sum(len(fragment) for fragment in prompt_fragments)
    message_count = _message_count(body)
    task_type = ctx.task_type
    task_confidence = ctx.task_confidence

    has_tools = bool(body.get("tools") or body.get("functions"))
    wants_json = _wants_json(body)
    has_multimodal = _body_has_multimodal(body)
    personalized = _has_personal_context(ctx) or _contains_any(prompt_text, _PERSONALIZED_TERMS)
    freshness_sensitive = _contains_any(prompt_text, _FRESHNESS_TERMS)

    unknown_task = not task_type or (task_confidence is not None and task_confidence < 0.5)
    risk_level = _risk_from_context(ctx.risk_level)
    has_high_risk_signal = _has_high_risk_signal(task_type, prompt_text)
    if has_high_risk_signal:
        risk_level = OptimizationRisk.HIGH

    reason_codes: list[str] = []
    if unknown_task:
        reason_codes.append("unknown_task")
    if task_confidence is not None and task_confidence < 0.5:
        reason_codes.append("low_task_confidence")
    if risk_level == OptimizationRisk.HIGH:
        reason_codes.append("risk_high")
    elif risk_level == OptimizationRisk.UNKNOWN:
        reason_codes.append("risk_unknown")
    if has_tools:
        reason_codes.append("tools_present")
    if wants_json:
        reason_codes.append("json_output")
    if has_multimodal:
        reason_codes.append("multimodal_content")
    if personalized:
        reason_codes.append("personalized_request")
    if freshness_sensitive:
        reason_codes.append("freshness_sensitive")
    if has_high_risk_signal:
        reason_codes.append("high_risk_signal")

    return RequestClassification(
        task_type=task_type,
        task_confidence=task_confidence,
        risk_level=risk_level,
        prompt_chars=prompt_chars,
        message_count=message_count,
        has_tools=has_tools,
        wants_json=wants_json,
        has_multimodal=has_multimodal,
        personalized=personalized,
        freshness_sensitive=freshness_sensitive,
        unknown_task=unknown_task,
        reason_codes=tuple(dict.fromkeys(reason_codes)),
    )


def _risk_from_context(raw_risk: str | None) -> OptimizationRisk:
    normalized = (raw_risk or "").strip().lower()
    if normalized in {OptimizationRisk.LOW, OptimizationRisk.MEDIUM, OptimizationRisk.HIGH}:
        return OptimizationRisk(normalized)
    return OptimizationRisk.UNKNOWN


def _iter_text_fragments(value: Any) -> Iterable[str]:
    if isinstance(value, str):
        if value.strip():
            yield value
        return
    if isinstance(value, dict):
        for key, nested in value.items():
            if key in {"text", "content", "prompt", "input", "system", "messages"}:
                yield from _iter_text_fragments(nested)
        return
    if isinstance(value, list):
        for item in value:
            yield from _iter_text_fragments(item)


def _message_count(body: dict[str, Any]) -> int:
    messages = body.get("messages")
    if isinstance(messages, list):
        return len(messages)
    return 0


def _wants_json(body: dict[str, Any]) -> bool:
    response_format = body.get("response_format")
    if isinstance(response_format, dict):
        response_type = response_format.get("type")
        if response_type in {"json_object", "json_schema"}:
            return True
    response_mime_type = body.get("response_mime_type")
    return response_mime_type == "application/json"


def _body_has_multimodal(body: dict[str, Any]) -> bool:
    return any(_has_multimodal(value) for value in (body.get("messages"), body.get("input"), body.get("content")))


def _has_multimodal(value: Any) -> bool:
    if isinstance(value, dict):
        content_type = value.get("type")
        if isinstance(content_type, str) and content_type.lower() in _MULTIMODAL_PART_TYPES:
            return True
        if any(field in value for field in _MULTIMODAL_FIELDS):
            return True
        return any(_has_multimodal(value.get(field)) for field in ("content", "messages", "input"))
    if isinstance(value, list):
        return any(_has_multimodal(item) for item in value)
    return False


def _has_personal_context(ctx: RequestContext) -> bool:
    return any((ctx.customer_id, ctx.external_user_id, ctx.user_id))


def _contains_any(text: str, terms: tuple[str, ...]) -> bool:
    return any(term in text for term in terms)


def _has_high_risk_signal(task_type: str | None, prompt_text: str) -> bool:
    task = (task_type or "").lower()
    return _contains_any(task, _HIGH_RISK_TASK_FRAGMENTS) or _contains_any(prompt_text, _HIGH_RISK_TERMS)
