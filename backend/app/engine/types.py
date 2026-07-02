from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from app.proxy.request_context import EMPTY_CONTEXT, RequestContext


class CandidateStatus(StrEnum):
    """Lifecycle state for one possible optimization."""

    ELIGIBLE = "eligible"
    RECOMMENDABLE = "recommendable"
    REJECTED = "rejected"
    SHADOW_ONLY = "shadow_only"
    UNAVAILABLE = "unavailable"


class QualityGateStatus(StrEnum):
    """Whether the candidate has enough quality evidence to execute."""

    PASSED = "passed"
    NOT_REQUIRED = "not_required"
    REQUIRED = "required"
    BLOCKED = "blocked"
    UNKNOWN = "unknown"


class OptimizationRisk(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class RequestClassification:
    """Content-free request features the planner can safely persist."""

    task_type: str | None
    task_confidence: float | None
    risk_level: OptimizationRisk
    prompt_chars: int
    message_count: int
    has_tools: bool
    wants_json: bool
    has_multimodal: bool
    personalized: bool
    freshness_sensitive: bool
    unknown_task: bool
    reason_codes: tuple[str, ...] = ()

    @property
    def risky_or_unknown(self) -> bool:
        return self.risk_level in {OptimizationRisk.HIGH, OptimizationRisk.UNKNOWN} or self.unknown_task


@dataclass(frozen=True)
class OutcomePrior:
    """Measured prior for one optimization lever and segment.

    These are learned from durable decision/feedback evidence and remain
    advisory until a caller explicitly chooses to authorize execution.
    """

    lever: str
    readiness_status: str
    sample_count: int
    measured_savings_count: int
    total_gross_savings_usd: str | None = None
    average_gross_savings_usd: str | None = None
    quality_pass_rate: str | None = None
    feedback_acceptance_rate: str | None = None
    reason_codes: tuple[str, ...] = ()


@dataclass(frozen=True)
class PlannerInput:
    """Pure planner input for observe-only evaluation.

    The body is inspected in memory only. The plan returned from this module stores
    derived facts and reason codes, never prompt or completion text.
    """

    request_id: str
    provider: str
    model: str
    body: dict[str, Any]
    context: RequestContext = field(default_factory=lambda: EMPTY_CONTEXT)
    optimize_enabled: bool = True
    exact_cache_enabled: bool = True
    semantic_cache_enabled: bool = False
    routing_policy_present: bool = False
    routing_policy_id: str | None = None
    trim_policy_present: bool = False
    trim_policy_id: str | None = None
    outcome_priors: tuple[OutcomePrior, ...] = ()


@dataclass(frozen=True)
class CandidateOptimization:
    lever: str
    status: CandidateStatus
    quality_gate: QualityGateStatus
    risk: OptimizationRisk
    reason_code: str
    reason_detail: dict[str, Any] = field(default_factory=dict)
    policy_id: str | None = None
    estimated_savings_usd: str | None = None


@dataclass(frozen=True)
class SelectedAction:
    """What the planner authorizes for this request.

    In this first chunk, selected actions are always observe-only so the proxy can
    later record planner output without behavior changes.
    """

    action: str
    mode: str
    reason_code: str


@dataclass(frozen=True)
class OptimizationPlan:
    request_id: str
    provider: str
    model: str
    classification: RequestClassification
    candidates: tuple[CandidateOptimization, ...]
    selected: SelectedAction
    planner_version: str = "planner_v1_observe_only"
