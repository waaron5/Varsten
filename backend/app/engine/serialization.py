from __future__ import annotations

from typing import Any

from app.engine.types import OptimizationPlan


def plan_to_metadata(plan: OptimizationPlan) -> dict[str, Any]:
    """Serialize a planner result for evidence metadata.

    This intentionally includes only derived facts and reason codes. Prompt text,
    completion text, tool arguments, and request bodies must not appear here.
    """
    return {
        "planner_version": plan.planner_version,
        "selected": {
            "action": plan.selected.action,
            "mode": plan.selected.mode,
            "reason_code": plan.selected.reason_code,
        },
        "classification": {
            "task_type": plan.classification.task_type,
            "task_confidence": plan.classification.task_confidence,
            "risk_level": plan.classification.risk_level.value,
            "prompt_chars": plan.classification.prompt_chars,
            "message_count": plan.classification.message_count,
            "has_tools": plan.classification.has_tools,
            "wants_json": plan.classification.wants_json,
            "has_multimodal": plan.classification.has_multimodal,
            "personalized": plan.classification.personalized,
            "freshness_sensitive": plan.classification.freshness_sensitive,
            "unknown_task": plan.classification.unknown_task,
            "reason_codes": list(plan.classification.reason_codes),
        },
        "candidates": [
            {
                "lever": candidate.lever,
                "status": candidate.status.value,
                "quality_gate": candidate.quality_gate.value,
                "risk": candidate.risk.value,
                "reason_code": candidate.reason_code,
                "reason_detail": candidate.reason_detail,
                "policy_id": str(candidate.policy_id) if candidate.policy_id else None,
                "estimated_savings_usd": candidate.estimated_savings_usd,
            }
            for candidate in plan.candidates
        ],
    }
