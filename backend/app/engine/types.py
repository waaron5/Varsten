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
class RequestFacts:
    """Provider-normalized, content-free request facts for planning.

    Raw request text is inspected only while building these booleans/counts. This
    object is safe to attach to planner metadata; it must never carry prompt,
    completion, tool-argument, or request-body content.
    """

    prompt_chars: int
    message_count: int
    has_tools: bool
    wants_json: bool
    has_multimodal: bool
    freshness_signal: bool
    personalized_signal: bool
    high_risk_signal: bool
    source: str = "provider_body"


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
    """Pure planner input for Base evaluation.

    The body is inspected in memory only. The plan returned from this module stores
    derived facts and reason codes, never prompt or completion text.
    """

    request_id: str
    provider: str
    model: str
    body: dict[str, Any]
    request_facts: RequestFacts | None = None
    context: RequestContext = field(default_factory=lambda: EMPTY_CONTEXT)
    optimize_enabled: bool = True
    exact_cache_enabled: bool = True
    semantic_cache_enabled: bool = False
    routing_policy_present: bool = False
    routing_policy_id: str | None = None
    trim_policy_present: bool = False
    trim_policy_id: str | None = None
    compression_policy_present: bool = False
    compression_policy_id: str | None = None
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
    """The primary optimization the planner authorizes for this request.

    ``action`` names the lever the planner would apply first (or ``observe`` when
    nothing is actionable). ``mode`` is how much authority it carries:
    - ``enforce`` — an eligible, gate-cleared lever the proxy may apply now;
    - ``shadow``  — a candidate that still needs a quality gate before it applies;
    - ``observe_only`` — nothing actionable (passthrough).
    The proxy records this alongside what it actually did (parity) so the planner
    can be trusted as the decision point before it is made authoritative per lever.
    """

    action: str
    mode: str
    reason_code: str


# Lever names in the order the proxy would apply them (cache short-circuits the
# forward first, then routing, then the body transforms). Selection walks this order.
SELECTION_PRIORITY: tuple[str, ...] = (
    "exact_cache",
    "semantic_cache",
    "model_routing",
    "token_trim",
    "prompt_compression",
)


@dataclass(frozen=True)
class OptimizationPlan:
    request_id: str
    provider: str
    model: str
    classification: RequestClassification
    candidates: tuple[CandidateOptimization, ...]
    selected: SelectedAction
    planner_version: str = "planner_v1_observe_only"

    def candidate_for(self, lever: str) -> CandidateOptimization | None:
        """The candidate for a lever, matching the routing aliases the proxy uses
        (``model_downshift``/``smart_routing`` both map to ``model_routing``)."""
        target = "model_routing" if lever in {"model_downshift", "smart_routing"} else lever
        for candidate in self.candidates:
            candidate_lever = (
                "model_routing" if candidate.lever in {"model_downshift", "smart_routing"} else candidate.lever
            )
            if candidate_lever == target:
                return candidate
        return None
