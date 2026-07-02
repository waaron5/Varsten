from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from app.engine.types import RequestClassification

CacheLever = Literal["exact_cache", "semantic_cache"]


@dataclass(frozen=True)
class CacheEligibilityDecision:
    """Decision metadata for the cache safety gate.

    Planner metadata stays content-free and shadow-shaped while the proxy rolls
    out runtime enforcement incrementally for the safest blockers first.
    """

    lever: CacheLever
    allowed: bool
    reason_code: str
    blockers: tuple[str, ...] = ()
    mode: str = "shadow"
    enforced: bool = False

    def metadata(self) -> dict[str, Any]:
        return {
            "cache_gate": {
                "mode": self.mode,
                "decision": "allow" if self.allowed else "reject",
                "enforced": self.enforced,
                "reason_code": self.reason_code,
                "blockers": list(self.blockers),
            }
        }


def evaluate_cache_eligibility(lever: CacheLever, classification: RequestClassification) -> CacheEligibilityDecision:
    blockers = _cache_blockers(classification)
    if lever == "semantic_cache":
        blockers = (*blockers, *_semantic_only_blockers(classification))

    if blockers:
        return CacheEligibilityDecision(
            lever=lever,
            allowed=False,
            reason_code="cache_gate_shadow_reject",
            blockers=tuple(dict.fromkeys(blockers)),
        )
    return CacheEligibilityDecision(
        lever=lever,
        allowed=True,
        reason_code="cache_gate_shadow_allow",
    )


def _cache_blockers(classification: RequestClassification) -> tuple[str, ...]:
    blockers: list[str] = []
    if classification.risky_or_unknown:
        blockers.append("risky_or_unknown")
    if classification.personalized:
        blockers.append("personalized_request")
    if classification.freshness_sensitive:
        blockers.append("freshness_sensitive")
    if classification.has_tools:
        blockers.append("tools_present")
    if classification.has_multimodal:
        blockers.append("multimodal_content")
    return tuple(blockers)


def _semantic_only_blockers(classification: RequestClassification) -> tuple[str, ...]:
    blockers: list[str] = []
    if classification.wants_json:
        blockers.append("json_output")
    return tuple(blockers)
