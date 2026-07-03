from __future__ import annotations

from typing import Any

from app.engine.request_facts import normalize_request_facts
from app.engine.types import OptimizationRisk, RequestClassification, RequestFacts
from app.proxy.request_context import EMPTY_CONTEXT, RequestContext

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


def classify_request(
    body: dict[str, Any] | RequestFacts, context: RequestContext | None = None
) -> RequestClassification:
    """Classify a provider request into conservative optimization features.

    The classifier intentionally avoids returning request text. Downstream code
    should persist only the derived flags and reason codes returned here.
    """
    ctx = context or EMPTY_CONTEXT
    facts = body if isinstance(body, RequestFacts) else normalize_request_facts(body)
    task_type = ctx.task_type
    task_confidence = ctx.task_confidence

    personalized = _has_personal_context(ctx) or facts.personalized_signal
    freshness_sensitive = facts.freshness_signal

    unknown_task = not task_type or (task_confidence is not None and task_confidence < 0.5)
    risk_level = _risk_from_context(ctx.risk_level)
    has_high_risk_signal = _has_high_risk_signal(task_type, facts)
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
    if facts.has_tools:
        reason_codes.append("tools_present")
    if facts.wants_json:
        reason_codes.append("json_output")
    if facts.has_multimodal:
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
        prompt_chars=facts.prompt_chars,
        message_count=facts.message_count,
        has_tools=facts.has_tools,
        wants_json=facts.wants_json,
        has_multimodal=facts.has_multimodal,
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


def _has_personal_context(ctx: RequestContext) -> bool:
    return any((ctx.customer_id, ctx.external_user_id, ctx.user_id))


def _has_high_risk_signal(task_type: str | None, facts: RequestFacts) -> bool:
    task = (task_type or "").lower()
    return any(fragment in task for fragment in _HIGH_RISK_TASK_FRAGMENTS) or facts.high_risk_signal
